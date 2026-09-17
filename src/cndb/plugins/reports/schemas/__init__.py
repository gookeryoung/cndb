"""reports 插件 Pydantic schemas（facade —— 只做导入导出）."""

from __future__ import annotations

from cndb.plugins.reports.schemas.models import (
    ParameterDef,
    RenderRequest,
    TemplateCreate,
    TemplateListResponse,
    TemplateResponse,
    TemplateUpdate,
)

__all__ = [
    "ParameterDef",
    "RenderRequest",
    "TemplateCreate",
    "TemplateListResponse",
    "TemplateResponse",
    "TemplateUpdate",
]
