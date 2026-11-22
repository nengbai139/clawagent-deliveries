"""**验收标准**的测试（逐条对应工单的 acceptance_criteria）。

工单原文的三条：
1. 只有一个角色审批时改判不生效，两个不同的人分别以两种角色审批后生效（有测试）
2. 同一个人同时拥有两个角色时，重复审批不计为双人审批（有测试）
3. 改判后按原报备时间重新判定归属，结果写入审计日志（集成测试）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AuditLog, DisputeApproval
from app.services import dispute as dispute_svc
from app.services.approval import ApprovalError, apply_approval, evaluate_quorum
from app.services.review import mark_verified
from tests.conftest import give_roles, make_report


def _submit(session: Session, org_id, report, *, code="wrong_attribution"):
    return dispute_svc.submit_dispute(
        session,
        report,
        disputer_id=uuid.uuid4(),
        disputer_type="staff",
        reason_code=code,
        reason_text="系统把这条判成重复了，实际是不同联系人",
        attachments=[],
    )


# ==================================================================
# 验收标准 1：只有一个角色审批时改判不生效；两个不同的人分别以两种
#              角色审批后生效
# ==================================================================

def test_criterion1_single_role_approval_does_not_take_effect(session: Session, org_id):
    """**一个**角色审批 ⇒ 改判**不生效**（状态仍是 pending）。"""
    report = make_report(session, org_id, status="rejected_invalid")
    dispute = _submit(session, org_id, report)

    manager = uuid.uuid4()
    give_roles(session, org_id, manager, "channel_manager")

    outcome = apply_approval(
        session, dispute, approver_id=manager, role="channel_manager",
        decision="overturn", comment="第一次",
    )
    session.flush()

    assert outcome.quorum_reached is False
    assert outcome.satisfied_roles == ("channel_manager",)
    assert outcome.missing_roles == ("finance",)
    # ⚠️ **状态没变**——没达成双人审批就不能改判。
    assert dispute.status == "pending"


def test_criterion1_two_different_people_two_roles_takes_effect(session: Session, org_id):
    """**两个不同的人**分别以两种角色审批 ⇒ 改判**生效**。"""
    report = make_report(session, org_id, status="rejected_invalid")
    dispute = _submit(session, org_id, report)

    manager = uuid.uuid4()
    finance = uuid.uuid4()
    assert manager != finance
    give_roles(session, org_id, manager, "channel_manager")
    give_roles(session, org_id, finance, "finance")

    # 第一次：只有 channel_manager ⇒ 不生效
    o1 = apply_approval(
        session, dispute, approver_id=manager, role="channel_manager",
        decision="overturn", comment="一",
    )
    session.flush()
    assert o1.quorum_reached is False
    assert dispute.status == "pending"

    # 第二次：**另一个人**以 finance 审批 ⇒ 达成 ⇒ 生效
    o2 = apply_approval(
        session, dispute, approver_id=finance, role="finance",
        decision="overturn", comment="二",
    )
    session.flush()
    assert o2.quorum_reached is True
    assert set(o2.satisfied_roles) == {"channel_manager", "finance"}
    assert o2.missing_roles == ()

    quorum, satisfied, missing = evaluate_quorum(session, dispute.id)
    assert quorum is True
    assert missing == ()


# ==================================================================
# 验收标准 2：同一个人同时拥有两个角色时，重复审批不计为双人审批
# ==================================================================

def test_criterion2_same_person_two_roles_is_not_dual_approval(session: Session, org_id):
    """**同一个人**有两个角色 ⇒ 重复审批**不计**为双人审批。"""
    report = make_report(session, org_id, status="rejected_invalid")
    dispute = _submit(session, org_id, report)

    one_person = uuid.uuid4()
    give_roles(session, org_id, one_person, "channel_manager", "finance")

    # 他以第一个角色批了一次
    o1 = apply_approval(
        session, dispute, approver_id=one_person, role="channel_manager",
        decision="overturn", comment="第一次",
    )
    session.flush()
    assert o1.quorum_reached is False

    # 他想用第二个角色再批一次 ⇒ **被拒**
    with pytest.raises(ApprovalError) as exc:
        apply_approval(
            session, dispute, approver_id=one_person, role="finance",
            decision="overturn", comment="第二次",
        )
    assert exc.value.code == "same_person_already_approved"

    # ⇒ 只有一个审批人 ⇒ **不构成双人审批**
    quorum, satisfied, missing = evaluate_quorum(session, dispute.id)
    assert quorum is False
    assert missing == ("finance",)
    approvals = list(
        session.scalars(
            select(DisputeApproval).where(DisputeApproval.dispute_id == dispute.id)
        )
    )
    assert len(approvals) == 1
    assert approvals[0].approver_id == one_person


def test_criterion2_same_person_two_roles_via_direct_rows_also_not_dual(
    session: Session, org_id
):
    """**绕过应用层**（直接写两行同一人两个角色的审批）⇒ 仍不算双人审批。

    ⚠️ 这条是**兜底**：验收标准 2 说的是「重复审批不计为双人审批」，
    而「双人」这个性质必须由**判定**保证，不能只由**写入**保证——
    否则换一条写入路径（数据修复、脚本）就能把它绕过去。
    """
    report = make_report(session, org_id, status="rejected_invalid")
    dispute = _submit(session, org_id, report)

    one_person = uuid.uuid4()
    give_roles(session, org_id, one_person, "channel_manager", "finance")
    # 直接塞两行审批记录（同一人、两个角色）——绕过 `apply_approval` 的检查。
    for role in ("channel_manager", "finance"):
        session.add(
            DisputeApproval(
                org_id=org_id,
                dispute_id=dispute.id,
                approver_id=one_person,
                approver_role=role,
                decision="overturn",
            )
        )
    session.flush()

    quorum, satisfied, missing = evaluate_quorum(session, dispute.id)
    assert quorum is False
    assert missing == ("finance",)


def test_criterion2_distinct_people_with_overlapping_roles_still_dual(
    session: Session, org_id
):
    """A 有两个角色、B 有一个角色 ⇒ A、B 各批一次**仍是**双人审批。"""
    report = make_report(session, org_id, status="rejected_invalid")
    dispute = _submit(session, org_id, report)

    a = uuid.uuid4()
    b = uuid.uuid4()
    give_roles(session, org_id, a, "channel_manager", "finance")
    give_roles(session, org_id, b, "finance")

    apply_approval(session, dispute, approver_id=a, role="channel_manager",
                   decision="overturn", comment="a")
    session.flush()
    o2 = apply_approval(session, dispute, approver_id=b, role="finance",
                         decision="overturn", comment="b")
    session.flush()
    assert o2.quorum_reached is True


# ==================================================================
# 验收标准 3：改判后按原报备时间重新判定归属，结果写入审计日志
# ==================================================================

def test_criterion3_recompute_attribution_by_original_reported_at(
    session: Session, org_id
):
    """改判后**按原报备时间**重新判定归属，结果写入审计日志（集成测试）。"""
    base = datetime.now(UTC) - timedelta(days=10)

    channel_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    early_owner = uuid.uuid4()

    # ⚠️⚠️ **「更早的报备」必须先 `created_at`（后 `reported_at`）**——
    # 这两条时间**故意反向**！
    #
    # 原因：归属重算的基准是 **`reported_at`（原报备时间）**，而
    # `created_at` 是**入库时间**（可被迁移/导入改写）。若两者顺序一致 ⇒
    # 用哪个算都一样 ⇒ **测不出**「有没有真的用 reported_at」⇒
    # 变异（改成 created_at）照样绿 ⇒ 门是**假的**。
    #
    # ⇒ 构造出「created_at 晚、reported_at 早」的样本 ⇒ 两个基准给出
    # **不同**答案 ⇒ 变异立刻暴露。
    early = make_report(
        session, org_id,
        status="verified",
        reported_at=base,                       # ← **原报备时间更早**
        owner_staff_id=early_owner,
        channel_id=channel_id,
        customer_id=customer_id,
    )
    # 把它的**入库时间**推到 base 之后（模拟「后导入的旧报备」）。
    early.created_at = base + timedelta(days=5)

    # 本次争议针对的报备：**reported_at 晚**，但 created_at 更早。
    late = make_report(
        session, org_id,
        status="rejected_invalid",
        reported_at=base + timedelta(minutes=10),  # ← 原报备时间更晚
        owner_staff_id=uuid.uuid4(),
        channel_id=channel_id,
        customer_id=customer_id,
    )
    # ⚠️⚠️ `late.created_at` 必须**早于** `early.reported_at`——
    # 这样「按 created_at 找更早的报备」会**找不到** early ⇒ 两种基准给出
    # **不同**答案 ⇒ 变异（改成 created_at）立刻暴露。
    #
    # 若只是让两者顺序相反但区间重叠（如 late.created_at 更晚）⇒
    # 两种查询**都**能查到 early ⇒ 结果一样 ⇒ **测不出** ⇒ 门是假的。
    late.created_at = base - timedelta(days=1)
    session.flush()

    assert late.owner_staff_id != early_owner
    # ⚠️ **前置断言**：确认两个时间基准给出**不同**的候选集
    # （否则下面的断言没有区分力）。
    assert early.reported_at < late.reported_at, "reported_at 顺序应相反"
    assert early.created_at > late.created_at, "created_at 顺序应相反"
    # ⚠️ **关键前置断言**：按 `created_at` 找，**找不到** early。
    assert late.created_at < early.reported_at, (
        "created_at 基准必须落在 early.reported_at 之前，"
        "否则两种基准结果相同、测不出差异"
    )

    dispute = _submit(session, org_id, late)

    manager = uuid.uuid4()
    finance = uuid.uuid4()
    give_roles(session, org_id, manager, "channel_manager")
    give_roles(session, org_id, finance, "finance")
    apply_approval(session, dispute, approver_id=manager, role="channel_manager",
                   decision="overturn", comment="改判")
    session.flush()
    result = dispute_svc.decide_dispute(
        session, dispute, approver_id=finance, role="finance",
        decision="overturn", reason="系统归一化误判为重复",
    )
    session.flush()

    # ⚠️ **改判生效**
    assert result["effective"] is True
    assert dispute.status == "overturned"

    # ⚠️ **归属按原报备时间重算** ⇒ 更早的报备优先 ⇒ 归给 early_owner
    session.refresh(late)
    assert late.owner_staff_id == early_owner

    # ⚠️ **重算结果写入审计日志**
    audit = list(
        session.scalars(
            select(AuditLog).where(
                AuditLog.target_type == "report",
                AuditLog.target_id == late.id,
                AuditLog.action == "attribution.recompute",
            )
        )
    )
    assert len(audit) == 1
    entry = audit[0]
    assert entry.actor_id == str(finance)
    assert entry.reason == "系统归一化误判为重复"
    assert entry.detail is not None
    assert "reported_at" in entry.detail
    assert "owner_staff_id" in entry.detail
    assert "basis" in entry.detail


def test_criterion3_audit_has_actor_before_after_reason(session: Session, org_id):
    """审计日志必须含「操作人、前后状态、理由」（工单原文）。"""
    report = make_report(session, org_id, status="accepted")
    reviewer = str(uuid.uuid4())

    mark_verified(session, report, reviewer, reason="资料齐全")
    session.flush()

    entries = list(
        session.scalars(
            select(AuditLog).where(
                AuditLog.target_id == report.id, AuditLog.action == "review.verify"
            )
        )
    )
    assert len(entries) == 1
    e = entries[0]
    assert e.actor_id == reviewer
    assert e.before_status == "accepted"
    assert e.after_status == "verified"
    assert e.reason == "资料齐全"


def test_criterion3_dispute_decision_written_to_audit(session: Session, org_id):
    """改判本身也要写审计（前后状态 + 理由）。"""
    report = make_report(session, org_id, status="rejected_invalid")
    dispute = _submit(session, org_id, report)
    manager = uuid.uuid4()
    finance = uuid.uuid4()
    give_roles(session, org_id, manager, "channel_manager")
    give_roles(session, org_id, finance, "finance")
    apply_approval(session, dispute, approver_id=manager, role="channel_manager",
                   decision="overturn", comment="一")
    session.flush()
    dispute_svc.decide_dispute(
        session, dispute, approver_id=finance, role="finance",
        decision="overturn", reason="改判理由",
    )
    session.flush()

    entries = list(
        session.scalars(
            select(AuditLog).where(
                AuditLog.target_type == "dispute",
                AuditLog.target_id == dispute.id,
                AuditLog.action == "dispute.overturn",
            )
        )
    )
    assert len(entries) == 1
    assert entries[0].before_status == "pending"
    assert entries[0].after_status == "overturned"
    assert entries[0].reason == "改判理由"
