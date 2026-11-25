"""创建 role_permissions 表（S2-IAM-015 角色与权限矩阵）

Revision ID: 0002_role_permissions
Revises: 0001_roles
Create Date: 2026-11-25

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_role_permissions"
down_revision = "0001_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "role_permissions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=True),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("permission_code", sa.String(length=64), nullable=False),
        sa.Column("data_scope", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name="fk_role_permissions_role_id"
        ),
        sa.CheckConstraint(
            "data_scope IN ('self', 'site', 'org')", name="ck_role_permissions_scope"
        ),
        sa.UniqueConstraint(
            "role_id", "permission_code", name="uq_role_permissions_role_code"
        ),
    )
    op.create_index("ix_role_permissions_org_id", "role_permissions", ["org_id"])
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])
    op.create_index(
        "ix_role_permissions_role", "role_permissions", ["role_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_role_permissions_role", table_name="role_permissions")
    op.drop_index("ix_role_permissions_role_id", table_name="role_permissions")
    op.drop_index("ix_role_permissions_org_id", table_name="role_permissions")
    op.drop_table("role_permissions")
