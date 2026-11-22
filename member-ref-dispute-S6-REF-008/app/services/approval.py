"""改判的**双人审批**逻辑。

⚠️ **验收标准 1**：只有一个角色审批时改判不生效，**两个不同的人**分别以
两种角色审批后生效。
⚠️ **验收标准 2**：**同一个人**同时拥有两个角色时，**重复审批不计为双人审批**。

⇒ ⇒ 判据是「**审批人（人）**」而不是「审批人拥有的**角色**」。
    一个人有 `channel_manager` + `finance` 两个角色，他点两次也只算**一次**。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import DisputeApproval, RefDispute, StaffRole

#: 改判需要的两个角色，**两个不同的人**各审批一次。
REQUIRED_ROLES: tuple[str, str] = ("channel_manager", "finance")


class ApprovalError(Exception):
    """审批被拒。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ApprovalOutcome:
    """一次审批的结果。"""

    #: 是否**已达成**改判条件（两角色、不同的人）。
    quorum_reached: bool
    #: 已满足的角色（有序）。
    satisfied_roles: tuple[str, ...]
    #: 还缺的角色。
    missing_roles: tuple[str, ...]
    #: 是否因为「同一人重复审批」而被拒。
    rejected_same_person: bool


def roles_of(session: Session, staff_id: uuid.UUID) -> set[str]:
    """取一个员工的角色集合（**S2-IAM 的接口桩**）。

    ⚠️ 真实实现时换成调 IAM 的客户端即可 ⇒ 调用方（下面的
    `apply_approval`）**不感知**桩与真接口的区别。
    """
    stmt = select(StaffRole.role).where(
        StaffRole.staff_id == staff_id, StaffRole.deleted_at.is_(None)
    )
    return set(session.scalars(stmt))


def _existing_approvals(
    session: Session, dispute_id: uuid.UUID
) -> list[DisputeApproval]:
    stmt = (
        select(DisputeApproval)
        .where(
            DisputeApproval.dispute_id == dispute_id,
            DisputeApproval.deleted_at.is_(None),
        )
        .order_by(DisputeApproval.created_at.asc())
    )
    return list(session.scalars(stmt))


def evaluate_quorum(
    session: Session, dispute_id: uuid.UUID
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    """判断是否已达成「两角色、两个不同的人」。

    返回 `(是否达成, 已满足角色, 缺失角色)`。

    ⚠️ **「不同的人」是这里的核心**：同一个人用两个角色各批一次 ⇒
    已满足角色集合虽然有两个，但**审批人只有一个** ⇒ **不算达成**。
    """
    approvals = _existing_approvals(session, dispute_id)
    # 角色 ⇒ 审批人。同一角色被同一人批过 ⇒ 只记一次（不同人各批一次
    # 也只算该角色一次，因为角色只需要**一次**审批）。
    role_to_approvers: dict[str, set[uuid.UUID]] = {}
    for ap in approvals:
        role_to_approvers.setdefault(ap.approver_role, set()).add(ap.approver_id)

    satisfied: list[str] = []
    # ⚠️ **角色与审批人是一一对应地配对**：「两个不同的人」要求
    # 两个角色**分别由两个不同的人**批 ⇒ 用**二分图匹配**的思路：
    # 每个角色挑一个审批人，且挑出来的**人互不相同**。
    used_people: set[uuid.UUID] = set()
    for role in REQUIRED_ROLES:
        approvers = role_to_approvers.get(role)
        if not approvers:
            continue
        # 挑一个**还没被别的角色占用**的人。
        picked = None
        for person in sorted(approvers, key=str):
            if person not in used_people:
                picked = person
                break
        if picked is None:
            # 这个角色只有已被占用的人 ⇒ 换个人来批才算数。
            continue
        used_people.add(picked)
        satisfied.append(role)

    satisfied_t = tuple(satisfied)
    missing = tuple(r for r in REQUIRED_ROLES if r not in satisfied_t)
    return (not missing), satisfied_t, missing


def apply_approval(
    session: Session,
    dispute: RefDispute,
    approver_id: uuid.UUID,
    role: str,
    decision: str,
    comment: str | None = None,
) -> ApprovalOutcome:
    """记录一次审批，并判定是否达成改判条件。

    ⚠️ **失败关闭**：缺角色、越权、重复审批 ⇒ **抛 `ApprovalError`**，
    不写任何东西。
    """
    if dispute.status != "pending":
        raise ApprovalError(
            "dispute_not_pending", f"争议状态为 {dispute.status}，不可再审批"
        )
    if decision not in ("uphold", "overturn"):
        raise ApprovalError("bad_decision", "decision 只能是 uphold 或 overturn")
    if role not in REQUIRED_ROLES:
        raise ApprovalError(
            "bad_role", f"角色 {role} 不在改判所需角色 {REQUIRED_ROLES} 内"
        )

    # ---- 角色必须**真的**是这个人的 ----
    actual_roles = roles_of(session, approver_id)
    if role not in actual_roles:
        raise ApprovalError(
            "role_not_held", f"该员工不具备角色 {role}（现有：{sorted(actual_roles)}）"
        )

    # ---- ⚠️ 验收标准 2：同一个人**已经用别的角色**批过 ⇒ 本次不计 ----
    #    （他即使有第二个角色，也**不能**凑成「两个人」）
    for ap in _existing_approvals(session, dispute.id):
        if ap.approver_id == approver_id:
            raise ApprovalError(
                "same_person_already_approved",
                "该员工已就本争议审批过；同一人重复审批不计为双人审批",
            )

    # ---- 写审批记录 ----
    session.add(
        DisputeApproval(
            org_id=dispute.org_id,
            site_id=dispute.site_id,
            dispute_id=dispute.id,
            approver_id=approver_id,
            approver_role=role,
            decision=decision,
            comment=comment,
        )
    )
    session.flush()

    quorum, satisfied, missing = evaluate_quorum(session, dispute.id)
    return ApprovalOutcome(
        quorum_reached=quorum,
        satisfied_roles=satisfied,
        missing_roles=missing,
        rejected_same_person=False,
    )
