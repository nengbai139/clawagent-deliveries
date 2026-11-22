"""路由：复核与争议。

工单原文的接口清单：
* `GET  /api/admin/ref/reports?status=&reporter_type=&owner_staff_id=`
* `POST /api/ref/reports/{id}/disputes`
* `POST /api/admin/ref/disputes/{id}/decide`
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import ActorDep, CurrentActor, SessionDep
from app.models.entities import RefDispute, RefReport
from app.schemas.api import (
    DecideResultOut,
    DisputeCreateRequest,
    DisputeDecideRequest,
    DisputeOut,
    RejectRequest,
    ReportOut,
    VerifyRequest,
)
from app.services import dispute as dispute_svc
from app.services import review as review_svc
from app.services.approval import REQUIRED_ROLES, roles_of

router = APIRouter()


# ---------------------------------------------------------------- 复核

@router.get("/api/admin/ref/reports", response_model=list[ReportOut])
def list_reports(
    session: Session = SessionDep,
    actor: CurrentActor = ActorDep,
    status_: str | None = Query(default=None, alias="status"),
    reporter_type: str | None = Query(default=None),
    owner_staff_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ReportOut]:
    """列出待复核的报备。"""
    reports = review_svc.list_reports(
        session,
        review_svc.ReportFilter(
            status=status_,
            reporter_type=reporter_type,
            owner_staff_id=owner_staff_id,
            org_id=actor.org_id,
        ),
        limit=limit,
        offset=offset,
    )
    return [ReportOut.model_validate(r) for r in reports]


def _load_report(session: Session, report_id: uuid.UUID) -> RefReport:
    report = session.get(RefReport, report_id)
    if report is None or report.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="报备不存在"
        )
    return report


@router.post("/api/admin/ref/reports/{report_id}/verify", response_model=ReportOut)
def verify_report(
    report_id: uuid.UUID,
    body: VerifyRequest,
    session: Session = SessionDep,
    actor: CurrentActor = ActorDep,
) -> ReportOut:
    """把 accepted 的报备标记为 verified。"""
    report = _load_report(session, report_id)
    try:
        review_svc.mark_verified(session, report, str(actor.actor_id), body.reason)
    except review_svc.ReviewError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"{exc.code}: {exc.message}"
        ) from exc
    session.commit()
    return ReportOut.model_validate(report)


@router.post("/api/admin/ref/reports/{report_id}/reject", response_model=ReportOut)
def reject_report(
    report_id: uuid.UUID,
    body: RejectRequest,
    session: Session = SessionDep,
    actor: CurrentActor = ActorDep,
) -> ReportOut:
    """以 rejected_invalid 驳回报备（原因必填）。"""
    report = _load_report(session, report_id)
    try:
        review_svc.reject_invalid(session, report, str(actor.actor_id), body.reason)
    except review_svc.ReviewError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"{exc.code}: {exc.message}"
        ) from exc
    session.commit()
    return ReportOut.model_validate(report)


# ---------------------------------------------------------------- 争议

@router.post(
    "/api/ref/reports/{report_id}/disputes",
    response_model=DisputeOut,
    status_code=status.HTTP_201_CREATED,
)
def submit_dispute(
    report_id: uuid.UUID,
    body: DisputeCreateRequest,
    session: Session = SessionDep,
    actor: CurrentActor = ActorDep,
) -> DisputeOut:
    """报备方对拒绝结果提出异议。"""
    report = _load_report(session, report_id)
    try:
        d = dispute_svc.submit_dispute(
            session,
            report,
            disputer_id=actor.actor_id,
            disputer_type=actor.actor_type,
            reason_code=body.reason_code,
            reason_text=body.reason_text,
            attachments=[
                dispute_svc.Attachment(a.file_id, a.name, a.url)
                for a in body.attachments
            ],
        )
    except dispute_svc.DisputeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{exc.code}: {exc.message}",
        ) from exc
    session.commit()
    return _to_dispute_out(d)


def _to_dispute_out(d: RefDispute) -> DisputeOut:
    # ⚠️ `attachments` 的 JSON 文本 → 对象列表，由 schema 的校验器负责
    #    （这里不再手工拆一次，避免两处解析逻辑漂移）。
    return DisputeOut.model_validate(d)


@router.get(
    "/api/admin/ref/disputes/{dispute_id}", response_model=DisputeOut
)
def get_dispute(
    dispute_id: uuid.UUID,
    session: Session = SessionDep,
    actor: CurrentActor = ActorDep,
) -> DisputeOut:
    """查看一条争议。"""
    d = session.get(RefDispute, dispute_id)
    if d is None or d.deleted_at is not None:
        raise HTTPException(status_code=404, detail="争议不存在")
    return _to_dispute_out(d)


def _resolve_role(
    session: Session, actor: CurrentActor, requested: str | None
) -> str:
    """确定本次审批用的角色。

    ⚠️ **两个角色都有时必须显式指定**：否则不知道这次是用哪个角色
    ⇒ 而「同一人用两个角色各批一次」正是验收标准 2 要拦的情况 ⇒
    这里**逼调用方把话说清楚**。
    """
    held = roles_of(session, actor.actor_id)
    usable = sorted(held & set(REQUIRED_ROLES))
    if requested:
        if requested not in REQUIRED_ROLES:
            raise HTTPException(
                status_code=422,
                detail=f"角色 {requested} 不在改判所需角色 {list(REQUIRED_ROLES)} 内",
            )
        if requested not in held:
            raise HTTPException(
                status_code=403, detail=f"当前用户不具备角色 {requested}"
            )
        return requested
    if not usable:
        raise HTTPException(
            status_code=403,
            detail=f"当前用户不具备改判所需角色 {list(REQUIRED_ROLES)}",
        )
    if len(usable) > 1:
        raise HTTPException(
            status_code=422,
            detail=(
                f"当前用户同时具备多个角色 {usable}；请在请求体里用 role 字段"
                "显式指定本次审批所用的角色"
            ),
        )
    return usable[0]


@router.post(
    "/api/admin/ref/disputes/{dispute_id}/decide",
    response_model=DecideResultOut,
)
def decide_dispute(
    dispute_id: uuid.UUID,
    body: DisputeDecideRequest,
    session: Session = SessionDep,
    actor: CurrentActor = ActorDep,
) -> DecideResultOut:
    """处理争议。

    ⚠️ **改判（overturn）需双人审批**：两个不同的人、各以一个角色，
    各审批一次。第一次调用会返回 `effective=false` 与还缺哪个角色。
    """
    d = session.get(RefDispute, dispute_id)
    if d is None or d.deleted_at is not None:
        raise HTTPException(status_code=404, detail="争议不存在")
    role = _resolve_role(session, actor, body.role)
    try:
        result = dispute_svc.decide_dispute(
            session,
            d,
            approver_id=actor.actor_id,
            role=role,
            decision=body.decision,
            reason=body.reason,
        )
    except dispute_svc.DisputeError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{exc.code}: {exc.message}",
        ) from exc
    session.commit()
    return DecideResultOut(**result)
