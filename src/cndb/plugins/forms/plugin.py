"""forms 插件 —— 表单定制与权限控制.

子模块：
- models.py          FormDefinition
- schemas/           Pydantic 请求/响应模型
- services/          权限判定 + 字段配置校验
- routers/           表单定义 CRUD + 表单行操作
"""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase
from cndb.plugins.forms.routers import router as forms_router


class FormsPlugin(PluginBase):
    """表单定制与权限控制插件."""

    name = "forms"
    version = "0.1.0"
    description = "数据表表单定制化视图（增删查改）与表单级权限控制"
    icon = "FormOutlined"
    route_prefix = "workspaces"  # 路由挂载到 workspaces 下: /api/v1/workspaces/{wid}/forms/...
    direct_router = forms_router

    @override
    def register_models(self) -> None:
        """导入 models 确保 Base.metadata 包含 FormDefinition."""
        from cndb.plugins.forms import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """注册路由（当 direct_router 未设置时的 fallback）."""
        router.include_router(forms_router)


plugin = FormsPlugin()

__all__ = ["FormsPlugin", "plugin"]
