"""Alembic 环境。

⚠️ **数据库 URL 从环境变量读**（统一技术约定：配置与密钥只从环境变量读取）
⇒ 不写进 alembic.ini，也不进版本库。

⚠️⚠️ **本单的迁移只建 `crm_job_run`**：其余四张表（会籍 / 合同 / 回款计划 /
变更历史）属别的工单 ⇒ 它们的表由**各自的**迁移建 ⇒ 本单的迁移**不碰**
⇒ 少了任何一张表 ⇒ 别的工单合入时会撞车。
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from crm.core.config import get_settings
from crm.models import entities  # noqa: F401  （确保所有模型都被注册）

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = entities.Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # ⚠️ **允许调用方自带连接**（`config.attributes["connection"]`）：
    #   测试要在**另一个 schema** 上真跑一遍迁移（为了对比迁移与模型的表结构）
    #   ⇒ 用自带连接 + `SET search_path` ⇒ 迁移落在那个 schema 里 ⇒
    #   不污染业务库。
    existing = config.attributes.get("connection")
    if existing is not None:
        _run_on_connection(existing)
        return
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _run_on_connection(connection)


def _run_on_connection(connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
