"""日终状态刷新任务（工单 S2-CRM-059 的主体）。

入口：`python -m crm.jobs.daily_status_refresh [--date YYYY-MM-DD]`

工单原文（拆成可执行的规则）：

* 调度器每天 00:10（按 `CRM_DEFAULT_TZ` 时区）调用一次；`--date` 补跑指定日期。
* 三类对象：
  1. **会籍**：未删除且 `status` 不在 `terminated`/`suspended` 的 ⇒ 调
     `derive_membership_status(membership, today)` 重新派生 ⇒ **只更新状态
     真的变化的行**；
  2. **合同**：`status=active` 且 `end_date` 早于 `today` 的 ⇒ 改为 `expired`；
  3. **回款计划**：未删除且 `status` 不在 `paid`/`written_off` 的 ⇒ 调
     `derive_payment_status(plan, today)` 重新派生 ⇒ 只更新变化的行。
* **分批**：每类对象每批 1000 行，**每批一个独立事务**；单批失败**只回滚
  该批**、记录错误、**继续下一批**；最终**以非零退出码结束**。
* **变更历史**：每次状态变化走 `record_change`，`actor_type=system`，
  **同一次运行共用一个 `operation_id`**。
* **幂等**：同一天重复运行**不产生新的状态变化与历史**。
* **并发**：Redis 锁 `crm:lock:daily_status_refresh`（TTL 30 分钟）。
* **产出**：JSON 汇总日志（各对象扫描数、变化数、按目标状态计数、失败批次、
  耗时）**并**写入 `crm_job_run`（`success`/`partial`/`failed`）。

⚠️⚠️ **分页用「键集」（`id > 上一页最大 id`），不用 `OFFSET`**：
派生会把 `status` 改掉 ⇒ 改过的行**仍然满足**扫描条件（`terminated`/
`suspended` 之外的都满足）⇒ 用 `OFFSET` 分页时**改过的行会被下一批重新读到**
⇒ 同一行被反复处理 ⇒ 分页永远走不到头（死循环）。
⇒ 键集分页与「行在扫描途中被改」无关 ⇒ 稳。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from crm.change_history import record_change
from crm.core.config import get_settings, resolve_timezone
from crm.db.session import new_session
from crm.derive.membership import derive_membership_status
from crm.derive.payment import derive_payment_status
from crm.locks import (
    LockBackend,
    LockBusy,
    LockHandle,
    RedisLockBackend,
    acquire_lock,
)
from crm.models.entities import (
    CONTRACT_STATUS_ACTIVE,
    CONTRACT_STATUS_EXPIRED,
    JOB_RUN_STATUS_FAILED,
    JOB_RUN_STATUS_PARTIAL,
    JOB_RUN_STATUS_SUCCESS,
    MEMBERSHIP_STATUS_EXCLUDED,
    PAYMENT_STATUS_EXCLUDED,
    Contract,
    JobRun,
    Membership,
    PaymentPlan,
)

JOB_NAME = "daily_status_refresh"

#: 退出码。
EXIT_OK = 0
#: 有批次失败（partial / failed）。
EXIT_FAILED = 1
#: 锁被别的实例占着 ⇒ 本次不跑。
EXIT_LOCKED = 2


# ---------------------------------------------------------------- 结果结构


@dataclass
class ObjectStats:
    """一类对象的统计。"""

    scanned: int = 0
    changed: int = 0
    by_target_status: dict[str, int] = field(default_factory=dict)
    failed_batches: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "changed": self.changed,
            "by_target_status": dict(sorted(self.by_target_status.items())),
            "failed_batches": self.failed_batches,
        }


@dataclass(frozen=True)
class RefreshResult:
    """一次运行的结果。"""

    run_date: date
    operation_id: str
    status: str
    stats: dict[str, Any]
    exit_code: int

    def summary(self) -> dict[str, Any]:
        """JSON 汇总（stdout 与 `crm_job_run.stats` 用同一份）。"""
        return {
            "job_name": JOB_NAME,
            "run_date": self.run_date.isoformat(),
            "operation_id": self.operation_id,
            "status": self.status,
            "stats": self.stats,
        }


# ---------------------------------------------------------------- 各对象的处理


@dataclass(frozen=True)
class BatchOutcome:
    """一批的处理结果。"""

    scanned: int
    changed: int
    by_target_status: dict[str, int]


def _process_batch(
    session: Session,
    rows: list[Any],
    *,
    entity_type: str,
    today: date,
    operation_id: str,
    derive: Callable[[Any, date], str],
    record: Callable[..., Any],
) -> BatchOutcome:
    """处理一批（**在调用方给的事务里**）。

    ⚠️ **只更新状态真的变化的行** ⇒ 没变化的行不写、不记历史 ⇒ 这就是
    幂等的根据（第二次跑没有变化 ⇒ 没有更新也没有历史）。
    """
    scanned = 0
    changed = 0
    by_target: dict[str, int] = {}

    for row in rows:
        scanned += 1
        target = derive(row, today)
        if target == row.status:
            # ⚠️ **没变化就不动它**（连 updated_at 都不改）⇒
            # 幂等：第二次跑这行还是「没变化」⇒ 不写历史。
            continue
        before = row.status
        row.status = target
        changed += 1
        by_target[target] = by_target.get(target, 0) + 1
        record(
            session,
            org_id=row.org_id,
            site_id=row.site_id,
            entity_type=entity_type,
            entity_id=row.id,
            field="status",
            from_value=before,
            to_value=target,
            operation_id=operation_id,
            effective_date=today,
        )
    session.flush()
    return BatchOutcome(scanned=scanned, changed=changed, by_target_status=by_target)


def _run_batches(
    *,
    session_factory: Callable[[], Session],
    model: Any,
    where: Any,
    today: date,
    operation_id: str,
    entity_type: str,
    derive: Callable[[Any, date], str],
    record: Callable[..., Any],
    batch_size: int,
    stats: ObjectStats,
    lock: LockHandle | None,
) -> None:
    """按键集分页逐批处理一类对象。

    ⚠️ **每批一个独立事务**：批内失败 ⇒ **只回滚该批** ⇒ 已提交的其他批不受影响。
    ⚠️ **失败批次也要往前推进游标**（`last_id`）⇒ 否则会反复重试同一批 ⇒
    死循环。失败的行本次**不重试** ⇒ 运维看 `failed_batches`，用 `--date` 补跑。
    """
    last_id = None
    batch_no = 0
    while True:
        batch_no += 1
        sess = session_factory()
        rows: list[Any] = []
        try:
            # ⚠️⚠️ **`where` 是「多个条件」⇒ 必须展开成 `where(*where)`**：
            # 写成 `.where(where)` 会把整个元组当成**一个**条件 ⇒
            # SQLAlchemy 抛 `ArgumentError` ⇒ **每一批都失败** ⇒
            # 而失败分支推进不了游标 ⇒ **死循环**（真踩过一次）。
            stmt = (
                select(model)
                .where(*where)
                .order_by(model.id)
                .limit(batch_size)
            )
            if last_id is not None:
                stmt = stmt.where(model.id > last_id)
            rows = list(sess.scalars(stmt))
            if not rows:
                sess.commit()
                return

            outcome = _process_batch(
                sess,
                rows,
                entity_type=entity_type,
                today=today,
                operation_id=operation_id,
                derive=derive,
                record=record,
            )
            sess.commit()

            stats.scanned += outcome.scanned
            stats.changed += outcome.changed
            for k, v in outcome.by_target_status.items():
                stats.by_target_status[k] = stats.by_target_status.get(k, 0) + v
            last_id = max(r.id for r in rows)
        except Exception as exc:  # noqa: BLE001 —— 批次失败要记录并继续
            sess.rollback()
            stats.failed_batches.append(
                {
                    "entity_type": entity_type,
                    "batch_no": batch_no,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                }
            )
            if not rows:
                # ⚠️⚠️ **连这一批都没取到 ⇒ 游标推进不了 ⇒ 再来一次还是同样的错
                # ⇒ 死循环** ⇒ 中止这一类对象（记录清楚，交由运维/补跑处理）。
                stats.failed_batches.append(
                    {
                        "entity_type": entity_type,
                        "batch_no": batch_no,
                        "error_type": "Aborted",
                        "error": "取批失败且游标无法推进 ⇒ 中止本类对象的处理（避免死循环）",
                    }
                )
                return
            # ⚠️ 失败批次的行**也要推进游标** ⇒ 否则反复重试同一批 ⇒ 死循环。
            last_id = max(r.id for r in rows)
        finally:
            sess.close()

        # ⚠️ **锁过期就中止**：TTL 30 分钟 ⇒ 跑太久锁就没了 ⇒ 另一个实例会
        # 进来 ⇒ 两个实例同时改同一批数据 ⇒ 宁可少跑。
        if lock is not None and not lock.owns():
            stats.failed_batches.append(
                {
                    "entity_type": entity_type,
                    "batch_no": batch_no,
                    "error_type": "LockLost",
                    "error": "并发锁已不在本实例手里（TTL 过期？）⇒ 中止本次运行",
                }
            )
            return


def _refresh_memberships(
    *, session_factory, today, operation_id, derive, record, batch_size, stats, lock
) -> None:
    where = (
        Membership.deleted_at.is_(None),
        Membership.status.not_in(MEMBERSHIP_STATUS_EXCLUDED),
    )
    _run_batches(
        session_factory=session_factory,
        model=Membership,
        where=where,
        today=today,
        operation_id=operation_id,
        entity_type="membership",
        derive=derive,
        record=record,
        batch_size=batch_size,
        stats=stats,
        lock=lock,
    )


def _refresh_contracts(
    *, session_factory, today, operation_id, record, batch_size, stats, lock
) -> None:
    # ⚠️ 合同的规则**没有派生函数**（工单原文写死）：`status=active` 且
    # `end_date` 早于 `today` ⇒ `expired`。
    def derive_contract(row: Contract, day: date) -> str:
        if (
            row.status == CONTRACT_STATUS_ACTIVE
            and row.end_date is not None
            and row.end_date < day
        ):
            return CONTRACT_STATUS_EXPIRED
        return row.status

    where = (
        Contract.deleted_at.is_(None),
        Contract.status == CONTRACT_STATUS_ACTIVE,
        Contract.end_date < today,
    )
    _run_batches(
        session_factory=session_factory,
        model=Contract,
        where=where,
        today=today,
        operation_id=operation_id,
        entity_type="contract",
        derive=derive_contract,
        record=record,
        batch_size=batch_size,
        stats=stats,
        lock=lock,
    )


def _refresh_payment_plans(
    *, session_factory, today, operation_id, derive, record, batch_size, stats, lock
) -> None:
    where = (
        PaymentPlan.deleted_at.is_(None),
        PaymentPlan.status.not_in(PAYMENT_STATUS_EXCLUDED),
    )
    _run_batches(
        session_factory=session_factory,
        model=PaymentPlan,
        where=where,
        today=today,
        operation_id=operation_id,
        entity_type="payment_plan",
        derive=derive,
        record=record,
        batch_size=batch_size,
        stats=stats,
        lock=lock,
    )


# ---------------------------------------------------------------- 主流程


def run_refresh(
    *,
    today: date,
    session_factory: Callable[[], Session] | None = None,
    lock: LockHandle | None = None,
    batch_size: int | None = None,
    derive_membership: Callable[[Any, date], str] = derive_membership_status,
    derive_payment: Callable[[Any, date], str] = derive_payment_status,
    record: Callable[..., Any] = record_change,
    clock: Callable[[], datetime] | None = None,
) -> RefreshResult:
    """跑一次日终刷新（**不含锁的获取与 `crm_job_run` 的写入**）。

    ⚠️ 拆成三段（`run_refresh` / 写运行记录 / CLI）是刻意的 ⇒ **好测**：
    验收标准 3 要「人为让一批失败 ⇒ 其他批次照常提交」⇒ 测试要能直接
    控制批次失败，而不是去 mock 整个 CLI。
    """
    factory = session_factory or new_session
    size = batch_size if batch_size is not None else get_settings().batch_size
    now_fn = clock or (lambda: datetime.now(UTC))
    operation_id = uuid.uuid4().hex

    started = now_fn()
    t0 = time.monotonic()

    membership_stats = ObjectStats()
    contract_stats = ObjectStats()
    payment_stats = ObjectStats()

    _refresh_memberships(
        session_factory=factory,
        today=today,
        operation_id=operation_id,
        derive=derive_membership,
        record=record,
        batch_size=size,
        stats=membership_stats,
        lock=lock,
    )
    _refresh_contracts(
        session_factory=factory,
        today=today,
        operation_id=operation_id,
        record=record,
        batch_size=size,
        stats=contract_stats,
        lock=lock,
    )
    _refresh_payment_plans(
        session_factory=factory,
        today=today,
        operation_id=operation_id,
        derive=derive_payment,
        record=record,
        batch_size=size,
        stats=payment_stats,
        lock=lock,
    )

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    failed_batches = (
        membership_stats.failed_batches
        + contract_stats.failed_batches
        + payment_stats.failed_batches
    )
    total_changed = (
        membership_stats.changed + contract_stats.changed + payment_stats.changed
    )

    # ⚠️ **partial 的判据**：有批次失败**且**还有成功的批次。
    if not failed_batches:
        status = JOB_RUN_STATUS_SUCCESS
    elif total_changed > 0 or any(
        s.scanned > 0 for s in (membership_stats, contract_stats, payment_stats)
    ):
        status = JOB_RUN_STATUS_PARTIAL
    else:
        status = JOB_RUN_STATUS_FAILED

    stats = {
        "objects": {
            "membership": membership_stats.as_dict(),
            "contract": contract_stats.as_dict(),
            "payment_plan": payment_stats.as_dict(),
        },
        "total_scanned": (
            membership_stats.scanned + contract_stats.scanned + payment_stats.scanned
        ),
        "total_changed": total_changed,
        "failed_batches": failed_batches,
        "elapsed_ms": elapsed_ms,
        "started_at": started.isoformat(),
        "finished_at": now_fn().isoformat(),
    }
    exit_code = EXIT_OK if status == JOB_RUN_STATUS_SUCCESS else EXIT_FAILED
    return RefreshResult(
        run_date=today,
        operation_id=operation_id,
        status=status,
        stats=stats,
        exit_code=exit_code,
    )


def write_job_run(result: RefreshResult, *, session_factory=None) -> JobRun:
    """把运行结果写进 `crm_job_run`（**独立事务** ⇒ 批次失败也照样留痕）。"""
    factory = session_factory or new_session
    sess = factory()
    try:
        row = JobRun(
            job_name=JOB_NAME,
            run_date=result.run_date,
            started_at=datetime.fromisoformat(result.stats["started_at"]),
            finished_at=datetime.fromisoformat(result.stats["finished_at"]),
            stats=result.stats,
            status=result.status,
        )
        sess.add(row)
        sess.commit()
        sess.refresh(row)
        return row
    finally:
        sess.close()


def _parse_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"--date 要 YYYY-MM-DD，收到 {raw!r}") from exc


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crm.jobs.daily_status_refresh",
        description="日终状态刷新：会籍到期、合同到期、回款逾期批量派生",
    )
    parser.add_argument(
        "--date",
        dest="run_date",
        default=None,
        help="补跑指定基准日（YYYY-MM-DD）；缺省＝按 CRM_DEFAULT_TZ 取今天",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="每批行数（缺省＝1000）",
    )
    return parser


def lock_backend(settings) -> LockBackend:
    """锁的后端（**可被测试替换** ⇒ CLI 的用例不依赖 Redis 起着）。

    ⚠️ 生产用 `RedisLockBackend`（真 Redis）；单测把这里换成
    `InMemoryLockBackend`；另有针对**真 Redis** 的用例
    （`CRM_TEST_REDIS_URL` 存在时才跑）。
    """
    return RedisLockBackend(settings.redis_url)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。

    ⚠️ **退出码**：0 成功 / 1 有批次失败（partial 或 failed）/ 2 锁被占用。
    """
    args = build_arg_parser().parse_args(argv)
    settings = get_settings()

    try:
        today = (
            _parse_date(args.run_date)
            if args.run_date
            else datetime.now(resolve_timezone(settings.default_tz)).date()
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), flush=True)
        return EXIT_FAILED

    backend: LockBackend = lock_backend(settings)
    try:
        lock = acquire_lock(backend, settings.lock_key, settings.lock_ttl_seconds)
    except LockBusy:
        print(
            json.dumps(
                {
                    "job_name": JOB_NAME,
                    "status": "locked",
                    "error": f"锁 {settings.lock_key} 被别的实例持有 ⇒ 本次不跑",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return EXIT_LOCKED

    try:
        result = run_refresh(
            today=today,
            lock=lock,
            batch_size=args.batch_size,
        )
        write_job_run(result)
        print(json.dumps(result.summary(), ensure_ascii=False, indent=2), flush=True)
        return result.exit_code
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
