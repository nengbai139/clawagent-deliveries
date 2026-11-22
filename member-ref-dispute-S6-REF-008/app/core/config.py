"""配置：只从环境变量读取（统一技术约定）。

⚠️ **不引入向境外发送数据的第三方 SDK**——本模块只依赖标准库与 pydantic。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。

    ⚠️ **密钥只从环境变量读取**（统一技术约定）⇒ 全部字段用
    `env_prefix="APP_"` 前缀，且**不提供任何默认值**给密钥类字段
    ⇒ 缺了就在启动时炸，而不是悄悄用弱口令。
    """

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    # ---- 数据库 ----
    #: ⚠️⚠️ **没有默认值**——必须显式给 `APP_DATABASE_URL`。
    #:
    #: 之前这里默认 `postgresql+psycopg://app:app@localhost:5432/app`
    #: ⇒ 一旦忘了设环境变量，**后台任务 CLI**（`python -m app.tasks`）
    #: 就会连到**本机 5432 端口上那个「碰巧在那儿」的库**
    #: （本机开发机上那个端口可能是**别的项目**的库！）⇒
    #: 超时提醒任务会往**不相关的数据库**里写通知与审计。
    #:
    #: ⇒ 缺配置就**启动时炸**（fail fast），比连错库安全得多。
    database_url: str

    # ---- Redis ----
    redis_url: str = "redis://localhost:6379/0"

    # ---- 业务参数 ----
    #: 争议提交后未处理时的提醒阈值（天）。
    dispute_reminder_days: int = 10
    #: 争议最多可附的证据文件数。
    max_dispute_attachments: int = 5
    #: 通知服务地址；本单用桩，故默认空。
    notify_base_url: str | None = None
    #: 审计日志里保留的操作人显示名兜底。
    system_actor_name: str = "system"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
