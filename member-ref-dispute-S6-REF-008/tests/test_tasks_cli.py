"""后台任务 CLI 的测试。

⚠️ **为什么要有这个文件**：CLI 入口的 `session_scope()` 曾经是**裸生成器**
⇒ `with session_scope()` 直接 `TypeError` ⇒ 而**服务层测试全绿**
（它们不用这个上下文管理器）⇒ **没人发现**。

⇒ ⇒ **凡是「有入口」的东西，入口本身也要测**。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.models.entities import NotificationStub, RefReport
from app.services import dispute as dispute_svc
from app.tasks import main


def _make_old_dispute(session: Session, org_id, age_days: int):
    report = RefReport(
        org_id=org_id,
        reporter_type="staff",
        reporter_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        reported_at=datetime.now(UTC),
        status="rejected_invalid",
    )
    session.add(report)
    session.flush()
    d = dispute_svc.submit_dispute(
        session,
        report,
        # ⚠️ 提交人必须是**该报备的报备方**（工单原文：「报备方对拒绝结果
        # 有异议时」）⇒ 提交人 = `report.reporter_id`。
        disputer_id=report.reporter_id,
        disputer_type="staff",
        reason_code="wrong_attribution",
        reason_text="归属错了",
        attachments=[],
    )
    d.created_at = datetime.now(UTC) - timedelta(days=age_days)
    session.flush()
    return d


def test_session_scope_is_a_context_manager():
    """`session_scope()` 必须是**上下文管理器**（不是裸生成器）。

    ⚠️ 这条是**回归测试**：裸生成器用在 `with` 里 ⇒ `TypeError`。
    """
    with session_scope() as sess:
        assert sess is not None
        sess.execute(__import__("sqlalchemy").text("SELECT 1"))


def test_session_scope_rolls_back_on_error():
    """异常时**回滚**（不留下半截数据）。"""
    before = None
    with session_scope() as sess:
        before = sess.query(NotificationStub).count()
    try:
        with session_scope() as sess:
            sess.add(NotificationStub(recipient="x", kind="k", payload="{}"))
            sess.flush()
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with session_scope() as sess:
        after = sess.query(NotificationStub).count()
    assert after == before


def test_remind_disputes_cli_runs_and_is_idempotent(session: Session, org_id, capsys):
    """CLI 能跑通，且**幂等**（第二次不再提醒）。"""
    _make_old_dispute(session, org_id, age_days=12)
    session.commit()

    assert main(["remind-disputes", "--days", "10"]) == 0
    out1 = capsys.readouterr().out
    assert "reminded=1" in out1

    assert main(["remind-disputes", "--days", "10"]) == 0
    out2 = capsys.readouterr().out
    assert "reminded=0" in out2
