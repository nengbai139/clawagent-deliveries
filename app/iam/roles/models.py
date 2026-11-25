"""角色与角色-权限矩阵的业务表。

统一约定：业务表含 id(UUID)、org_id、site_id、created_at、created_by、updated_at、deleted_at（软删除）。

roles：
    id / org_id / site_id / code / name / level（site 或 org）/ is_system / description
role_permissions：
    id / org_id / site_id / role_id / permission_code / data_scope（self / site / org）

删除保护：is_system=true 的内置角色不可删除，接口层返回 409（见 app/iam/roles/service.py）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.iam.models import new_uuid, utcnow
from app.iam.roles.constants import (  # noqa: F401  （转出以便其它模块直接引用）
    DATA_SCOPE_ORG,
    DATA_SCOPE_SELF,
    DATA_SCOPE_SITE,
    DATA_SCOPES,
    ROLE_LEVEL_ORG,
    ROLE_LEVEL_SITE,
    ROLE_LEVELS,
)


class Role(Base):
    """岗位角色。is_system=true 的是内置角色，不可删除。"""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_roles_org_code"),
        CheckConstraint(
            "level IN ('site', 'org')", name="ck_roles_level"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    site_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(64))
    # site / org
    level: Mapped[str] = mapped_column(String(8), default=ROLE_LEVEL_SITE)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class RolePermission(Base):
    """角色-权限点映射。data_scope 决定该权限点的数据范围。"""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint(
            "role_id", "permission_code", name="uq_role_permissions_role_code"
        ),
        CheckConstraint(
            "data_scope IN ('self', 'site', 'org')", name="ck_role_permissions_scope"
        ),
        Index("ix_role_permissions_role", "role_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    site_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roles.id"), index=True
    )
    permission_code: Mapped[str] = mapped_column(String(64))
    # self / site / org
    data_scope: Mapped[str] = mapped_column(String(8), default=DATA_SCOPE_SELF)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    role: Mapped[Role] = relationship(back_populates="permissions")
