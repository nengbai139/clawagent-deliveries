"""数据库会话与事务边界。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from crm.core.config import get_settings

_engine = None
_SessionLocal = None


def get_engine():
    """全局引擎（进程内复用）。"""
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_sessionmaker():
    get_engine()
    return _SessionLocal


def new_session() -> Session:
    """开一个**新**会话（每批一个事务 ⇒ 每批一个会话）。"""
    factory = get_sessionmaker()
    return factory()


@contextmanager
def session_scope() -> Iterator[Session]:
    """一个事务边界：正常结束提交，异常回滚。

    ⚠️ **必须是 `@contextmanager`**（不是裸生成器）：裸生成器不能用在
    `with` 语句里 ⇒ `TypeError: 'generator' object does not support the
    context manager protocol`（本项目的前一版就踩过这个 ⇒ CLI 入口完全不可用，
    而服务层测试全绿 ⇒ 没人发现）。
    """
    sess = new_session()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()
