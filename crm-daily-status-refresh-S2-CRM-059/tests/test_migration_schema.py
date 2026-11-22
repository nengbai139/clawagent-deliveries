"""迁移与 ORM 模型的**表结构一致性**检查。

⚠️⚠️ **为什么这条测试值得单独写**：测试用 `create_all` 建表（**模型**的
表结构），生产用 **Alembic**（**迁移**的表结构）⇒ 两边不一致 ⇒
**测试跑的是另一套东西** ⇒ 上一张工单就是这么出的事（迁移里的唯一约束比
模型弱 ⇒ 生产上那条约束根本没生效，而测试是绿的）。

⇒ 这里**真的跑一遍迁移**（跑在另一个 schema 上）⇒ 再把两边的表结构
（列 / 可空性 / 类型 / 约束）**逐项对比** ⇒ 不一致就红。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text

from crm.core.config import get_settings
from crm.models.entities import JobRun

SCHEMA = "crm_job_run_schema_check"


def _type_family(raw: str) -> str:
    """把类型名归一到「族」再比。

    ⚠️ **必须归一**：PostgreSQL 的 inspector 把 `DateTime(timezone=True)` 报成
    `TIMESTAMP`，SQLAlchemy 的通用类型名是 `DATETIME` ⇒ **同一个类型、两个名字**
    ⇒ 不归一就会误报「类型不一致」。
    """
    t = raw.upper()
    if "TIMESTAMP" in t or "DATETIME" in t:
        return "TIMESTAMP"
    if t.startswith("UUID"):
        return "UUID"
    if "JSONB" in t or "JSON" in t:
        return "JSONB"
    if t.startswith("VARCHAR") or t.startswith("CHAR"):
        return "VARCHAR"
    if t.startswith("DATE"):
        return "DATE"
    if "INT" in t:
        return "INTEGER"
    return t


def _column_map(inspector, table_name: str, schema: str = SCHEMA) -> dict[str, dict]:
    out = {}
    for col in inspector.get_columns(table_name, schema=schema):
        out[col["name"]] = {
            "type": str(col["type"]),
            "nullable": col["nullable"],
        }
    return out


def _constraint_names(inspector, table_name: str, schema: str = SCHEMA) -> set[str]:
    names = set()
    for c in inspector.get_unique_constraints(table_name, schema=schema):
        names.add(c["name"])
    for c in inspector.get_check_constraints(table_name, schema=schema):
        names.add(c["name"])
    for c in inspector.get_foreign_keys(table_name, schema=schema):
        names.add(c["name"])
    for c in inspector.get_indexes(table_name, schema=schema):
        names.add(c["name"])
    return names


@pytest.fixture()
def migrated_schema():
    """在**另一个 schema** 上真跑一遍迁移（不动业务库）。"""
    url = get_settings().database_url
    eng = create_engine(url, future=True)
    with eng.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))

    # ⚠️ **自带连接 + `SET search_path`** ⇒ 迁移落在新 schema 里 ⇒
    #   不污染业务库（而 `version_table_schema` 只挪版本表，**不挪表**）。
    from alembic.config import Config

    from alembic import command

    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False

    with eng.connect() as conn:
        conn.execute(text(f"SET search_path TO {SCHEMA}"))
        conn.commit()
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        conn.commit()

    yield eng

    with eng.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
    eng.dispose()


def test_migrated_columns_match_model(migrated_schema):
    """迁移建出来的列与模型**逐列一致**（名字 / 类型 / 可空性）。"""
    insp = inspect(migrated_schema)
    migrated = _column_map(insp, "crm_job_run")
    model = {
        c.name: {"type": str(c.type), "nullable": c.nullable}
        for c in JobRun.__table__.columns
    }

    assert set(migrated) == set(model), "列集合不一致"
    for name, spec in model.items():
        assert migrated[name]["nullable"] == spec["nullable"], f"{name} 可空性不一致"
        assert _type_family(migrated[name]["type"]) == _type_family(spec["type"]), (
            f"{name} 类型不一致：迁移={migrated[name]['type']} 模型={spec['type']}"
        )


def test_migrated_constraints_match_model(migrated_schema):
    """迁移建出来的约束/索引与模型**同名**（名字变了就是行为变了）。"""
    insp = inspect(migrated_schema)
    migrated = _constraint_names(insp, "crm_job_run")
    model = set()
    for c in JobRun.__table__.constraints:
        if c.name:
            model.add(c.name)
    for idx in JobRun.__table__.indexes:
        if idx.name:
            model.add(idx.name)

    assert model <= migrated, f"迁移缺少约束/索引：{model - migrated}"


def test_migration_creates_only_crm_job_run(migrated_schema):
    """⚠️ **本单的迁移只建 `crm_job_run`**：其余四张表属别的工单。

    ⇒ 迁移若建了别的表 ⇒ 别的工单合入时会撞车（两张迁移建同一张表）。
    """
    insp = inspect(migrated_schema)
    tables = set(insp.get_table_names(schema=SCHEMA))
    # alembic 自己的版本表不算。
    tables = {t for t in tables if t != "alembic_version"}
    assert tables == {"crm_job_run"}, f"迁移建了不该建的表：{tables - {'crm_job_run'}}"


def test_org_id_is_nullable_in_migration(migrated_schema):
    """`crm_job_run.org_id` 必须**可空**（系统级运行记录不属于任何租户）。

    ⚠️ 这条单独钉住：模型里改成可空、迁移里忘了改 ⇒ 运行记录写不进去
    ⇒ **整个任务在生产上跑不起来**（而模型侧的测试还是绿的）。
    """
    insp = inspect(migrated_schema)
    cols = {c["name"]: c for c in insp.get_columns("crm_job_run", schema=SCHEMA)}
    assert cols["org_id"]["nullable"] is True


def test_check_constraint_rejects_unknown_status(migrated_schema):
    """状态枚举在数据库层也钉住（`success`/`partial`/`failed`）。"""
    from sqlalchemy.exc import IntegrityError

    with migrated_schema.connect() as conn:
        conn.execute(text(f"SET search_path TO {SCHEMA}"))
        conn.commit()
    with migrated_schema.begin() as conn:
        conn.execute(text(f"SET search_path TO {SCHEMA}"))
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO crm_job_run (id, org_id, created_at, updated_at, "
                    "job_name, run_date, started_at, stats, status) VALUES "
                    "('11111111-1111-1111-1111-111111111111', NULL, now(), now(), "
                    "'daily_status_refresh', current_date, now(), '{}'::jsonb, 'bogus')"
                )
            )
