"""扫码登录 state：生成、存储、与浏览器绑定、一次性消费。

存储口径（投标方案已定口径）：
- state：32 字节随机（secrets.token_urlsafe(32)），不可预测；
- Redis 主键：auth:qrstate:{state}，TTL 5 分钟（APP_QR_STATE_TTL_SECONDS）；
- 副本键：auth:qrstate:issued:{state}，TTL 更长，用于区分「从未存在 / 已过期」；
- 使用标记：auth:qrstate:used:{state}，用于识别「重复使用」；
- 浏览器绑定：Cookie 名 qr_state，值为与 state 一一对应的 browser_token（HttpOnly / SameSite=Lax / 生产环境 Secure）。

错误码（机器可读）：state_invalid / state_expired / state_used。
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass

from redis.exceptions import WatchError

logger = logging.getLogger(__name__)

STATE_KEY_PREFIX = "auth:qrstate:"
ISSUED_KEY_PREFIX = "auth:qrstate:issued:"
USED_KEY_PREFIX = "auth:qrstate:used:"

QR_STATE_COOKIE_NAME = "qr_state"

# 三类非法 state 的机器可读错误码
CODE_STATE_INVALID = "state_invalid"
CODE_STATE_EXPIRED = "state_expired"
CODE_STATE_USED = "state_used"


class QrStateError(Exception):
    """state 校验失败。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class QrStateInfo:
    """一次扫码登录发起时留下的上下文。"""

    state: str
    provider: str
    redirect_uri: str
    created_at: float


class QrStateStore:
    """state 的存取与一次性消费。"""

    def __init__(
        self,
        redis_client,
        *,
        ttl_seconds: int = 300,
        issued_ttl_seconds: int = 3600,
    ) -> None:
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds
        self.issued_ttl_seconds = issued_ttl_seconds

    # ------------------------------------------------------------------ 发起
    def issue(self, provider: str, redirect_uri: str) -> tuple[str, str]:
        """生成 state 并写入 Redis，返回 (state, browser_token)。"""
        state = secrets.token_urlsafe(32)  # 32 字节随机
        browser_token = secrets.token_urlsafe(32)
        payload = json.dumps(
            {
                "provider": provider,
                "redirect_uri": redirect_uri,
                "browser_token": browser_token,
                "created_at": time.time(),
            },
            ensure_ascii=False,
        )
        pipe = self.redis.pipeline()
        pipe.set(f"{STATE_KEY_PREFIX}{state}", payload, ex=self.ttl_seconds)
        # 副本留得久一点：主键消失时据此判定「过期」而不是「不存在」
        pipe.set(f"{ISSUED_KEY_PREFIX}{state}", payload, ex=self.issued_ttl_seconds)
        pipe.execute()
        logger.info("qr state issued provider=%s ttl=%ss", provider, self.ttl_seconds)
        return state, browser_token

    # ------------------------------------------------------------------ 回调
    def consume(self, state: str, browser_token: str | None) -> QrStateInfo:
        """校验并一次性消费 state。

        校验顺序：已使用 → 存在性（过期 / 无效）→ 与浏览器 Cookie 一致性。
        校验通过后立即删除，保证 state 只能用一次。
        """
        if not state or not isinstance(state, str):
            raise QrStateError(CODE_STATE_INVALID, "state 缺失或格式非法")

        state_key = f"{STATE_KEY_PREFIX}{state}"
        used_key = f"{USED_KEY_PREFIX}{state}"
        issued_key = f"{ISSUED_KEY_PREFIX}{state}"

        if self.redis.exists(used_key):
            raise QrStateError(CODE_STATE_USED, "state 已被使用")

        raw = self.redis.get(state_key)
        if raw is None:
            if self.redis.exists(issued_key):
                raise QrStateError(CODE_STATE_EXPIRED, "state 已过期")
            raise QrStateError(CODE_STATE_INVALID, "state 无效")

        try:
            data = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise QrStateError(CODE_STATE_INVALID, "state 内容非法") from exc

        expected_token = str(data.get("browser_token", ""))
        if not browser_token or not hmac.compare_digest(expected_token, browser_token):
            raise QrStateError(CODE_STATE_INVALID, "state 与浏览器会话不匹配")

        # 原子消费：确认主键仍在 → 删除主键 → 打上「已使用」标记
        try:
            with self.redis.pipeline() as pipe:
                pipe.watch(state_key)
                current = pipe.get(state_key)
                if current is None:
                    pipe.unwatch()
                    raise QrStateError(CODE_STATE_EXPIRED, "state 已过期")
                pipe.multi()
                pipe.delete(state_key)
                pipe.set(used_key, "1", ex=self.issued_ttl_seconds)
                pipe.execute()
        except WatchError:  # 并发回调，只有一个能消费成功
            raise QrStateError(CODE_STATE_USED, "state 已被使用") from None

        return QrStateInfo(
            state=state,
            provider=str(data.get("provider", "")),
            redirect_uri=str(data.get("redirect_uri", "")),
            created_at=float(data.get("created_at", 0.0)),
        )
