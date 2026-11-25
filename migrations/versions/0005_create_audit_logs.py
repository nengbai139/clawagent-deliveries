"""创建 audit_logs 表（S2-IAM-011 扫码登录适配器接口、state 校验与身份绑定流程）

Revision ID: 0005_audit_logs
Revises: 0004_user_identities
Create Date: 2026-11-25

⚠️ **为什么这张表现在有迁移了**（实测 2026-11-25 合规体检）：本单原先用
   `create_all` 建表 ⇒ ⇒ 偏离客户统一技术约定的 Alembic 要求 ⇒ ⇒ 现在补上。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_audit_logs"
down_revision = "0004_user_identities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=True),
        sa.Column("actor_employee_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_audit_logs_org_id", "audit_logs", ["org_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_org_id", table_name="audit_logs")
    op.drop_table("audit_logs")
