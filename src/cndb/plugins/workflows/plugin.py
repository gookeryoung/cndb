"""workflows 插件 —— 审批流定义与表单提交审批.

子模块：
- models.py          Workflow/WorkflowNode/WorkflowEdge + ApprovalInstance/ApprovalAction
- schemas/           Pydantic 请求/响应模型
- services/          图校验保存 + 实例流转
- routers/           审批流 CRUD + 审批动作
"""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase
from cndb.plugins.workflows.routers import router as workflows_router


class WorkflowsPlugin(PluginBase):
    """审批流插件：多步审批流配置与表单提交审批."""

    name = "workflows"
    version = "0.1.0"
    description = "工作区多步审批流（线性链）配置与表单提交审批"
    icon = "AuditOutlined"
    route_prefix = "workspaces"  # 路由挂载到 workspaces 下: /api/v1/workspaces/{wid}/workflows|approvals/...
    direct_router = workflows_router

    @override
    def register_models(self) -> None:
        """导入 models 确保 Base.metadata 包含 workflows 全部模型."""
        from cndb.plugins.workflows import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """注册路由（当 direct_router 未设置时的 fallback）."""
        router.include_router(workflows_router)


plugin = WorkflowsPlugin()

__all__ = ["WorkflowsPlugin", "plugin"]
