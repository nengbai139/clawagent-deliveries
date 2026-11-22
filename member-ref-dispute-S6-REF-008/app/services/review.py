"""复核（人工审核报备）。

工单原文：
* `GET /api/admin/ref/reports?status=&reporter_type=&owner_staff_id=`
* 员工可对 **accepted** 报备标记 **verified**，或以 **rejected_invalid** 驳回
  并填写原因（如「联系人信息虚假」）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import RefReport
from app.services.audit import write_audit


class ReviewError(Exception):
    """复核被拒。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ReportFilter:
    """复核列表的过滤条件。"""

    status: str | None = None
    reporter_type: str | None = None
    owner_staff_id: uuid.UUID | None = None
    org_id: uuid.UUID | None = None


def list_reports(
    session: Session, flt: ReportFilter, limit: int = 50, offset: int = 0
) -> list[RefReport]:
    """按条件列出报备（**软删除的排除**）。

    ⚠️ **分页必须有上限**：`limit` 不封顶的话，一个不带过滤条件的请求
    就能把整表拉出来 ⇒ 内存打爆。
    """
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    stmt = select(RefReport).where(RefReport.deleted_at.is_(None))
    if flt.status:
        stmt = stmt.where(RefReport.status == flt.status)
    if flt.reporter_type:
        stmt = stmt.where(RefReport.reporter_type == flt.reporter_type)
    if flt.owner_staff_id:
        stmt = stmt.where(RefReport.owner_staff_id == flt.owner_staff_id)
    if flt.org_id:
        stmt = stmt.where(RefReport.org_id == flt.org_id)
    stmt = stmt.order_by(RefReport.reported_at.desc()).limit(limit).offset(offset)
    return list(session.scalars(stmt))


def mark_verified(
    session: Session,
    report: RefReport,
    reviewer_id: str,
    reason: str | None = None,
) -> RefReport:
    """把 **accepted** 的报备标记为 **verified**。"""
    if report.status != "accepted":
        raise ReviewError(
            "bad_status",
            f"只有 accepted 的报备可以标记 verified，当前状态是 {report.status}",
        )
    before = report.status
    report.status = "verified"
    write_audit(
        session,
        org_id=report.org_id,
        site_id=report.site_id,
        actor_id=reviewer_id,
        target_type="report",
        target_id=report.id,
        action="review.verify",
        before_status=before,
        after_status=report.status,
        reason=reason,
    )
    return report


def reject_invalid(
    session: Session,
    report: RefReport,
    reviewer_id: str,
    reason: str,
) -> RefReport:
    """以 **rejected_invalid** 驳回报备，**必须填原因**。

    ⚠️ **原因必填**（工单原文「驳回并填写原因」）⇒ 空字符串也拒。
    """
    if report.status != "accepted":
        raise ReviewError(
            "bad_status",
            f"只有 accepted 的报备可以驳回，当前状态是 {report.status}",
        )
    if not reason or not reason.strip():
        raise ReviewError("reason_required", "驳回必须填写原因")
    before = report.status
    report.status = "rejected_invalid"
    report.reject_reason = reason.strip()
    write_audit(
        session,
        org_id=report.org_id,
        site_id=report.site_id,
        actor_id=reviewer_id,
        target_type="report",
        target_id=report.id,
        action="review.reject",
        before_status=before,
        after_status=report.status,
        reason=reason.strip(),
    )
    return report
