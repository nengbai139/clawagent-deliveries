"""接口测试（工单原文：「接口测试」是交付物之一）。

用 `httpx` + `TestClient` 打**真实的 HTTP 接口** ⇒ 走完整的
FastAPI 依赖、校验、错误映射 ⇒ 测的是「接口对不对」，不是「函数对不对」。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.main import create_app
from tests.conftest import give_roles, make_report


@pytest.fixture()
def client(session: Session, monkeypatch):
    """把应用绑到测试 session 上（每个测试独立事务）。"""
    app = create_app()

    def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as c:
        yield c


def _headers(actor_id: uuid.UUID | None = None, org_id: uuid.UUID | None = None):
    h = {"X-Actor-Type": "staff"}
    if actor_id:
        h["X-Actor-Id"] = str(actor_id)
    if org_id:
        h["X-Org-Id"] = str(org_id)
    return h


# ---------------------------------------------------------------- 复核

def test_list_reports_requires_actor(client):
    """没身份 ⇒ 401（不猜、不默认成某个人）。"""
    r = client.get("/api/admin/ref/reports")
    assert r.status_code == 401


def test_list_reports_filters(client, session: Session, org_id):
    """按 status / reporter_type / owner_staff_id 过滤。"""
    owner = uuid.uuid4()
    a = make_report(session, org_id, status="accepted", owner_staff_id=owner)
    b = make_report(session, org_id, status="rejected_invalid", owner_staff_id=owner)
    c = make_report(session, org_id, status="accepted", reporter_type="member")
    session.flush()

    actor = uuid.uuid4()
    r = client.get(
        "/api/admin/ref/reports",
        params={"status": "accepted"},
        headers=_headers(actor, org_id),
    )
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()}
    assert str(a.id) in ids
    assert str(b.id) not in ids

    r2 = client.get(
        "/api/admin/ref/reports",
        params={"owner_staff_id": str(owner)},
        headers=_headers(actor, org_id),
    )
    got = {x["id"] for x in r2.json()}
    assert {str(a.id), str(b.id)} <= got
    assert str(c.id) not in got

    r3 = client.get(
        "/api/admin/ref/reports",
        params={"reporter_type": "member"},
        headers=_headers(actor, org_id),
    )
    got3 = {x["id"] for x in r3.json()}
    assert str(c.id) in got3
    assert str(a.id) not in got3


def test_verify_and_reject_reports(client, session: Session, org_id):
    """标记 verified / 驳回（原因必填）。"""
    report = make_report(session, org_id, status="accepted")
    session.flush()
    actor = uuid.uuid4()

    r = client.post(
        f"/api/admin/ref/reports/{report.id}/verify",
        json={"reason": "资料齐全"},
        headers=_headers(actor, org_id),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "verified"

    # 驳回：**空原因** ⇒ 422（schema 层）
    r2 = client.post(
        f"/api/admin/ref/reports/{report.id}/reject",
        json={"reason": "   "},
        headers=_headers(actor, org_id),
    )
    assert r2.status_code == 422


def test_reject_only_from_accepted(client, session: Session, org_id):
    """非 accepted 的报备不可复核 ⇒ 409。"""
    report = make_report(session, org_id, status="submitted")
    session.flush()
    r = client.post(
        f"/api/admin/ref/reports/{report.id}/verify",
        json={},
        headers=_headers(uuid.uuid4(), org_id),
    )
    assert r.status_code == 409


# ---------------------------------------------------------------- 争议

def test_submit_dispute_rejects_disallowed_reason(client, session: Session, org_id):
    """「更早在线下接触过客户」这类理由**不受理** ⇒ 422。"""
    report = make_report(session, org_id, status="rejected_invalid")
    session.flush()
    r = client.post(
        f"/api/ref/reports/{report.id}/disputes",
        json={
            "reason_code": "earlier_offline_contact",
            "reason_text": "我之前就线下见过这个客户",
        },
        headers=_headers(uuid.uuid4(), org_id),
    )
    assert r.status_code == 422
    assert "不受理" in r.text


def test_submit_dispute_allows_system_error_reason(client, session: Session, org_id):
    """系统判断错误类理由**可受理** ⇒ 201。"""
    report = make_report(session, org_id, status="rejected_invalid")
    session.flush()
    r = client.post(
        f"/api/ref/reports/{report.id}/disputes",
        json={
            "reason_code": "normalization_false_duplicate",
            "reason_text": "归一化把它误判成重复了",
            "attachments": [{"file_id": "f1", "name": "a.png", "url": "https://x/a.png"}],
        },
        headers=_headers(uuid.uuid4(), org_id),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert len(body["attachments"]) == 1


def test_submit_dispute_rejects_more_than_5_attachments(
    client, session: Session, org_id
):
    """附件**最多 5 个** ⇒ 第 6 个 ⇒ 422。"""
    report = make_report(session, org_id, status="rejected_invalid")
    session.flush()
    r = client.post(
        f"/api/ref/reports/{report.id}/disputes",
        json={
            "reason_code": "wrong_attribution",
            "reason_text": "归属判错了",
            "attachments": [
                {"file_id": f"f{i}", "name": f"{i}.png", "url": f"https://x/{i}.png"}
                for i in range(6)
            ],
        },
        headers=_headers(uuid.uuid4(), org_id),
    )
    assert r.status_code == 422


def test_decide_overturn_needs_two_different_people(client, session: Session, org_id):
    """改判接口：第一次不生效（还缺一个角色），第二个人批后生效。"""
    report = make_report(session, org_id, status="rejected_invalid")
    session.flush()
    r = client.post(
        f"/api/ref/reports/{report.id}/disputes",
        json={"reason_code": "wrong_attribution", "reason_text": "归属错了"},
        headers=_headers(uuid.uuid4(), org_id),
    )
    assert r.status_code == 201
    dispute_id = r.json()["id"]

    manager = uuid.uuid4()
    finance = uuid.uuid4()
    give_roles(session, org_id, manager, "channel_manager")
    give_roles(session, org_id, finance, "finance")

    # 第一个（channel_manager）⇒ 不生效
    r1 = client.post(
        f"/api/admin/ref/disputes/{dispute_id}/decide",
        json={"decision": "overturn", "reason": "同意改判"},
        headers=_headers(manager, org_id),
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["effective"] is False
    assert b1["missing_roles"] == ["finance"]

    # 第二个（finance，另一个人）⇒ 生效
    r2 = client.post(
        f"/api/admin/ref/disputes/{dispute_id}/decide",
        json={"decision": "overturn", "reason": "同意改判"},
        headers=_headers(finance, org_id),
    )
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert b2["effective"] is True
    assert b2["status"] == "overturned"


def test_decide_same_person_two_roles_rejected(client, session: Session, org_id):
    """同一个人有两个角色 ⇒ 第二次审批**被拒**（409）。"""
    report = make_report(session, org_id, status="rejected_invalid")
    session.flush()
    r = client.post(
        f"/api/ref/reports/{report.id}/disputes",
        json={"reason_code": "wrong_attribution", "reason_text": "归属错了"},
        headers=_headers(uuid.uuid4(), org_id),
    )
    dispute_id = r.json()["id"]

    one = uuid.uuid4()
    give_roles(session, org_id, one, "channel_manager", "finance")

    r1 = client.post(
        f"/api/admin/ref/disputes/{dispute_id}/decide",
        json={"decision": "overturn", "reason": "第一次", "role": "channel_manager"},
        headers=_headers(one, org_id),
    )
    assert r1.status_code == 200
    assert r1.json()["effective"] is False

    r2 = client.post(
        f"/api/admin/ref/disputes/{dispute_id}/decide",
        json={"decision": "overturn", "reason": "第二次", "role": "finance"},
        headers=_headers(one, org_id),
    )
    assert r2.status_code == 409
    assert "same_person_already_approved" in r2.text


def test_decide_ambiguous_role_requires_explicit(client, session: Session, org_id):
    """两个角色都有却**没指定** role ⇒ 422（逼调用方说清楚）。"""
    report = make_report(session, org_id, status="rejected_invalid")
    session.flush()
    r = client.post(
        f"/api/ref/reports/{report.id}/disputes",
        json={"reason_code": "wrong_attribution", "reason_text": "归属错了"},
        headers=_headers(uuid.uuid4(), org_id),
    )
    dispute_id = r.json()["id"]

    one = uuid.uuid4()
    give_roles(session, org_id, one, "channel_manager", "finance")
    r1 = client.post(
        f"/api/admin/ref/disputes/{dispute_id}/decide",
        json={"decision": "overturn", "reason": "没指定角色"},
        headers=_headers(one, org_id),
    )
    assert r1.status_code == 422
    assert "role" in r1.text


def test_decide_uphold_takes_effect_immediately(client, session: Session, org_id):
    """**维持（uphold）** 一次即生效，不需要双人审批。"""
    report = make_report(session, org_id, status="rejected_invalid")
    session.flush()
    r = client.post(
        f"/api/ref/reports/{report.id}/disputes",
        json={"reason_code": "wrong_attribution", "reason_text": "归属错了"},
        headers=_headers(uuid.uuid4(), org_id),
    )
    dispute_id = r.json()["id"]

    manager = uuid.uuid4()
    give_roles(session, org_id, manager, "channel_manager")
    r1 = client.post(
        f"/api/admin/ref/disputes/{dispute_id}/decide",
        json={"decision": "uphold", "reason": "维持原判"},
        headers=_headers(manager, org_id),
    )
    assert r1.status_code == 200
    assert r1.json()["effective"] is True
    assert r1.json()["status"] == "upheld"


def test_decide_without_required_role_403(client, session: Session, org_id):
    """没有改判所需角色 ⇒ 403。"""
    report = make_report(session, org_id, status="rejected_invalid")
    session.flush()
    r = client.post(
        f"/api/ref/reports/{report.id}/disputes",
        json={"reason_code": "wrong_attribution", "reason_text": "归属错了"},
        headers=_headers(uuid.uuid4(), org_id),
    )
    dispute_id = r.json()["id"]
    other = uuid.uuid4()
    give_roles(session, org_id, other, "sales")
    r1 = client.post(
        f"/api/admin/ref/disputes/{dispute_id}/decide",
        json={"decision": "overturn", "reason": "改判"},
        headers=_headers(other, org_id),
    )
    assert r1.status_code == 403
