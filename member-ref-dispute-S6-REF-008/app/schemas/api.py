"""API 的请求/响应模型（Pydantic v2）。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.services.dispute import ALLOWED_REASON_CODES, MAX_ATTACHMENTS

# ---------------------------------------------------------------- 报备

class ReportOut(BaseModel):
    """报备（列表项）。"""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    org_id: uuid.UUID
    reporter_type: str
    reporter_id: uuid.UUID
    owner_staff_id: uuid.UUID | None
    customer_id: uuid.UUID
    channel_id: uuid.UUID
    reported_at: datetime
    status: str
    reject_reason: str | None = None
    amount_cents: int = 0
    created_at: datetime


# ---------------------------------------------------------------- 复核

class VerifyRequest(BaseModel):
    """标记 verified。"""

    reason: str | None = Field(default=None, max_length=1000)


class RejectRequest(BaseModel):
    """驳回（原因必填）。"""

    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("驳回原因不能为空")
        return v.strip()


# ---------------------------------------------------------------- 争议

class AttachmentIn(BaseModel):
    """证据附件。"""

    file_id: str = Field(min_length=1, max_length=128)
    name: str = Field(default="", max_length=255)
    url: str = Field(default="", max_length=1024)


class DisputeCreateRequest(BaseModel):
    """提交争议。"""

    reason_code: str = Field(min_length=1, max_length=48)
    reason_text: str = Field(min_length=1, max_length=4000)
    attachments: list[AttachmentIn] = Field(default_factory=list)

    @field_validator("attachments")
    @classmethod
    def _cap_attachments(cls, v: list[AttachmentIn]) -> list[AttachmentIn]:
        if len(v) > MAX_ATTACHMENTS:
            raise ValueError(f"证据附件最多 {MAX_ATTACHMENTS} 个")
        return v

    @field_validator("reason_code")
    @classmethod
    def _allowed_reason(cls, v: str) -> str:
        if v not in ALLOWED_REASON_CODES:
            raise ValueError(
                f"争议理由 {v} 不受理；只受理系统判断错误类原因"
                f"（可用：{sorted(ALLOWED_REASON_CODES)}）"
            )
        return v


class DisputeOut(BaseModel):
    """争议。

    ⚠️ `attachments` 在库里是 **JSON 文本**（一列，够用且不用另建关联表），
    在这里用校验器转成对象列表 ⇒ 对外的形状是结构化的。
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    org_id: uuid.UUID
    report_id: uuid.UUID
    disputer_id: uuid.UUID
    disputer_type: str
    reason_code: str
    reason_text: str
    attachments: list[AttachmentIn] = []
    status: str
    decision_reason: str | None = None
    created_at: datetime
    decided_at: datetime | None = None

    @field_validator("attachments", mode="before")
    @classmethod
    def _parse_attachments(cls, v):
        """把库里的 JSON 文本转成对象列表。

        ⚠️ 已经对象列表时**原样返回**（避免二次解析）。
        """
        if isinstance(v, str):
            try:
                data = json.loads(v or "[]")
            except json.JSONDecodeError:
                return []
            if not isinstance(data, list):
                return []
            return [
                AttachmentIn(
                    file_id=str(item.get("file_id", "")),
                    name=str(item.get("name", "")),
                    url=str(item.get("url", "")),
                )
                for item in data
                if isinstance(item, dict)
            ]
        return v


class DisputeDecideRequest(BaseModel):
    """处理争议。

    ⚠️ `role` 是**可选**的：只带一个角色时由系统自动取；
    两个角色都有时必须显式指定（否则不知道这次是用哪个角色）。
    """

    decision: str = Field(pattern="^(uphold|overturn)$")
    reason: str = Field(min_length=1, max_length=2000)
    role: str | None = Field(default=None, max_length=48)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("处理理由不能为空")
        return v.strip()


class DecideResultOut(BaseModel):
    """处理结果。

    ⚠️ `effective=False` 表示**改判未生效**（还差一个角色的审批）⇒
    调用方能明确知道「这次没改成」。
    """

    effective: bool
    status: str
    satisfied_roles: list[str] = []
    missing_roles: list[str] = []
    attribution: dict = {}
