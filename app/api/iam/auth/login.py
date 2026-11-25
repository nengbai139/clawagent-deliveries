"""口令登录接口。

扫码登录命中已绑定员工后，走的是与这里完全一致的后续步骤
（见 app/iam/auth/service.py 的 complete_login）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_redis, get_session, get_settings
from app.core.config import Settings
from app.core.errors import error_body
from app.iam.auth.passwords import verify_password
from app.iam.auth.service import AMR_PASSWORD, complete_login
from app.iam.models import Employee

router = APIRouter(prefix="/api/iam/auth", tags=["iam-auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    redis_client=Depends(get_redis),
):
    """账号密码登录：绑定外部身份后，员工用它换取绑定票据、完成绑定。"""
    stmt = select(Employee).where(
        Employee.username == payload.username, Employee.deleted_at.is_(None)
    )
    employee = session.execute(stmt).scalar_one_or_none()
    # 用户不存在与口令错误返回同一份错误体，避免账号枚举
    if employee is None or not verify_password(payload.password, employee.password_hash):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=error_body("invalid_credentials", "用户名或口令不正确"),
        )
    if not employee.is_active:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=error_body("employee_not_active", "员工账号不可用，无法登录"),
        )
    return complete_login(
        employee=employee, amr=AMR_PASSWORD, settings=settings, redis_client=redis_client
    )
