"""回款期次状态派生（**桩**）。

⚠️⚠️ **这是接口桩**：工单原文「两个派生函数由**会籍校验**、**回款校验**工单
提供，未合入时按函数签名写桩」。

⇒ **签名是对接契约**：真实现合入时**只换函数体，不改调用方**。

⚠️ **别把桩的语义当业务真相**：下面的规则是为了让本单**可测**而定的；
真规则以「回款校验」工单为准。
"""

from __future__ import annotations

from datetime import date

from crm.models.entities import (
    PAYMENT_STATUS_DUE,
    PAYMENT_STATUS_OVERDUE,
    PAYMENT_STATUS_PENDING,
    PaymentPlan,
)


def derive_payment_status(plan: PaymentPlan, today: date) -> str:
    """派生回款期次在 `today` 应有的状态。

    **接口桩**（真实现由「回款校验」工单提供）。

    桩的规则：
    * `today > due_date` ⇒ `overdue`（逾期）
    * `today == due_date` ⇒ `due`（今日到期）
    * `today < due_date` ⇒ `pending`（未到期）

    ⚠️ **不改人工状态**：`paid`（已结清）/ `written_off`（已核销）由人工
    设置 ⇒ 派生永远不产出这两个值（调用方先把它们**排除在扫描范围外**）。
    """
    due_date = plan.due_date
    if due_date is None:
        return plan.status
    if today > due_date:
        return PAYMENT_STATUS_OVERDUE
    if today == due_date:
        return PAYMENT_STATUS_DUE
    return PAYMENT_STATUS_PENDING
