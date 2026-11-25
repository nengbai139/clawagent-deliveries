"""钉住「生产环境不许用默认密钥」。

⚠️ **真踩过**（2026-11-25，订单 #2968 的合规体检）：`app/core/config.py` 里

    token_secret: str = "dev-only-change-me"

是**硬编码的兜底默认值** ⇒ ⇒ 生产部署**忘配** `APP_TOKEN_SECRET` 时，服务
**不报错**、照常启动、照常签发令牌 ⇒ ⇒ 而这个默认值**写在公开的交付仓库里**
（`clawagent-deliveries`，任何人都能读到）⇒ ⇒ 等于**用公开已知的密钥在签发
登录令牌**。

⚠️ **与客户的统一技术约定直接冲突**：「配置与密钥只从环境变量读取」。

⇒ ⇒ 修法：**生产环境（APP_ENV=prod/production）下用默认值 ⇒ 拒绝启动**。

⚠️ **为什么不是「干脆不给默认值」**：本地开发与单测到处直接构造 `Settings()`
⇒ 改造成本大 ⇒ 而**本地默认值本身没有风险**（生产的密钥不该是默认值）
⇒ ⇒ 只在**生产**拦。
"""

from __future__ import annotations

import pytest

from app.core.config import (
    DEFAULT_TOKEN_SECRET,
    Settings,
    validate_settings,
)


def test_prod_with_default_secret_is_rejected():
    """生产 + 兜底默认值 ⇒ 必须报错（否则等于用公开的密钥签发令牌）。"""
    with pytest.raises(ValueError) as exc:
        validate_settings(Settings(app_env="prod", token_secret=DEFAULT_TOKEN_SECRET))
    assert "APP_TOKEN_SECRET" in str(exc.value)


def test_prod_with_real_secret_is_ok():
    """生产 + 真密钥 ⇒ 放行。"""
    validate_settings(Settings(app_env="prod", token_secret="a-real-secret"))


def test_production_spelling_is_also_prod():
    """APP_ENV=production 同样算生产。"""
    with pytest.raises(ValueError):
        validate_settings(
            Settings(app_env="production", token_secret=DEFAULT_TOKEN_SECRET)
        )


def test_non_prod_with_default_secret_is_ok():
    """本地开发与单测不该被拦（默认值在本地没有风险）。"""
    validate_settings(Settings(app_env="local", token_secret=DEFAULT_TOKEN_SECRET))
    validate_settings(Settings(app_env="", token_secret=DEFAULT_TOKEN_SECRET))


def test_prod_with_empty_secret_is_rejected():
    """生产 + 空密钥 ⇒ 必须报错（空 ⇒ 签的令牌任何人都能伪造）。"""
    with pytest.raises(ValueError):
        validate_settings(Settings(app_env="prod", token_secret=""))


def test_from_env_reads_the_guard():
    """闸门要真的从环境变量读（不然改了环境变量也没用）。"""
    s = Settings.from_env()
    assert s.app_env is not None
    if s.is_production:
        with pytest.raises(ValueError):
            validate_settings(s)
