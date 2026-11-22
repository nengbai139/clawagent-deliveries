"""运维只读接口的测试。"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from crm.api.deps import get_session
from crm.main import create_app
from crm.models.entities import JobRun


@pytest.fixture()
def client(session):
    app = create_app()

    def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as c:
        yield c


def _run(session, **kwargs) -> JobRun:
    row = JobRun(
        org_id=None,
        job_name=kwargs.get("job_name", "daily_status_refresh"),
        run_date=kwargs.get("run_date", date(2026, 3, 15)),
        started_at=kwargs.get("started_at", datetime(2026, 3, 15, 0, 10, tzinfo=UTC)),
        finished_at=kwargs.get(
            "finished_at", datetime(2026, 3, 15, 0, 10, 5, tzinfo=UTC)
        ),
        stats=kwargs.get("stats", {"total_changed": 3}),
        status=kwargs.get("status", "success"),
    )
    session.add(row)
    session.flush()
    return row


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_list_job_runs(client, session):
    _run(session, run_date=date(2026, 3, 15), status="success")
    _run(session, run_date=date(2026, 3, 14), status="partial")
    session.commit()

    r = client.get("/api/admin/crm/job-runs")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert {x["status"] for x in body} == {"success", "partial"}
    assert all(x["job_name"] == "daily_status_refresh" for x in body)
    assert body[0]["stats"]["total_changed"] == 3


def test_list_job_runs_filters_by_date_and_name(client, session):
    _run(session, run_date=date(2026, 3, 15))
    _run(session, run_date=date(2026, 3, 14))
    _run(session, job_name="other_job", run_date=date(2026, 3, 15))
    session.commit()

    r = client.get("/api/admin/crm/job-runs", params={"run_date": "2026-03-15"})
    got = r.json()
    assert len(got) == 2

    r2 = client.get(
        "/api/admin/crm/job-runs", params={"job_name": "other_job"}
    )
    assert len(r2.json()) == 1
    assert r2.json()[0]["job_name"] == "other_job"


def test_list_job_runs_limit_is_capped(client, session):
    """⚠️ `limit` 必须有上限（否则一个请求就能把表拉爆）。"""
    r = client.get("/api/admin/crm/job-runs", params={"limit": 100000})
    assert r.status_code == 422


def test_soft_deleted_runs_are_hidden(client, session):
    """软删除的运行记录不出现在列表里。"""
    row = _run(session)
    row.deleted_at = datetime.now(UTC)
    session.commit()

    r = client.get("/api/admin/crm/job-runs")
    assert r.json() == []
