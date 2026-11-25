"""创建 roles 表（S2-IAM-015 角色与权限矩阵）

Revision ID: 0001_roles
Revises:
Create Date: 2026-11-25

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_roles"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("level IN ('site', 'org')", name="ck_roles_level"),
        sa.UniqueConstraint("org_id", "code", name="uq_roles_org_code"),
    )
    op.create_index("ix_roles_org_id", "roles", ["org_id"])
    op.create_index("ix_roles_code", "roles", ["code"])


def downgrade() -> None:
    op.drop_index("ix_roles_code", table_name="roles")
    op.drop_index("ix_roles_org_id", table_name="roles")
    op.drop_table("roles")
