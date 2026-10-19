"""change_requests 插件 Pydantic schemas：请求体模型."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChangeItemIn(BaseModel):
    """单个变更项：create 无 row_id；update/delete 必须带 row_id."""

    model_config = ConfigDict(str_strip_whitespace=False)

    op: Literal["create", "update", "delete"]
    row_id: int | None = None
    values: dict[str, Any] = Field(default_factory=dict)


class ChangeRequestCreate(BaseModel):
    """创建修改申请请求体（支持多 item，用于批量删除与新建对话框）."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=255)
    description: str = ""
    items: list[ChangeItemIn] = Field(min_length=1)


class MergeDecision(BaseModel):
    """单个变更项的处理决策."""

    item_id: int
    action: Literal["apply", "skip"]


class MergePayload(BaseModel):
    """merge 请求体：逐项决策 + 处理意见."""

    items: list[MergeDecision] = Field(min_length=1)
    comment: str = ""


class ChangeCommentCreate(BaseModel):
    """申请评论请求体."""

    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(min_length=1)


class RowFieldResolution(BaseModel):
    """行组批量合并时，单个冲突字段的裁决.

    - strategy=item：采用指定 item（item_id 必须属于该字段的写者之一）的值；
    - strategy=current：保留当前行值，跳过该字段写入。
    """

    strategy: Literal["item", "current"]
    item_id: int | None = None


class RowMergePayload(BaseModel):
    """行组批量合并请求体：一次审批同一行的多份 open 申请.

    - request_ids：待合并的申请 id（每份申请的变更项须全部属于本行，且不含 create）；
    - row_action：仅当存在 delete 与修改互斥时必填（keep=保留行并应用修改 / delete=执行删除）；
    - resolutions：冲突字段（多个申请写同一字段且值不等）的逐字段裁决，未裁决则 409。
    """

    request_ids: list[int] = Field(min_length=1)
    row_action: Literal["keep", "delete"] | None = None
    resolutions: dict[str, RowFieldResolution] = Field(default_factory=dict)
    comment: str = ""


__all__ = [
    "ChangeCommentCreate",
    "ChangeItemIn",
    "ChangeRequestCreate",
    "MergeDecision",
    "MergePayload",
    "RowFieldResolution",
    "RowMergePayload",
]
