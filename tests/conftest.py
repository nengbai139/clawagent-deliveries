"""pytest 公共夹具。

- SQLite 内存库（SQLAlchemy 2.0，同步）
- fakeredis（state / bind_ticket / TOTP challenge 的存储）
- FakeProvider（扫码登录适配器替身）
"""

from __future__ import annotations

import sys
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.core.db import build_engine, create_all  # noqa: E402
from app.iam.auth.passwords import hash_password  # noqa: E402
from app.iam.models import Employee, STATUS_ACTIVE, STATUS_DISABLED  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.fakes.fake_qr_provider import FakeProvider  # noqa: E402

ALLOWED_REDIRECT_URI = "https://portal.example.test/iam/qr/callback"


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://unused",
        token_secret="test-secret",
        token_ttl_seconds=3600,
        qr_state_ttl_seconds=300,
        qr_bind_ticket_ttl_seconds=300,
        qr_login_skip_totp=True,
        qr_redirect_allowlist=(ALLOWED_REDIRECT_URI,),
    )


@pytest.fixture()
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture()
def engine():
    eng = build_engine("sqlite+pysqlite:///:memory:")
    create_all(eng)
    return eng


@pytest.fixture()
def provider() -> FakeProvider:
    return FakeProvider("fake")


@pytest.fixture()
def app(settings, engine, redis_client, provider):
    return create_app(
        settings=settings,
        engine=engine,
        redis_client=redis_client,
        providers=[provider],
    )


@pytest.fixture()
def client(app) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def session_factory(app):
    return app.state.session_factory


@pytest.fixture()
def make_employee(session_factory):
    """造一个虚构员工（口令 hash 走标准库 pbkdf2）。"""

    def _make(
        username: str = "zhang.san",
        password: str = "correct-horse-battery",
        *,
        status: str = STATUS_ACTIVE,
        totp_enabled: bool = False,
        totp_secret: str | None = None,
        org_id: str = "org-001",
        site_id: str | None = "site-001",
        display_name: str = "张三（虚构）",
    ) -> Employee:
        with session_factory() as session:
            employee = Employee(
                org_id=org_id,
                site_id=site_id,
                username=username,
                display_name=display_name,
                password_hash=hash_password(password, iterations=1000),
                status=status,
                totp_enabled=totp_enabled,
                totp_secret=totp_secret,
                created_by="test",
            )
            session.add(employee)
            session.commit()
            session.refresh(employee)
            session.expunge(employee)
            return employee

    return _make


@pytest.fixture()
def employee(make_employee) -> Employee:
    return make_employee()


@pytest.fixture()
def disabled_employee(make_employee) -> Employee:
    return make_employee(
        username="disabled.user", status=STATUS_DISABLED, display_name="停用员工（虚构）"
    )


@pytest.fixture()
def db_session(session_factory) -> Session:
    with session_factory() as session:
        yield session
