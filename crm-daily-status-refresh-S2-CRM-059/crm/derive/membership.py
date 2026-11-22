"""会籍状态派生（**桩**）。

⚠️⚠️ **这是接口桩**：工单原文「两个派生函数由**会籍校验**、**回款校验**工单
提供，未合入时按函数签名写桩」。

⇒ **签名是对接契约**：真实现合入时，**只换函数体，不改调用方**
（调用方在 `crm/jobs/daily_status_refresh.py`）。

⚠️ **别把桩的语义当业务真相**：下面这套规则（到期前 30 天算 `expiring`）
是为了让本单**可测**而定的；真规则以「会籍校验」工单为准 ⇒ 真实现合入后
**本单的冻结时间用例要按真规则重算期望值**（README 里写了这一点）。
"""

from __future__ import annotations

from datetime import date, timedelta

from crm.core.config import get_settings
from crm.models.entities import (
    MEMBERSHIP_STATUS_ACTIVE,
    MEMBERSHIP_STATUS_EXPIRED,
    MEMBERSHIP_STATUS_EXPIRING,
    Membership,
)


def derive_membership_status(membership: Membership, today: date) -> str:
    """派生会籍在 `today` 应有的状态。

    **接口桩**（真实现由「会籍校验」工单提供）。

    桩的规则：
    * `today > end_date` ⇒ `expired`（已过期）
    * `today >= end_date - 提前天数` ⇒ `expiring`（即将到期）
    * 否则 ⇒ `active`

    ⚠️ **不改人工状态**：`terminated` / `suspended` 由人工设置 ⇒ 派生
    永远不产出这两个值（调用方也会先把这两种状态**排除在扫描范围外**）。
    """
    window = get_settings().membership_expiring_window_days
    end_date = membership.end_date
    if end_date is None:
        # 没有到期日 ⇒ 无从派生 ⇒ 保持原样（调用方只在状态变化时才写）。
        return membership.status
    if today > end_date:
        return MEMBERSHIP_STATUS_EXPIRED
    if today >= end_date - timedelta(days=window):
        return MEMBERSHIP_STATUS_EXPIRING
    return MEMBERSHIP_STATUS_ACTIVE
