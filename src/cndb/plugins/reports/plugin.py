"""reports 插件 —— 报告模板管理与渲染."""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase
from cndb.plugins.reports.routers import router as reports_router


class ReportsPlugin(PluginBase):
    """报告模板管理与渲染插件."""

    name = "reports"
    version = "0.1.0"
    description = "报告模板 CRUD + Jinja2 渲染 + docx/pdf/xlsx 输出"
    icon = "FileTextOutlined"
    route_prefix = ""
    direct_router = reports_router

    @override
    def register_models(self) -> None:
        """导入 models 确保 Base.metadata 包含 ReportTemplate."""
        from cndb.plugins.reports import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """注册路由（当 direct_router 未设置时的 fallback）."""
        router.include_router(reports_router)


plugin = ReportsPlugin()

__all__ = ["ReportsPlugin", "plugin"]
