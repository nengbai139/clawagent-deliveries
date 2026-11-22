"""接口测试（工单原文：「接口测试」是交付物之一）。

用 `httpx` + `TestClient` 打**真实的 HTTP 接口** ⇒ 走完整的
FastAPI 依赖、校验、错误映射 ⇒ 测的是「接口对不对」，不是「函数对不对」。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.main import create_app
from app.models.entities import NotificationStub
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


def _submit_dispute(
    client,
    session: Session,
    org_id,
    report,
    *,
    reason_code: str = "wrong_attribution",
    reason_text: str = "归属错了",
    attachments: list[dict] | None = None,
    actor: uuid.UUID | None = None,
):
    """以**报备方**身份提交争议。

    ⚠️ 工单原文：「**报备方**对拒绝结果有异议时」提交 ⇒ 默认提交人就是
    该报备的报备方（`report.reporter_id`）⇒ 与接口的「只有报备方可提
    争议」这条规则一致。
    """
    body = {
        "reason_code": reason_code,
        "reason_text": reason_text,
        "attachments": attachments or [],
    }
    return client.post(
        f"/api/ref/reports/{report.id}/disputes",
        json=body,
        headers=_headers(actor or report.reporter_id, org_id),
    )


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
    r = _submit_dispute(
        client,
        session,
        org_id,
        report,
        reason_code="earlier_offline_contact",
        reason_text="我之前就线下见过这个客户",
    )
    assert r.status_code == 422
    assert "不受理" in r.text


def test_submit_dispute_allows_system_error_reason(client, session: Session, org_id):
    """系统判断错误类理由**可受理** ⇒ 201。"""
    report = make_report(session, org_id, status="rejected_invalid")
    session.flush()
    r = _submit_dispute(
        client,
        session,
        org_id,
        report,
        reason_code="normalization_false_duplicate",
        reason_text="归一化把它误判成重复了",
        attachments=[{"file_id": "f1", "name": "a.png", "url": "https://x/a.png"}],
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
    r = _submit_dispute(
        client,
        session,
        org_id,
        report,
        reason_text="归属判错了",
        attachments=[
            {"file_id": f"f{i}", "name": f"{i}.png", "url": f"https://x/{i}.png"}
            for i in range(6)
        ],
    )
    assert r.status_code == 422


def test_submit_dispute_rejected_when_not_the_reporter(client, session: Session, org_id):
    """**不是报备方**的人不能替别人提争议 ⇒ 422。"""
    report = make_report(session, org_id, status="rejected_invalid")
    session.flush()
    r = _submit_dispute(
        client, session, org_id, report, actor=uuid.uuid4()  # ≠ report.reporter_id
    )
    assert r.status_code == 422
    assert "not_the_reporter" in r.text


def test_submit_dispute_rejected_when_report_not_rejected(
    client, session: Session, org_id
):
    """**没被驳回**的报备不能提争议（没有「拒绝结果」可异议）⇒ 422。"""
    report = make_report(session, org_id, status="accepted")
    session.flush()
    r = _submit_dispute(client, session, org_id, report)
    assert r.status_code == 422
    assert "report_not_rejected" in r.text


def test_decide_overturn_needs_two_different_people(client, session: Session, org_id):
    """改判接口：第一次不生效（还缺一个角色），第二个人批后生效。"""
    report = make_report(session, org_id, status="rejected_invalid")
    session.flush()
    r = _submit_dispute(client, session, org_id, report)
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
    # ⚠️⚠️ **已满足的角色要如实报出来**：刚批完 channel_manager，
    # `missing_roles` 就**只该**剩 `finance` ⇒ 若报成两个角色都缺，
    # 调用方会以为「刚那次没生效」⇒ 接口契约就废了。
    assert b1["satisfied_roles"] == ["channel_manager"]
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
    assert b2["missing_roles"] == []


def test_decide_same_person_two_roles_rejected(client, session: Session, org_id):
    """同一个人有两个角色 ⇒ 第二次审批**被拒**（409）。"""
    report = make_report(session, org_id, status="rejected_invalid")
    session.flush()
    r = _submit_dispute(client, session, org_id, report)
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
    r = _submit_dispute(client, session, org_id, report)
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
    r = _submit_dispute(client, session, org_id, report)
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
    r = _submit_dispute(client, session, org_id, report)
    dispute_id = r.json()["id"]
    other = uuid.uuid4()
    give_roles(session, org_id, other, "sales")
    r1 = client.post(
        f"/api/admin/ref/disputes/{dispute_id}/decide",
        json={"decision": "overturn", "reason": "改判"},
        headers=_headers(other, org_id),
    )
    assert r1.status_code == 403


def test_decide_already_decided_is_409(client, session: Session, org_id):
    """**已处理**的争议不能再处理（防止「改判之后又 uphold」的倒流）⇒ 409。"""
    report = make_report(session, org_id, status="rejected_invalid")
    session.flush()
    r = _submit_dispute(client, session, org_id, report)
    dispute_id = r.json()["id"]

    manager = uuid.uuid4()
    give_roles(session, org_id, manager, "channel_manager")
    r1 = client.post(
        f"/api/admin/ref/disputes/{dispute_id}/decide",
        json={"decision": "uphold", "reason": "维持原判"},
        headers=_headers(manager, org_id),
    )
    assert r1.status_code == 200

    # 再处理一次 ⇒ 409
    r2 = client.post(
        f"/api/admin/ref/disputes/{dispute_id}/decide",
        json={"decision": "uphold", "reason": "再维持一次"},
        headers=_headers(manager, org_id),
    )
    assert r2.status_code == 409
    assert "dispute_not_pending" in r2.text


def test_overturn_restores_the_rejected_report(client, session: Session, org_id):
    """改判 = 认定系统判错了 ⇒ 被驳回的报备**恢复为 accepted**。

    ⚠️ 不恢复的话，这条报备仍带着 `rejected_invalid` 与驳回原因 ⇒
    下游按 status 取数时**仍把它当成被否决的报备** ⇒ 改判只改了归属、
    没改结论。
    """
    report = make_report(session, org_id, status="accepted")
    session.flush()
    # 走一遍真实驳回流程，把驳回原因也填上。
    reviewer = uuid.uuid4()
    r0 = client.post(
        f"/api/admin/ref/reports/{report.id}/reject",
        json={"reason": "联系人信息虚假"},
        headers=_headers(reviewer, org_id),
    )
    assert r0.status_code == 200, r0.text
    assert r0.json()["status"] == "rejected_invalid"

    r = _submit_dispute(client, session, org_id, report)
    dispute_id = r.json()["id"]

    manager = uuid.uuid4()
    finance = uuid.uuid4()
    give_roles(session, org_id, manager, "channel_manager")
    give_roles(session, org_id, finance, "finance")
    client.post(
        f"/api/admin/ref/disputes/{dispute_id}/decide",
        json={"decision": "overturn", "reason": "同意改判"},
        headers=_headers(manager, org_id),
    )
    r2 = client.post(
        f"/api/admin/ref/disputes/{dispute_id}/decide",
        json={"decision": "overturn", "reason": "同意改判"},
        headers=_headers(finance, org_id),
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["effective"] is True

    after = client.get(
        "/api/admin/ref/reports?status=accepted",
        headers=_headers(finance, org_id),
    )
    ids = {x["id"] for x in after.json()}
    assert str(report.id) in ids, "改判后报备应恢复为 accepted"
    row = next(x for x in after.json() if x["id"] == str(report.id))
    assert row["reject_reason"] is None, "改判后不应再留驳回原因"


def test_overturn_notifies_the_previous_owner(client, session: Session, org_id):
    """改判后**归属被夺走的一方**也要收到通知（「通知受影响各方」）。

    ⚠️ 最典型的受影响方就是**旧归属人** ⇒ 只通知新归属人是不够的。
    """
    channel_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    early_owner = uuid.uuid4()
    previous_owner = uuid.uuid4()

    # 更早的报备（归属 early_owner）—— 改判后归属应当归它。
    make_report(
        session,
        org_id,
        status="accepted",
        reported_at=datetime.now(UTC) - timedelta(days=10),
        owner_staff_id=early_owner,
        channel_id=channel_id,
        customer_id=customer_id,
    )
    # 本次争议针对的报备：归属 previous_owner。
    report = make_report(
        session,
        org_id,
        status="rejected_invalid",
        reported_at=datetime.now(UTC),
        owner_staff_id=previous_owner,
        channel_id=channel_id,
        customer_id=customer_id,
    )
    session.flush()
    r = _submit_dispute(client, session, org_id, report)
    dispute_id = r.json()["id"]

    manager = uuid.uuid4()
    finance = uuid.uuid4()
    give_roles(session, org_id, manager, "channel_manager")
    give_roles(session, org_id, finance, "finance")
    client.post(
        f"/api/admin/ref/disputes/{dispute_id}/decide",
        json={"decision": "overturn", "reason": "同意改判"},
        headers=_headers(manager, org_id),
    )
    client.post(
        f"/api/admin/ref/disputes/{dispute_id}/decide",
        json={"decision": "overturn", "reason": "同意改判"},
        headers=_headers(finance, org_id),
    )

    kinds = {
        (n.recipient, n.kind)
        for n in session.scalars(select(NotificationStub))
    }
    # ⚠️ 归属确实易主了（更早的报备归 early_owner）⇒ 旧归属人收到「失去归属」。
    session.refresh(report)
    assert report.owner_staff_id == early_owner, "归属应按原报备时间改判给更早那条"
    assert (str(previous_owner), "attribution.lost") in kinds, (
        "失去归属的一方必须被通知"
    )
    assert (str(early_owner), "attribution.gained") in kinds, (
        "获得归属的一方必须被通知"
    )
