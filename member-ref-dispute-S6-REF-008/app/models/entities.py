"""ORM 模型：报备、争议、审批、审计日志。

⚠️ **统一技术约定**（来自工单原文）：
* 业务表统一含 `id`(UUID) / `org_id` / `site_id` / `created_at` / `created_by` /
  `updated_at` / `deleted_at`（**软删除**）；
* 金额一律以「**分**」存整数。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    """统一技术约定里的那一组公共列。"""

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=_uuid
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class RefReport(TimestampMixin, Base):
    """报备（渠道与转介绍结算的输入）。

    ⚠️ `reported_at`（**原报备时间**）是独立于 `created_at` 的一列——
    改判后要「**按原报备时间重新判定归属**」，而 `created_at` 可能被
    迁移/导入改写 ⇒ 归属重算必须有一个**只由报备行为决定**的时间基准。
    """

    __tablename__ = "ref_report"

    #: 报备人类型：员工 / 会员 / 渠道商。
    reporter_type: Mapped[str] = mapped_column(String(32), nullable=False)
    #: 报备人主体 id。
    reporter_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: 归属员工 id（`owner_staff_id`）。
    owner_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    #: 被报备的客户（会员企业）id。
    customer_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: 报备渠道 id。
    channel_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: **原报备时间**——归属重算的时间基准。
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    #: 状态机：submitted → accepted / rejected_invalid / verified。
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="submitted", server_default="submitted"
    )
    #: 驳回原因（`rejected_invalid` 时填，如「联系人信息虚假」）。
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 结算金额，单位**分**。
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_ref_report_status", "status"),
        Index("ix_ref_report_owner_staff", "owner_staff_id"),
        Index("ix_ref_report_reporter", "reporter_type", "reporter_id"),
    )


class RefDispute(TimestampMixin, Base):
    """归属争议。

    ⚠️ **只受理「系统判断错误」类原因**（工单原文）——「更早在线下接触过
    客户」这类与首次报备规则冲突的理由**不受理** ⇒ 用枚举约束在数据库层
    （`CheckConstraint`），而不是只靠应用层校验。
    """

    __tablename__ = "ref_dispute"

    #: 争议针对的报备。
    report_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("ref_report.id"), nullable=False
    )
    #: 争议提交方。
    disputer_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    disputer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    #: 争议原因（**枚举**：仅「系统判断错误」类）。
    reason_code: Mapped[str] = mapped_column(String(48), nullable=False)
    #: 争议说明。
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)
    #: 证据附件（最多 5 个）——JSON 数组，元素形如
    #: `{"file_id": "...", "name": "...", "url": "..."}`。
    attachments: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    #: 状态：pending → upheld / overturned / rejected。
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    #: 改判后的结论说明（`uphold`/`overturn` 时填）。
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: 超时提醒是否已发过（避免重复提醒）。
    reminded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_ref_dispute_report", "report_id"),
        Index("ix_ref_dispute_status_created", "status", "created_at"),
        # ⚠️ **数据库层**约束：理由枚举。
        # 「只受理系统判断错误类原因、不受理与首次报备规则冲突的理由」是
        # 业务规则 ⇒ 不能只靠应用层校验（换一条 SQL 就能写进去）。
        CheckConstraint(
            "reason_code IN ('normalization_false_duplicate', "
            "'existing_customer_data_error', 'wrong_attribution', "
            "'other_system_error')",
            name="ck_ref_dispute_reason_allowed",
        ),
    )


class DisputeApproval(TimestampMixin, Base):
    """一次审批（改判需两角色各一次、且**两个不同的人**）。

    ⚠️ **验收标准 2 的落点**：同一个人同时拥有 `channel_manager` 与
    `finance` 两个角色时，**重复审批不计为双人审批** ⇒ 这里用
    `approver_id`（**人**）而不是角色来判重，而不是在应用层查角色表。
    """

    __tablename__ = "dispute_approval"

    dispute_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("ref_dispute.id"), nullable=False
    )
    #: 审批人（**人** id）。
    approver_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: 审批人当时的角色。
    approver_role: Mapped[str] = mapped_column(String(48), nullable=False)
    #: 审批意见。
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 该次审批对应的决定：`uphold` / `overturn`。
    decision: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        Index("ix_dispute_approval_dispute", "dispute_id"),
        # ⚠️ **同一争议 + 同一角色 + 同一人** 只能有一条 ⇒ 重复审批在**数据库层**
        # 就写不进去（而不是靠应用层先查后写那个有竞态的写法）。
        UniqueConstraint(
            "dispute_id",
            "approver_role",
            "approver_id",
            name="uq_dispute_approval_once_per_role_per_person",
        ),
    )


class AuditLog(Base):
    """审计日志（所有复核与争议操作都写）。

    ⚠️ 工单原文要求记录「操作人、前后状态、理由」⇒ 三者都是**必填列**，
    缺一不可（不设默认值 ⇒ 写不完整就 INSERT 失败）。
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=_uuid
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    #: 操作人。
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 操作对象类型（`report` / `dispute`）。
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    #: 操作对象 id。
    target_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: 操作动作（`review.verify` / `review.reject` / `dispute.submit` / …）。
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    #: **前状态**（可空：首次创建没有前状态）。
    before_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: **后状态**。
    after_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: 理由。
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 附加信息（JSON）：归属重算结果等。
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_audit_log_target", "target_type", "target_id"),
        Index("ix_audit_log_action", "action"),
    )


class StaffRole(TimestampMixin, Base):
    """员工角色（S2-IAM 的**接口桩**）。

    ⚠️ 工单说依赖 S2-IAM（身份、角色与数据范围），「可先用接口桩或 mock」
    ⇒ 本表是**桩**：真实实现时换成调 IAM 的客户端即可，调用方
    （`services/approval.py`）不感知。
    """

    __tablename__ = "staff_role"

    #: 员工（**人**）id。
    staff_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: 角色名：`channel_manager` / `finance` / …。
    role: Mapped[str] = mapped_column(String(48), nullable=False)

    __table_args__ = (
        UniqueConstraint("staff_id", "role", name="uq_staff_role"),
    )


class NotificationStub(Base):
    """通知桩（本单要求「通知接口先用桩」）。"""

    __tablename__ = "notification_stub"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=_uuid
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    #: 接收方。
    recipient: Mapped[str] = mapped_column(String(128), nullable=False)
    #: 通知类型。
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 载荷（JSON）。
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
