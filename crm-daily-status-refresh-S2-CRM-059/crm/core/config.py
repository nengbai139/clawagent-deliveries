"""配置：只从环境变量读取（统一技术约定）。

⚠️ **密钥与连接串都不给默认值** ⇒ 缺了就在启动时炸，而不是悄悄连到某个
「碰巧在那儿」的库（本机开发机上 5432 端口跑着的可能是**别的项目**的库）。
"""

from __future__ import annotations

import os
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。"""

    model_config = SettingsConfigDict(env_prefix="CRM_", env_file=".env", extra="ignore")

    # ---- 数据库 ----
    #: ⚠️ **必填**（没有默认值）⇒ 缺了就启动时炸。
    database_url: str

    # ---- Redis（并发锁）----
    #: Redis 连接串（并发锁用）。
    redis_url: str = "redis://127.0.0.1:6379/0"

    # ---- 业务参数 ----
    #: 日终任务跑哪个时区的「今天」（工单原文：调度器每天 00:10 按
    #: `CRM_DEFAULT_TZ` 时区调用一次）。
    default_tz: str = "Asia/Shanghai"
    #: 每批多少行（工单原文：每批 1000 行）。
    batch_size: int = 1000
    #: 并发锁的键（工单原文：`crm:lock:daily_status_refresh`）。
    lock_key: str = "crm:lock:daily_status_refresh"
    #: 并发锁的 TTL（工单原文：30 分钟）。
    lock_ttl_seconds: int = 1800
    #: 会籍「即将到期」的提前天数（**桩参数**，真实现由「会籍校验」工单定义）。
    membership_expiring_window_days: int = 30


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def resolve_timezone(name: str | None = None) -> ZoneInfo:
    """把时区名解析成 `ZoneInfo`。

    ⚠️ **未知时区不许静默吞掉**：调度器按错时区跑 ⇒ 「今天」算错 ⇒
    整批状态派生错 ⇒ 宁可启动时炸。
    """
    tz_name = name or get_settings().default_tz
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"未知时区 {tz_name!r}：{exc}") from exc


def env_flag(name: str, default: bool = False) -> bool:
    """读布尔环境变量（`1/true/yes/on` 都算真）。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
