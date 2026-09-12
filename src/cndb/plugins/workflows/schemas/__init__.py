"""workflows 插件 Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Workflow schemas ─────────────────────────────────


class WorkflowCreate(BaseModel):
    name: str
    description: str = ""


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    order: int | None = None


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    name: str
    description: str = ""
    order: int
    node_count: int = 0
    created_at: datetime
    updated_at: datetime


# ── Node schemas ─────────────────────────────────────


class NodeCreate(BaseModel):
    name: str
    table_id: int | None = None
    pos_x: int = Field(default=0, ge=0, le=100000)
    pos_y: int = Field(default=0, ge=0, le=100000)
    config: dict[str, Any] = Field(default_factory=dict)


class NodeUpdate(BaseModel):
    name: str | None = None
    table_id: int | None = None
    pos_x: int | None = Field(default=None, ge=0, le=100000)
    pos_y: int | None = Field(default=None, ge=0, le=100000)
    config: dict[str, Any] | None = None


class NodeTableBrief(BaseModel):
    """节点绑定表的摘要（前端节点卡片展示 + 跳转）."""

    id: int
    name: str
    view_count: int
    row_count: int | None = None


class NodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    name: str
    table_id: int | None = None
    pos_x: int
    pos_y: int
    config: dict[str, Any]
    table: NodeTableBrief | None = None
    created_at: datetime
    updated_at: datetime


# ── Edge schemas ─────────────────────────────────────


class EdgeCreate(BaseModel):
    source_node_id: int
    target_node_id: int
    label: str = ""


class EdgeUpdate(BaseModel):
    label: str | None = None


class EdgeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    source_node_id: int
    target_node_id: int
    label: str
    created_at: datetime
    updated_at: datetime


# ── Detail ───────────────────────────────────────────


class WorkflowDetailResponse(WorkflowResponse):
    nodes: list[NodeResponse] = []
    edges: list[EdgeResponse] = []


__all__ = [
    "EdgeCreate",
    "EdgeResponse",
    "EdgeUpdate",
    "NodeCreate",
    "NodeResponse",
    "NodeTableBrief",
    "NodeUpdate",
    "WorkflowCreate",
    "WorkflowDetailResponse",
    "WorkflowResponse",
    "WorkflowUpdate",
]
