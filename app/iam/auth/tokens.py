"""访问令牌签发与校验（HS256，标准库实现，不引入外部依赖）。

amr（Authentication Method Reference）记录本次认证方式：pwd / qr。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid


class TokenError(Exception):
    """令牌签发/校验失败。"""


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(signing_input: bytes, secret: str) -> str:
    return _b64encode(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest())


def issue_access_token(
    *,
    employee_id: str,
    org_id: str,
    amr: str,
    secret: str,
    ttl_seconds: int,
    extra_claims: dict | None = None,
) -> str:
    if not secret:
        raise TokenError("令牌签名密钥未配置")
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": employee_id,
        "org_id": org_id,
        "amr": amr,
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    segments = [
        _b64encode(json.dumps(header, separators=(",", ":")).encode()),
        _b64encode(json.dumps(payload, separators=(",", ":")).encode()),
    ]
    signing_input = ".".join(segments).encode()
    segments.append(_sign(signing_input, secret))
    return ".".join(segments)


def decode_access_token(token: str, secret: str) -> dict:
    if not token or token.count(".") != 2:
        raise TokenError("令牌格式非法")
    header_b64, payload_b64, signature = token.split(".")
    signing_input = f"{header_b64}.{payload_b64}".encode()
    if not hmac.compare_digest(_sign(signing_input, secret), signature):
        raise TokenError("令牌签名校验失败")
    try:
        payload = json.loads(_b64decode(payload_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise TokenError("令牌内容非法") from exc
    if int(payload.get("exp", 0)) < int(time.time()):
        raise TokenError("令牌已过期")
    return payload
