"""workflows 插件 Pydantic v2 schemas."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkflowNodeSave(BaseModel):
    """保存审批流时的单个节点（key 为客户端临时键，edges 以其引用）.

    approver_role 不在 schema 层做枚举校验，统一由
    services.graph.validate_graph_payload 返回中文明细并映射 400。
    """

    key: str
    name: str = ""
    node_type: Literal["start", "approval", "end"] = "start"
    approver_role: str = ""
    pos_x: int = 0
    pos_y: int = 0


class WorkflowEdgeSave(BaseModel):
    """保存审批流时的单条有向边（source/target 引用节点 key）."""

    source: str
    target: str


class WorkflowSave(BaseModel):
    """创建/更新审批流（整图覆盖语义）."""

    name: str
    description: str = ""
    order: int = 0
    nodes: list[WorkflowNodeSave] = Field(default_factory=list)
    edges: list[WorkflowEdgeSave] = Field(default_factory=list)


class WorkflowNodeDto(BaseModel):
    """审批流节点响应（config 已解析为 node_type / approver_role）."""

    id: int
    name: str
    node_type: str
    approver_role: str
    pos_x: int
    pos_y: int


class WorkflowEdgeDto(BaseModel):
    """审批流有向边响应（source/target 为节点 id）."""

    source: int
    target: int


class WorkflowListItemResponse(BaseModel):
    """审批流列表项."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    order: int
    updated_at: dt.datetime | None = None


class WorkflowResponse(BaseModel):
    """审批流详情（含整图）."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    name: str
    description: str
    order: int
    nodes: list[WorkflowNodeDto]
    edges: list[WorkflowEdgeDto]
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class ApprovalActionCreate(BaseModel):
    """审批动作载荷（approve/reject 共用，comment 可选）."""

    comment: str = ""


class ApprovalInstanceResponse(BaseModel):
    """审批实例响应（含上下文名称与快照值，供待审批列表/详情展示）."""

    id: int
    workspace_id: int
    workflow_id: int
    workflow_name: str = ""
    form_id: int
    form_name: str = ""
    table_id: int
    status: str
    current_node_id: int | None = None
    current_node_name: str = ""
    current_approver_role: str = ""
    submitted_by: int | None = None
    submitted_by_name: str = ""
    values: dict[str, Any] = Field(default_factory=dict)
    record_id: int | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


__all__ = [
    "ApprovalActionCreate",
    "ApprovalInstanceResponse",
    "WorkflowEdgeDto",
    "WorkflowEdgeSave",
    "WorkflowListItemResponse",
    "WorkflowNodeDto",
    "WorkflowNodeSave",
    "WorkflowResponse",
    "WorkflowSave",
]
