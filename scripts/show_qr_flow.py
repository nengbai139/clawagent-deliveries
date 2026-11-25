"""取证脚本：用 FakeProvider 跑一遍扫码登录全流程，打印每一步的 HTTP 状态码与响应体。

用法（在仓库根目录执行）：
    python3 scripts/show_qr_flow.py

输出即 README §9.3 的证据：未绑定 → bind_required → 口令登录 → 绑定 → 再扫码直接登录
→ state 篡改 400 → state 重复使用 400 → 非白名单 redirect_uri 400 → disabled 员工 403 → 解绑。
脚本只用虚构数据（虚构员工「张三（虚构）」、虚构企业 corp-fake-001），不涉及任何真实个人信息。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fakeredis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.db import build_engine, build_session_factory, create_all  # noqa: E402
from app.iam.auth.passwords import hash_password  # noqa: E402
from app.iam.models import Employee, UserIdentity  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.fakes.fake_qr_provider import FakeProvider  # noqa: E402

REDIRECT_URI = "https://portal.example.test/iam/qr/callback"


def build():
    settings = Settings(
        app_env="test",
        token_secret="test-secret",
        qr_login_skip_totp=True,
        qr_redirect_allowlist=(REDIRECT_URI,),
    )
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    session_factory = build_session_factory(engine)
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    provider = FakeProvider("fake")
    app = create_app(
        settings=settings,
        engine=engine,
        redis_client=redis_client,
        providers=[provider],
    )
    return app, session_factory, redis_client, provider


def show(title: str, response) -> None:
    print(f"\n### {title}")
    print(f"HTTP {response.status_code}")
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2)[:1200])
    except Exception:  # noqa: BLE001
        print(response.text[:800])


def main() -> None:
    app, session_factory, redis_client, provider = build()

    with session_factory() as session:
        employee = Employee(
            org_id="org-001",
            site_id="site-001",
            username="zhang.san",
            display_name="张三（虚构）",
            password_hash=hash_password("correct-horse-battery", iterations=1000),
            status="active",
            created_by="script",
        )
        session.add(employee)
        session.commit()
        session.refresh(employee)
        employee_id = employee.id

    provider.register_code(
        "code-fake-0001", corp_id="corp-fake-001", external_user_id="ext-user-001"
    )

    with TestClient(app) as client:
        # ① start
        start = client.get(
            "/api/iam/auth/qr/fake/start", params={"redirect_uri": REDIRECT_URI}
        )
        show("① start（成功）", start)
        print("Set-Cookie:", start.headers.get("set-cookie"))

        # ② callback：未绑定
        first = client.get(
            "/api/iam/auth/qr/fake/callback",
            params={"code": "code-fake-0001", "state": start.json()["state"]},
        )
        show("② callback（未绑定 ⇒ bind_required）", first)
        ticket = first.json()["bind_ticket"]

        # ③ 口令登录
        login = client.post(
            "/api/iam/auth/login",
            json={"username": "zhang.san", "password": "correct-horse-battery"},
        )
        show("③ 口令登录", login)
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        # ④ bind
        bound = client.post(
            "/api/iam/me/identities/bind",
            json={"bind_ticket": ticket},
            headers=headers,
        )
        show("④ bind（绑定完成）", bound)

        # ⑤ 再扫一次：直接登录
        start2 = client.get(
            "/api/iam/auth/qr/fake/start", params={"redirect_uri": REDIRECT_URI}
        )
        second = client.get(
            "/api/iam/auth/qr/fake/callback",
            params={"code": "code-fake-0001", "state": start2.json()["state"]},
        )
        show("⑤ 再扫一次（已绑定 ⇒ 直接登录，amr=qr）", second)

        # ⑥ state 被篡改
        tampered = start2.json()["state"][:-1] + "X"
        bad = client.get(
            "/api/iam/auth/qr/fake/callback",
            params={"code": "code-fake-0001", "state": tampered},
        )
        show("⑥ callback（state 被篡改 ⇒ 400）", bad)

        # ⑦ state 重复使用
        reused = client.get(
            "/api/iam/auth/qr/fake/callback",
            params={"code": "code-fake-0001", "state": start2.json()["state"]},
        )
        show("⑦ callback（state 重复使用 ⇒ 400）", reused)

        # ⑧ redirect_uri 不在白名单
        not_allowed = client.get(
            "/api/iam/auth/qr/fake/start",
            params={"redirect_uri": "https://evil.example.net/steal"},
        )
        show("⑧ start（redirect_uri 不在白名单 ⇒ 400）", not_allowed)
        print("Redis 中的 state 键:", redis_client.keys("auth:qrstate:*"))

        # ⑨ 员工 disabled
        with session_factory() as session:
            session.add(
                UserIdentity(
                    org_id="org-001",
                    site_id="site-001",
                    employee_id=employee_id,
                    provider="fake",
                    corp_id="corp-fake-001",
                    external_user_id="ext-user-disabled",
                    created_by="script",
                )
            )
            session.commit()
            emp = session.get(Employee, employee_id)
            emp.status = "disabled"
            session.commit()
        provider.register_code(
            "code-fake-0002",
            corp_id="corp-fake-001",
            external_user_id="ext-user-disabled",
        )
        start3 = client.get(
            "/api/iam/auth/qr/fake/start", params={"redirect_uri": REDIRECT_URI}
        )
        disabled = client.get(
            "/api/iam/auth/qr/fake/callback",
            params={"code": "code-fake-0002", "state": start3.json()["state"]},
        )
        show("⑨ callback（员工 disabled ⇒ 403）", disabled)

        # ⑩ 解绑
        with session_factory() as session:
            emp = session.get(Employee, employee_id)
            emp.status = "active"
            session.commit()
        unbind = client.delete("/api/iam/me/identities/fake", headers=headers)
        show("⑩ unbind（解绑）", unbind)


if __name__ == "__main__":
    main()
