"""角色管理接口（最小集合）。

- GET    /api/iam/roles            列出角色及其权限矩阵
- POST   /api/iam/roles            新建自定义角色（is_system=false）
- DELETE /api/iam/roles/{role_id}  删除角色；内置角色返回 409

说明：运行时「谁可以改角色」的鉴权接入不在本单范围（另一单），本单只要求
已登录员工 + 组织隔离；删除内置角色始终 409。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_employee, get_session
from app.core.errors import error_body
from app.iam.models import Employee
from app.iam.roles.service import (
    RoleError,
    create_custom_role,
    delete_role,
    get_role,
    list_permissions,
    list_roles,
    serialize_role,
)

router = APIRouter(prefix="/api/iam/roles", tags=["iam-roles"])


class RoleCreateRequest(BaseModel):
    code: str = Field(..., description="角色 code，例如 event_coordinator")
    name: str = Field(..., description="角色名称")
    level: str = Field("site", description="site 或 org")
    description: str = Field("", description="角色说明")
    permissions: dict[str, str] = Field(
        default_factory=dict, description="权限点 → 数据范围（self / site / org）"
    )


@router.get("")
def list_roles_endpoint(
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_session),
):
    """列出本组织的角色及其权限矩阵。"""
    roles = list_roles(session, org_id=employee.org_id)
    return {
        "items": [
            serialize_role(role, list_permissions(session, role.id)) for role in roles
        ]
    }


@router.post("")
def create_role_endpoint(
    payload: RoleCreateRequest,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_session),
):
    """新建自定义角色（is_system=false，可正常删除）。"""
    try:
        role = create_custom_role(
            session,
            org_id=employee.org_id,
            code=payload.code,
            name=payload.name,
            level=payload.level,
            description=payload.description,
            permissions=payload.permissions,
            created_by=employee.id,
            site_id=employee.site_id,
        )
    except RoleError as exc:
        return JSONResponse(
            status_code=exc.status_code, content=error_body(exc.code, exc.message)
        )
    return serialize_role(role, list_permissions(session, role.id))


@router.delete("/{role_id}")
def delete_role_endpoint(
    role_id: str,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_session),
):
    """删除角色。内置角色（is_system=true）不可删除 ⇒ 409。"""
    existing = get_role(session, role_id)
    if existing is None or existing.deleted_at is not None:
        return JSONResponse(
            status_code=404, content=error_body("role_not_found", "角色不存在")
        )
    if existing.org_id != employee.org_id:
        # 跨组织 ⇒ 按「不存在」处理，不泄露其他组织的数据
        return JSONResponse(
            status_code=404, content=error_body("role_not_found", "角色不存在")
        )
    try:
        role = delete_role(session, role_id=role_id)
    except RoleError as exc:
        return JSONResponse(
            status_code=exc.status_code, content=error_body(exc.code, exc.message)
        )
    return {"status": "deleted", "id": role.id, "code": role.code}
