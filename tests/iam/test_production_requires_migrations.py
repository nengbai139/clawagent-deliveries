"""钉住「生产环境不再由应用自动建表」。

⚠️ **真踩过**（2026-11-25，订单 #2968 合规体检）：`app/main.py` 里原先**无条件**
`create_all(engine)` ⇒ ⇒ 生产建表靠**应用启动的副作用** ⇒ ⇒ 表结构由**模型**
决定、而不是由**Alembic 迁移**决定 ⇒ ⇒ ① 偏离客户统一技术约定的 Alembic
要求；② 模型改了结构、线上库不会跟着变（迁移链才是真源）。

⇒ ⇒ 现在：生产 ⇒ **不建表**，只校验「迁移跑过了」⇒ 没跑就**报错并说清怎么建**
（fail-closed）；非生产 ⇒ 仍然 `create_all`（本地开发与单测要「一条命令就能跑」）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.core.db import build_engine, require_migrated

ROOT = Path(__file__).resolve().parents[2]


def _run_alembic(db_path: Path, *args: str) -> None:
    env = dict(os.environ)
    env["APP_DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    r = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic {args} 失败:\n{r.stdout}\n{r.stderr}"


def _first_revision() -> str:
    """取迁移链上的第一条（基线）—— 不写死编号 ⇒ 换分支也能用。"""
    env = dict(os.environ)
    env["APP_DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "history", "--verbose"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"alembic history 失败:\n{r.stdout}\n{r.stderr}"
    # 输出里每条迁移有 "Rev: <id>" ⇒ 取**最后一个**（基线在链的末尾输出）
    revs = [line.split("Rev:")[1].strip() for line in r.stdout.splitlines() if "Rev:" in line]
    assert revs, f"alembic history 没输出：\n{r.stdout}"
    return revs[-1]


def test_require_migrated_accepts_a_migrated_db(tmp_path):
    """迁移跑过的库 ⇒ 校验通过。"""
    db = tmp_path / "ok.db"
    _run_alembic(db, "upgrade", "head")
    require_migrated(create_engine(f"sqlite+pysqlite:///{db}"))


def test_require_migrated_rejects_an_empty_db(tmp_path):
    """没跑迁移的库 ⇒ 必须报错（fail-closed），且要说清怎么建。"""
    db = tmp_path / "empty.db"
    engine = build_engine(f"sqlite+pysqlite:///{db}")
    with pytest.raises(RuntimeError) as exc:
        require_migrated(engine)
    assert "alembic upgrade head" in str(exc.value)


def test_require_migrated_rejects_a_partially_migrated_db(tmp_path):
    """迁移只跑了一半 ⇒ 必须报错（不能放过缺表的库）。

    ⚠️ **为什么按「第一条迁移」而不是写死 `0001_roles`**：这个仓库是多单累积的
    ⇒ 每单分支的迁移编号不同 ⇒ 写死某个编号 ⇒ 换分支就找不到那条迁移 ⇒
    ⇒ **自动取链条上的第一条**（`alembic history` 的第一条）。
    """
    db = tmp_path / "partial.db"
    first = _first_revision()
    _run_alembic(db, "upgrade", first)
    engine = create_engine(f"sqlite+pysqlite:///{db}")
    with pytest.raises(RuntimeError) as exc:
        require_migrated(engine)
    assert "alembic upgrade head" in str(exc.value)


def test_prod_app_refuses_to_start_without_migrations(tmp_path, monkeypatch):
    """生产环境 ⇒ 缺表 ⇒ 应用**拒绝启动**（而不是偷偷建表）。"""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("APP_TOKEN_SECRET", "real-secret-for-test")
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path}/nope.db")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/0")

    from app.main import create_app

    with pytest.raises(RuntimeError) as exc:
        create_app()
    assert "alembic upgrade head" in str(exc.value)


def test_non_prod_still_auto_creates(tmp_path, monkeypatch):
    """本地 ⇒ 仍然自动建表（本地开发与单测不该被迁移卡住）。"""
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path}/auto.db")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/0")

    from app.main import create_app

    app = create_app()
    assert app is not None

    from sqlalchemy import inspect

    engine = build_engine(f"sqlite+pysqlite:///{tmp_path}/auto.db")
    names = set(inspect(engine).get_table_names())
    assert "employees" in names, f"本地应当自动建表，实际有：{sorted(names)}"
