"""角色的读写与删除保护。

删除保护：is_system=true 的内置角色不可删除 ⇒ 调用方收到 RoleError(code="role_is_system")，
接口层映射为 HTTP 409；自定义角色（is_system=false）照常软删除。
角色不存在 ⇒ RoleError(code="role_not_found")，接口层映射为 HTTP 404。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.iam.roles.models import (
    DATA_SCOPES,
    ROLE_LEVELS,
    Role,
    RolePermission,
    utcnow,
)


class RoleError(Exception):
    """角色操作失败。code 决定接口层返回的 HTTP 状态码。"""

    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def list_roles(session: Session, *, org_id: str | None = None) -> list[Role]:
    stmt = select(Role).where(Role.deleted_at.is_(None))
    if org_id is not None:
        stmt = stmt.where(Role.org_id == org_id)
    stmt = stmt.order_by(Role.is_system.desc(), Role.code.asc())
    return list(session.execute(stmt).scalars())


def get_role(session: Session, role_id: str) -> Role | None:
    return session.get(Role, role_id)


def get_role_by_code(session: Session, *, org_id: str, code: str) -> Role | None:
    stmt = select(Role).where(
        Role.org_id == org_id,
        Role.code == code,
        Role.deleted_at.is_(None),
    ).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def list_permissions(session: Session, role_id: str) -> list[RolePermission]:
    stmt = (
        select(RolePermission)
        .where(
            RolePermission.role_id == role_id,
            RolePermission.deleted_at.is_(None),
        )
        .order_by(RolePermission.permission_code.asc())
    )
    return list(session.execute(stmt).scalars())


def create_custom_role(
    session: Session,
    *,
    org_id: str,
    code: str,
    name: str,
    level: str,
    description: str = "",
    permissions: dict[str, str] | None = None,
    created_by: str | None = None,
    site_id: str | None = None,
) -> Role:
    """新建自定义角色（is_system=false）。"""
    code = (code or "").strip()
    if not code:
        raise RoleError("role_invalid", "角色 code 不能为空", status_code=400)
    if level not in ROLE_LEVELS:
        raise RoleError("role_invalid", f"角色 level 非法：{level}", status_code=400)
    if get_role_by_code(session, org_id=org_id, code=code) is not None:
        raise RoleError("role_exists", f"角色 code 已存在：{code}")

    role = Role(
        org_id=org_id,
        site_id=site_id,
        code=code,
        name=name,
        level=level,
        is_system=False,
        description=description,
        created_by=created_by,
    )
    session.add(role)
    session.flush()
    for perm_code, scope in (permissions or {}).items():
        if scope not in DATA_SCOPES:
            raise RoleError(
                "role_invalid", f"data_scope 非法：{scope}", status_code=400
            )
        session.add(
            RolePermission(
                org_id=org_id,
                site_id=site_id,
                role_id=role.id,
                permission_code=perm_code,
                data_scope=scope,
                created_by=created_by,
            )
        )
    session.commit()
    session.refresh(role)
    return role


def delete_role(session: Session, *, role_id: str) -> Role:
    """删除角色（软删除）。

    内置角色（is_system=true）⇒ 409，记录保留不动。
    """
    role = session.get(Role, role_id)
    if role is None or role.deleted_at is not None:
        raise RoleError("role_not_found", "角色不存在", status_code=404)
    if role.is_system:
        raise RoleError(
            "role_is_system", f"内置角色不可删除：{role.code}", status_code=409
        )
    now = utcnow()
    role.deleted_at = now
    role.updated_at = now
    for perm in list_permissions(session, role.id):
        perm.deleted_at = now
        perm.updated_at = now
    session.commit()
    return role


def serialize_role(role: Role, permissions: list[RolePermission]) -> dict:
    return {
        "id": role.id,
        "code": role.code,
        "name": role.name,
        "level": role.level,
        "is_system": role.is_system,
        "description": role.description,
        "permissions": [
            {"permission_code": p.permission_code, "data_scope": p.data_scope}
            for p in permissions
        ],
    }
