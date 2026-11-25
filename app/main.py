"""应用装配。

生产启动：
    uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000

测试：直接调用 create_app(...) 注入 SQLite 引擎、fakeredis 与 FakeProvider。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.iam.auth import login as login_routes
from app.api.iam.auth import totp as totp_routes
from app.api.iam.auth import qr as qr_routes
from app.api.iam.me import identities as identity_routes
from app.core.config import Settings
from app.core.db import build_engine, build_session_factory, create_all
from app.core.redis_client import build_redis_client
from app.iam.auth.qr.registry import ProviderRegistry
from app.iam.auth.totp import NotImplementedTotpVerifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    engine=None,
    redis_client=None,
    providers: list | None = None,
    totp_verifier=None,
) -> FastAPI:
    settings = settings or Settings.from_env()

    app = FastAPI(
        title="会员空间平台 · IAM",
        version="0.1.0",
        description="扫码登录适配器接口、state 校验与身份绑定流程",
    )

    if engine is None:
        engine = build_engine(settings.database_url)
    create_all(engine)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.redis = redis_client if redis_client is not None else build_redis_client(settings.redis_url)
    app.state.qr_providers = ProviderRegistry(providers or [])
    app.state.totp_verifier = totp_verifier or NotImplementedTotpVerifier()

    app.include_router(login_routes.router)
    app.include_router(totp_routes.router)
    app.include_router(qr_routes.router)
    app.include_router(identity_routes.router)

    @app.get("/healthz", tags=["ops"])
    def healthz():
        return {"status": "ok"}

    @app.get("/api/iam/auth/qr/providers", tags=["iam-qr-login"])
    def list_providers():
        """列出已注册的扫码登录适配器（供前端判断可用厂商）。"""
        registry: ProviderRegistry = app.state.qr_providers
        health = {}
        for name in registry.names():
            adapter = registry.get(name)
            try:
                health[name] = bool(adapter.health_check())
            except Exception:  # noqa: BLE001 —— 探针不因单个厂商异常而失败
                health[name] = False
        return {"providers": registry.names(), "health": health}

    logger.info("app created: providers=%s", app.state.qr_providers.names())
    return app


app = create_app()
