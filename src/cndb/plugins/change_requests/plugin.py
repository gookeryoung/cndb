"""change_requests 插件 —— 修改申请（GitHub Pull Request 风格变更协作）."""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase


class ChangeRequestsPlugin(PluginBase):
    """修改申请插件：成员发起行级变更申请，owner/editor 逐项决策后落库."""

    name = "change_requests"
    version = "0.1.0"
    description = "修改申请：所有成员可发起，仅 owner/editor 可 merge/close/reopen，处理后数据正式落库"
    icon = "PullRequestOutlined"
    route_prefix = "workspaces"

    @override
    def register_models(self) -> None:
        """导入 models 确保 Base.metadata 包含 ChangeRequest / ChangeItem / ChangeRequestAction."""
        from cndb.plugins.change_requests import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """挂载 change-requests 路由."""
        from cndb.plugins.change_requests.routers import router as cr_router

        router.include_router(cr_router)


plugin = ChangeRequestsPlugin()

__all__ = ["ChangeRequestsPlugin", "plugin"]
