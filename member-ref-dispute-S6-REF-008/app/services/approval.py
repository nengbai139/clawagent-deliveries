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


def roles_of(
    session: Session, staff_id: uuid.UUID, org_id: uuid.UUID | None = None
) -> set[str]:
    """取一个员工的角色集合（**S2-IAM 的接口桩**）。

    ⚠️ 真实实现时换成调 IAM 的客户端即可 ⇒ 调用方（下面的
    `apply_approval`）**不感知**桩与真接口的区别。

    ⚠️⚠️ **必须按 `org_id` 过滤**（跨租户越权）：同一个 `staff_id` 若在
    另一个 org 下持有 `channel_manager`，不该能审批**本 org** 的争议
    ⇒ 而审批记录里的 `org_id` 是从争议拷贝的 ⇒ 事后**看不出**越权。
    """
    stmt = select(StaffRole.role).where(
        StaffRole.staff_id == staff_id, StaffRole.deleted_at.is_(None)
    )
    if org_id is not None:
        stmt = stmt.where(StaffRole.org_id == org_id)
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

    ⚠️⚠️ **未达成时也要报出「已满足哪些」**（不能一律报成「一个都没满足」）：
    接口契约是 `missing_roles` = **还缺哪个角色** ⇒ 只审批了
    `channel_manager` 的人看到的必须是 `["finance"]` ⇒ 如果这里报成
    `["channel_manager", "finance"]`，调用方会以为**刚批的那次没生效**
    ⇒ 会重复审批（被 409 挡下）⇒ 调用方一脸困惑。
    """
    approvals = _existing_approvals(session, dispute_id)
    # ⚠️ **决策必须一致**：两人对同一争议投了**不同**结论 ⇒ 不算达成
    # （否则「最后一个人写什么就按什么生效」⇒ 一人的反对被悄悄吞掉）。
    if len({a.decision for a in approvals}) > 1:
        return False, (), REQUIRED_ROLES

    # 角色 ⇒ 审批人集合。
    role_to_approvers: dict[str, set[uuid.UUID]] = {}
    for ap in approvals:
        role_to_approvers.setdefault(ap.approver_role, set()).add(ap.approver_id)

    # ⚠️ 取**最大匹配**（能配几个角色就配几个）⇒ 已配上的角色就是
    # 「已满足」⇒ 没配上的就是「还缺」。
    matched = _match_roles_to_people(role_to_approvers)
    satisfied_t = tuple(r for r in REQUIRED_ROLES if r in matched)
    missing = tuple(r for r in REQUIRED_ROLES if r not in satisfied_t)
    return (not missing), satisfied_t, missing


def _match_roles_to_people(
    role_to_approvers: dict[str, set[uuid.UUID]],
) -> dict[str, uuid.UUID]:
    """把角色配给**互不相同的人**（**增广路二分图匹配**，Kuhn 算法）。

    返回 `角色 → 人` 的**最大匹配**（可能是**部分**匹配：凑不齐就是凑不齐）。

    ⚠️⚠️ **配对的单位是「人」**：同一个人**只能占一个角色** ⇒
    「同一人持两角色各批一次」**配不出**两个角色 ⇒ 判定为未达成。

    ⚠️⚠️ **不能用贪心**（「按 UUID 序取第一个未被占用的人」）：
    贪心在这种数据上会**假阴性**——

        审批行 = (P, channel_manager)、(P, finance)、(Q, channel_manager)
        且 P 的 UUID 串序 < Q
    ⇒ 贪心把 P 配给 channel_manager ⇒ finance 只剩 P（已占用）⇒
    ⇒ 判成「无人可配」⇒ **漏判**（其实存在合法匹配 cm=Q, fin=P）。

    ⇒ 这里用**增广路**⇒ 判定是**充要**的（存在合法匹配 ⇔ 达成双人审批）。

    ⚠️ 这不是理论洁癖：验收标准 2 的**兜底判定**依赖它判得准 ——
    判漏了 ⇒ 同一人两角色会被误判成「双人」⇒ **验收标准 2 直接失效**。

    ⚠️⚠️ **「这个人已被占用」时改配失败，必须换下一个人**（不能直接占用）：
    否则 `(P, cm)`、`(P, fin)` 这种数据会把 **P 配给两个角色**
    ⇒ 同一个人凑成「双人」⇒ 验收标准 2 **直接失效**。
    """
    #: 角色 → 人。
    assigned: dict[str, uuid.UUID] = {}
    #: 人 → 角色（**反向索引**，用来判断「这个人是否已被占用」）。
    person_to_role: dict[uuid.UUID, str] = {}

    def augment(role: str, visited: set[uuid.UUID]) -> bool:
        """给 `role` 找一个人；对方已被占用就**改配**，改配不成**换下一个人**。"""
        for person in sorted(role_to_approvers.get(role, set()), key=str):
            if person in visited:
                continue
            visited.add(person)
            held_role = person_to_role.get(person)
            if held_role is not None:
                # 这个人已配给别的角色 ⇒ 试着把那个角色改配给别人。
                # ⚠️ 改配失败 ⇒ **换下一个人**（不能直接占用 ⇒ 那会让
                #    同一个人占两个角色 ⇒ 双人审批形同虚设）。
                if augment(held_role, visited):
                    assigned[role] = person
                    person_to_role[person] = role
                    return True
                continue
            # 这个人**还没被占用** ⇒ 直接配给他。
            assigned[role] = person
            person_to_role[person] = role
            return True
        return False

    # ⚠️ **不中途放弃**：某个角色配不上就**继续**下一个 ⇒ 得到的是
    # **最大匹配**（能配几个算几个）⇒ 未配上的角色就是「还缺的角色」。
    for role in REQUIRED_ROLES:
        augment(role, set())
    return assigned


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

    # ⚠️⚠️ **必须先锁住争议行**（并发原子性）：
    #
    # 两个人**同时**提交两个角色的审批时，各自的 `evaluate_quorum` 在
    # PostgreSQL 默认 READ COMMITTED 下**看不到对方未提交的审批行**
    # ⇒ 双方都判定「还差一个角色」⇒ **没有任何一方把争议翻成 overturned**
    # ⇒ 争议永远卡在 pending，而审批表里已经有两条合法审批
    # ⇒ ⇒ **验收标准 1 在并发下不成立**。
    #
    # ⇒ `SELECT ... FOR UPDATE` 把争议行锁住 ⇒ 第二个审批**等**第一个提交
    # ⇒ 之后它能看见对方已提交的审批行 ⇒ 达成。
    locked = session.execute(
        select(RefDispute).where(RefDispute.id == dispute.id).with_for_update()
    ).scalar_one_or_none()
    if locked is None:
        raise ApprovalError("dispute_not_found", "争议不存在")
    # ⚠️ 用**锁内读到的**状态重新判断（外层对象可能是过期的快照）。
    if locked.status != "pending":
        raise ApprovalError(
            "dispute_not_pending", f"争议状态为 {locked.status}，不可再审批"
        )
    dispute = locked

    # ---- 角色必须**真的**是这个人的（且在**本 org**）----
    actual_roles = roles_of(session, approver_id, dispute.org_id)
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
