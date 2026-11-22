"""依赖注入：数据库会话、当前操作人。

⚠️ **S2-IAM（身份、角色与数据范围）是依赖工单** ⇒ 本单用**接口桩**：
真实实现时把 `CurrentActor` 的解析换成调 IAM 的客户端即可，
路由层**不感知**。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker


@dataclass(frozen=True)
class CurrentActor:
    """当前操作人。

    ⚠️ 桩实现：从 `X-Actor-Id` / `X-Actor-Type` 头取。
    """

    actor_id: uuid.UUID
    actor_type: str = "staff"
    org_id: uuid.UUID | None = None
    roles: frozenset[str] = field(default_factory=frozenset)


def get_session() -> Session:
    factory = get_sessionmaker()
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()


def get_actor(
    x_actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
    x_actor_type: str | None = Header(default=None, alias="X-Actor-Type"),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
) -> CurrentActor:
    """解析当前操作人（**S2-IAM 的桩**）。

    ⚠️ **失败关闭**：没有身份头 ⇒ 401（不猜、不默认成某个用户）。
    """
    if not x_actor_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少身份信息（X-Actor-Id）",
        )
    try:
        actor_id = uuid.UUID(x_actor_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Actor-Id 不是合法 UUID",
        ) from exc
    org_id = None
    if x_org_id:
        try:
            org_id = uuid.UUID(x_org_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-Org-Id 不是合法 UUID",
            ) from exc
    return CurrentActor(
        actor_id=actor_id,
        actor_type=x_actor_type or "staff",
        org_id=org_id,
    )


SessionDep = Depends(get_session)
ActorDep = Depends(get_actor)
