"""扫码登录通用接口。

- GET  /api/iam/auth/qr/{provider}/start?redirect_uri=...
- GET  /api/iam/auth/qr/{provider}/callback?code=&state=

流程（与厂商解耦，企业微信 / 飞书各自实现 QrLoginProvider 即可复用）：
start    → 校验 redirect_uri 白名单 → 生成 state（Redis，5 分钟）→ 绑定浏览器 Cookie → 返回授权 URL
callback → 校验 state（存在/未用过/与 Cookie 一致）→ exchange_code → 查 user_identities
           → 命中且员工 active ⇒ 走与口令登录相同的后续步骤（令牌 amr=qr）
           → 未命中 ⇒ 返回 {step: 'bind_required', bind_ticket}
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_providers, get_redis, get_session, get_settings
from app.core.config import Settings
from app.core.errors import error_body
from app.iam.audit import ACTION_QR_LOGIN, record_audit
from app.iam.auth.qr.bind_ticket import BindTicketStore
from app.iam.auth.qr.provider import QrProviderError
from app.iam.auth.qr.redirect import (
    allowlist_error,
    is_redirect_uri_allowed,
    redirect_not_allowed_error,
)
from app.iam.auth.qr.state import (
    QR_STATE_COOKIE_NAME,
    QrStateError,
    QrStateStore,
)
from app.iam.auth.service import AMR_QR, complete_login
from app.iam.identities import find_identity_by_triple
from app.iam.models import Employee

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/iam/auth/qr", tags=["iam-qr-login"])

# 403 时统一文案：不泄露「这个外部身份存不存在、绑的是谁」
_FORBIDDEN_BODY = error_body("employee_not_active", "员工账号不可用，无法登录")


@router.get("/{provider}/start")
def qr_start(
    provider: str,
    request: Request,
    response: Response,
    redirect_uri: str = Query(..., description="扫码完成后厂商回跳的地址（须在白名单内）"),
    settings: Settings = Depends(get_settings),
    providers=Depends(get_providers),
    redis_client=Depends(get_redis),
):
    """发起扫码登录：生成 state、绑定浏览器 Cookie、返回授权 URL。"""
    provider_name = (provider or "").strip().lower()
    adapter = providers.get(provider_name)
    if adapter is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=error_body("provider_not_found", "未知的扫码登录 provider"),
        )

    # 白名单为空 ⇒ fail-closed（不生成 state、不写 Redis）
    if not settings.qr_redirect_allowlist:
        logger.error("APP_QR_REDIRECT_ALLOWLIST 未配置，拒绝扫码登录 start")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, content=allowlist_error(settings.qr_redirect_allowlist)
        )
    if not is_redirect_uri_allowed(redirect_uri, settings.qr_redirect_allowlist):
        logger.warning("redirect_uri 不在白名单内: %s", redirect_uri)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, content=redirect_not_allowed_error()
        )

    store = QrStateStore(
        redis_client,
        ttl_seconds=settings.qr_state_ttl_seconds,
        issued_ttl_seconds=max(settings.qr_state_ttl_seconds * 12, settings.qr_state_ttl_seconds),
    )
    state, browser_token = store.issue(provider_name, redirect_uri)
    authorize_url = adapter.build_authorize_url(state, redirect_uri)

    response.set_cookie(
        key=QR_STATE_COOKIE_NAME,
        value=browser_token,
        max_age=settings.qr_state_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )
    return {
        "provider": provider_name,
        "authorize_url": authorize_url,
        "state": state,
        "expires_in": settings.qr_state_ttl_seconds,
    }


@router.get("/{provider}/callback")
def qr_callback(
    provider: str,
    request: Request,
    code: str = Query(..., description="厂商回调带回的授权码"),
    state: str = Query(..., description="start 阶段生成的 state"),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    providers=Depends(get_providers),
    redis_client=Depends(get_redis),
):
    """扫码回调：校验 state → 换外部身份 → 查绑定 → 登录或要求绑定。"""
    provider_name = (provider or "").strip().lower()
    adapter = providers.get(provider_name)
    if adapter is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=error_body("provider_not_found", "未知的扫码登录 provider"),
        )

    store = QrStateStore(
        redis_client,
        ttl_seconds=settings.qr_state_ttl_seconds,
        issued_ttl_seconds=max(settings.qr_state_ttl_seconds * 12, settings.qr_state_ttl_seconds),
    )
    try:
        # state 校验发生在调用 exchange_code 之前：无效 state 不会消耗上游 code
        qr_state = store.consume(state, request.cookies.get(QR_STATE_COOKIE_NAME))
    except QrStateError as exc:
        logger.warning("qr state 校验失败 provider=%s code=%s", provider_name, exc.code)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=error_body(exc.code, exc.message),
        )

    if qr_state.provider != provider_name:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=error_body("state_provider_mismatch", "state 与 provider 不匹配"),
        )

    try:
        identity = adapter.exchange_code(code)
    except QrProviderError as exc:
        logger.warning("exchange_code 失败 provider=%s code=%s", provider_name, exc.code)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=error_body("provider_exchange_failed", exc.message),
        )
    except TimeoutError as exc:
        logger.warning("exchange_code 超时 provider=%s", provider_name)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=error_body("provider_exchange_failed", f"上游适配器超时: {exc}"),
        )

    identity_row = find_identity_by_triple(session, identity)
    if identity_row is None:
        # 未绑定：下发一次性 bind_ticket，员工用账号密码登录后完成绑定
        ticket_store = BindTicketStore(
            redis_client, ttl_seconds=settings.qr_bind_ticket_ttl_seconds
        )
        ticket = ticket_store.issue(identity)
        return {
            "step": "bind_required",
            "bind_ticket": ticket,
            "provider": identity.provider,
            "external_user_id": identity.external_user_id,
            "display_name": identity.display_name,
            "expires_in": settings.qr_bind_ticket_ttl_seconds,
        }

    employee = session.get(Employee, identity_row.employee_id)
    # 跨组织的绑定关系一律拒绝；员工不存在 / 已停用也用同一份 403 响应体
    if (
        employee is None
        or employee.deleted_at is not None
        or not employee.is_active
        or identity_row.org_id != employee.org_id
    ):
        logger.warning(
            "qr 登录被拒 provider=%s employee_id=%s", provider_name, identity_row.employee_id
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN, content=_FORBIDDEN_BODY
        )

    result = complete_login(
        employee=employee, amr=AMR_QR, settings=settings, redis_client=redis_client
    )
    record_audit(
        session,
        action=ACTION_QR_LOGIN,
        actor_employee_id=employee.id,
        org_id=employee.org_id,
        site_id=employee.site_id,
        target_type="provider",
        target_id=provider_name,
        detail={"amr": AMR_QR, "step": result.get("step", "login_complete")},
    )
    if "access_token" in result:
        return {"step": "login_complete", **result}
    return result
