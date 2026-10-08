"""数据治理 Pydantic schemas：检测 / 合并 / 清洗请求与任务输出."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Survivorship = Literal["non_empty_first", "latest", "oldest", "manual"]


class DetectRequest(BaseModel):
    """重复检测请求."""

    match_fields: list[str] = Field(min_length=1, description="判重字段名列表")
    ignore_case: bool = False
    ignore_whitespace: bool = False


class MergeGroup(BaseModel):
    """单组合并配置：保留行 + 字段策略."""

    member_row_ids: list[int] = Field(min_length=2)
    survivor_row_id: int
    survivorship: Survivorship = "non_empty_first"
    field_policies: dict[str, Survivorship] = Field(default_factory=dict)
    manual_values: dict[str, Any] = Field(default_factory=dict)


class MergeRequest(BaseModel):
    """合并请求（groups 来自检测报告的人工确认结果）."""

    match_fields: list[str] = Field(default_factory=list, description="判重字段（用于键漂移校验）")
    ignore_case: bool = False
    ignore_whitespace: bool = False
    groups: list[MergeGroup] = Field(min_length=1)


class CleanAction(BaseModel):
    """单条清洗动作（复用导入侧 4 动作）."""

    action: Literal["trim_whitespace", "fill_null", "coerce_type", "drop_outliers"]
    column: str
    strategy: str | None = None
    on_fail: Literal["nullify", "reject"] = "nullify"
    fill_value: Any = None


class CleanRequest(BaseModel):
    """已存表清洗请求（preview=True 只出预览报告，不写库）."""

    actions: list[CleanAction] = Field(min_length=1)
    preview: bool = True


class GovernanceTaskOut(BaseModel):
    """治理任务状态输出."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    table_id: int
    user_id: int | None = None
    kind: str
    status: str
    progress: int
    config: dict[str, Any]
    report: str
    error_message: str
    total_groups: int
    done_groups: int
    created_at: datetime
    updated_at: datetime


__all__ = [
    "CleanAction",
    "CleanRequest",
    "DetectRequest",
    "GovernanceTaskOut",
    "MergeGroup",
    "MergeRequest",
]
