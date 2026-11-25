"""当前登录员工的外部身份绑定接口。

- POST   /api/iam/me/identities/bind      {"bind_ticket": "..."}
- GET    /api/iam/me/identities
- DELETE /api/iam/me/identities/{provider}
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_employee, get_redis, get_session, get_settings
from app.core.config import Settings
from app.core.errors import error_body
from app.iam.audit import ACTION_IDENTITY_BIND, ACTION_IDENTITY_UNBIND, record_audit
from app.iam.auth.qr.bind_ticket import BindTicketError, BindTicketStore
from app.iam.identities import (
    bind_identity,
    find_identity_by_triple,
    list_identities,
    unbind_identities,
)
from app.iam.models import Employee

router = APIRouter(prefix="/api/iam/me/identities", tags=["iam-identities"])


class BindRequest(BaseModel):
    bind_ticket: str = Field(..., description="扫码回调下发的 bind_ticket")


@router.get("")
def list_my_identities(
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_session),
):
    rows = list_identities(session, employee.id)
    return {
        "items": [
            {
                "provider": row.provider,
                "corp_id": row.corp_id,
                "external_user_id": row.external_user_id,
                "display_name": row.display_name,
                "bound_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.post("/bind")
def bind_identity_endpoint(
    payload: BindRequest,
    request: Request,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    redis_client=Depends(get_redis),
):
    """凭 bind_ticket 完成外部身份绑定（票据单次有效，短 TTL）。"""
    ticket_store = BindTicketStore(
        redis_client, ttl_seconds=settings.qr_bind_ticket_ttl_seconds
    )
    try:
        identity = ticket_store.consume(payload.bind_ticket)
    except BindTicketError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=error_body(exc.code, exc.message),
        )

    existing = find_identity_by_triple(session, identity)
    if existing is not None:
        if existing.employee_id == employee.id:
            return {
                "status": "already_bound",
                "provider": identity.provider,
                "corp_id": identity.corp_id,
                "external_user_id": identity.external_user_id,
            }
        # 同一外部身份已绑定到另一员工 ⇒ 拒绝，并记日志
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=error_body(
                "identity_already_bound", "该外部身份已绑定到其他员工，请先解绑"
            ),
        )

    bind_identity(
        session,
        employee=employee,
        identity=identity,
        created_by=employee.id,
    )
    record_audit(
        session,
        action=ACTION_IDENTITY_BIND,
        actor_employee_id=employee.id,
        org_id=employee.org_id,
        site_id=employee.site_id,
        target_type="provider",
        target_id=identity.provider,
        detail={
            "provider": identity.provider,
            "corp_id": identity.corp_id,
            "external_user_id": identity.external_user_id,
        },
    )
    return {
        "status": "bound",
        "provider": identity.provider,
        "corp_id": identity.corp_id,
        "external_user_id": identity.external_user_id,
    }


@router.delete("/{provider}")
def unbind_identity_endpoint(
    provider: str,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_session),
):
    """解绑：删除该员工在该 provider 下的全部绑定关系。"""
    provider_name = (provider or "").strip().lower()
    rows = unbind_identities(
        session, employee_id=employee.id, provider=provider_name
    )
    if not rows:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=error_body("identity_not_found", "未找到该 provider 的绑定关系"),
        )
    record_audit(
        session,
        action=ACTION_IDENTITY_UNBIND,
        actor_employee_id=employee.id,
        org_id=employee.org_id,
        site_id=employee.site_id,
        target_type="provider",
        target_id=provider_name,
        detail={"provider": provider_name, "count": len(rows)},
    )
    return {"status": "unbound", "provider": provider_name, "count": len(rows)}
