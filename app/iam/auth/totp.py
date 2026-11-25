"""TOTP 二次验证的接入点。

**本单不实现 TOTP 本身**（投标方案明确不含 TOTP 二次验证实现），
这里只定义校验协议与挑战票据的存取，默认实现一律拒绝，由部署方注入真实校验器。
"""

from __future__ import annotations

import json
import secrets
from typing import Protocol

from redis.exceptions import WatchError

TOTP_CHALLENGE_KEY_PREFIX = "auth:totp:"


class TotpNotImplementedError(Exception):
    """默认校验器：TOTP 实现不在本单范围内。"""


class TotpVerifier(Protocol):
    """TOTP 校验器（由部署方实现并注入）。"""

    def verify(self, *, secret: str | None, code: str) -> bool:
        ...


class NotImplementedTotpVerifier:
    """默认实现：拒绝一切校验请求，并明确提示对接点。"""

    def verify(self, *, secret: str | None, code: str) -> bool:
        raise TotpNotImplementedError(
            "TOTP 校验器未注入：TOTP 二次验证实现不在本单范围内，"
            "请在 app.state.totp_verifier 注入 TotpVerifier 实现"
        )


class TotpChallengeStore:
    """TOTP 挑战票据：记录「这次验证通过后要给谁签发什么令牌」。"""

    def __init__(self, redis_client, *, ttl_seconds: int = 300) -> None:
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds

    def issue(self, *, employee_id: str, org_id: str, amr: str) -> str:
        challenge = secrets.token_urlsafe(24)
        payload = json.dumps(
            {"employee_id": employee_id, "org_id": org_id, "amr": amr},
            ensure_ascii=False,
        )
        self.redis.set(
            f"{TOTP_CHALLENGE_KEY_PREFIX}{challenge}", payload, ex=self.ttl_seconds
        )
        return challenge

    def consume(self, challenge: str) -> dict | None:
        if not challenge:
            return None
        key = f"{TOTP_CHALLENGE_KEY_PREFIX}{challenge}"
        try:
            with self.redis.pipeline() as pipe:
                pipe.watch(key)
                raw = pipe.get(key)
                if raw is None:
                    pipe.unwatch()
                    return None
                pipe.multi()
                pipe.delete(key)
                pipe.execute()
        except WatchError:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None
