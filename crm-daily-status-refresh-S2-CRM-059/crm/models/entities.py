"""ORM 模型。

⚠️⚠️ **哪些表是本单建的，哪些不是**（这一条很容易搞错 ⇒ 后果是「测试跑的是
另一套东西」）：

| 表 | 归属 | 本单的迁移建它吗 |
|---|---|---|
| `crm_job_run` | **本单**（工单原文：「写入新表 crm_job_run … 迁移包含在本单」） | ✅ 建 |
| `crm_membership` | 「CRM 核心对象」别的工单 | ❌ 不建（测试夹具里建） |
| `crm_contract` | 同上 | ❌ 不建 |
| `crm_payment_plan` | 「回款计划」别的工单 | ❌ 不建 |
| `crm_change_history` | 「变更历史」别的工单 | ❌ 不建 |

⇒ 本单的 Alembic 迁移**只建 `crm_job_run`**；其余四张表在本单里**只有 ORM
声明**（别的工单合入后它们由各自的迁移建表）⇒ 测试夹具用 `create_all` 建
它们（测试专用路径，README 里写明）。

⇒ ⚠️ **每张表都带统一约定的那组公共列**：id(UUID) / org_id / site_id /
created_at / created_by / updated_at / deleted_at（**软删除**）。
⇒ 金额一律以「**分**」存整数。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
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


# ---------------------------------------------------------------- 会籍

#: 会籍状态取值。
#: ⚠️ `terminated`（终止）与 `suspended`（挂起）是**终态/人工状态**
#: ⇒ 工单原文：这两种**不参与派生**（系统不碰人工做过的决定）。
MEMBERSHIP_STATUS_ACTIVE = "active"
MEMBERSHIP_STATUS_EXPIRING = "expiring"
MEMBERSHIP_STATUS_EXPIRED = "expired"
MEMBERSHIP_STATUS_TERMINATED = "terminated"
MEMBERSHIP_STATUS_SUSPENDED = "suspended"

#: **不参与派生**的会籍状态。
MEMBERSHIP_STATUS_EXCLUDED: tuple[str, ...] = (
    MEMBERSHIP_STATUS_TERMINATED,
    MEMBERSHIP_STATUS_SUSPENDED,
)


class Membership(TimestampMixin, Base):
    """会籍（**属别的工单**，这里只声明模型）。"""

    __tablename__ = "crm_membership"

    #: 会籍所属会员企业。
    member_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: 会籍类型/档位。
    tier_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: 会籍状态（见 `MEMBERSHIP_STATUS_*`）。
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MEMBERSHIP_STATUS_ACTIVE
    )
    #: 生效日 / 到期日。
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: 会籍金额（**分**）。
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_crm_membership_status", "status"),
        Index("ix_crm_membership_member", "member_id"),
    )


# ---------------------------------------------------------------- 合同

CONTRACT_STATUS_ACTIVE = "active"
CONTRACT_STATUS_EXPIRED = "expired"
CONTRACT_STATUS_TERMINATED = "terminated"


class Contract(TimestampMixin, Base):
    """合同（**属别的工单**，这里只声明模型）。"""

    __tablename__ = "crm_contract"

    #: 合同所属会员企业。
    member_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: 关联会籍（可空：有些合同不挂会籍）。
    membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    #: 合同状态。
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CONTRACT_STATUS_ACTIVE
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: 合同金额（**分**）。
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_crm_contract_status", "status"),
        Index("ix_crm_contract_end_date", "end_date"),
    )


# ---------------------------------------------------------------- 回款计划（期次）

PAYMENT_STATUS_PENDING = "pending"
PAYMENT_STATUS_DUE = "due"
PAYMENT_STATUS_OVERDUE = "overdue"
PAYMENT_STATUS_PAID = "paid"
PAYMENT_STATUS_WRITTEN_OFF = "written_off"

#: **不参与派生**的回款状态（已结清 / 已核销 ⇒ 系统不碰）。
PAYMENT_STATUS_EXCLUDED: tuple[str, ...] = (
    PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_WRITTEN_OFF,
)


class PaymentPlan(TimestampMixin, Base):
    """回款计划的一期（**属别的工单**，这里只声明模型）。"""

    __tablename__ = "crm_payment_plan"

    #: 关联合同。
    contract_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("crm_contract.id"), nullable=False
    )
    #: 期次序号（第几期）。
    installment_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: 回款状态。
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PAYMENT_STATUS_PENDING
    )
    #: 应回款日。
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: 应回款金额 / 已回款金额（**分**）。
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paid_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_crm_payment_plan_status", "status"),
        Index("ix_crm_payment_plan_due_date", "due_date"),
        UniqueConstraint(
            "contract_id", "installment_no", name="uq_crm_payment_plan_installment"
        ),
    )


# ---------------------------------------------------------------- 变更历史

CHANGE_ACTOR_TYPE_SYSTEM = "system"


class ChangeHistory(TimestampMixin, Base):
    """变更历史（**属别的工单**，这里只声明模型）。"""

    __tablename__ = "crm_change_history"

    #: 被改对象的类型：`membership` / `contract` / `payment_plan`。
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    #: 被改对象的 id。
    entity_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: 被改的字段（固定 `status`）。
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 改前值 / 改后值。
    from_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 操作人类型（系统任务 ⇒ `system`）与操作人 id。
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: **同一次运行共用一个 operation_id** ⇒ 一次跑出来的历史能串成一组。
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 变更生效的基准日（补跑时是 `--date` 给的那天）。
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (
        Index("ix_crm_change_history_entity", "entity_type", "entity_id"),
        Index("ix_crm_change_history_operation", "operation_id"),
    )


# ---------------------------------------------------------------- 任务运行记录（本单建）

JOB_RUN_STATUS_SUCCESS = "success"
JOB_RUN_STATUS_PARTIAL = "partial"
JOB_RUN_STATUS_FAILED = "failed"


class JobRun(TimestampMixin, Base):
    """日终任务的运行记录（**本单新建的表** ⇒ 迁移包含在本单）。

    工单原文：「写入新表 crm_job_run（job_name、run_date、started_at、
    finished_at、stats jsonb、status：success / partial / failed）」。

    ⚠️⚠️ **`org_id` 在这张表上是「可空」的**（其它业务表是 NOT NULL）：
    日终任务是**跨租户的系统级任务** ⇒ 它的一条运行记录**不属于任何租户**
    ⇒ 硬塞一个租户 id 反而是**错的**（会让「这条运行属于哪个租户」的查询
    给出假答案）⇒ 留空并在这里写清楚。
    ⇒ ⚠️ 迁移里也必须是 `nullable=True` ⇒ **两边不一致 ⇒ 测试跑的是另一套东西**。
    """

    __tablename__ = "crm_job_run"

    # ⚠️ 覆盖 mixin 的 NOT NULL ⇒ 系统级运行记录不属于任何租户。
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )

    #: 任务名（`daily_status_refresh`）。
    job_name: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 运行基准日（补跑时是 `--date` 给的那天）。
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: 汇总统计（JSONB）：各对象扫描数/变化数/按目标状态计数/失败批次/耗时。
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: 运行结果：`success` / `partial` / `failed`。
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        Index("ix_crm_job_run_job_date", "job_name", "run_date"),
        CheckConstraint(
            "status IN ('success', 'partial', 'failed')", name="ck_crm_job_run_status"
        ),
        # ⚠️⚠️ **刻意不加** `UNIQUE(job_name, run_date)`：
        #   同一天**可以跑多次**（失败后补跑）⇒ 每次运行都要留一条记录 ⇒
        #   加了唯一约束 ⇒ 第二次跑写不进去 ⇒ 运维看到的是第一次（失败）那条
        #   ⇒ **补跑成功的记录被吞了** ⇒ 运维以为还没成功。
        #   幂等的要求是「**不产生新的状态变化与历史**」（不是「只留一条运行记录」）。
    )
