"""命令行脚本的公共支撑：数据库连接与建表检查。

数据库 URL 只从环境变量读取（APP_DATABASE_URL），命令行可用 --database-url 覆盖。
本地默认落 SQLite 文件，便于本地复核。
"""

from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import build_engine, build_session_factory
from app.iam.roles.models import Role, RolePermission

ENV_DATABASE_URL = "APP_DATABASE_URL"
DEFAULT_DATABASE_URL = "sqlite+pysqlite:///./local_roles.db"


def resolve_database_url(override: str | None = None) -> str:
    if override:
        return override
    return os.getenv(ENV_DATABASE_URL) or DEFAULT_DATABASE_URL


def build_cli_engine(database_url: str) -> Engine:
    return build_engine(database_url)


@contextmanager
def session_scope(engine: Engine):
    factory: sessionmaker[Session] = build_session_factory(engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def ensure_tables_exist(engine: Engine) -> None:
    """表不存在时给出明确提示（迁移由 alembic 负责，脚本不偷偷建表）。"""
    from sqlalchemy import inspect

    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    missing = {"roles", "role_permissions"} - existing
    if missing:
        raise SystemExit(
            "数据库缺少表："
            + "、".join(sorted(missing))
            + "；请先执行 `alembic upgrade head`（或对测试库执行 `python -m app.iam.roles.init_db`）。"
        )


__all__ = [
    "DEFAULT_DATABASE_URL",
    "ENV_DATABASE_URL",
    "Role",
    "RolePermission",
    "build_cli_engine",
    "ensure_tables_exist",
    "resolve_database_url",
    "session_scope",
]
