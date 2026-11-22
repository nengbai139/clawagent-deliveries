"""FastAPI 应用入口。"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="会员空间平台 · 报备人工复核与归属争议处理接口（员工端）",
        version="0.1.0",
        description=(
            "工单 S6-REF-008。统一技术约定：Python 3.11+ / FastAPI / "
            "SQLAlchemy 2 / Alembic / PostgreSQL 16。"
        ),
    )
    app.include_router(router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        # ⚠️ 只做配置自检，不打数据库（打库会因数据库短暂不可用而让
        # 编排器误判本容器不健康 ⇒ 反复重启 ⇒ 故障放大）。
        settings = get_settings()
        return {"status": "ok", "db": settings.database_url.split("@")[-1]}

    return app


app = create_app()
