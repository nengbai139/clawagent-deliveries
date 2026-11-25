"""登录后续步骤：口令登录与扫码登录共用。

扫码登录走到「找到 active 员工」之后，走的就是这里 —— 与口令登录完全一致的
后续步骤（是否需要 TOTP、签发令牌、令牌里写 amr）。
"""

from __future__ import annotations

from app.core.config import Settings
from app.iam.auth.totp import TotpChallengeStore
from app.iam.auth.tokens import issue_access_token
from app.iam.models import Employee

AMR_PASSWORD = "pwd"
AMR_QR = "qr"


def issue_login_tokens(
    *, employee: Employee, amr: str, settings: Settings
) -> dict:
    """签发访问令牌。"""
    token = issue_access_token(
        employee_id=employee.id,
        org_id=employee.org_id,
        amr=amr,
        secret=settings.token_secret,
        ttl_seconds=settings.token_ttl_seconds,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.token_ttl_seconds,
        "amr": amr,
        "employee": {
            "id": employee.id,
            "org_id": employee.org_id,
            "username": employee.username,
            "display_name": employee.display_name,
        },
    }


def requires_totp(*, employee: Employee, settings: Settings, amr: str) -> bool:
    """是否还需要 TOTP 二次验证。

    - 扫码登录：默认仍需 TOTP（员工启用 TOTP 时）；APP_QR_LOGIN_SKIP_TOTP=true 则跳过；
      APP_QR_LOGIN_FORCE_TOTP=true 则强制所有扫码登录都验证。
    - 口令登录：员工启用 TOTP 时需要（与扫码登录共用同一套开关）。
    """
    if amr == AMR_QR:
        if settings.qr_login_force_totp:
            return True
        if settings.qr_login_skip_totp:
            return False
    return bool(employee.totp_enabled)


def complete_login(
    *,
    employee: Employee,
    amr: str,
    settings: Settings,
    redis_client,
) -> dict:
    """登录后续步骤：要么下发 TOTP 挑战，要么直接签发令牌。"""
    if requires_totp(employee=employee, settings=settings, amr=amr):
        challenge_store = TotpChallengeStore(
            redis_client, ttl_seconds=settings.qr_totp_challenge_ttl_seconds
        )
        challenge = challenge_store.issue(
            employee_id=employee.id, org_id=employee.org_id, amr=amr
        )
        return {
            "step": "totp_required",
            "challenge": challenge,
            "amr": amr,
        }
    return issue_login_tokens(employee=employee, amr=amr, settings=settings)
