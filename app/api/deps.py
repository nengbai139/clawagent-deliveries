"""接口层公共依赖。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.iam.auth.qr.registry import ProviderRegistry
from app.iam.auth.tokens import TokenError, decode_access_token
from app.iam.models import Employee


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_redis(request: Request):
    return request.app.state.redis


def get_providers(request: Request) -> ProviderRegistry:
    return request.app.state.qr_providers


def get_session(request: Request) -> Session:
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_current_employee(
    request: Request, session: Session = Depends(get_session)
) -> Employee:
    """从 Bearer 令牌里取出当前登录员工。"""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthenticated", "message": "缺少访问令牌"},
        )
    settings: Settings = request.app.state.settings
    try:
        payload = decode_access_token(token, settings.token_secret)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_token", "message": str(exc)},
        ) from exc

    employee = session.get(Employee, payload.get("sub", ""))
    if employee is None or employee.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_token", "message": "令牌主体不存在"},
        )
    if not employee.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "employee_not_active", "message": "员工账号不可用"},
        )
    return employee
