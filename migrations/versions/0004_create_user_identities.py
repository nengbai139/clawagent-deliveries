"""创建 user_identities 表（S2-IAM-011 扫码登录适配器接口、state 校验与身份绑定流程）

Revision ID: 0004_user_identities
Revises: 0003_employees
Create Date: 2026-11-25

⚠️ **为什么这张表现在有迁移了**（实测 2026-11-25 合规体检）：本单原先用
   `create_all` 建表 ⇒ ⇒ 偏离客户统一技术约定的 Alembic 要求 ⇒ ⇒ 现在补上。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_user_identities"
down_revision = "0003_employees"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_identities",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=True),
        sa.Column("employee_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("corp_id", sa.String(length=64), nullable=False),
        sa.Column("external_user_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=True),
        sa.Column("mobile", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"], name="fk_user_identities_employee_id"
        ),
        sa.UniqueConstraint(
            "provider",
            "corp_id",
            "external_user_id",
            name="uq_user_identities_provider_corp_user",
        ),
    )
    op.create_index("ix_user_identities_org_id", "user_identities", ["org_id"])
    op.create_index("ix_user_identities_provider", "user_identities", ["provider"])
    # ⚠️ **employee_id 只建一个索引**：模型里 `employee_id` 带 `index=True`
    #    ⇒ SQLAlchemy 自动生成 `ix_user_identities_employee_id`；而
    #    `__table_args__` 里又显式声明了一个 `ix_user_identities_employee`
    #    ⇒ **两个索引打在同一个列上**（纯冗余，写放大）⇒ ⇒ 这里只建自动生成
    #    的那个，模型里那个重复的另由 `models.py` 修掉（见该文件注释）。
    op.create_index(
        "ix_user_identities_employee_id", "user_identities", ["employee_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_identities_employee_id", table_name="user_identities")
    op.drop_index("ix_user_identities_provider", table_name="user_identities")
    op.drop_index("ix_user_identities_org_id", table_name="user_identities")
    op.drop_table("user_identities")
