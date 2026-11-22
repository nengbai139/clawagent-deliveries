"""争议：提交与处理。

工单原文：
* 报备方对拒绝结果有异议时，`POST /api/ref/reports/{id}/disputes` 提交说明
  与证据附件（**最多 5 个文件**）。
* 争议**只受理「系统判断错误」类原因**（如归一化误判为重复、存量客户信息
  有误），**不受理**「更早在线下接触过客户」这类与首次报备规则冲突的理由。
* 处理：`POST /api/admin/ref/disputes/{id}/decide {decision: uphold 维持 /
  overturn 改判, reason}`；**改判需要 `channel_manager` 与 `finance` 两个
  角色由两个不同的人各审批一次才生效**；改判后系统按**原报备时间**重新
  判定归属，并通知受影响各方（通知接口先用桩）。
* 争议提交后 **10 天**未处理时提醒负责人。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import NotificationStub, RefDispute, RefReport
from app.services.approval import ApprovalError, apply_approval
from app.services.attribution import recompute_attribution
from app.services.audit import write_audit

#: ⚠️ **只受理这些原因**（工单原文：「只受理系统判断错误类原因」）。
#: 「更早在线下接触过客户」这类**与首次报备规则冲突**的理由不在其中。
ALLOWED_REASON_CODES: frozenset[str] = frozenset(
    {
        # 归一化误判为重复
        "normalization_false_duplicate",
        # 存量客户信息有误
        "existing_customer_data_error",
        # 归属判错
        "wrong_attribution",
        # 其它系统错误
        "other_system_error",
    }
)

#: 明确**不受理**的理由（用于给出更清楚的提示；不是白名单的补充说明）。
REJECTED_REASON_HINTS: dict[str, str] = {
    "earlier_offline_contact": "与首次报备规则冲突的理由不受理（只受理系统判断错误类）",
    "first_report_rule_conflict": "与首次报备规则冲突的理由不受理（只受理系统判断错误类）",
}

#: 证据附件上限。
MAX_ATTACHMENTS = 5


class DisputeError(Exception):
    """争议操作被拒。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Attachment:
    """证据附件。"""

    file_id: str
    name: str
    url: str


def _parse_attachments(raw: str) -> list[Attachment]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    out: list[Attachment] = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict):
            out.append(
                Attachment(
                    file_id=str(item.get("file_id", "")),
                    name=str(item.get("name", "")),
                    url=str(item.get("url", "")),
                )
            )
    return out


def submit_dispute(
    session: Session,
    report: RefReport,
    *,
    disputer_id: uuid.UUID,
    disputer_type: str,
    reason_code: str,
    reason_text: str,
    attachments: list[Attachment],
    now: datetime | None = None,
) -> RefDispute:
    """提交一条争议。

    ⚠️⚠️ **只允许对「被拒绝的报备」提争议，且只允许报备方本人提**
    （工单原文：「**报备方对拒绝结果有异议时**」）：
    * 报备状态必须是 `rejected_invalid` ⇒ 对 `accepted`/`verified` 的报备
      提争议**没有依据**（那是正常受理的）；
    * 提交人必须是**该报备的报备方** ⇒ 否则**任何人都能替别人提争议**。
    """
    if report.status != "rejected_invalid":
        raise DisputeError(
            "report_not_rejected",
            f"只有被驳回（rejected_invalid）的报备可以提争议，当前状态是 {report.status}",
        )
    if disputer_id != report.reporter_id:
        raise DisputeError(
            "not_the_reporter", "只有该报备的报备方可以对它提出争议"
        )

    # ---- 理由白名单（失败关闭）----
    if reason_code in REJECTED_REASON_HINTS:
        raise DisputeError(
            "reason_not_accepted", REJECTED_REASON_HINTS[reason_code]
        )
    if reason_code not in ALLOWED_REASON_CODES:
        raise DisputeError(
            "reason_not_accepted",
            f"争议理由 {reason_code} 不受理；只受理系统判断错误类原因",
        )
    if not reason_text or not reason_text.strip():
        raise DisputeError("reason_text_required", "争议说明不能为空")
    # ---- 附件上限 ----
    if len(attachments) > MAX_ATTACHMENTS:
        raise DisputeError(
            "too_many_attachments",
            f"证据附件最多 {MAX_ATTACHMENTS} 个，收到 {len(attachments)} 个",
        )

    dispute = RefDispute(
        org_id=report.org_id,
        site_id=report.site_id,
        report_id=report.id,
        disputer_id=disputer_id,
        disputer_type=disputer_type,
        reason_code=reason_code,
        reason_text=reason_text.strip(),
        attachments=json.dumps(
            [
                {"file_id": a.file_id, "name": a.name, "url": a.url}
                for a in attachments
            ],
            ensure_ascii=False,
        ),
        status="pending",
    )
    session.add(dispute)
    session.flush()

    write_audit(
        session,
        org_id=report.org_id,
        site_id=report.site_id,
        actor_id=str(disputer_id),
        target_type="dispute",
        target_id=dispute.id,
        action="dispute.submit",
        before_status=None,
        after_status="pending",
        reason=reason_text.strip(),
        detail={
            "report_id": str(report.id),
            "reason_code": reason_code,
            "attachments": len(attachments),
        },
    )
    return dispute


def _notify(session: Session, recipient: str, kind: str, payload: dict) -> None:
    """通知**桩**（工单原文：「通知接口先用桩」）。"""
    session.add(
        NotificationStub(
            recipient=recipient,
            kind=kind,
            payload=json.dumps(payload, ensure_ascii=False),
        )
    )
    session.flush()


def decide_dispute(
    session: Session,
    dispute: RefDispute,
    *,
    approver_id: uuid.UUID,
    role: str,
    decision: str,
    reason: str,
    now: datetime | None = None,
) -> dict:
    """处理一条争议。

    ⚠️ **`uphold`（维持）一次即生效**；**`overturn`（改判）需双人审批**
    ——两个不同的人、各以一个角色，**各审批一次**。

    ⚠️⚠️ **入口统一状态闸门**（两条路径共用）：
    已生效的改判（`overturned`）**不能**再被 `uphold` 静默回退 ⇒ 否则
    审计日志里出现「overturn 之后又 uphold」的倒流，而**归属不会回滚**
    ⇒ 审计与实际归属对不上 ⇒ 数据自相矛盾。
    """
    if not reason or not reason.strip():
        raise DisputeError("reason_required", "处理必须填写理由")
    if dispute.status != "pending":
        raise DisputeError(
            "dispute_not_pending", f"争议状态为 {dispute.status}，不可再处理"
        )

    if decision == "uphold":
        # 维持：不需要双人审批。
        before = dispute.status
        dispute.status = "upheld"
        dispute.decision_reason = reason.strip()
        dispute.decided_at = now or datetime.now(UTC)
        write_audit(
            session,
            org_id=dispute.org_id,
            site_id=dispute.site_id,
            actor_id=str(approver_id),
            target_type="dispute",
            target_id=dispute.id,
            action="dispute.uphold",
            before_status=before,
            after_status=dispute.status,
            reason=reason.strip(),
            detail={"role": role},
        )
        _notify(
            session,
            str(dispute.disputer_id),
            "dispute.upheld",
            {"dispute_id": str(dispute.id), "reason": reason.strip()},
        )
        return {"effective": True, "status": dispute.status, "missing_roles": []}

    if decision != "overturn":
        raise DisputeError("bad_decision", "decision 只能是 uphold 或 overturn")

    # ---- 改判：走双人审批 ----
    try:
        outcome = apply_approval(
            session,
            dispute,
            approver_id=approver_id,
            role=role,
            decision=decision,
            comment=reason.strip(),
        )
    except ApprovalError as exc:
        # ⚠️ 审批被拒 ⇒ **不写审批记录**（apply_approval 在写之前就抛了）
        raise DisputeError(exc.code, exc.message) from exc

    if not outcome.quorum_reached:
        # 只记了一条审批，**状态不变**（失败关闭：改判未生效）。
        write_audit(
            session,
            org_id=dispute.org_id,
            site_id=dispute.site_id,
            actor_id=str(approver_id),
            target_type="dispute",
            target_id=dispute.id,
            action="dispute.approval",
            before_status=dispute.status,
            after_status=dispute.status,
            reason=reason.strip(),
            detail={
                "role": role,
                "satisfied_roles": list(outcome.satisfied_roles),
                "missing_roles": list(outcome.missing_roles),
                "effective": False,
            },
        )
        return {
            "effective": False,
            "status": dispute.status,
            "satisfied_roles": list(outcome.satisfied_roles),
            "missing_roles": list(outcome.missing_roles),
        }

    # ---- 达成双人审批 ⇒ 改判生效 ----
    before = dispute.status
    dispute.status = "overturned"
    dispute.decision_reason = reason.strip()
    dispute.decided_at = now or datetime.now(UTC)
    write_audit(
        session,
        org_id=dispute.org_id,
        site_id=dispute.site_id,
        actor_id=str(approver_id),
        target_type="dispute",
        target_id=dispute.id,
        action="dispute.overturn",
        before_status=before,
        after_status=dispute.status,
        reason=reason.strip(),
        detail={
            "role": role,
            "satisfied_roles": list(outcome.satisfied_roles),
            "effective": True,
        },
    )

    # ---- ⚠️ 改判后按**原报备时间**重新判定归属，并写入审计 ----
    report = session.get(RefReport, dispute.report_id)
    attribution_detail: dict = {}
    if report is not None:
        # ⚠️⚠️ **先记下旧归属人**：重算会**就地覆盖** `owner_staff_id`
        # ⇒ 之后再取就只剩新归属人了 ⇒ **失去归属的那一方（旧归属人）
        # 既收不到通知、也不在审计里** ⇒ 而它恰恰是最典型的「受影响各方」。
        previous_owner = report.owner_staff_id
        report_status_before = report.status
        reject_reason_before = report.reject_reason

        # ⚠️⚠️ **改判 = 认定系统判错了 ⇒ 被驳回的状态要恢复**
        # （否则这条报备仍带着 `rejected_invalid` 与驳回原因，下游按 status
        #   取数时**仍把它当成被否决的报备** ⇒ 改判只改了归属、没改结论。）
        report.status = "accepted"
        report.reject_reason = None

        result = recompute_attribution(session, report)
        new_owner = report.owner_staff_id
        attribution_detail = {
            "report_id": str(report.id),
            "channel_id": str(report.channel_id),
            "customer_id": str(report.customer_id),
            "reported_at": report.reported_at.isoformat(),
            # ⚠️ **旧归属人**也要进审计 ⇒ 否则「谁失去了归属」查不到。
            "previous_owner_staff_id": str(previous_owner) if previous_owner else None,
            "owner_staff_id": str(new_owner) if new_owner else None,
            "basis": result.basis,
            "candidates_considered": result.candidates_considered,
            # ⚠️ 判定要能**复现**：获胜的是哪条报备、候选集是哪些。
            "winning_report_id": result.winning_report_id,
            "winning_report_reported_at": result.winning_report_reported_at,
            "candidate_ids": list(result.candidate_ids),
            "strategy": result.strategy,
            "report_status_before": report_status_before,
            "report_status_after": report.status,
            "reject_reason_before": reject_reason_before,
        }
        write_audit(
            session,
            org_id=report.org_id,
            site_id=report.site_id,
            actor_id=str(approver_id),
            target_type="report",
            target_id=report.id,
            action="attribution.recompute",
            before_status=report_status_before,
            after_status=report.status,
            reason=reason.strip(),
            detail=attribution_detail,
        )
        # ---- 通知受影响各方（桩）----
        _notify(
            session,
            str(dispute.disputer_id),
            "dispute.overturned",
            {
                "dispute_id": str(dispute.id),
                "reason": reason.strip(),
                **attribution_detail,
            },
        )
        # ⚠️ **新归属人**（获得归属）。
        if new_owner:
            _notify(
                session,
                str(new_owner),
                "attribution.gained",
                {
                    "dispute_id": str(dispute.id),
                    "report_id": str(report.id),
                    "owner_staff_id": str(new_owner),
                    "previous_owner_staff_id": (
                        str(previous_owner) if previous_owner else None
                    ),
                },
            )
        # ⚠️ **旧归属人**（失去归属）—— 工单明写「通知受影响各方」，
        #    而**归属被夺走的一方**是最典型的受影响方 ⇒ 必须通知。
        #    ⚠️ 新旧同一人时**不重复通知**。
        if previous_owner and previous_owner != new_owner:
            _notify(
                session,
                str(previous_owner),
                "attribution.lost",
                {
                    "dispute_id": str(dispute.id),
                    "report_id": str(report.id),
                    "previous_owner_staff_id": str(previous_owner),
                    "owner_staff_id": str(new_owner) if new_owner else None,
                },
            )

    return {
        "effective": True,
        "status": dispute.status,
        "satisfied_roles": list(outcome.satisfied_roles),
        "missing_roles": [],
        "attribution": attribution_detail,
    }


def remind_overdue_disputes(
    session: Session,
    *,
    days: int = 10,
    now: datetime | None = None,
    owner_recipient: str = "channel_manager",
) -> int:
    """提醒**超过 N 天未处理**的争议的负责人。

    ⚠️ **幂等**：已提醒过的（`reminded_at` 非空）不再重复提醒 ⇒ 定时任务
    每次跑不会重复骚扰。
    """
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(days=days)
    stmt = (
        select(RefDispute)
        .where(
            RefDispute.status == "pending",
            RefDispute.deleted_at.is_(None),
            RefDispute.created_at <= cutoff,
            RefDispute.reminded_at.is_(None),
        )
        .order_by(RefDispute.created_at.asc())
    )
    disputes = list(session.scalars(stmt))
    for d in disputes:
        d.reminded_at = current
        _notify(
            session,
            owner_recipient,
            "dispute.overdue",
            {
                "dispute_id": str(d.id),
                "age_days": days,
                "created_at": d.created_at.isoformat(),
            },
        )
        write_audit(
            session,
            org_id=d.org_id,
            site_id=d.site_id,
            actor_id="system",
            target_type="dispute",
            target_id=d.id,
            action="dispute.remind_overdue",
            before_status=d.status,
            after_status=d.status,
            reason=f"争议已超过 {days} 天未处理",
            detail={"age_days": days},
        )
    return len(disputes)
