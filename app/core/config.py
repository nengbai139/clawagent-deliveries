"""集中读取环境变量配置。

约定（与投标方案一致）：配置与密钥只从环境变量读取，不落库、不写死在业务代码里。
测试通过构造 Settings 实例覆盖，不需要改环境变量。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

# 扫码登录相关环境变量名（README 对接说明里用同一套名字）
ENV_APP_ENV = "APP_ENV"
ENV_DATABASE_URL = "APP_DATABASE_URL"
ENV_REDIS_URL = "REDIS_URL"
ENV_TOKEN_SECRET = "APP_TOKEN_SECRET"
ENV_TOKEN_TTL = "APP_TOKEN_TTL_SECONDS"
ENV_QR_STATE_TTL = "APP_QR_STATE_TTL_SECONDS"
ENV_QR_BIND_TTL = "APP_QR_BIND_TICKET_TTL_SECONDS"
ENV_QR_TOTP_TTL = "APP_QR_TOTP_CHALLENGE_TTL_SECONDS"
ENV_QR_SKIP_TOTP = "APP_QR_LOGIN_SKIP_TOTP"
ENV_QR_FORCE_TOTP = "APP_QR_LOGIN_FORCE_TOTP"
ENV_QR_ALLOWLIST = "APP_QR_REDIRECT_ALLOWLIST"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


# DEFAULT_TOKEN_SECRET 是**兜底默认值**（本地开发/单测用）。
#
# ⚠️ **它同时是「生产不许用它」的判据**（见 validate_settings）：因为这个值
#    **写在公开的交付仓库里**（任何人都能读到）⇒ ⇒ 生产拿它签发令牌等于
#    **用公开已知的密钥签发登录令牌**。
DEFAULT_TOKEN_SECRET = "dev-only-change-me"


def validate_settings(settings: "Settings") -> None:
    """校验配置；**不合法就抛异常**（调用方要么启动失败，要么不调它）。

    ⚠️ **为什么只在生产拦**（实测 2026-11-25，订单 #2968 合规体检）：
    #   - 本地开发与单测到处直接构造 `Settings()` ⇒ 若「没有默认值就不给」
    #     ⇒ 到处都得先配环境变量 ⇒ ⇒ 改造成本大；
    #   - 而**本地的默认值本身没有风险**（生产的密钥本来就不该是默认值）
    #     ⇒ ⇒ 只在生产拦，恰好堵住「忘配环境变量 ⇒ 用公开密钥上线」这条路。
    #
    ⚠️ **与客户统一技术约定的关系**：「配置与密钥只从环境变量读取」
    #   ⇒ 生产必须显式给 `APP_TOKEN_SECRET` ⇒ ⇒ 本闸门就是那条约定的守卫。
    """
    if not settings.is_production:
        return
    if not settings.token_secret.strip():
        raise ValueError(
            "生产环境必须设置 APP_TOKEN_SECRET（当前为空 ⇒ 签发的登录令牌任何人都能伪造）"
        )
    if settings.token_secret == DEFAULT_TOKEN_SECRET:
        raise ValueError(
            "生产环境不能使用默认的 APP_TOKEN_SECRET（dev-only-change-me）："
            "该值写在公开的交付仓库里，任何人都能读到 ⇒ 等于用公开的密钥签发令牌"
        )


@dataclass(frozen=True)
class Settings:
    """运行期配置快照。"""

    app_env: str = "local"
    database_url: str = "sqlite+pysqlite:///:memory:"
    redis_url: str = "redis://localhost:6379/0"
    token_secret: str = DEFAULT_TOKEN_SECRET
    token_ttl_seconds: int = 3600
    # state / bind_ticket 默认 5 分钟
    qr_state_ttl_seconds: int = 300
    qr_bind_ticket_ttl_seconds: int = 300
    qr_totp_challenge_ttl_seconds: int = 300
    # 默认 false：扫码登录仍需 TOTP 二次验证（员工启用 TOTP 时）
    qr_login_skip_totp: bool = False
    # 置 true 时，所有扫码登录都强制走 TOTP（默认 false）
    qr_login_force_totp: bool = False
    # redirect_uri 白名单（逗号分隔），为空时 fail-closed
    qr_redirect_allowlist: tuple[str, ...] = ()

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"prod", "production"}

    @classmethod
    def from_env(cls) -> "Settings":
        allowlist = tuple(
            item.strip()
            for item in os.getenv(ENV_QR_ALLOWLIST, "").split(",")
            if item.strip()
        )
        return cls(
            app_env=os.getenv(ENV_APP_ENV, "local"),
            database_url=os.getenv(
                ENV_DATABASE_URL, "sqlite+pysqlite:///:memory:"
            ),
            redis_url=os.getenv(ENV_REDIS_URL, "redis://localhost:6379/0"),
            token_secret=os.getenv(ENV_TOKEN_SECRET, DEFAULT_TOKEN_SECRET),
            token_ttl_seconds=_env_int(ENV_TOKEN_TTL, 3600),
            qr_state_ttl_seconds=_env_int(ENV_QR_STATE_TTL, 300),
            qr_bind_ticket_ttl_seconds=_env_int(ENV_QR_BIND_TTL, 300),
            qr_totp_challenge_ttl_seconds=_env_int(ENV_QR_TOTP_TTL, 300),
            qr_login_skip_totp=_env_bool(ENV_QR_SKIP_TOTP, False),
            qr_login_force_totp=_env_bool(ENV_QR_FORCE_TOTP, False),
            qr_redirect_allowlist=allowlist,
        )

    def with_overrides(self, **kwargs) -> "Settings":
        return replace(self, **kwargs)
