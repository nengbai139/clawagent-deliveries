"""运维只读接口。

工单原文：「写入新表 crm_job_run（…）**供运维查询**」⇒ 这里给它一个**只读**
的查询口。

⚠️ **刻意只做只读**：本单的交付物是**日终任务**，不是业务接口 ⇒ 加写接口
就是**扩范围**（扩了就要多测、多担风险）⇒ 这里只有查询。

⚠️ **分页必须有上限**：不带上限的 `limit` ⇒ 一个请求就能把表拉爆。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from crm.api.deps import SessionDep
from crm.models.entities import JobRun

router = APIRouter()


@router.get("/api/admin/crm/job-runs", summary="列出日终任务运行记录")
def list_job_runs(
    session: Session = SessionDep,
    job_name: str | None = Query(default=None),
    run_date: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    """列出 `crm_job_run`（按时间倒序）。

    ⚠️ **软删除的排除**（统一约定）。
    """
    stmt = select(JobRun).where(JobRun.deleted_at.is_(None))
    if job_name:
        stmt = stmt.where(JobRun.job_name == job_name)
    if run_date:
        stmt = stmt.where(JobRun.run_date == run_date)
    stmt = stmt.order_by(JobRun.started_at.desc()).limit(limit)
    return [
        {
            "id": str(r.id),
            "job_name": r.job_name,
            "run_date": r.run_date.isoformat(),
            "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "status": r.status,
            "stats": r.stats,
        }
        for r in session.scalars(stmt)
    ]
