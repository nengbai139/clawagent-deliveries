"""Redis 客户端工厂（state / bind_ticket / TOTP challenge 都存 Redis）。"""

from __future__ import annotations

import redis


def build_redis_client(redis_url: str) -> "redis.Redis":
    # decode_responses=True：state / bind_ticket 的值都按 JSON 文本存取
    return redis.Redis.from_url(redis_url, decode_responses=True)
