"""FastAPI 应用入口（**只含运维只读接口**）。

⚠️ 本单的交付物是**日终任务**（`python -m crm.jobs.daily_status_refresh`），
不是业务接口 ⇒ 这里**只有**运维查询口（`crm_job_run`），不扩业务范围。
"""

from __future__ import annotations

from fastapi import FastAPI

from crm.api.ops import router as ops_router
from crm.core.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="会员空间平台 · 日终状态刷新任务（运维只读）",
        version="0.1.0",
        description=(
            "工单 S2-CRM-059。日终任务本体是命令行入口 "
            "`python -m crm.jobs.daily_status_refresh`；"
            "本 HTTP 服务只提供 `crm_job_run` 的**只读**查询。"
        ),
    )
    app.include_router(ops_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        # ⚠️ 只做配置自检，不打数据库（打库失败 ⇒ 编排器误判不健康 ⇒ 反复重启）。
        settings = get_settings()
        return {"status": "ok", "db": settings.database_url.split("@")[-1]}

    return app


app = create_app()
