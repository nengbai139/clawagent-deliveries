"""并发锁与 CLI 入口的测试。

⚠️ **凡是「有入口」的东西，入口本身也要测**：上一版项目的 CLI 入口
（`session_scope` 退回裸生成器）就是**服务层全绿、入口完全不可用** ⇒ 没人发现。

⚠️ **单测不依赖 Redis**：CLI 用例把锁后端换成 `InMemoryLockBackend`
⇒ 不要求 Redis 起着；另有针对**真 Redis** 的用例（`CRM_TEST_REDIS_URL`
存在时才跑）。
"""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest

from crm.jobs import daily_status_refresh
from crm.jobs.daily_status_refresh import EXIT_LOCKED, EXIT_OK, main
from crm.locks import (
    InMemoryLockBackend,
    LockBusy,
    RedisLockBackend,
    acquire_lock,
)
from tests.conftest import make_membership

# ---------------------------------------------------------------- 锁

def test_in_memory_lock_is_exclusive():
    """同一个键只能被一个持有者拿到。"""
    backend = InMemoryLockBackend()
    assert backend.acquire("k", "token-a", 60) is True
    assert backend.acquire("k", "token-b", 60) is False
    backend.release("k", "token-a")
    assert backend.acquire("k", "token-b", 60) is True


def test_in_memory_lock_release_only_own_token():
    """只删自己持有的锁（别人的锁不能被误删）。"""
    backend = InMemoryLockBackend()
    backend.acquire("k", "token-a", 60)
    backend.release("k", "token-b")  # 不是自己的 token
    assert backend.owns("k", "token-a") is True


def test_acquire_lock_raises_when_busy():
    """抢不到锁 ⇒ 抛 `LockBusy`（调用方据此以非零退出码结束）。"""
    backend = InMemoryLockBackend()
    acquire_lock(backend, "k", 60, token_factory=lambda: "a")
    with pytest.raises(LockBusy):
        acquire_lock(backend, "k", 60, token_factory=lambda: "b")


def test_lock_handle_reports_ownership():
    """锁句柄能报出「还在不在我手里」。"""
    backend = InMemoryLockBackend()
    handle = acquire_lock(backend, "k", 60, token_factory=lambda: "a")
    assert handle.owns() is True
    backend.release("k", "a")
    assert handle.owns() is False


# ---------------------------------------------------------------- 真 Redis（可选）

@pytest.mark.skipif(
    not os.environ.get("CRM_TEST_REDIS_URL"),
    reason="未设 CRM_TEST_REDIS_URL（真 Redis 用例跳过；用 docker compose 起 redis）",
)
def test_redis_lock_is_exclusive_and_releases():
    """**真 Redis** 上的锁：互斥 + 只删自己的 + TTL。"""
    import redis

    url = os.environ["CRM_TEST_REDIS_URL"]
    client = redis.Redis.from_url(url, decode_responses=True)
    key = f"crm:lock:test:{uuid.uuid4().hex}"

    backend = RedisLockBackend(url)
    assert backend.acquire(key, "token-a", 60) is True
    assert backend.acquire(key, "token-b", 60) is False
    assert backend.owns(key, "token-a") is True
    assert backend.owns(key, "token-b") is False

    # ⚠️ 用别人的 token 释放 ⇒ 不该删掉
    backend.release(key, "token-b")
    assert backend.owns(key, "token-a") is True

    backend.release(key, "token-a")
    assert backend.owns(key, "token-a") is False
    assert client.get(key) is None
    client.close()


@pytest.mark.skipif(
    not os.environ.get("CRM_TEST_REDIS_URL"),
    reason="未设 CRM_TEST_REDIS_URL（真 Redis 用例跳过）",
)
def test_redis_lock_has_ttl():
    """锁带 TTL（工单原文：30 分钟）⇒ 进程崩了不会永久卡住。"""
    import redis

    url = os.environ["CRM_TEST_REDIS_URL"]
    client = redis.Redis.from_url(url, decode_responses=True)
    key = f"crm:lock:test:{uuid.uuid4().hex}"
    backend = RedisLockBackend(url)
    backend.acquire(key, "token-a", 30)
    ttl = client.ttl(key)
    assert 0 < ttl <= 30
    client.delete(key)
    client.close()


# ---------------------------------------------------------------- CLI

def test_cli_runs_and_writes_job_run(
    session, session_factory, monkeypatch, capsys
):
    """CLI 能跑通 ⇒ 写 `crm_job_run` + 打 JSON 汇总 + 退出码 0。"""
    from crm.locks import InMemoryLockBackend as _IB

    monkeypatch.setattr(daily_status_refresh, "lock_backend", lambda s: _IB())

    make_membership(
        session, status="active", end_date=date(2026, 3, 14)
    )
    session.commit()

    rc = main(["--date", "2026-03-15"])
    out = capsys.readouterr().out
    assert rc == EXIT_OK, out
    assert '"job_name": "daily_status_refresh"' in out
    assert '"status": "success"' in out
    assert '"total_changed": 1' in out

    from sqlalchemy import select

    from crm.models.entities import JobRun

    rows = list(session.scalars(select(JobRun)))
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].run_date == date(2026, 3, 15)
    assert rows[0].stats["total_changed"] == 1


def test_cli_locked_returns_exit_code_2(monkeypatch, capsys):
    """锁被别人占着 ⇒ 退出码 2 + 明确提示（不是 0，也不是崩）。"""
    from crm.locks import InMemoryLockBackend as _IB

    backend = _IB()
    backend.acquire("crm:lock:daily_status_refresh", "someone-else", 60)
    monkeypatch.setattr(daily_status_refresh, "lock_backend", lambda s: backend)

    rc = main(["--date", "2026-03-15"])
    out = capsys.readouterr().out
    assert rc == EXIT_LOCKED
    assert "locked" in out


def test_cli_rejects_bad_date(capsys):
    """`--date` 格式不对 ⇒ 明确报错 + 非零退出（不是崩）。"""
    rc = main(["--date", "2026-3-1"])
    out = capsys.readouterr().out
    assert rc != EXIT_OK
    assert "YYYY-MM-DD" in out


def test_cli_help_lists_date_option():
    """`--help` 里能看到 `--date`（补跑入口是交付物之一）。"""
    parser = daily_status_refresh.build_arg_parser()
    help_text = parser.format_help()
    assert "--date" in help_text
    assert "补跑" in help_text
