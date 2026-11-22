"""测试夹具。

⚠️ **跑在真实 PostgreSQL 16 上**（不用 SQLite）：验收标准 1/3 涉及
`CheckConstraint`、JSONB、批量事务 ⇒ SQLite 下测的是另一套东西。

⚠️⚠️ **表从哪来**：
* `crm_job_run` ⇒ **本单的迁移**（`alembic upgrade head` 建）；
* 其余四张表（会籍/合同/回款计划/变更历史）⇒ **别的工单的** ⇒ 本单只声明
  ORM ⇒ 测试夹具用 `create_all` 建它们（测试专用路径）⇒
  **本单的迁移不碰它们**（否则别的工单合入时撞车）。
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from crm.core.config import get_settings
from crm.models.entities import (
    MEMBERSHIP_STATUS_ACTIVE,
    PAYMENT_STATUS_PENDING,
    Base,
    Contract,
    Membership,
    PaymentPlan,
)

#: 项目根目录（跑 alembic 迁移时要用）。
ROOT = Path(__file__).resolve().parent.parent

#: 会籍「即将到期」的提前天数（与 `crm.core.config` 的默认值一致）。
EXPIRING_WINDOW_DAYS = 30


def _database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("未设置 TEST_DATABASE_URL（需要 PostgreSQL 16）")
    return url


@pytest.fixture(scope="session", autouse=True)
def app_points_at_test_db():
    """让**应用自己的**配置也指向测试库。

    ⚠️ 后台任务的 CLI 自己开引擎（读 `CRM_DATABASE_URL`）⇒ 不指过去的话，
    CLI 会连到 `CRM_DATABASE_URL` 给的别的库（默认没有 ⇒ 启动时炸，但
    跑测试时可能指到**别的项目**的库）⇒ 这里统一指到测试库。
    """
    os.environ["CRM_DATABASE_URL"] = _database_url()
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def engine():
    """测试库引擎。

    ⚠️ **本单的迁移建 `crm_job_run`** ⇒ 这里先跑迁移，再补建**别的工单的**
    四张表（测试专用）。
    """
    eng = create_engine(_database_url(), future=True)

    # 1) 本单的表：走真正的迁移（验证迁移本身可用）。
    from alembic.config import Config

    from alembic import command

    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", _database_url())
    command.upgrade(cfg, "head")

    # 2) 别的工单的表：测试夹具建（生产由它们的迁移建）。
    other_tables = [
        Base.metadata.tables[name]
        for name in (
            "crm_membership",
            "crm_contract",
            "crm_payment_plan",
            "crm_change_history",
        )
    ]
    for table in other_tables:
        table.create(eng, checkfirst=True)

    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine) -> Session:
    """每个用例一个**干净**的库。

    ⚠️ **必须清表**：任务代码会 `session.commit()`（那是真实行为）⇒ 数据会留在
    库里 ⇒ 后一个用例看到前一个用例的残留 ⇒ 测试之间互相污染。
    """
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    sess = factory()
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()


@pytest.fixture()
def session_factory(engine):
    """给任务用的「每批开一个会话」的工厂（与真实运行同形）。"""

    def factory() -> Session:
        return sessionmaker(bind=engine, expire_on_commit=False, future=True)()

    return factory


# ---------------------------------------------------------------- 冻结时间

#: 冻结的基准日（验收标准 1 用）。
FROZEN_TODAY = date(2026, 3, 15)


@pytest.fixture()
def frozen_today() -> date:
    return FROZEN_TODAY


@pytest.fixture()
def frozen_clock():
    """冻结的时钟（`started_at`/`finished_at` 固定 ⇒ 汇总可复现）。"""
    seq = iter(
        [
            datetime(2026, 3, 15, 0, 10, 0, tzinfo=UTC),
            datetime(2026, 3, 15, 0, 10, 1, tzinfo=UTC),
        ]
    )

    def clock() -> datetime:
        try:
            return next(seq)
        except StopIteration:
            return datetime(2026, 3, 15, 0, 10, 1, tzinfo=UTC)

    return clock


# ---------------------------------------------------------------- 造数据

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
MEMBER = uuid.UUID("22222222-2222-2222-2222-222222222222")


def make_membership(
    session: Session,
    *,
    status: str = MEMBERSHIP_STATUS_ACTIVE,
    end_date: date | None = None,
    start_date: date | None = None,
    member_id: uuid.UUID = MEMBER,
    org_id: uuid.UUID = ORG,
) -> Membership:
    row = Membership(
        org_id=org_id,
        member_id=member_id,
        tier_id=uuid.uuid4(),
        status=status,
        start_date=start_date or (date(2026, 1, 1)),
        end_date=end_date or (date(2026, 12, 31)),
        amount_cents=7925,
    )
    session.add(row)
    session.flush()
    return row


def make_contract(
    session: Session,
    *,
    status: str = "active",
    end_date: date | None = None,
    start_date: date | None = None,
    member_id: uuid.UUID = MEMBER,
    org_id: uuid.UUID = ORG,
) -> Contract:
    row = Contract(
        org_id=org_id,
        member_id=member_id,
        status=status,
        start_date=start_date or (date(2026, 1, 1)),
        end_date=end_date or (date(2026, 12, 31)),
        amount_cents=10500,
    )
    session.add(row)
    session.flush()
    return row


def make_payment_plan(
    session: Session,
    contract: Contract,
    *,
    status: str = PAYMENT_STATUS_PENDING,
    due_date: date | None = None,
    installment_no: int = 1,
    org_id: uuid.UUID = ORG,
) -> PaymentPlan:
    row = PaymentPlan(
        org_id=org_id,
        contract_id=contract.id,
        installment_no=installment_no,
        status=status,
        due_date=due_date or (date(2026, 3, 1)),
        amount_cents=5000,
        paid_amount_cents=0,
    )
    session.add(row)
    session.flush()
    return row


@pytest.fixture()
def helper():
    """造数据函数集合。"""
    return type(
        "H",
        (),
        {
            "make_membership": staticmethod(make_membership),
            "make_contract": staticmethod(make_contract),
            "make_payment_plan": staticmethod(make_payment_plan),
        },
    )


@pytest.fixture()
def clean_tables(engine):
    """用例之间清库（有些用例自己开事务，不走 `session` 夹具）。"""
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


def count_rows(engine, table_name: str) -> int:
    with engine.begin() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one()
