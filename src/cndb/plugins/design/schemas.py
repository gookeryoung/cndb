"""design 插件请求 / 响应模型（ADR 0079 D6 / D7）."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DesignCreate(BaseModel):
    """新建设计：原文必经编译，失败 400（I2）."""

    title: str = Field(min_length=1, max_length=200, description="设计名称（工作区内唯一）")
    content: str = Field(default="", description="结构 DSL 原文（.cnmd），可为空（空为合法程序）")
    description: str = Field(default="", max_length=500, description="用途说明")


class DesignUpdate(BaseModel):
    """改名 / 描述（None = 不改；不触发重编译）."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)


class DesignContentSave(BaseModel):
    """保存原文：编译通过才落库并生成新版本（失败旧 IR 不动，边界 #2）."""

    content: str = Field(description="结构 DSL 原文")
    comment: str = Field(default="", max_length=200, description="版本备注")


class PreviewRequest(BaseModel):
    """即时编译（无落库）：编辑器防抖与参数面板共用（D3）."""

    content: str = Field(description="结构 DSL 原文")
    overrides: dict[str, float] | None = Field(default=None, description="参数覆盖（param 面板改参重编译）")


class DiagnosticItem(BaseModel):
    """编译诊断：编辑器 gutter 按行 / 列定位（D2）."""

    severity: str
    line: int
    col: int
    message: str


class PreviewResponse(BaseModel):
    """即时编译结果：``ok=false`` 时 ``ir`` 为空、诊断非空（I6 不出半截 IR）."""

    ok: bool
    ir: dict[str, Any] | None = None
    diagnostics: list[DiagnosticItem] = Field(default_factory=list)


class DesignListItem(BaseModel):
    """设计列表项（不含原文与 IR，降低响应体量）."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    title: str
    description: str
    created_at: Any
    updated_at: Any
    version_count: int = 0


class DesignDetail(BaseModel):
    """设计详情：原文唯一真相源 + 编译快照 + 当前版本号."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    title: str
    description: str
    content: str
    compiled: dict[str, Any]
    version_number: int = 0
    created_at: Any
    updated_at: Any


class DesignVersionItem(BaseModel):
    """版本列表项（不含原文，降低响应体量）."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    design_id: int
    version_number: int
    comment: str
    created_by_id: int | None
    created_at: Any


class DesignVersionDetail(DesignVersionItem):
    """版本回看（P2，ADR 0079 §3）：该版原文与编译快照."""

    content: str
    compiled: dict[str, Any]


__all__ = [
    "DesignContentSave",
    "DesignCreate",
    "DesignDetail",
    "DesignListItem",
    "DesignUpdate",
    "DesignVersionDetail",
    "DesignVersionItem",
    "DiagnosticItem",
    "PreviewRequest",
    "PreviewResponse",
]
