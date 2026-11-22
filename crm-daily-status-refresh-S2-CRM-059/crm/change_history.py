"""变更历史写入（**桩**）。

⚠️⚠️ **这是接口桩**：工单原文「每次状态变化通过 `record_change` 写变更
历史，actor_type=system，同一次运行共用 operation_id（未合入时用空实现桩）」。

⇒ **签名是对接契约**：真实现合入时**只换函数体，不改调用方**。

⚠️ **桩不是「空实现」**：本单**真的写** `crm_change_history` 表（那张表属
别的工单，但本单要有变更历史才能满足验收标准 2 的「无新增历史」断言）⇒
所以桩 = 「按约定的字段写表」，等真工单合入后换成它的实现。
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from crm.models.entities import CHANGE_ACTOR_TYPE_SYSTEM, ChangeHistory


def record_change(
    session: Session,
    *,
    org_id: UUID,
    entity_type: str,
    entity_id: UUID,
    field: str,
    from_value: str | None,
    to_value: str | None,
    operation_id: str,
    effective_date: date,
    actor_type: str = CHANGE_ACTOR_TYPE_SYSTEM,
    actor_id: str | None = None,
    site_id: UUID | None = None,
) -> ChangeHistory:
    """记一条变更历史。

    **接口桩**（真实现由「变更历史」工单提供）。

    ⚠️ `operation_id` 由**调用方**给（一次运行共用一个）⇒ 一次跑出来的
    历史能按 operation_id 串成一组 ⇒ 运维/对账能按「这次运行」回溯。
    """
    row = ChangeHistory(
        org_id=org_id,
        site_id=site_id,
        entity_type=entity_type,
        entity_id=entity_id,
        field=field,
        from_value=from_value,
        to_value=to_value,
        actor_type=actor_type,
        actor_id=actor_id,
        operation_id=operation_id,
        effective_date=effective_date,
    )
    session.add(row)
    session.flush()
    return row
