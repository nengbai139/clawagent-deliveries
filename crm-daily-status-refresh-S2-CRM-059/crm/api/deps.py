"""FastAPI 依赖（数据库会话）。"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from crm.db.session import get_sessionmaker


def get_session() -> Iterator[Session]:
    factory = get_sessionmaker()
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()


SessionDep = Depends(get_session)
