"""**验收标准**的测试（逐条对应工单 S2-CRM-059 的 acceptance_criteria）。

工单原文：
1. 构造会籍进入 expiring 与 expired、合同到期、回款进入 due 与 overdue 的
   虚构数据，运行一次后状态全部正确（**冻结时间**测试）
2. 同一天连续运行两次，第二次**变化数为 0 且无新增历史**（测试断言）
3. 人为让一批更新失败时**其他批次照常提交**，进程**退出码非 0**，
   `crm_job_run.status=partial`（测试断言）
4. 用 `--date` 补跑时**按指定日期**派生状态（测试断言）
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crm.jobs import daily_status_refresh
from crm.jobs.daily_status_refresh import (
    EXIT_FAILED,
    JOB_NAME,
    run_refresh,
    write_job_run,
)
from crm.models.entities import (
    ChangeHistory,
    Contract,
    JobRun,
    Membership,
    PaymentPlan,
)
from tests.conftest import FROZEN_TODAY, make_contract

TODAY = FROZEN_TODAY


def _status(session: Session, model, row_id) -> str:
    """读某行的当前状态。

    ⚠️⚠️ **必须 `refresh`**：任务是**另开会话**改的行（每批一个事务 ⇒
    真实行为）⇒ 本会话的**身份映射里还是旧对象** ⇒ 直接 `session.get()`
    拿到的是**改之前的值** ⇒ 断言会假失败（真踩过一次）。
    """
    obj = session.get(model, row_id)
    session.refresh(obj)
    return obj.status


# ==================================================================
# 验收标准 1：冻结时间 ⇒ 状态全部正确
# ==================================================================


def test_criterion1_all_statuses_correct_after_one_run(
    session: Session, session_factory, frozen_clock
):
    """会籍 → expiring/expired、合同 → expired、回款 → due/overdue（一次跑完）。"""
    # ---- 会籍 ----
    # end_date 在今天之后 10 天 ⇒ 落在「即将到期」窗口内（30 天）⇒ expiring
    from tests.conftest import make_membership, make_payment_plan

    membership_expiring = make_membership(
        session, status="active", end_date=TODAY + timedelta(days=10)
    )
    # end_date 在今天之前 ⇒ expired
    membership_expired = make_membership(
        session, status="active", end_date=TODAY - timedelta(days=1)
    )
    # end_date 很远 ⇒ 保持 active（**不该被改**）
    membership_active = make_membership(
        session, status="active", end_date=TODAY + timedelta(days=365)
    )
    # ⚠️ **人工状态不该被碰**
    membership_terminated = make_membership(
        session, status="terminated", end_date=TODAY - timedelta(days=10)
    )
    membership_suspended = make_membership(
        session, status="suspended", end_date=TODAY - timedelta(days=10)
    )

    # ---- 合同 ----
    contract_expired = make_contract(session, status="active", end_date=TODAY - timedelta(days=1))
    contract_active = make_contract(session, status="active", end_date=TODAY + timedelta(days=30))
    contract_terminated = make_contract(
        session, status="terminated", end_date=TODAY - timedelta(days=10)
    )

    # ---- 回款 ----
    plan_due = make_payment_plan(session, contract_expired, status="pending", due_date=TODAY)
    plan_overdue = make_payment_plan(
        session, contract_expired, status="pending", due_date=TODAY - timedelta(days=3),
        installment_no=2,
    )
    plan_future = make_payment_plan(
        session, contract_expired, status="pending", due_date=TODAY + timedelta(days=5),
        installment_no=3,
    )
    plan_paid = make_payment_plan(
        session, contract_expired, status="paid", due_date=TODAY - timedelta(days=3),
        installment_no=4,
    )
    session.commit()

    result = run_refresh(
        today=TODAY, session_factory=session_factory, clock=frozen_clock
    )

    assert result.status == "success"
    assert result.exit_code == 0

    # ---- 会籍 ----
    assert _status(session, Membership, membership_expiring.id) == "expiring"
    assert _status(session, Membership, membership_expired.id) == "expired"
    assert _status(session, Membership, membership_active.id) == "active"
    assert _status(session, Membership, membership_terminated.id) == "terminated"
    assert _status(session, Membership, membership_suspended.id) == "suspended"

    # ---- 合同 ----
    assert _status(session, Contract, contract_expired.id) == "expired"
    assert _status(session, Contract, contract_active.id) == "active"
    assert _status(session, Contract, contract_terminated.id) == "terminated"

    # ---- 回款 ----
    assert _status(session, PaymentPlan, plan_due.id) == "due"
    assert _status(session, PaymentPlan, plan_overdue.id) == "overdue"
    assert _status(session, PaymentPlan, plan_future.id) == "pending"
    assert _status(session, PaymentPlan, plan_paid.id) == "paid"

    # ---- 统计 ----
    stats = result.stats["objects"]
    assert stats["membership"]["changed"] == 2
    assert stats["contract"]["changed"] == 1
    assert stats["payment_plan"]["changed"] == 2
    assert stats["membership"]["by_target_status"] == {"expired": 1, "expiring": 1}
    assert stats["payment_plan"]["by_target_status"] == {"due": 1, "overdue": 1}
    assert result.stats["total_changed"] == 5
    assert result.stats["failed_batches"] == []


def test_criterion1_change_history_written_for_each_change(
    session: Session, session_factory, frozen_clock
):
    """每次状态变化都写一条历史，且 `actor_type=system`、共用一个 operation_id。"""
    from tests.conftest import make_membership

    m = make_membership(session, status="active", end_date=TODAY - timedelta(days=1))
    session.commit()

    result = run_refresh(
        today=TODAY, session_factory=session_factory, clock=frozen_clock
    )

    rows = list(session.scalars(select(ChangeHistory)))
    assert len(rows) == 1
    row = rows[0]
    assert row.entity_type == "membership"
    assert row.entity_id == m.id
    assert row.field == "status"
    assert row.from_value == "active"
    assert row.to_value == "expired"
    assert row.actor_type == "system"
    assert row.operation_id == result.operation_id
    assert row.effective_date == TODAY


# ==================================================================
# 验收标准 2：同一天跑两次 ⇒ 第二次变化数 0 且无新增历史
# ==================================================================


def test_criterion2_second_run_changes_nothing(session: Session, session_factory):
    """同一天连续跑两次 ⇒ 第二次变化数 0、无新增历史。"""
    from tests.conftest import make_membership

    make_membership(session, status="active", end_date=TODAY - timedelta(days=1))
    session.commit()

    first = run_refresh(today=TODAY, session_factory=session_factory)
    assert first.stats["total_changed"] == 1
    history_after_first = session.scalar(select(func.count()).select_from(ChangeHistory))
    assert history_after_first == 1

    second = run_refresh(today=TODAY, session_factory=session_factory)

    assert second.stats["total_changed"] == 0, "第二次跑不应有变化"
    assert second.exit_code == 0
    assert second.status == "success"
    for obj_stats in second.stats["objects"].values():
        assert obj_stats["changed"] == 0

    history_after_second = session.scalar(select(func.count()).select_from(ChangeHistory))
    assert history_after_second == 1, "第二次跑不应新增历史"

    # ⚠️ **两次运行共用两个 operation_id**（历史按 operation 分组）
    ops = set(session.scalars(select(ChangeHistory.operation_id)))
    assert len(ops) == 1


# ==================================================================
# 验收标准 3：一批失败 ⇒ 其他批次照常提交、退出码非 0、status=partial
# ==================================================================


def test_criterion3_failed_batch_others_still_commit(
    session: Session, session_factory, frozen_clock
):
    """人为让一批失败 ⇒ 其他批次照常提交、退出码非 0、`crm_job_run.status=partial`。"""
    from tests.conftest import make_membership

    # 造 5 条要变化的会籍；batch_size=2 ⇒ 三批：2 / 2 / 1
    rows = [
        make_membership(session, status="active", end_date=TODAY - timedelta(days=1))
        for _ in range(5)
    ]
    session.commit()

    real_process_batch = daily_status_refresh._process_batch
    calls = {"n": 0}

    def flaky_process_batch(sess, batch_rows, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            # ⚠️ 人为让**第二批**失败
            raise RuntimeError("人为制造的批次失败")
        return real_process_batch(sess, batch_rows, **kwargs)

    daily_status_refresh._process_batch = flaky_process_batch
    try:
        result = run_refresh(
            today=TODAY,
            session_factory=session_factory,
            batch_size=2,
            clock=frozen_clock,
        )
    finally:
        daily_status_refresh._process_batch = real_process_batch

    # ⚠️ 结果要标成 partial、退出码非 0
    assert result.status == "partial"
    assert result.exit_code != 0
    assert result.exit_code == EXIT_FAILED
    assert len(result.stats["failed_batches"]) == 1
    assert result.stats["failed_batches"][0]["batch_no"] == 2
    assert "人为制造的批次失败" in result.stats["failed_batches"][0]["error"]

    # ⚠️ **其他批次照常提交**：第一、三批的行状态已经改了
    changed = [
        r for r in rows if _status(session, Membership, r.id) == "expired"
    ]
    assert len(changed) == 3, "失败批之外的批次必须照常提交"

    # 写运行记录 ⇒ status=partial
    write_job_run(result, session_factory=session_factory)
    job_run = session.scalars(
        select(JobRun).where(JobRun.job_name == JOB_NAME)
    ).one()
    assert job_run.status == "partial"
    assert job_run.run_date == TODAY
    assert job_run.stats["total_changed"] == 3


def test_criterion3_failed_batch_does_not_rollback_other_batches(
    session: Session, session_factory
):
    """失败批的写入被回滚，但**其它批的写入不受影响**（独立事务）。"""
    from tests.conftest import make_membership

    rows = [
        make_membership(session, status="active", end_date=TODAY - timedelta(days=1))
        for _ in range(4)
    ]
    session.commit()

    real_process_batch = daily_status_refresh._process_batch
    calls = {"n": 0}

    def flaky(sess, batch_rows, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            # ⚠️ 先写点东西再抛 ⇒ 验证这批真的被回滚了
            sess.add(
                ChangeHistory(
                    org_id=rows[0].org_id,
                    entity_type="membership",
                    entity_id=rows[0].id,
                    field="status",
                    from_value="active",
                    to_value="expired",
                    actor_type="system",
                    operation_id="should-be-rolled-back",
                    effective_date=TODAY,
                )
            )
            sess.flush()
            raise RuntimeError("boom")
        return real_process_batch(sess, batch_rows, **kwargs)

    daily_status_refresh._process_batch = flaky
    try:
        result = run_refresh(
            today=TODAY, session_factory=session_factory, batch_size=2
        )
    finally:
        daily_status_refresh._process_batch = real_process_batch

    assert result.status == "partial"
    # ⚠️ 失败批里那条历史被回滚了（没留下）
    ops = list(session.scalars(select(ChangeHistory.operation_id)))
    assert "should-be-rolled-back" not in ops
    # ⚠️ 成功批的历史留下了
    assert len(ops) == 2


# ==================================================================
# 验收标准 4：--date 补跑按指定日期派生
# ==================================================================


def test_criterion4_backfill_uses_given_date(session: Session, session_factory):
    """`--date` 补跑 ⇒ 按**指定日期**派生状态。"""
    from tests.conftest import make_membership

    # 基准日 2026-03-15 ⇒ 这条会籍（end_date=3-16）离到期 1 天 ⇒ expiring
    membership = make_membership(
        session, status="active", end_date=date(2026, 3, 16)
    )
    session.commit()

    # 补跑 2026-03-15 ⇒ expiring
    result = run_refresh(today=date(2026, 3, 15), session_factory=session_factory)
    assert result.run_date == date(2026, 3, 15)
    assert _status(session, Membership, membership.id) == "expiring"

    # ⚠️ **同一行补跑更早的日期** ⇒ 那天离到期 43 天（> 30 天窗口）⇒ active
    #    （⚠️ 这里必须挑一个「离到期 > 窗口」的日子：否则期望值本身是错的）
    result2 = run_refresh(today=date(2026, 2, 1), session_factory=session_factory)
    assert result2.run_date == date(2026, 2, 1)
    assert _status(session, Membership, membership.id) == "active"
    # ⚠️ 历史里两条，effective_date 分别是两个基准日
    eff = sorted(
        session.scalars(select(ChangeHistory.effective_date).order_by(ChangeHistory.created_at))
    )
    assert eff == [date(2026, 2, 1), date(2026, 3, 15)]


def test_criterion4_cli_date_argument(session: Session, session_factory, monkeypatch):
    """CLI 的 `--date` 真的传到了派生逻辑（不是只在服务层测）。"""
    from crm.locks import InMemoryLockBackend as _IB
    from tests.conftest import make_membership

    # ⚠️ 单测不依赖 Redis 起着 ⇒ 锁后端换成内存实现（真 Redis 另有专门用例）
    monkeypatch.setattr(daily_status_refresh, "lock_backend", lambda s: _IB())

    membership = make_membership(
        session, status="active", end_date=date(2026, 3, 16)
    )
    session.commit()

    rc = daily_status_refresh.main(["--date", "2026-03-15"])
    assert rc == 0
    assert _status(session, Membership, membership.id) == "expiring"

    job_run = session.scalars(select(JobRun).where(JobRun.job_name == JOB_NAME)).one()
    assert job_run.run_date == date(2026, 3, 15)


# ==================================================================
# 其它不变量（工单原文里明确写了、但验收标准没单列的）
# ==================================================================


def test_soft_deleted_rows_are_skipped(session: Session, session_factory):
    """**软删除**的会籍不参与派生。"""
    from datetime import UTC, datetime

    from tests.conftest import make_membership

    m = make_membership(session, status="active", end_date=TODAY - timedelta(days=1))
    m.deleted_at = datetime.now(UTC)
    session.commit()

    result = run_refresh(today=TODAY, session_factory=session_factory)
    assert result.stats["total_changed"] == 0
    assert _status(session, Membership, m.id) == "active"


def test_paid_and_written_off_plans_are_skipped(session: Session, session_factory):
    """`paid` / `written_off` 的回款期次不参与派生。"""
    from tests.conftest import make_payment_plan

    contract = make_contract(session, status="active", end_date=TODAY + timedelta(days=30))
    paid = make_payment_plan(
        session, contract, status="paid", due_date=TODAY - timedelta(days=5)
    )
    written_off = make_payment_plan(
        session, contract, status="written_off", due_date=TODAY - timedelta(days=5),
        installment_no=2,
    )
    session.commit()

    result = run_refresh(today=TODAY, session_factory=session_factory)
    assert result.stats["objects"]["payment_plan"]["changed"] == 0
    assert session.get(PaymentPlan, paid.id).status == "paid"
    assert session.get(PaymentPlan, written_off.id).status == "written_off"


def test_batch_size_splits_into_several_batches(session: Session, session_factory):
    """超过一批的行会被拆成多批处理（每批 1000 行 ⇒ 分批逻辑生效）。"""
    from tests.conftest import make_membership

    for _ in range(5):
        make_membership(session, status="active", end_date=TODAY - timedelta(days=1))
    session.commit()

    result = run_refresh(today=TODAY, session_factory=session_factory, batch_size=2)
    assert result.stats["objects"]["membership"]["changed"] == 5
    assert result.stats["objects"]["membership"]["scanned"] == 5


@pytest.mark.parametrize(
    "status_in,end_offset,expected",
    [
        ("active", 365, "active"),
        ("active", 10, "expiring"),
        ("active", -1, "expired"),
        ("terminated", -10, "terminated"),
        ("suspended", -10, "suspended"),
    ],
)
def test_membership_derivation_table(session, session_factory, status_in, end_offset, expected):
    """派生表逐项对（冻结时间）。"""
    from tests.conftest import make_membership

    m = make_membership(
        session, status=status_in, end_date=TODAY + timedelta(days=end_offset)
    )
    session.commit()
    run_refresh(today=TODAY, session_factory=session_factory)
    assert _status(session, Membership, m.id) == expected


def test_expiring_window_is_configurable(session, session_factory, monkeypatch):
    """「即将到期」的提前天数可配（默认 30 天）。"""
    from tests.conftest import make_membership

    monkeypatch.setenv("CRM_MEMBERSHIP_EXPIRING_WINDOW_DAYS", "90")
    from crm.core.config import get_settings

    get_settings.cache_clear()
    try:
        # 距到期 60 天：默认窗口 30 ⇒ 还不到「即将到期」⇒ active；
        # 窗口改成 90 ⇒ 60 ≤ 90 ⇒ expiring ⇒ **窗口确实在起作用**。
        m = make_membership(session, status="active", end_date=TODAY + timedelta(days=60))
        session.commit()
        run_refresh(today=TODAY, session_factory=session_factory)
        assert _status(session, Membership, m.id) == "expiring"
    finally:
        get_settings.cache_clear()

