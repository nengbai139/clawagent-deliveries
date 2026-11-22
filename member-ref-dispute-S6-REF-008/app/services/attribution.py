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
    #: ⚠️ **获胜的那条报备**（id 与原报备时间）——审计要能据此**复现**判定。
    winning_report_id: str | None = None
    winning_report_reported_at: str | None = None
    #: 全部候选的 id（写进审计 ⇒ 事后能核对候选集）。
    candidate_ids: tuple[str, ...] = ()
    #: 用的哪个策略。
    strategy: str = ""


class AttributionStrategy(Protocol):
    """归属判定策略（可替换）。"""

    def attribute(
        self, session: Session, report: RefReport
    ) -> AttributionResult: ...


class FirstReportWinsStrategy:
    """默认策略：**同一渠道内最早报备的人**优先。

    ⚠️ 这是**确定性**规则（同输入同输出）——归属重算要能复现，否则
    「改判后按原报备时间重新判定」没有意义（每次算出来不一样）。

    # 候选集定义（真实归属规则属其它工单，接入时替换本类即可）

    * **同一渠道** + **同一客户** + **未软删**；
    * **状态** ∈ {`accepted`, `verified`} ⇒ ⚠️ **被否决的报备
      （`rejected_invalid`）不得夺得归属**（复核已经否定了它）；
    * **原报备时间** ≤ 本条的 `reported_at`。

    ⚠️ **tie-break**：`reported_at` **完全相等**时，比 `created_at`
    （谁先入库谁算首次报备），再比 `id`（保证全序 ⇒ 结果确定）。
    """

    #: 参与归属判定的报备状态（**被否决的不算**）。
    ELIGIBLE_STATUSES: tuple[str, ...] = ("accepted", "verified")

    def attribute(self, session: Session, report: RefReport) -> AttributionResult:
        # 候选：**同一渠道**、**同一客户**、未软删、**状态可参与归属**、
        # 且**原报备时间**不晚于本条。
        stmt = (
            select(RefReport)
            .where(
                RefReport.channel_id == report.channel_id,
                RefReport.customer_id == report.customer_id,
                RefReport.id != report.id,
                RefReport.deleted_at.is_(None),
                RefReport.status.in_(self.ELIGIBLE_STATUSES),
                RefReport.reported_at <= report.reported_at,
            )
            .order_by(
                RefReport.reported_at.asc(),
                RefReport.created_at.asc(),
                RefReport.id.asc(),
            )
        )
        candidates = list(session.scalars(stmt))
        candidate_ids = tuple(str(c.id) for c in candidates)

        # ⚠️⚠️ **跳过没有归属人的候选**，继续往后找。
        #    否则会出现「有一条更早的报备但它没有归属人 ⇒ 直接判成无人可归」
        #    ⇒ **把本来有归属的报备清成 NULL**（比原来更差）。
        eligible = [c for c in candidates if c.owner_staff_id is not None]
        if eligible:
            winner = eligible[0]
            basis = (
                f"first_report_wins:earlier_report_exists:"
                f"earlier_count={len(candidates)}:"
                f"eligible_count={len(eligible)}"
            )
            return AttributionResult(
                owner_staff_id=str(winner.owner_staff_id),
                basis=basis,
                candidates_considered=len(candidates),
                winning_report_id=str(winner.id),
                winning_report_reported_at=winner.reported_at.isoformat(),
                candidate_ids=candidate_ids,
                strategy="FirstReportWinsStrategy",
            )

        if candidates:
            # ⚠️ 有更早的报备，但它们**都没有归属人** ⇒ 无人可归
            #    （**不沿用旧归属**，也不清成 NULL —— 由调用方决定）。
            return AttributionResult(
                owner_staff_id=None,
                basis=(
                    "first_report_wins:earlier_reports_exist_but_have_no_owner:"
                    f"earlier_count={len(candidates)}"
                ),
                candidates_considered=len(candidates),
                candidate_ids=candidate_ids,
                strategy="FirstReportWinsStrategy",
            )

        # 没有更早的报备 ⇒ 归属本条报备人所属员工。
        basis = "first_report_wins:no_earlier_report:self"
        owner = report.owner_staff_id
        return AttributionResult(
            owner_staff_id=str(owner) if owner else None,
            basis=basis,
            candidates_considered=0,
            strategy="FirstReportWinsStrategy",
        )


def recompute_attribution(
    session: Session,
    report: RefReport,
    strategy: AttributionStrategy | None = None,
) -> AttributionResult:
    """按**原报备时间**重新判定归属，并把结果落到 `report.owner_staff_id`。

    返回判定结果（调用方负责写审计日志）。

    ⚠️⚠️ **判定不出归属时不清空旧归属**（失败关闭）：
    「候选里都没有归属人」⇒ 说明**数据不全**，而不是「这条报备没有归属」
    ⇒ 此时把 `owner_staff_id` 置 NULL ⇒ **把一条本来有归属的报备变成无归属**
    ⇒ 结算不给钱 ⇒ 数据损坏。

    ⇒ 判不出时**保持原值不变**，并靠 `basis` 标明原因
    （`earlier_reports_exist_but_have_no_owner`）⇒ 调用方据此决定是否要人工介入。
    """
    strat = strategy or FirstReportWinsStrategy()
    result = strat.attribute(session, report)
    if result.owner_staff_id:
        report.owner_staff_id = uuid.UUID(result.owner_staff_id)
    # ⚠️ `owner_staff_id is None` ⇒ **保持原值**（不清空），理由见上。
    return result
