"""forms 插件 —— 表单定义 CRUD + 运行器提交端点."""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase
from cndb.plugins.forms.routers import router as forms_router


class FormsPlugin(PluginBase):
    """表单插件：表单定义管理 + 运行器提交."""

    name = "forms"
    version = "0.1.0"
    description = "表单定义 CRUD + 运行器提交（映射为表记录创建）"
    icon = "FormOutlined"
    # 挂在 workspaces 下: /api/v1/workspaces/{wid}/forms/...
    route_prefix = "workspaces"
    direct_router = forms_router

    @override
    def register_models(self) -> None:
        """导入 models 确保 Base.metadata 包含 FormDefinition."""
        from cndb.plugins.forms import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """register_routes 由 direct_router 绕过；保留空实现."""


plugin = FormsPlugin()

__all__ = ["FormsPlugin", "plugin"]
