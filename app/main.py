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
from app.core.config import validate_settings
from app.core.db import build_engine, build_session_factory, create_all, require_migrated
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

    # ⚠️ **生产守卫**（2026-11-25，订单 #2968 合规体检）：生产环境用**兜底
    #    默认密钥**（它写在公开的交付仓库里）⇒ 等于用公开已知的密钥签发登录
    #    令牌 ⇒ ⇒ **拒绝启动**（fail-closed）⇒ 而不是照常起来再让人发现。
    validate_settings(settings)

    app = FastAPI(
        title="会员空间平台 · IAM",
        version="0.1.0",
        description="扫码登录适配器接口、state 校验与身份绑定流程",
    )

    if engine is None:
        engine = build_engine(settings.database_url)
    # ⚠️ **生产不建表，只校验**（2026-11-25 合规体检）。
    #
    #	原先这里无条件 `create_all(engine)` ⇒ ⇒ 生产建表靠**应用启动副作用** ⇒
    #	⇒ 表结构由**模型**决定、而不是**迁移** ⇒ ⇒ 偏离客户统一技术约定的
    #	Alembic 要求（且模型改了结构、线上库却不会跟着变）⇒ ⇒ 现在：
    #
    #	  - **生产**：表必须已经由 `alembic upgrade head` 建好 ⇒ 缺表就**报错
    #	    并说清怎么建**（fail-closed）⇒ 而不是悄悄建出一张和迁移不一致的表；
    #	  - **非生产**：仍然 `create_all`（本地开发与单测要的是「一条命令就能跑」）。
    if settings.is_production:
        require_migrated(engine)
    else:
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
