"""S2-CRM-059: 新建 crm_job_run（日终任务运行记录）

⚠️⚠️ **只建这一张表**：会籍 / 合同 / 回款计划 / 变更历史四张表属别的工单
⇒ 它们的表由**各自的**迁移建 ⇒ 本单不碰（碰了 ⇒ 别的工单合入时撞车）。

Revision ID: 6c1f0a52b7d9
Revises:
Create Date: 2026-11-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "6c1f0a52b7d9"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_job_run",
        # ---- 统一技术约定的那组公共列 ----
        sa.Column("id", sa.UUID(), nullable=False),
        # ⚠️ `org_id` **可空**：日终任务是跨租户的系统级任务 ⇒ 一条运行记录
        #    不属于任何租户 ⇒ 硬塞租户 id 是错的（会让「这条运行属于谁」的
        #    查询给出假答案）⇒ 与 `app/models/entities.py` 的 JobRun 一致。
        sa.Column("org_id", sa.UUID(), nullable=True),
        sa.Column("site_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # ---- 本单的列 ----
        sa.Column("job_name", sa.String(length=64), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # ⚠️ **状态枚举在数据库层也钉住**（不只靠应用层）
        sa.CheckConstraint(
            "status IN ('success', 'partial', 'failed')", name="ck_crm_job_run_status"
        ),
    )
    op.create_index(
        "ix_crm_job_run_job_date", "crm_job_run", ["job_name", "run_date"], unique=False
    )
    # ⚠️⚠️ **刻意不加** UNIQUE(job_name, run_date)：
    #   同一天可以跑多次（失败后补跑）⇒ 每次运行都要留一条记录 ⇒ 加了唯一
    #   约束 ⇒ 第二次跑写不进去 ⇒ **补跑成功的记录被吞** ⇒ 运维以为还没成功。
    #   幂等的要求是「不产生新的状态变化与历史」，不是「一天只留一条运行记录」。


def downgrade() -> None:
    op.drop_index("ix_crm_job_run_job_date", table_name="crm_job_run")
    op.drop_table("crm_job_run")
