"""workspaces 插件 —— 工作区与成员管理."""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase
from cndb.plugins.workspaces.routers.workspaces import router as workspaces_router


class WorkspacesPlugin(PluginBase):
    """工作区与成员管理插件."""

    name = "workspaces"
    version = "0.1.0"
    description = "工作区 CRUD、成员管理（owner/admin/editor/viewer）、pin 切换"
    icon = "AppstoreOutlined"
    route_prefix = ""
    direct_router = workspaces_router

    @override
    def register_models(self) -> None:
        """导入 models 确保 SQLAlchemy Base.metadata 包含 Workspace / WorkspaceMember."""
        from cndb.plugins.workspaces import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """注册工作区路由（当 direct_router 未设置时的 fallback）."""
        router.include_router(workspaces_router)


__all__ = ["WorkspacesPlugin"]
