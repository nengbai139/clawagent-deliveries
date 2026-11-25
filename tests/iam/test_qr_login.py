"""扫码登录流程测试。

覆盖四条验收标准：
1. state 被篡改 / 过期 / 重复使用时 callback 返回 400；
2. 未绑定的外部身份返回 bind_required，绑定后再次扫码可直接登录；
3. redirect_uri 不在白名单时 start 返回 400；
4. disabled 状态的员工扫码登录返回 403。
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.iam.models import Employee, UserIdentity
from tests.conftest import ALLOWED_REDIRECT_URI

PROVIDER = "fake"
CODE = "code-fake-0001"
CORP_ID = "corp-fake-001"
EXT_USER_ID = "ext-user-001"


# --------------------------------------------------------------------- 辅助
def start_qr(client: TestClient, redirect_uri: str = ALLOWED_REDIRECT_URI):
    return client.get(
        f"/api/iam/auth/qr/{PROVIDER}/start", params={"redirect_uri": redirect_uri}
    )


def callback_qr(client: TestClient, code: str = CODE, state: str = "x"):
    return client.get(
        f"/api/iam/auth/qr/{PROVIDER}/callback", params={"code": code, "state": state}
    )


def login_with_password(client: TestClient, username: str, password: str):
    return client.post(
        "/api/iam/auth/login", json={"username": username, "password": password}
    )


def bind_row(session_factory, employee: Employee, provider=PROVIDER, corp_id=CORP_ID, ext=EXT_USER_ID):
    with session_factory() as session:
        row = UserIdentity(
            org_id=employee.org_id,
            site_id=employee.site_id,
            employee_id=employee.id,
            provider=provider,
            corp_id=corp_id,
            external_user_id=ext,
            display_name="虚构员工",
            created_by="test",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


# ============================================================ 验收标准 1：state
def test_start_returns_authorize_url_and_sets_http_only_cookie(client, provider, redis_client):
    """start：生成 state、写 Redis、下发 HttpOnly Cookie。"""
    response = start_qr(client)

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == PROVIDER
    assert body["state"]
    assert body["authorize_url"].startswith("https://qr.example.test/authorize")
    assert f"state={body['state']}" in body["authorize_url"]

    # state 存 Redis，5 分钟过期
    assert redis_client.exists(f"auth:qrstate:{body['state']}") == 1
    assert redis_client.ttl(f"auth:qrstate:{body['state']}") <= 300

    # 浏览器 Cookie：HttpOnly + SameSite=Lax
    cookie_header = response.headers.get("set-cookie", "")
    assert "qr_state=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header.replace("samesite", "SameSite")


def test_callback_with_tampered_state_returns_400(client, provider, redis_client):
    """验收标准 1（篡改）：state 被改 ⇒ 400，且不调用 exchange_code。"""
    started = start_qr(client).json()
    tampered = started["state"][:-1] + ("a" if started["state"][-1] != "a" else "b")

    response = callback_qr(client, state=tampered)

    assert response.status_code == 400
    assert response.json()["code"] == "state_invalid"
    # 无效 state 不应消耗上游 code
    assert provider.exchange_call_count == 0


def test_callback_with_missing_cookie_returns_400(client, provider):
    """验收标准 1（绑定）：缺少与发起浏览器对应的 Cookie ⇒ 400。"""
    started = start_qr(client).json()
    fresh_client = TestClient(client.app)  # 无 Cookie 的浏览器

    response = callback_qr(fresh_client, state=started["state"])

    assert response.status_code == 400
    assert response.json()["code"] == "state_invalid"
    assert provider.exchange_call_count == 0


def test_callback_with_mismatched_cookie_returns_400(client, provider):
    """验收标准 1（篡改）：Cookie 与 state 不一致 ⇒ 400。"""
    started = start_qr(client).json()
    other_client = TestClient(client.app)

    response = other_client.get(
        f"/api/iam/auth/qr/{PROVIDER}/callback",
        params={"code": CODE, "state": started["state"]},
        cookies={"qr_state": "someone-elses-browser-token"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "state_invalid"
    assert provider.exchange_call_count == 0


def test_callback_with_expired_state_returns_400(client, provider, redis_client):
    """验收标准 1（过期）：state 超过 5 分钟 TTL ⇒ 400 state_expired。"""
    started = start_qr(client).json()
    state = started["state"]

    # 模拟 TTL 到期：主键消失，但 issued 副本还在 ⇒ 判定为「过期」而非「无效」
    redis_client.delete(f"auth:qrstate:{state}")
    assert redis_client.exists(f"auth:qrstate:issued:{state}") == 1

    response = callback_qr(client, state=state)

    assert response.status_code == 400
    assert response.json()["code"] == "state_expired"
    assert provider.exchange_call_count == 0


def test_callback_with_really_expired_state_returns_400(
    settings, engine, redis_client, provider
):
    """验收标准 1（过期）：按真实 TTL 到期（缩短 TTL 到 1 秒后等待）⇒ 400 state_expired。"""
    import time

    from app.main import create_app

    short_ttl = settings.with_overrides(qr_state_ttl_seconds=1)
    app = create_app(
        settings=short_ttl, engine=engine, redis_client=redis_client, providers=[provider]
    )
    with TestClient(app) as client:
        started = start_qr(client).json()
        state = started["state"]
        assert redis_client.exists(f"auth:qrstate:{state}") == 1

        time.sleep(1.2)  # 超过 TTL
        assert redis_client.exists(f"auth:qrstate:{state}") == 0

        response = callback_qr(client, state=state)
        assert response.status_code == 400
        assert response.json()["code"] == "state_expired"
        assert provider.exchange_call_count == 0


def test_callback_with_reused_state_returns_400(client, provider, employee, session_factory):
    """验收标准 1（重复使用）：同一个 state 第二次回调 ⇒ 400 state_used。"""
    provider.register_code(CODE, corp_id=CORP_ID, external_user_id=EXT_USER_ID)
    bind_row(session_factory, employee)

    started = start_qr(client).json()
    state = started["state"]

    first = callback_qr(client, state=state)
    assert first.status_code == 200
    assert first.json()["step"] == "login_complete"

    second = callback_qr(client, state=state)
    assert second.status_code == 400
    assert second.json()["code"] == "state_used"
    # 只有第一次消费掉了上游 code
    assert provider.exchange_call_count == 1


def test_callback_with_unknown_provider_returns_404(client):
    response = client.get(
        "/api/iam/auth/qr/not-registered/start",
        params={"redirect_uri": ALLOWED_REDIRECT_URI},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "provider_not_found"


# ============================================================ 验收标准 2：绑定
def test_unbound_identity_returns_bind_required_then_bind_then_login(
    client, provider, employee, session_factory, redis_client
):
    """验收标准 2：未绑定 ⇒ bind_required；绑定后再次扫码可直接登录（amr=qr）。"""
    provider.register_code(CODE, corp_id=CORP_ID, external_user_id=EXT_USER_ID)

    # --- 第一次扫码：外部身份还没绑定
    started = start_qr(client).json()
    first = callback_qr(client, state=started["state"])
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["step"] == "bind_required"
    assert first_body["bind_ticket"]
    # 未绑定前不签发任何令牌
    assert "access_token" not in first_body
    # bind_ticket 存 Redis，短 TTL
    assert redis_client.exists(f"auth:qrbind:{first_body['bind_ticket']}") == 1
    assert redis_client.ttl(f"auth:qrbind:{first_body['bind_ticket']}") <= 300

    # --- 员工用账号密码登录，拿到访问令牌
    login = login_with_password(client, "zhang.san", "correct-horse-battery")
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # --- 凭 bind_ticket 完成绑定
    bound = client.post(
        "/api/iam/me/identities/bind",
        json={"bind_ticket": first_body["bind_ticket"]},
        headers=headers,
    )
    assert bound.status_code == 200
    assert bound.json()["status"] == "bound"
    assert bound.json()["provider"] == PROVIDER

    # 绑定写审计日志
    with session_factory() as session:
        from app.iam.models import AuditLog

        actions = [row.action for row in session.query(AuditLog).all()]
    assert "iam.identity.bind" in actions

    # --- 第二次扫码：已绑定，直接登录，amr=qr
    started2 = start_qr(client).json()
    second = callback_qr(client, state=started2["state"])
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["step"] == "login_complete"
    assert second_body["amr"] == "qr"
    assert second_body["access_token"]

    # 令牌里 amr=qr
    payload_b64 = second_body["access_token"].split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    assert claims["amr"] == "qr"
    assert claims["sub"] == employee.id


def test_bind_ticket_is_single_use(client, provider, employee, session_factory):
    """绑定票据单次有效：重复使用返回 400。"""
    provider.register_code(CODE, corp_id=CORP_ID, external_user_id=EXT_USER_ID)
    started = start_qr(client).json()
    bind_required = callback_qr(client, state=started["state"]).json()
    ticket = bind_required["bind_ticket"]

    token = login_with_password(client, "zhang.san", "correct-horse-battery").json()[
        "access_token"
    ]
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post(
        "/api/iam/me/identities/bind", json={"bind_ticket": ticket}, headers=headers
    )
    assert first.status_code == 200

    second = client.post(
        "/api/iam/me/identities/bind", json={"bind_ticket": ticket}, headers=headers
    )
    assert second.status_code == 400
    assert second.json()["code"] == "bind_ticket_invalid"


def test_bind_requires_authentication(client, provider):
    """未登录调用 bind ⇒ 401。"""
    response = client.post(
        "/api/iam/me/identities/bind", json={"bind_ticket": "whatever"}
    )
    assert response.status_code == 401


def test_unbind_then_scan_returns_bind_required_again(
    client, provider, employee, session_factory
):
    """解绑后再次扫码 ⇒ 重新返回 bind_required。"""
    provider.register_code(CODE, corp_id=CORP_ID, external_user_id=EXT_USER_ID)
    bind_row(session_factory, employee)

    started = start_qr(client).json()
    assert callback_qr(client, state=started["state"]).json()["step"] == "login_complete"

    token = login_with_password(client, "zhang.san", "correct-horse-battery").json()[
        "access_token"
    ]
    headers = {"Authorization": f"Bearer {token}"}

    unbound = client.delete(f"/api/iam/me/identities/{PROVIDER}", headers=headers)
    assert unbound.status_code == 200
    assert unbound.json()["status"] == "unbound"

    # 解绑写审计日志
    with session_factory() as session:
        from app.iam.models import AuditLog

        actions = [row.action for row in session.query(AuditLog).all()]
    assert "iam.identity.unbind" in actions

    started2 = start_qr(client).json()
    again = callback_qr(client, state=started2["state"])
    assert again.json()["step"] == "bind_required"


# ============================================================ 验收标准 3：白名单
def test_start_with_redirect_uri_not_in_allowlist_returns_400(
    client, redis_client, provider
):
    """验收标准 3：redirect_uri 不在白名单 ⇒ 400，且不写 Redis。"""
    response = start_qr(client, redirect_uri="https://evil.example.net/steal")

    assert response.status_code == 400
    assert response.json()["code"] == "redirect_uri_not_allowed"
    # 没有生成 state，也没有调用适配器
    assert redis_client.keys("auth:qrstate:*") == []
    assert provider.build_calls == []


def test_start_with_allowlist_empty_fails_closed(settings, engine, redis_client, provider):
    """白名单为空 ⇒ fail-closed（400），不做「空即放行」。"""
    empty = settings.with_overrides(qr_redirect_allowlist=())
    from app.main import create_app

    app = create_app(
        settings=empty, engine=engine, redis_client=redis_client, providers=[provider]
    )
    with TestClient(app) as client:
        response = start_qr(client)
        assert response.status_code == 400
        assert response.json()["code"] == "redirect_allowlist_not_configured"
        assert redis_client.keys("auth:qrstate:*") == []


def test_start_rejects_redirect_uri_same_path_other_host(client):
    """host 不同但 path 相同 ⇒ 不在白名单。"""
    response = start_qr(client, redirect_uri="https://other.example.test/iam/qr/callback")
    assert response.status_code == 400
    assert response.json()["code"] == "redirect_uri_not_allowed"


def test_start_rejects_redirect_uri_with_extra_query(client):
    """多带 query 参数 ⇒ 不在白名单（白名单条目必须完全一致）。"""
    response = start_qr(client, redirect_uri=f"{ALLOWED_REDIRECT_URI}?next=/home")
    assert response.status_code == 400
    assert response.json()["code"] == "redirect_uri_not_allowed"


def test_start_accepts_allowlist_entry_with_trailing_slash(settings, engine, redis_client, provider):
    """白名单条目末尾带斜杠 ⇒ 先规范化再比较。"""
    normalized = settings.with_overrides(
        qr_redirect_allowlist=("https://portal.example.test/iam/qr/callback/",)
    )
    from app.main import create_app

    app = create_app(
        settings=normalized, engine=engine, redis_client=redis_client, providers=[provider]
    )
    with TestClient(app) as client:
        response = start_qr(client, redirect_uri=ALLOWED_REDIRECT_URI)
        assert response.status_code == 200


# ============================================================ 验收标准 4：disabled
def test_disabled_employee_qr_login_returns_403(
    client, provider, disabled_employee, session_factory
):
    """验收标准 4：disabled 员工扫码登录 ⇒ 403，且不签发令牌。"""
    provider.register_code(CODE, corp_id=CORP_ID, external_user_id=EXT_USER_ID)
    bind_row(session_factory, disabled_employee)

    started = start_qr(client).json()
    response = callback_qr(client, state=started["state"])

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "employee_not_active"
    assert "access_token" not in body
    # 403 响应体不泄露该外部身份绑定的是谁
    assert disabled_employee.id not in json.dumps(body, ensure_ascii=False)


def test_cross_org_identity_returns_403(client, provider, employee, session_factory):
    """绑定关系与员工不在同一组织 ⇒ 同样 403。"""
    provider.register_code(CODE, corp_id=CORP_ID, external_user_id=EXT_USER_ID)
    row = bind_row(session_factory, employee)
    with session_factory() as session:
        db_row = session.get(UserIdentity, row.id)
        db_row.org_id = "org-other-999"
        session.commit()

    started = start_qr(client).json()
    response = callback_qr(client, state=started["state"])
    assert response.status_code == 403
    assert response.json()["code"] == "employee_not_active"


# ================================================ TOTP 开关与其它边界
def test_qr_login_requires_totp_by_default(settings, engine, redis_client, provider, make_employee):
    """APP_QR_LOGIN_SKIP_TOTP 默认 false：启用 TOTP 的员工扫码后仍需二次验证。"""
    default_settings = settings.with_overrides(qr_login_skip_totp=False)
    employee = make_employee(
        username="totp.user", totp_enabled=True, totp_secret="FAKESECRET"
    )
    from app.main import create_app

    app = create_app(
        settings=default_settings,
        engine=engine,
        redis_client=redis_client,
        providers=[provider],
    )
    provider.register_code(CODE, corp_id=CORP_ID, external_user_id=EXT_USER_ID)
    with app.state.session_factory() as session:
        row = UserIdentity(
            org_id=employee.org_id,
            site_id=employee.site_id,
            employee_id=employee.id,
            provider=PROVIDER,
            corp_id=CORP_ID,
            external_user_id=EXT_USER_ID,
            created_by="test",
        )
        session.add(row)
        session.commit()

    with TestClient(app) as client:
        started = start_qr(client).json()
        response = callback_qr(client, state=started["state"])
        assert response.status_code == 200
        body = response.json()
        assert body["step"] == "totp_required"
        assert body["challenge"]
        assert "access_token" not in body


def test_qr_login_skips_totp_when_env_flag_true(client, provider, employee, session_factory):
    """APP_QR_LOGIN_SKIP_TOTP=true ⇒ 直接签发令牌（amr=qr）。"""
    provider.register_code(CODE, corp_id=CORP_ID, external_user_id=EXT_USER_ID)
    bind_row(session_factory, employee)

    started = start_qr(client).json()
    body = callback_qr(client, state=started["state"]).json()
    assert body["step"] == "login_complete"
    assert body["amr"] == "qr"


def test_provider_exchange_failure_returns_502(client, provider, employee, session_factory):
    """适配器兑换失败 ⇒ 502（并记录可读错误码）。"""
    provider.register_code(CODE, corp_id=CORP_ID, external_user_id=EXT_USER_ID)
    provider.inject_failure(CODE)
    bind_row(session_factory, employee)

    started = start_qr(client).json()
    response = callback_qr(client, state=started["state"])
    assert response.status_code == 502
    assert response.json()["code"] == "provider_exchange_failed"


def test_state_consumed_even_when_identity_unbound(client, provider):
    """未绑定时 state 也已被消费（一次性），同一个 state 不能反复试探。"""
    provider.register_code(CODE, corp_id=CORP_ID, external_user_id=EXT_USER_ID)
    started = start_qr(client).json()
    state = started["state"]

    first = callback_qr(client, state=state)
    assert first.json()["step"] == "bind_required"

    second = callback_qr(client, state=state)
    assert second.status_code == 400
    assert second.json()["code"] == "state_used"


@pytest.mark.parametrize("code", ["unknown-code"])
def test_callback_with_invalid_code_returns_502(client, provider, code):
    """上游不认识 code ⇒ 502。"""
    started = start_qr(client).json()
    response = callback_qr(client, code=code, state=started["state"])
    assert response.status_code == 502
    assert response.json()["code"] == "provider_exchange_failed"


def test_fake_provider_satisfies_protocol(provider):
    """FakeProvider 满足 QrLoginProvider 协议 ⇒ 真实厂商实现照抄即可。"""
    from app.iam.auth.qr.provider import QrLoginProvider

    assert isinstance(provider, QrLoginProvider)
    assert provider.health_check() is True
    url = provider.build_authorize_url("state-1", ALLOWED_REDIRECT_URI)
    assert url.startswith("https://qr.example.test/authorize?")
    assert "state=state-1" in url


def test_provider_registry_is_case_insensitive(provider):
    """provider 名一律小写（wecom / feishu）。"""
    from app.iam.auth.qr.registry import ProviderRegistry

    registry = ProviderRegistry([provider])
    assert registry.has("FAKE") is True
    assert registry.get("Fake") is provider
    assert registry.names() == ["fake"]


def test_state_store_uses_expected_keys(redis_client):
    """状态存储口径：auth:qrstate:{state} + issued 副本。"""
    from app.iam.auth.qr.state import QrStateStore

    store = QrStateStore(redis_client, ttl_seconds=300)
    state, token = store.issue("fake", ALLOWED_REDIRECT_URI)
    assert redis_client.exists(f"auth:qrstate:{state}") == 1
    assert redis_client.exists(f"auth:qrstate:issued:{state}") == 1
    assert len(token) > 20

    info = store.consume(state, token)
    assert info.provider == "fake"
    assert redis_client.exists(f"auth:qrstate:{state}") == 0
