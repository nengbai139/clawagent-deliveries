"""IAM 业务表。

统一约定：业务表含 id(UUID)、org_id、site_id、created_at、created_by、updated_at、deleted_at（软删除）。
本单只用到其中三张：employees、user_identities、audit_logs。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# 员工状态取值
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"


class Employee(Base):
    """员工（IAM 主体）。"""

    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    site_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(255))
    # enabled 布尔 / status 枚举二选一：仓库用 status 枚举，取值见 STATUS_* 常量
    status: Mapped[str] = mapped_column(String(16), default=STATUS_ACTIVE, index=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    identities: Mapped[list["UserIdentity"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE and self.deleted_at is None


class UserIdentity(Base):
    """外部身份绑定：扫码登录按 (provider, corp_id, external_user_id) 查这里。"""

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "corp_id",
            "external_user_id",
            name="uq_user_identities_provider_corp_user",
        ),
        # ⚠️ **这里原来还有一个 Index("ix_user_identities_employee", "employee_id")**
        #    ⇒ 而 `employee_id` 本身又带 `index=True` ⇒ ⇒ **两个索引打在同一个
        #    列上**（autogenerate 实测：ix_user_identities_employee 与
        #    ix_user_identities_employee_id 各建一个）⇒ ⇒ 纯冗余、写放大
        #    ⇒ ⇒ 去掉显式那个，留自动生成的 `ix_user_identities_employee_id`。
        #    （2026-11-25 合规体检时发现；迁移 0004 与模型已对齐。）
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    site_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32), index=True)
    corp_id: Mapped[str] = mapped_column(String(64))
    external_user_id: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    employee: Mapped[Employee] = relationship(back_populates="identities")


class AuditLog(Base):
    """审计日志（绑定 / 解绑等敏感动作都写这里）。"""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    site_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_employee_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
