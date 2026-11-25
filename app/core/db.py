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
