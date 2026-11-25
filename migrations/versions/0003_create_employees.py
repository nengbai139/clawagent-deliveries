"""创建 employees 表（S2-IAM-011 扫码登录适配器接口、state 校验与身份绑定流程）

Revision ID: 0003_employees
Revises: 0002_role_permissions
Create Date: 2026-11-25

⚠️ **为什么这张表现在有迁移了**（实测 2026-11-25 合规体检）：本单原先用
   `create_all` 建表（README 写的是「临时通道，上线前换成 alembic upgrade
   head」）⇒ ⇒ 偏离客户统一技术约定的 Alembic 要求 ⇒ ⇒ 现在补上。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_employees"
down_revision = "0002_role_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False),
        sa.Column("totp_secret", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_employees_org_id", "employees", ["org_id"])
    op.create_index("ix_employees_status", "employees", ["status"])
    # ⚠️ **username 既唯一又带索引** ⇒ 唯一索引本身就能当索引用 ⇒ 不要再建一个
    #    非唯一的（模型里 `unique=True, index=True` ⇒ SQLAlchemy 建的就是唯一
    #    索引 `ix_employees_username`）。
    op.create_index("ix_employees_username", "employees", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_employees_username", table_name="employees")
    op.drop_index("ix_employees_status", table_name="employees")
    op.drop_index("ix_employees_org_id", table_name="employees")
    op.drop_table("employees")
