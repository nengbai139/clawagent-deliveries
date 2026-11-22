"""报备方页面的测试。

⚠️ 工单原文：「争议只受理「系统判断错误」类原因……**接口文档与报备方页面
都写明这一点**」⇒ ⇒ **两处都要能查到**（缺一处就是不达标）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.dispute import ALLOWED_REASON_CODES


@pytest.fixture()
def client():
    with TestClient(create_app()) as c:
        yield c


def test_dispute_page_states_accepted_reasons(client):
    """页面**列全**了受理的理由（且与代码白名单一致）。"""
    r = client.get("/ref/report/00000000-0000-0000-0000-000000000001/dispute")
    assert r.status_code == 200
    html = r.text
    for code in ALLOWED_REASON_CODES:
        assert code in html, f"页面缺少受理理由 {code}"


def test_dispute_page_states_rejected_reasons(client):
    """页面**写明**了不受理的理由（否则报备方会反复提交被拒的理由）。"""
    r = client.get("/ref/report/00000000-0000-0000-0000-000000000001/dispute")
    assert r.status_code == 200
    html = r.text
    assert "earlier_offline_contact" in html
    assert "不受理" in html
    # ⚠️ 必须说明**为什么**不受理（首次报备规则）
    assert "首次报备" in html


def test_dispute_page_states_attachment_limit(client):
    """页面写明附件上限。"""
    r = client.get("/ref/report/00000000-0000-0000-0000-000000000001/dispute")
    assert "最多 5 个" in r.text


def test_openapi_states_the_rule_too(client):
    """**接口文档**（OpenAPI）里也要写明（工单要求两处都写）。"""
    spec = client.get("/openapi.json").json()
    desc = spec["paths"]["/api/ref/reports/{report_id}/disputes"]["post"]["description"]
    assert "只受理" in desc
    assert "earlier_offline_contact" in desc
    for code in ALLOWED_REASON_CODES:
        assert code in desc


def test_openapi_states_two_person_rule(client):
    """改判接口的文档里也要写明双人审批规则。"""
    spec = client.get("/openapi.json").json()
    desc = spec["paths"]["/api/admin/ref/disputes/{dispute_id}/decide"]["post"]["description"]
    assert "两个不同的人" in desc
    assert "重复审批不计为双人审批" in desc
