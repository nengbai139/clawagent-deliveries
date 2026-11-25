"""审计日志写入。"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.iam.models import AuditLog

logger = logging.getLogger(__name__)

ACTION_IDENTITY_BIND = "iam.identity.bind"
ACTION_IDENTITY_UNBIND = "iam.identity.unbind"
ACTION_QR_LOGIN = "iam.qr.login"


def record_audit(
    session: Session,
    *,
    action: str,
    actor_employee_id: str | None,
    org_id: str,
    site_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        org_id=org_id,
        site_id=site_id,
        actor_employee_id=actor_employee_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=json.dumps(detail or {}, ensure_ascii=False),
        created_by=actor_employee_id,
    )
    session.add(entry)
    session.commit()
    logger.info("audit action=%s actor=%s target=%s", action, actor_employee_id, target_id)
    return entry
