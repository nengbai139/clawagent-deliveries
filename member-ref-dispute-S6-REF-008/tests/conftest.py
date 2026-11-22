"""测试夹具。

⚠️ **用真实的 PostgreSQL**（不是 SQLite）：本单的验收标准 3 是**集成测试**
（「改判后按原报备时间重新判定归属，结果写入审计日志」）⇒ 涉及
`CheckConstraint`、`UniqueConstraint`、部分索引等 **PostgreSQL 特性** ⇒
用 SQLite 测等于**测了个假的**（SQLite 不认 `pgvector`/`UUID` 方言，
约束行为也不同）。

⇒ 测试跑在**一次性容器**里（`docker run postgres:16-alpine`）⇒
与生产同大版本（16）。
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models.entities import (
    Base,
    RefReport,
    StaffRole,
)


def _database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("未设置 TEST_DATABASE_URL（需要 PostgreSQL 16）")
    return url


@pytest.fixture(scope="session", autouse=True)
def app_points_at_test_db():
    """让**应用自己的**数据库配置也指向**测试库**。

    ⚠️⚠️ **为什么必须这样**：有些代码路径**不走**测试夹具注入的
    session，而是**自己开引擎**——比如后台任务 CLI 的
    `app/db/session.py::session_scope()`（它读 `APP_DATABASE_URL`）。
    ⇒ 若 `APP_DATABASE_URL` 没设，配置里的默认值会指向
    **`localhost:5432`** —— 那台机器上那个端口**碰巧**跑着**别的库**
    （本机开发机上就是另一个项目的 Postgres！）⇒
    **跑测试会往不相关的数据库里写通知与审计**。

    ⇒ 这里把 `APP_DATABASE_URL` 指向**同一个测试库** ⇒
    CLI 测的确实是「测试库」⇒ 不会碰任何别的库。
    """
    url = _database_url()
    os.environ["APP_DATABASE_URL"] = url
    # ⚠️ `get_settings()` 是 `lru_cache` 的 ⇒ 改了环境变量要**清缓存**，
    # 否则第一次调用时缓存的旧值会一直用着。
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(_database_url(), future=True)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine) -> Session:
    """每个用例一个**干净**的库。

    ⚠️ **必须清表**：接口测试里会 `session.commit()`（那是真实行为）⇒
    数据会留在库里 ⇒ 后一个用例看到前一个用例的残留 ⇒ 测试之间**互相污染**
    ⇒ 出现「单跑绿、一起跑红」的假象。
    """
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    sess = factory()
    # 先清干净（顺序无所谓，无外键级联问题）。
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()


# ---------------------------------------------------------------- 造数据

@pytest.fixture()
def org_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def now() -> datetime:
    return datetime.now(UTC)


def make_report(
    session: Session,
    org_id: uuid.UUID,
    *,
    status: str = "accepted",
    reported_at: datetime | None = None,
    owner_staff_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    reporter_id: uuid.UUID | None = None,
    reporter_type: str = "staff",
) -> RefReport:
    r = RefReport(
        org_id=org_id,
        reporter_type=reporter_type,
        reporter_id=reporter_id or uuid.uuid4(),
        owner_staff_id=owner_staff_id,
        customer_id=customer_id or uuid.uuid4(),
        channel_id=channel_id or uuid.uuid4(),
        reported_at=reported_at or datetime.now(UTC),
        status=status,
        amount_cents=7925,
    )
    session.add(r)
    session.flush()
    return r


def give_roles(session: Session, org_id: uuid.UUID, staff_id: uuid.UUID, *roles: str):
    for role in roles:
        session.add(StaffRole(org_id=org_id, staff_id=staff_id, role=role))
    session.flush()


@pytest.fixture()
def helper():
    """给测试用的造数据函数集合。"""
    return type("H", (), {"make_report": staticmethod(make_report),
                          "give_roles": staticmethod(give_roles)})
