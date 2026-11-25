"""取证脚本：打印库里 9 个内置角色的权限矩阵，并演示删除保护。

用法：
    export APP_DATABASE_URL='sqlite+pysqlite:///./local_roles.db'
    python3 -m app.iam.roles.seed     # 先播种
    python3 scripts/show_role_matrix.py

输出：
    1) roles 表的 9 行记录（code / name / level / is_system）；
    2) 每个角色的权限点与数据范围（来自 role_permissions）；
    3) DELETE 内置角色 ⇒ 409 的响应体；
    4) DELETE 自定义角色 ⇒ 2xx 的响应体。
脚本只读内置角色、只删自己刚建的临时角色，不会动矩阵里的 9 个内置角色。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fakeredis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.db import build_engine  # noqa: E402
from app.iam.auth.tokens import issue_access_token  # noqa: E402
from app.iam.models import Employee  # noqa: E402
from app.iam.roles.cli import resolve_database_url  # noqa: E402
from app.iam.roles.matrix import load_matrix  # noqa: E402
from app.main import create_app  # noqa: E402


def main() -> int:
    matrix = load_matrix()
    url = resolve_database_url(None)
    engine = build_engine(url)
    settings = Settings.from_env().with_overrides(database_url=url)
    app = create_app(
        settings=settings, engine=engine, redis_client=fakeredis.FakeRedis()
    )

    with TestClient(app) as client:
        factory = app.state.session_factory
        with factory() as session:
            employee = (
                session.query(Employee)
                .filter(Employee.username == "evidence.sysadmin")
                .one_or_none()
            )
            if employee is None:
                employee = Employee(
                    org_id=matrix.org_id,
                    site_id="site-001",
                    username="evidence.sysadmin",
                    display_name="取证用系统管理员（虚构）",
                    password_hash="not-used",
                    status="active",
                    created_by="script",
                )
                session.add(employee)
                session.commit()
                session.refresh(employee)
            employee_id = employee.id

        token = issue_access_token(
            employee_id=employee_id,
            org_id=matrix.org_id,
            amr="pwd",
            secret=settings.token_secret,
            ttl_seconds=3600,
        )
        headers = {"Authorization": f"Bearer {token}"}

        print("### ① roles 表里的 9 个内置角色")
        listing = client.get("/api/iam/roles", headers=headers).json()
        for item in listing["items"]:
            print(
                f"  - {item['code']:<22} {item['name']:<6} level={item['level']:<5} "
                f"is_system={item['is_system']} 权限点数={len(item['permissions'])}"
            )

        print("\n### ② 每个角色的权限点与数据范围（来自 role_permissions）")
        for item in listing["items"]:
            scopes = ", ".join(
                f"{p['permission_code']}={p['data_scope']}" for p in item["permissions"]
            )
            print(f"  {item['code']}: {scopes}")

        print("\n### ③ DELETE 内置角色 ⇒ 409")
        system_role = next(r for r in listing["items"] if r["code"] == "front_desk")
        response = client.delete(f"/api/iam/roles/{system_role['id']}", headers=headers)
        print(f"  HTTP {response.status_code}")
        print(f"  {response.json()}")

        print("\n### ④ DELETE 不存在的角色 ⇒ 404")
        response = client.delete(
            "/api/iam/roles/00000000-0000-4000-8000-000000000000", headers=headers
        )
        print(f"  HTTP {response.status_code}")
        print(f"  {response.json()}")

        print("\n### ⑤ 自定义角色可正常删除 ⇒ 2xx")
        created = client.post(
            "/api/iam/roles",
            headers=headers,
            json={
                "code": "evidence_temp_role",
                "name": "取证临时角色（虚构）",
                "level": "site",
                "description": "取证用，脚本结束即删除",
                "permissions": {"event.read": "site"},
            },
        )
        print(f"  创建：HTTP {created.status_code} id={created.json().get('id')}")
        response = client.delete(
            f"/api/iam/roles/{created.json()['id']}", headers=headers
        )
        print(f"  删除：HTTP {response.status_code}")
        print(f"  {response.json()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
