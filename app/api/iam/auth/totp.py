"""TOTP 二次验证接口。

TOTP 校验器本身不在本单范围（由部署方注入 app.state.totp_verifier），
这里只提供挑战票据的提交入口：校验通过后按挑战里记录的 amr 签发令牌。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_redis, get_session, get_settings
from app.core.config import Settings
from app.core.errors import error_body
from app.iam.auth.service import issue_login_tokens
from app.iam.auth.totp import TotpChallengeStore, TotpNotImplementedError
from app.iam.models import Employee

router = APIRouter(prefix="/api/iam/auth", tags=["iam-auth"])


class TotpVerifyRequest(BaseModel):
    challenge: str
    code: str


@router.post("/totp/verify")
def verify_totp(
    payload: TotpVerifyRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    redis_client=Depends(get_redis),
):
    store = TotpChallengeStore(
        redis_client, ttl_seconds=settings.qr_totp_challenge_ttl_seconds
    )
    challenge_data = store.consume(payload.challenge)
    if not challenge_data:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=error_body("challenge_invalid", "挑战票据无效或已过期"),
        )

    employee = session.get(Employee, challenge_data.get("employee_id", ""))
    if employee is None or not employee.is_active:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=error_body("employee_not_active", "员工账号不可用，无法登录"),
        )

    verifier = request.app.state.totp_verifier
    try:
        ok = verifier.verify(secret=employee.totp_secret, code=payload.code)
    except TotpNotImplementedError as exc:
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content=error_body("totp_not_implemented", str(exc)),
        )
    if not ok:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=error_body("totp_invalid", "TOTP 验证码不正确"),
        )

    return {
        "step": "login_complete",
        **issue_login_tokens(
            employee=employee,
            amr=str(challenge_data.get("amr", "pwd")),
            settings=settings,
        ),
    }
