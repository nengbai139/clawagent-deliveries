"""超时提醒任务（工单原文：「争议提交后 10 天未处理时提醒负责人」）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AuditLog, NotificationStub, RefDispute
from app.services import dispute as dispute_svc
from tests.conftest import make_report


def _make_pending(session: Session, org_id, age_days: int) -> RefDispute:
    report = make_report(session, org_id, status="rejected_invalid")
    d = dispute_svc.submit_dispute(
        session,
        report,
        disputer_id=uuid.uuid4(),
        disputer_type="staff",
        reason_code="wrong_attribution",
        reason_text="归属错了",
        attachments=[],
    )
    # ⚠️ 改 `created_at` 模拟「提交于 N 天前」（ORM 的 default 只在 INSERT 时用）。
    d.created_at = datetime.now(UTC) - timedelta(days=age_days)
    session.flush()
    return d


def test_overdue_dispute_reminded(session: Session, org_id):
    """**超过 10 天**未处理 ⇒ 提醒。"""
    old = _make_pending(session, org_id, age_days=12)
    now = datetime.now(UTC)

    n = dispute_svc.remind_overdue_disputes(session, days=10, now=now)
    session.flush()

    assert n == 1
    assert old.reminded_at is not None
    notes = list(session.scalars(select(NotificationStub)))
    assert any(x.kind == "dispute.overdue" for x in notes)


def test_recent_dispute_not_reminded(session: Session, org_id):
    """**不到 10 天** ⇒ 不提醒。"""
    _make_pending(session, org_id, age_days=3)
    n = dispute_svc.remind_overdue_disputes(
        session, days=10, now=datetime.now(UTC)
    )
    session.flush()
    assert n == 0
    assert list(session.scalars(select(NotificationStub))) == []


def test_reminder_is_idempotent(session: Session, org_id):
    """**幂等**：跑第二次不再重复提醒。"""
    _make_pending(session, org_id, age_days=12)
    now = datetime.now(UTC)

    first = dispute_svc.remind_overdue_disputes(session, days=10, now=now)
    session.flush()
    second = dispute_svc.remind_overdue_disputes(session, days=10, now=now)
    session.flush()

    assert first == 1
    assert second == 0
    notes = list(session.scalars(select(NotificationStub)))
    assert len([x for x in notes if x.kind == "dispute.overdue"]) == 1


def test_reminder_writes_audit(session: Session, org_id):
    """提醒也要写审计日志（工单原文：所有争议操作写审计）。"""
    d = _make_pending(session, org_id, age_days=12)
    dispute_svc.remind_overdue_disputes(
        session, days=10, now=datetime.now(UTC)
    )
    session.flush()

    entries = list(
        session.scalars(
            select(AuditLog).where(
                AuditLog.target_id == d.id,
                AuditLog.action == "dispute.remind_overdue",
            )
        )
    )
    assert len(entries) == 1
    assert entries[0].actor_id == "system"


def test_decided_dispute_not_reminded(session: Session, org_id):
    """已处理的争议**不再提醒**（它已经不等「负责人」了）。"""
    report = make_report(session, org_id, status="rejected_invalid")
    d = dispute_svc.submit_dispute(
        session, report, disputer_id=uuid.uuid4(), disputer_type="staff",
        reason_code="wrong_attribution", reason_text="x", attachments=[],
    )
    d.created_at = datetime.now(UTC) - timedelta(days=30)
    d.status = "upheld"
    session.flush()

    n = dispute_svc.remind_overdue_disputes(
        session, days=10, now=datetime.now(UTC)
    )
    session.flush()
    assert n == 0
