"""workflows 插件 —— 业务流程编排（工作流 → 节点 ↔ 数据表 → 视图）."""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase
from cndb.plugins.workflows.routers import router as workflows_router


class WorkflowsPlugin(PluginBase):
    """业务流程编排插件：工作流 → 节点绑定数据表 → 边表达流程顺序."""

    name = "workflows"
    version = "0.1.0"
    description = "业务流程编排：工作流 → 节点绑定数据表 → 边表达流程顺序"
    icon = "ApartmentOutlined"
    route_prefix = "workspaces"  # 路由挂载到 workspaces 下: /api/v1/workspaces/{wid}/workflows/...
    direct_router = workflows_router

    @override
    def register_models(self) -> None:
        """导入 models 确保 Base.metadata 包含所有表."""
        from cndb.plugins.workflows import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """注册路由（当 direct_router 未设置时的 fallback）."""


__all__ = ["WorkflowsPlugin"]
