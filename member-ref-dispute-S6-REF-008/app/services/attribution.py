"""归属判定：按**原报备时间**重新判定归属。

⚠️ **为什么归属重算要单独成模块**：验收标准 3 要求「改判后**按原报备时间**
重新判定归属，结果写入审计日志」⇒ 这段逻辑被**两个**地方调用（首次报备
受理、改判后重算）⇒ 必须只有**一份**实现，否则两处会漂移。

⚠️ **「原报备时间」是 `reported_at`，不是 `created_at`**：`created_at` 可能
被数据迁移/导入改写 ⇒ 用它做时间基准会让重算结果与当初不一样。

本单**不依赖**其它工单的归属算法（S6-REF-xxx 系列的归属规则在别处）⇒
这里定义一个**可替换的策略接口**，默认实现是「按渠道优先级 + 时间先后」
的确定性规则；真实规则接入时替换实现即可，调用方不感知。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import RefReport


@dataclass(frozen=True)
class AttributionCandidate:
    """一个候选归属人。"""

    staff_id: str
    #: 该候选人在该渠道上的**优先级**（数值越大越优先）。
    priority: int
    #: 该候选人在该渠道上的**最早可报备时间**（用于「先到先得」）。
    first_report_at: datetime


@dataclass(frozen=True)
class AttributionResult:
    """归属判定结果。"""

    #: 归属到的员工 id；`None` 表示**无人可归**（不猜、不平摊）。
    owner_staff_id: str | None
    #: 判定依据（写进审计日志的 `detail`）。
    basis: str
    #: 参与判定的候选数。
    candidates_considered: int


class AttributionStrategy(Protocol):
    """归属判定策略（可替换）。"""

    def attribute(
        self, session: Session, report: RefReport
    ) -> AttributionResult: ...


class FirstReportWinsStrategy:
    """默认策略：**同一渠道内最早报备的人**优先，其余按渠道优先级。

    ⚠️ 这是**确定性**规则（同输入同输出）——归属重算要能复现，否则
    「改判后按原报备时间重新判定」没有意义（每次算出来不一样）。
    """

    def attribute(self, session: Session, report: RefReport) -> AttributionResult:
        # 只看**同一渠道**、**同一客户**、且**在 report.reported_at 之前**
        # （含同时）的其它报备 ⇒ 找出「更早的报备」。
        stmt = (
            select(RefReport)
            .where(
                RefReport.channel_id == report.channel_id,
                RefReport.customer_id == report.customer_id,
                RefReport.id != report.id,
                RefReport.deleted_at.is_(None),
                RefReport.reported_at <= report.reported_at,
            )
            .order_by(RefReport.reported_at.asc(), RefReport.created_at.asc())
        )
        earlier = list(session.scalars(stmt))
        if earlier:
            owner = earlier[0].owner_staff_id
            basis = (
                f"first_report_wins:earlier_report_exists:"
                f"earlier_count={len(earlier)}"
            )
            return AttributionResult(
                owner_staff_id=str(owner) if owner else None,
                basis=basis,
                candidates_considered=len(earlier),
            )
        # 没有更早的报备 ⇒ 归属本条报备人所属员工。
        basis = "first_report_wins:no_earlier_report:self"
        owner = report.owner_staff_id
        return AttributionResult(
            owner_staff_id=str(owner) if owner else None,
            basis=basis,
            candidates_considered=0,
        )


def recompute_attribution(
    session: Session,
    report: RefReport,
    strategy: AttributionStrategy | None = None,
) -> AttributionResult:
    """按**原报备时间**重新判定归属，并把结果落到 `report.owner_staff_id`。

    返回判定结果（调用方负责写审计日志）。
    """
    strat = strategy or FirstReportWinsStrategy()
    result = strat.attribute(session, report)
    # ⚠️ 归属可能变成「无人」⇒ 那就置空，**不猜、不沿用旧值**
    # （沿用旧值 = 明知有更早的报备却装作没有 ⇒ 结算会给错的人）。
    report.owner_staff_id = (
        uuid.UUID(result.owner_staff_id) if result.owner_staff_id else None
    )
    return result
