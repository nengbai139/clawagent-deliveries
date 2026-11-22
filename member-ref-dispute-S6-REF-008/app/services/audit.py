"""审计日志：所有复核与争议操作都写。

⚠️ 工单原文：「所有复核与争议操作写审计日志（**操作人、前后状态、理由**）」。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import AuditLog


def write_audit(
    session: Session,
    *,
    org_id: uuid.UUID,
    actor_id: str,
    target_type: str,
    target_id: uuid.UUID,
    action: str,
    before_status: str | None = None,
    after_status: str | None = None,
    reason: str | None = None,
    site_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """写一条审计日志。

    ⚠️ **不吞异常**：审计写失败 ⇒ 整个操作失败（失败关闭）。
    审计是「谁在什么时候把什么改成了什么」的**唯一凭证** ⇒ 写不进去
    就**不能**让操作生效，否则会出现「状态变了但查不到谁改的」。
    """
    entry = AuditLog(
        org_id=org_id,
        site_id=site_id,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        action=action,
        before_status=before_status,
        after_status=after_status,
        reason=reason,
        detail=json.dumps(detail, ensure_ascii=False) if detail else None,
    )
    session.add(entry)
    session.flush()
    return entry
