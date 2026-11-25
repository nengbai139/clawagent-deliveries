"""数据库引擎与会话工厂。

生产：PostgreSQL 16（URL 从环境变量 APP_DATABASE_URL 读取）。
测试：SQLite 内存库 + StaticPool。
"""

from __future__ import annotations

import importlib

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    """所有业务表的声明式基类。"""


def build_engine(database_url: str) -> Engine:
    kwargs: dict = {"future": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in database_url:
            kwargs["poolclass"] = StaticPool
    return create_engine(database_url, **kwargs)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_all(engine: Engine) -> None:
    # 确保业务模型已 import，表才注册到 metadata 里
    importlib.import_module("app.iam.models")
    importlib.import_module("app.iam.roles.models")

    Base.metadata.create_all(engine)


# require_migrated 校验「表已经由 Alembic 迁移建好」。
#
# ⚠️ **为什么需要**（实测 2026-11-25，合规体检）：应用启动时无条件
#    `create_all(engine)` ⇒ ⇒ 生产建表靠**应用启动的副作用** ⇒ ⇒ 表结构
#    由**模型**决定、不是由**迁移**决定 ⇒ ⇒ ① 偏离客户统一技术约定的 Alembic
#    要求；② 模型改了结构，线上库不会跟着变（迁移链才是真源）。
#
# ⚠️ **为什么是「报错」而不是「自动建」**：自动建表会让「迁移链」与「模型」
#    悄悄分叉（谁能保证两边的空值性、索引、外键一致？）⇒ ⇒ 生产宁可**起不来**
#    并告诉运维跑 `alembic upgrade head` ⇒ ⇒ fail-closed。
#
# ⚠️ **判据**：查 `alembic_version` 表 ⇒ 它记录着「当前迁移到哪一版」⇒
#    表在、版本在 ⇒ 说明迁移跑过；表不在 ⇒ 说明没跑（或跑的是另一条链）。
def require_migrated(engine: Engine) -> None:
    from sqlalchemy import inspect

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "alembic_version" not in tables:
        raise RuntimeError(
            "数据库里没有 alembic_version 表 ⇒ 说明还没跑过迁移。"
            "请先执行 `alembic upgrade head`（生产环境不再由应用自动建表）"
        )
    expected = set(Base.metadata.tables)
    missing = sorted(expected - tables)
    if missing:
        raise RuntimeError(
            f"数据库缺少这些表：{missing} ⇒ 迁移没跑完。"
            f"请执行 `alembic upgrade head`（当前库里有 {len(tables)} 张表）"
        )
