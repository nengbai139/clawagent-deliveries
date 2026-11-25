"""钉住「Alembic 迁移链建出来的表 == 应用模型声明的表」。

⚠️ **真踩过**（2026-11-25，订单 #2968 合规体检）：

1. **本单原先没有 Alembic 迁移**（三张表走 `create_all`）⇒ ⇒ 偏离客户统一
   技术约定的 Alembic 要求 ⇒ ⇒ 补了 `0003_employees` /
   `0004_user_identities` / `0005_audit_logs`。

2. **补迁移时发现既有迁移与模型对不上**：`0001_roles` /
   `0002_role_permissions` 里 `created_at` / `updated_at` 写的是
   `nullable=True`，而模型里是 `Mapped[datetime]`（**NOT NULL**）⇒ ⇒
   **用迁移建的库**与**用 `create_all` 建的库**结构不同 ⇒ ⇒ 同一份代码在
   两种库上行为可能不一样 ⇒ ⇒ 已按模型为准改正。

⇒ ⇒ 这个测试就是那道防线：**两边必须一模一样**（表、列、类型、可空性、
索引、唯一约束、外键）。

⚠️ **为什么必须测**：这类不一致**不会报错**（SQLAlchemy 不会因为列可空性
不一致而拒绝操作）⇒ ⇒ 只有显式比对 schema 才抓得到 ⇒ ⇒ 靠人读是读不出来的。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parents[2]


def _schema_fingerprint(engine) -> dict:
    """把一个库的 schema 压成一个可比对的字典。"""
    insp = inspect(engine)
    out: dict = {"tables": {}}
    for table in sorted(insp.get_table_names()):
        if table == "alembic_version":
            continue
        cols = {}
        for c in sorted(insp.get_columns(table), key=lambda x: x["name"]):
            cols[c["name"]] = {
                "type": str(c["type"]),
                "nullable": bool(c["nullable"]),
                "pk": bool(c.get("primary_key")),
            }
        idx = {}
        for i in insp.get_indexes(table):
            idx[i["name"]] = {"unique": bool(i["unique"]), "cols": list(i["column_names"])}
        uq = sorted(
            tuple(sorted(u["column_names"])) for u in insp.get_unique_constraints(table)
        )
        fk = sorted(
            (tuple(sorted(f["constrained_columns"])), f["referred_table"])
            for f in insp.get_foreign_keys(table)
        )
        out["tables"][table] = {"columns": cols, "indexes": idx, "unique": uq, "fk": fk}
    return out


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


def test_migration_chain_matches_models(tmp_path):
    """迁移链建出来的库 == create_all 建出来的库。"""
    # ① 迁移链
    migrated_db = tmp_path / "migrated.db"
    _run_alembic(migrated_db, "upgrade", "head")
    migrated = create_engine(f"sqlite+pysqlite:///{migrated_db}")

    # ② 模型（create_all）
    models_db = tmp_path / "models.db"
    from app.core.db import Base, build_engine

    # ⚠️ **要 import 全部模型模块** ⇒ 否则 Base.metadata 里只有被 import 到的表。
    import app.iam.models  # noqa: F401
    import app.iam.roles.models  # noqa: F401

    engine = build_engine(f"sqlite+pysqlite:///{models_db}")
    Base.metadata.create_all(engine)

    a = _schema_fingerprint(migrated)
    b = _schema_fingerprint(engine)

    assert set(a["tables"]) == set(b["tables"]), (
        f"表集合不一致：迁移={sorted(a['tables'])} 模型={sorted(b['tables'])}"
    )
    for table in sorted(a["tables"]):
        assert a["tables"][table] == b["tables"][table], (
            f"表 {table} 的结构不一致：\n迁移={a['tables'][table]}\n模型={b['tables'][table]}"
        )


def test_migration_chain_has_all_five_tables(tmp_path):
    """迁移链要建出全部 5 张表（含上一单 2980 的两张）。"""
    db = tmp_path / "all.db"
    _run_alembic(db, "upgrade", "head")
    engine = create_engine(f"sqlite+pysqlite:///{db}")
    names = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert names == {
        "employees",
        "user_identities",
        "audit_logs",
        "roles",
        "role_permissions",
    }


def test_downgrade_base_removes_everything(tmp_path):
    """`downgrade base` 要能干净回退（每条迁移都得写完整 downgrade）。"""
    db = tmp_path / "down.db"
    _run_alembic(db, "upgrade", "head")
    _run_alembic(db, "downgrade", "base")
    engine = create_engine(f"sqlite+pysqlite:///{db}")
    names = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert names == set(), f"回退后还有表：{sorted(names)}"


def test_business_tables_have_the_standard_columns(tmp_path):
    """统一约定的 7 个字段，每张业务表都要有。"""
    db = tmp_path / "std.db"
    _run_alembic(db, "upgrade", "head")
    engine = create_engine(f"sqlite+pysqlite:///{db}")
    insp = inspect(engine)
    required = {
        "id",
        "org_id",
        "site_id",
        "created_at",
        "created_by",
        "updated_at",
        "deleted_at",
    }
    for table in ("employees", "user_identities", "audit_logs", "roles", "role_permissions"):
        cols = {c["name"] for c in insp.get_columns(table)}
        missing = required - cols
        assert not missing, f"{table} 缺统一约定的字段：{sorted(missing)}"


@pytest.mark.parametrize("table", ["employees", "user_identities", "audit_logs"])
def test_soft_delete_column_exists(tmp_path, table):
    """软删除字段必须是可空的（有值 = 已删）。"""
    db = tmp_path / f"sd_{table}.db"
    _run_alembic(db, "upgrade", "head")
    engine = create_engine(f"sqlite+pysqlite:///{db}")
    insp = inspect(engine)
    col = next(c for c in insp.get_columns(table) if c["name"] == "deleted_at")
    assert col["nullable"] is True, "deleted_at 必须可空（NULL = 未删除）"
