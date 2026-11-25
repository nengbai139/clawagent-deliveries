"""bind_ticket：未绑定外部身份时下发的一次性绑定票据。

- 存 Redis，短 TTL（APP_QR_BIND_TICKET_TTL_SECONDS，默认 300 秒）；
- 单次有效：取用即删；
- 票据里记录外部身份三元组，员工用账号密码登录后凭票据完成绑定。
"""

from __future__ import annotations

import json
import secrets
import time

from redis.exceptions import WatchError

from app.iam.auth.qr.external_identity import ExternalIdentity

TICKET_KEY_PREFIX = "auth:qrbind:"
CODE_BIND_TICKET_INVALID = "bind_ticket_invalid"


class BindTicketError(Exception):
    """bind_ticket 校验失败（过期或已使用）。"""

    def __init__(self, code: str = CODE_BIND_TICKET_INVALID, message: str = "bind_ticket 无效或已过期") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class BindTicketStore:
    """bind_ticket 的签发与消费。"""

    def __init__(self, redis_client, *, ttl_seconds: int = 300) -> None:
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds

    def issue(self, identity: ExternalIdentity) -> str:
        ticket = secrets.token_urlsafe(24)
        payload = json.dumps(
            {
                **identity.as_dict(),
                "issued_at": time.time(),
            },
            ensure_ascii=False,
        )
        self.redis.set(f"{TICKET_KEY_PREFIX}{ticket}", payload, ex=self.ttl_seconds)
        return ticket

    def consume(self, ticket: str) -> ExternalIdentity:
        """取用并删除票据（单次有效）。"""
        if not ticket or not isinstance(ticket, str):
            raise BindTicketError()
        key = f"{TICKET_KEY_PREFIX}{ticket}"
        try:
            with self.redis.pipeline() as pipe:
                pipe.watch(key)
                raw = pipe.get(key)
                if raw is None:
                    pipe.unwatch()
                    raise BindTicketError()
                pipe.multi()
                pipe.delete(key)
                pipe.execute()
        except WatchError:
            raise BindTicketError() from None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise BindTicketError() from exc
        return ExternalIdentity(
            provider=str(data.get("provider", "")),
            corp_id=str(data.get("corp_id", "")),
            external_user_id=str(data.get("external_user_id", "")),
            display_name=data.get("display_name"),
            mobile=data.get("mobile"),
        )
