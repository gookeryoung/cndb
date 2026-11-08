"""工作区项目上下文接口模型（ADR 0122）."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProjectListItem(BaseModel):
    """项目清单行：根表单行 + 当前阶段 + 门禁摘要."""

    project_row_id: int
    title: str
    stage_key: str | None = None
    stage_name: str | None = None
    gate_satisfied: bool = False
    missing_forms: list[str] = Field(default_factory=list)
    missing_documents: list[str] = Field(default_factory=list)
    initialized: bool = False
    updated_at: Any = None


class ProjectListResponse(BaseModel):
    """项目清单（只读汇总）."""

    project_mode: str = "workspace"
    root_form: str | None = None
    link_field: str | dict[str, str] | None = None
    title_field: str | None = None
    items: list[ProjectListItem] = Field(default_factory=list)
    total: int = 0


class ProjectModeEnableRequest(BaseModel):
    """启用项目级管理；``generate_documents`` 仅为缺失规则补占位."""

    generate_documents: bool = False


class ProjectModeEnableResponse(BaseModel):
    project_mode: str
    projects: int
    initialized: int
    documents_created: int


class ProjectDocumentsResponse(BaseModel):
    project_row_id: int
    created: int


__all__ = [
    "ProjectDocumentsResponse",
    "ProjectListItem",
    "ProjectListResponse",
    "ProjectModeEnableRequest",
    "ProjectModeEnableResponse",
]
