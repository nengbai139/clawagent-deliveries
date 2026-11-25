"""Alembic 环境配置。

连接串只从环境变量读取（APP_DATABASE_URL），不落库、不写死在代码里。
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# 让项目根目录可 import（app / migrations）
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.db import Base  # noqa: E402

# ⚠️ **自动发现模型模块**（不要写死 import 列表）。
#
#	**为什么**（实测 2026-11-25）：这个交付仓库是**多单累积**的 ⇒ 每单的分支
#	带的模型模块**不一样**（订单 2968 有 `app/iam/models.py`，订单 2980 又有
#	`app/iam/roles/models.py`）⇒ ⇒ 写死 import 列表 ⇒ 换分支就 import 失败
#	（`ModuleNotFoundError`）⇒ ⇒ **两个分支就得各维护一份 env.py** ⇒ ⇒
#	合并时冲突、且一单新增模型模块时还得记得改这里。
#	⇒ ⇒ 改成**遍历 app 包、import 所有名字以 models 结尾的模块** ⇒ ⇒
#	哪个分支有什么就导入什么 ⇒ ⇒ **一份 env.py 通用**。
import importlib  # noqa: E402
import pkgutil  # noqa: E402

import app  # noqa: E402

for _m in pkgutil.walk_packages(app.__path__, prefix="app."):
    if _m.name.endswith(".models"):
        importlib.import_module(_m.name)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.getenv("APP_DATABASE_URL")
    if url:
        return url
    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
