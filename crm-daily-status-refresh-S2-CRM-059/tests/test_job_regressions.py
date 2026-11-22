"""回归测试：**这个项目真踩过的两个坑**，各钉一条。

坑 1：**分批死循环**。`.where(where)` 把「多个条件」的元组当成了**一个**条件
⇒ SQLAlchemy 抛 `ArgumentError` ⇒ 每一批都失败 ⇒ 而失败分支推进不了游标
⇒ **永远转下去**（整个任务卡死，运维那边看到的是「任务不结束」）。

坑 2：**失败批次推进不了游标**。失败后不推进 `last_id` ⇒ 下一批又取到同一批
⇒ 同样的错再来一次 ⇒ 死循环。

⇒ 这两条不是「假想」：坑 1 是本单开发时真踩的（任务跑起来不返回）。
⇒ 所以要有测试：**失败也必须能结束**。
"""

from __future__ import annotations

from datetime import date, timedelta

from crm.jobs import daily_status_refresh
from crm.jobs.daily_status_refresh import run_refresh
from crm.models.entities import Membership
from tests.conftest import make_membership

TODAY = date(2026, 3, 15)


def _status(session, row_id) -> str:
    """读当前状态（⚠️ 必须 refresh：任务在**别的会话**里改的行）。"""
    obj = session.get(Membership, row_id)
    session.refresh(obj)
    return obj.status


def test_every_batch_failing_still_terminates(session, session_factory):
    """⚠️ **每批都失败 ⇒ 也必须跑完**（不能死循环）。"""

    for _ in range(7):
        make_membership(session, status="active", end_date=TODAY - timedelta(days=1))
    session.commit()

    def always_fail(*_args, **_kwargs):
        raise RuntimeError("每批都失败")

    real = daily_status_refresh._process_batch
    daily_status_refresh._process_batch = always_fail
    try:
        result = run_refresh(today=TODAY, session_factory=session_factory, batch_size=2)
    finally:
        daily_status_refresh._process_batch = real

    # ⚠️ 有失败批次、状态非 success、退出码非 0
    assert result.stats["failed_batches"], "失败批次必须被记录"
    assert result.status in ("partial", "failed")
    assert result.exit_code != 0


def test_scan_query_failure_aborts_instead_of_looping(session, session_factory):
    """⚠️ **取批本身失败**（连行都没取到）⇒ 中止本类对象，**不能死循环**。

    ⇒ 因为此时**游标推进不了** ⇒ 再来一次还是同样的错。
    """

    make_membership(session, status="active", end_date=TODAY - timedelta(days=1))
    session.commit()

    real_select = daily_status_refresh.select

    def broken_select(*_args, **_kwargs):
        raise RuntimeError("取批失败（模拟 SQL 写错/表不存在）")

    daily_status_refresh.select = broken_select
    try:
        result = run_refresh(today=TODAY, session_factory=session_factory, batch_size=2)
    finally:
        daily_status_refresh.select = real_select

    errors = [b["error_type"] for b in result.stats["failed_batches"]]
    assert "RuntimeError" in errors
    assert "Aborted" in errors, "取批失败必须显式中止（而不是悄悄重试）"
    assert result.exit_code != 0


def test_cursor_advances_after_a_failed_batch(session, session_factory):
    """失败的那批之后，**游标必须往前推** ⇒ 不会反复处理同一批。"""

    rows = [
        make_membership(session, status="active", end_date=TODAY - timedelta(days=1))
        for _ in range(4)
    ]
    session.commit()

    real = daily_status_refresh._process_batch
    seen_batches = []

    def flaky(sess, batch_rows, **kwargs):
        seen_batches.append([r.id for r in batch_rows])
        if len(seen_batches) == 1:
            raise RuntimeError("第一批失败")
        return real(sess, batch_rows, **kwargs)

    daily_status_refresh._process_batch = flaky
    try:
        result = run_refresh(today=TODAY, session_factory=session_factory, batch_size=2)
    finally:
        daily_status_refresh._process_batch = real

    # ⚠️ **没有哪一批被处理两次** ⇒ 游标确实往前推了
    flat = [rid for batch in seen_batches for rid in batch]
    assert len(flat) == len(set(flat)), f"有行被重复处理：{flat}"
    # 第一批失败 ⇒ 它的行本次没被改；第二批（另外两行）照常改了
    changed = [r for r in rows if _status(session, r.id) == "expired"]
    assert len(changed) == 2
    assert result.stats["failed_batches"][0]["batch_no"] == 1


def test_keyset_pagination_does_not_reprocess_changed_rows(
    session, session_factory
):
    """⚠️ **分页必须不受「行在扫描途中被改」影响**。

    ⇒ 派生把 `status` 改掉 ⇒ 改过的行**仍满足**扫描条件
    ⇒ 用 `OFFSET` 分页会**反复读到同一批** ⇒ 永远走不到头。
    ⇒ 这里用键集分页 ⇒ 改过的行**不会被重复处理**。
    """

    rows = [
        make_membership(session, status="active", end_date=TODAY - timedelta(days=1))
        for _ in range(6)
    ]
    session.commit()

    seen = []
    real = daily_status_refresh._process_batch

    def spy(sess, batch_rows, **kwargs):
        seen.extend(r.id for r in batch_rows)
        return real(sess, batch_rows, **kwargs)

    daily_status_refresh._process_batch = spy
    try:
        result = run_refresh(today=TODAY, session_factory=session_factory, batch_size=2)
    finally:
        daily_status_refresh._process_batch = real

    assert len(seen) == len(set(seen)), "同一行被处理了多次 ⇒ 分页有问题"
    assert len(seen) == len(rows) == 6
    assert result.stats["objects"]["membership"]["changed"] == 6
