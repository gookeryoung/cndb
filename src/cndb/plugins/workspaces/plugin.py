"""workspaces 插件 —— 工作区与成员管理."""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase
from cndb.plugins.workspaces.routers.data_flow import router as data_flow_router
from cndb.plugins.workspaces.routers.lifecycle import router as lifecycle_router
from cndb.plugins.workspaces.routers.projects import router as projects_router
from cndb.plugins.workspaces.routers.roles import router as roles_router
from cndb.plugins.workspaces.routers.search import global_router as search_global_router
from cndb.plugins.workspaces.routers.search import router as search_router
from cndb.plugins.workspaces.routers.templates import router as templates_router
from cndb.plugins.workspaces.routers.workspaces import router as workspaces_router


class WorkspacesPlugin(PluginBase):
    """工作区与成员管理插件 + 全局数据角色（Role）管理."""

    name = "workspaces"
    version = "0.1.0"
    description = "工作区 CRUD、成员管理、pin、模板与生命周期流程、全局数据角色（Role）CRUD"
    icon = "AppstoreOutlined"
    route_prefix = ""

    @override
    def register_models(self) -> None:
        """导入 models 确保 SQLAlchemy Base.metadata 包含 Workspace / WorkspaceMember / Role."""
        from cndb.plugins.workspaces import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """挂载 workspaces + roles + search（工作区级 + 全局）路由."""
        router.include_router(workspaces_router)
        router.include_router(lifecycle_router)
        router.include_router(data_flow_router)
        router.include_router(projects_router)
        router.include_router(templates_router)
        router.include_router(roles_router)
        router.include_router(search_router)
        router.include_router(search_global_router)


__all__ = ["WorkspacesPlugin"]
