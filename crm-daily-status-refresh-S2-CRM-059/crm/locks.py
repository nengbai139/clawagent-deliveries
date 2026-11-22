"""并发锁。

工单原文：「并发：Redis 锁 `crm:lock:daily_status_refresh`（TTL 30 分钟）」。

⇒ 用 Redis 的 `SET key value NX EX ttl` 实现（**原子**，靠 Redis 单线程语义）。

⚠️⚠️ **锁必须「自己续命」是不行的**：TTL 30 分钟 ⇒ 任务跑超 30 分钟时锁会过期
⇒ 第二个实例会拿到锁 ⇒ 两个实例同时改同一批数据。
⇒ ⇒ 实现里**在每批之前检查锁还在不在自己手里**（`assert_owned`）⇒ 锁过期
就**立刻中止**（宁可少跑，也不要两个实例同时跑）。

⚠️ **测试不依赖 Redis**：锁做成可注入的接口（`LockBackend`）⇒ 单测用
`InMemoryLock`；另有针对真 Redis 的用例（`CRM_TEST_REDIS_URL` 存在时才跑）。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class LockBackend(Protocol):
    """锁的后端（真 Redis / 测试用内存实现）。"""

    def acquire(self, key: str, token: str, ttl_seconds: int) -> bool: ...

    def release(self, key: str, token: str) -> None: ...

    def owns(self, key: str, token: str) -> bool: ...


class RedisLockBackend:
    """真 Redis 后端。

    ⚠️ **Redis 不可用 ⇒ 直接炸**（不放行）：并发锁失效比任务失败严重得多
    ⇒ 两个实例同时跑 ⇒ 状态互相覆盖。
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client = None

    def _get(self):
        if self._client is None:
            import redis  # 延迟导入：没用到 Redis 时不必装它

            self._client = redis.Redis.from_url(
                self._redis_url, decode_responses=True, socket_timeout=5
            )
        return self._client

    def acquire(self, key: str, token: str, ttl_seconds: int) -> bool:
        # ⚠️ `nx=True` + `ex=ttl` 在 Redis 里是**一条命令** ⇒ 原子。
        return bool(self._get().set(key, token, nx=True, ex=ttl_seconds))

    def release(self, key: str, token: str) -> None:
        client = self._get()
        # ⚠️ **只删自己持有的锁**（Lua 保证 compare-and-delete）⇒
        # 锁过期后被别人拿到时，我们不会把别人的锁删了。
        client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            key,
            token,
        )

    def owns(self, key: str, token: str) -> bool:
        return self._get().get(key) == token


class InMemoryLockBackend:
    """进程内锁（**测试用**，也用于单实例本地跑）。

    ⚠️ 只在**单进程**内有效 ⇒ 多副本部署必须用 `RedisLockBackend`。
    """

    def __init__(self) -> None:
        self._held: dict[str, tuple[str, float]] = {}

    def acquire(self, key: str, token: str, ttl_seconds: int) -> bool:
        import time

        now = time.monotonic()
        held = self._held.get(key)
        if held is not None and held[1] > now:
            return False
        self._held[key] = (token, now + ttl_seconds)
        return True

    def release(self, key: str, token: str) -> None:
        held = self._held.get(key)
        if held is not None and held[0] == token:
            del self._held[key]

    def owns(self, key: str, token: str) -> bool:
        import time

        held = self._held.get(key)
        return held is not None and held[0] == token and held[1] > time.monotonic()


@dataclass
class LockHandle:
    """锁的持有凭证。"""

    key: str
    token: str
    backend: LockBackend

    def owns(self) -> bool:
        return self.backend.owns(self.key, self.token)

    def release(self) -> None:
        self.backend.release(self.key, self.token)


class LockBusy(RuntimeError):
    """锁被别人占着（另一个实例在跑）。"""

    def __init__(self, key: str) -> None:
        super().__init__(f"锁 {key} 已被其它实例持有 ⇒ 本次不跑")
        self.key = key


def acquire_lock(
    backend: LockBackend,
    key: str,
    ttl_seconds: int,
    token_factory: Callable[[], str] | None = None,
) -> LockHandle:
    """抢锁；抢不到就抛 `LockBusy`（调用方据此以非零退出码结束）。"""
    token = (token_factory or (lambda: uuid.uuid4().hex))()
    if not backend.acquire(key, token, ttl_seconds):
        raise LockBusy(key)
    return LockHandle(key=key, token=token, backend=backend)
