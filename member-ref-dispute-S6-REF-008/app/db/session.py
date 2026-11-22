"""数据库会话。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models.entities import Base

_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            future=True,
        )
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_sessionmaker():
    get_engine()
    return _SessionLocal


def init_db() -> None:
    """建表（测试与本地开发用；生产走 Alembic 迁移）。"""
    Base.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """一个事务边界：正常结束提交，异常回滚。

    ⚠️ **必须是 `@contextmanager`**（不是裸生成器）：裸生成器不能用在
    `with` 语句里 ⇒ `TypeError: 'generator' object does not support the
    context manager protocol`（真实踩过一次）。
    """
    factory = get_sessionmaker()
    sess = factory()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()
