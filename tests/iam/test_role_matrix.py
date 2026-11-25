"""岗位角色定义与权限矩阵测试（覆盖四条验收标准）。

1. 种子执行后 9 个角色存在且 is_system=true，删除内置角色返回 409；
2. sys_admin 不含任何以 crm. / opp. / lead. 开头的权限点；
3. executive 的权限点动作只有 read / read_basic / use 三种；
4. Markdown 矩阵表由 role_matrix.yml 生成，与数据库内容一致（脚本比对通过）。
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.core.db import build_engine, build_session_factory, create_all
from app.iam.auth.tokens import issue_access_token
from app.iam.models import Employee
from app.iam.roles.compare import compare
from app.iam.roles.export import export_markdown, render_markdown
from app.iam.roles.matrix import (
    PERMISSION_CODES,
    MatrixError,
    action_of,
    load_matrix,
)
from app.iam.roles.models import Role, RolePermission
from app.iam.roles.seed import seed_roles
from app.main import create_app

EXPECTED_ROLE_CODES = [
    "front_desk",
    "ops_specialist",
    "member_manager",
    "opportunity_manager",
    "bizdev_consultant",
    "ops_supervisor",
    "knowledge_admin",
    "executive",
    "sys_admin",
]

SITE_LEVEL_ROLES = {
    "front_desk",
    "ops_specialist",
    "member_manager",
    "opportunity_manager",
    "bizdev_consultant",
    "ops_supervisor",
}
ORG_LEVEL_ROLES = {"knowledge_admin", "executive", "sys_admin"}

BUSINESS_PREFIXES = ("crm.", "opp.", "lead.")
EXECUTIVE_ALLOWED_ACTIONS = {"read", "read_basic", "use"}


# --------------------------------------------------------------------- 夹具
@pytest.fixture()
def matrix():
    return load_matrix()


@pytest.fixture()
def role_engine():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


@pytest.fixture()
def seeded_session(role_engine):
    """已按矩阵播种的数据库会话。"""
    factory = build_session_factory(role_engine)
    with factory() as session:
        seed_roles(session)
        yield session


@pytest.fixture()
def role_client(settings, role_engine, redis_client):
    app = create_app(
        settings=settings, engine=role_engine, redis_client=redis_client
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def admin_headers(role_client, matrix):
    """一个虚构的系统管理员账号的鉴权头。"""
    factory = role_client.app.state.session_factory
    with factory() as session:
        employee = Employee(
            org_id=matrix.org_id,
            site_id="site-001",
            username="sysadmin.test",
            display_name="系统管理员（虚构）",
            password_hash="not-used",
            status="active",
            created_by="test",
        )
        session.add(employee)
        session.commit()
        session.refresh(employee)
        employee_id = employee.id

    token = issue_access_token(
        employee_id=employee_id,
        org_id=matrix.org_id,
        amr="pwd",
        secret=role_client.app.state.settings.token_secret,
        ttl_seconds=3600,
    )
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------- 辅助
def role_by_code(session, code: str) -> Role:
    return (
        session.query(Role)
        .filter(Role.org_id == load_matrix().org_id, Role.code == code)
        .one()
    )


def permission_codes_of(session, role_code: str) -> set[str]:
    role = role_by_code(session, role_code)
    rows = (
        session.query(RolePermission)
        .filter(RolePermission.role_id == role.id, RolePermission.deleted_at.is_(None))
        .all()
    )
    return {row.permission_code for row in rows}


def scopes_of(session, role_code: str) -> dict[str, str]:
    role = role_by_code(session, role_code)
    rows = (
        session.query(RolePermission)
        .filter(RolePermission.role_id == role.id, RolePermission.deleted_at.is_(None))
        .all()
    )
    return {row.permission_code: row.data_scope for row in rows}


def parse_markdown_matrix(text: str) -> dict[tuple[str, str], str]:
    """解析 Markdown 矩阵表，返回 (role_code, permission_code) → data_scope。

    单元格为 `—` 表示该角色没有这个权限点（不进入结果）。
    """
    lines = text.splitlines()
    header_index = None
    for index, line in enumerate(lines):
        if line.startswith("| 权限点 |"):
            header_index = index
            break
    assert header_index is not None, "Markdown 里找不到权限矩阵表头"

    header_cells = [c.strip() for c in lines[header_index].strip().strip("|").split("|")]
    role_codes = [cell.split("<br>")[0].strip() for cell in header_cells[2:]]

    result: dict[tuple[str, str], str] = {}
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != len(header_cells):
            break
        permission_code = cells[0].strip("`")
        for role_code, cell in zip(role_codes, cells[2:]):
            if cell == "—":
                continue
            result[(role_code, permission_code)] = cell
    return result


# ================================================= 验收标准 1：9 个内置角色
def test_seed_creates_nine_system_roles(seeded_session):
    """种子执行后 9 个角色存在，且全部 is_system=true。"""
    roles = (
        seeded_session.query(Role)
        .filter(Role.deleted_at.is_(None))
        .order_by(Role.code)
        .all()
    )
    assert len(roles) == 9
    assert sorted(role.code for role in roles) == sorted(EXPECTED_ROLE_CODES)
    assert all(role.is_system is True for role in roles)


def test_role_levels_follow_matrix(seeded_session):
    """site 级角色 6 个、org 级角色 3 个。"""
    levels = {
        role.code: role.level
        for role in seeded_session.query(Role).all()
    }
    assert {code for code, level in levels.items() if level == "site"} == SITE_LEVEL_ROLES
    assert {code for code, level in levels.items() if level == "org"} == ORG_LEVEL_ROLES


def test_delete_system_role_returns_409(seeded_session, role_client, admin_headers):
    """删除内置角色返回 409，且记录保留。"""
    role = role_by_code(seeded_session, "front_desk")
    response = role_client.delete(f"/api/iam/roles/{role.id}", headers=admin_headers)

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "role_is_system"

    seeded_session.expire_all()
    still_there = seeded_session.get(Role, role.id)
    assert still_there is not None
    assert still_there.deleted_at is None


def test_delete_custom_role_succeeds(role_client, admin_headers, role_engine):
    """自定义角色（is_system=false）可以正常删除。"""
    factory = build_session_factory(role_engine)
    with factory() as session:
        created = role_client.post(
            "/api/iam/roles",
            headers=admin_headers,
            json={
                "code": "event_coordinator",
                "name": "活动统筹（虚构）",
                "level": "site",
                "description": "自定义角色",
                "permissions": {"event.read": "site"},
            },
        )
        assert created.status_code == 200
        role_id = created.json()["id"]

    response = role_client.delete(f"/api/iam/roles/{role_id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "deleted"

    with factory() as session:
        row = session.get(Role, role_id)
        assert row is not None
        assert row.deleted_at is not None


def test_delete_missing_role_returns_404(role_client, admin_headers):
    """角色不存在返回 404（不是 409）。"""
    response = role_client.delete(
        "/api/iam/roles/00000000-0000-4000-8000-000000000000",
        headers=admin_headers,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "role_not_found"


def test_seed_is_idempotent(role_engine):
    """重复执行种子：角色数、权限行数不变，也不产生重复角色。"""
    factory = build_session_factory(role_engine)
    with factory() as session:
        first = seed_roles(session)
        roles_after_first = session.query(Role).count()
        perms_after_first = (
            session.query(RolePermission).filter(RolePermission.deleted_at.is_(None)).count()
        )

    with factory() as session:
        second = seed_roles(session)
        roles_after_second = session.query(Role).count()
        perms_after_second = (
            session.query(RolePermission).filter(RolePermission.deleted_at.is_(None)).count()
        )

    assert first.roles_created == 9
    assert second.roles_created == 0
    assert second.roles_updated == 9
    assert roles_after_first == roles_after_second == 9
    assert perms_after_first == perms_after_second


def test_seed_rejects_unknown_permission_code(tmp_path):
    """yml 出现白名单外的权限点 ⇒ 直接报错，不静默跳过。"""
    bad = tmp_path / "role_matrix.yml"
    bad.write_text(
        "version: 1\n"
        "org_id: org-0001\n"
        "roles:\n"
        "  - code: front_desk\n"
        "    name: 前台接待\n"
        "    level: site\n"
        "    is_system: true\n"
        "    description: 非法矩阵\n"
        "    permissions:\n"
        "      - {code: visitor.read, data_scope: site}\n"
        "      - {code: crm.unknown, data_scope: site}\n",
        encoding="utf-8",
    )
    with pytest.raises(MatrixError) as excinfo:
        load_matrix(bad)
    assert "crm.unknown" in str(excinfo.value)


# ============================================ 验收标准 2：系统管理员职责分离
def test_sys_admin_has_no_business_domain_permissions(seeded_session):
    """sys_admin 不含任何以 crm. / opp. / lead. 开头的权限点。"""
    codes = permission_codes_of(seeded_session, "sys_admin")
    assert codes, "sys_admin 的权限集合不能为空（防止误配成空集而假通过）"

    offending = sorted(
        code for code in codes if code.startswith(BUSINESS_PREFIXES)
    )
    assert offending == []

    # 只落在 iam. / sys. / audit. 三个域
    assert all(
        code.startswith(("iam.", "sys.", "audit.")) for code in codes
    ), f"sys_admin 出现了非 iam./sys./audit. 权限：{sorted(codes)}"

    # data_scope 统一 org
    assert set(scopes_of(seeded_session, "sys_admin").values()) == {"org"}


# ================================== 验收标准 3：管理层只有 read / read_basic / use
def test_executive_actions_are_only_read_read_basic_use(seeded_session):
    """executive 的权限点动作只有 read、read_basic、use 三种。"""
    scopes = scopes_of(seeded_session, "executive")
    assert scopes, "executive 的权限集合不能为空"

    actions = {action_of(code) for code in scopes}
    assert actions <= EXECUTIVE_ALLOWED_ACTIONS, f"executive 出现了越权动作：{actions}"
    # 三种允许动作都要在集合内（防止漏配）
    assert actions == EXECUTIVE_ALLOWED_ACTIONS

    # 明确不含 write / manage / assign / export / publish / approve / read_sensitive
    forbidden = {"write", "manage", "assign", "export", "publish", "approve", "read_sensitive"}
    assert actions & forbidden == set()

    # data_scope 统一 org
    assert set(scopes.values()) == {"org"}


def test_matrix_matrix_data_scopes_follow_spec(seeded_session):
    """矩阵要点：会员经理 / 商机经理 / 招商顾问 / 运营主管 的数据范围。"""
    member = scopes_of(seeded_session, "member_manager")
    assert member["crm.read"] == "site"
    assert member["crm.write"] == "self"
    assert member["crm.follow_up"] == "self"
    assert member["crm.read_sensitive"] == "self"

    opportunity = scopes_of(seeded_session, "opportunity_manager")
    assert opportunity["opp.read"] == "org"
    assert opportunity["opp.match"] == "self"

    consultant = scopes_of(seeded_session, "bizdev_consultant")
    assert consultant["lead.read"] == "self"
    assert consultant["lead.write"] == "self"

    supervisor = scopes_of(seeded_session, "ops_supervisor")
    assert set(supervisor.values()) == {"site"}
    assert supervisor["space.export"] == "site"
    assert supervisor["opp.assign"] == "site"
    assert supervisor["lead.export"] == "site"
    # 运营主管不得持有任何 iam. / sys. 权限
    assert not [code for code in supervisor if code.startswith(("iam.", "sys."))]

    front_desk = scopes_of(seeded_session, "front_desk")
    assert set(front_desk) == {
        "visitor.read",
        "visitor.write",
        "checkin.read",
        "checkin.write",
        "space.read",
        "event.read",
        "crm.read_basic",
        "kb.read",
        "ai.assistant.use",
    }


# ================================ 验收标准 4：Markdown 矩阵表与数据库一致
def test_compare_script_reports_no_difference(seeded_session):
    """yml ↔ 数据库比对脚本：差异 0 条。"""
    result = compare(seeded_session)
    assert result.diff_count == 0, result.describe()
    assert result.consistent


def test_markdown_matrix_matches_database(seeded_session):
    """Markdown 矩阵表（由 yml 生成）与数据库内容逐格一致。"""
    text = render_markdown(load_matrix())
    parsed = parse_markdown_matrix(text)

    db_cells = {}
    for role in seeded_session.query(Role).all():
        for row in seeded_session.query(RolePermission).filter(
            RolePermission.role_id == role.id, RolePermission.deleted_at.is_(None)
        ):
            db_cells[(role.code, row.permission_code)] = row.data_scope

    assert parsed == db_cells


def test_markdown_row_count_matches_permission_count():
    """Markdown 表的行数 = yml 里权限点的条数（36 条）。"""
    text = render_markdown(load_matrix())
    matrix = load_matrix()
    assert len(matrix.permission_codes) == 36
    rows = [
        line
        for line in text.splitlines()
        if line.startswith("| `") and line.count("|") >= 3
    ]
    # 角色定义表里的角色 code 行不在矩阵表内（矩阵表以 `|` + 反引号开头的权限点行为准）
    permission_rows = [
        line
        for line in rows
        if line.split("|")[1].strip().strip("`") in matrix.permission_codes
    ]
    assert len(permission_rows) == len(matrix.permission_codes)


def test_export_markdown_writes_file(tmp_path):
    """导出脚本把 Markdown 写到指定路径。"""
    target = tmp_path / "role_matrix.md"
    path = export_markdown(target)
    assert path == target
    content = target.read_text(encoding="utf-8")
    assert "权限矩阵" in content
    assert "| `visitor.read` | read |" in content


def test_compare_detects_extra_permission(seeded_session):
    """库里多出一条矩阵外的权限点 ⇒ 比对脚本必须报出差异。"""
    role = role_by_code(seeded_session, "front_desk")
    seeded_session.add(
        RolePermission(
            org_id=role.org_id,
            role_id=role.id,
            permission_code="crm.read_sensitive",
            data_scope="self",
            created_by="test",
        )
    )
    seeded_session.commit()

    result = compare(seeded_session)
    assert not result.consistent
    assert result.diff_count == 1
    assert result.extra == [("front_desk", "crm.read_sensitive", "self")]
    assert "多余" in result.describe()[0]


def test_compare_detects_scope_mismatch(seeded_session):
    """data_scope 与 yml 不一致 ⇒ 比对脚本报出差异。"""
    role = role_by_code(seeded_session, "front_desk")
    row = (
        seeded_session.query(RolePermission)
        .filter(
            RolePermission.role_id == role.id,
            RolePermission.permission_code == "crm.read_basic",
        )
        .one()
    )
    row.data_scope = "self"
    seeded_session.commit()

    result = compare(seeded_session)
    assert not result.consistent
    assert result.scope_mismatch == [("front_desk", "crm.read_basic", "site", "self")]


def test_permission_whitelist_has_36_unique_codes():
    """权限点白名单：36 条、互不重复、域段合法。"""
    assert len(PERMISSION_CODES) == 36
    assert len(set(PERMISSION_CODES)) == 36
    assert all("." in code for code in PERMISSION_CODES)


def test_every_whitelisted_permission_is_used_by_some_role():
    """白名单里的每条权限点都至少被一个角色使用（矩阵不留悬空条目）。"""
    matrix = load_matrix()
    used = {code for role in matrix.roles for code in role.permission_codes}
    assert used == set(matrix.permission_codes)


def test_role_codes_are_stable(matrix):
    """9 个角色 code 与约定一致。"""
    assert list(matrix.role_codes) == EXPECTED_ROLE_CODES
    assert re.fullmatch(r"[a-z_]+", matrix.role_codes[0])
