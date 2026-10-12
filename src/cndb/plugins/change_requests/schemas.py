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


__all__ = ["ChangeCommentCreate", "ChangeItemIn", "ChangeRequestCreate", "MergeDecision", "MergePayload"]
