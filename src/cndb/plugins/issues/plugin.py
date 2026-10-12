"""issues 插件 —— 问题清单（GitHub Issue 风格协作反馈）."""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase


class IssuesPlugin(PluginBase):
    """问题清单插件：数据表上的问题提交、评论与状态流转."""

    name = "issues"
    version = "0.1.0"
    description = "问题清单：所有成员可提交问题与评论，owner/editor 可关闭/重开"
    icon = "ExclamationCircleOutlined"
    route_prefix = "workspaces"

    @override
    def register_models(self) -> None:
        """导入 models 确保 SQLAlchemy Base.metadata 包含 Issue / IssueComment / IssueEvent."""
        from cndb.plugins.issues import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """挂载 issues 路由."""
        from cndb.plugins.issues.routers import router as issues_router

        router.include_router(issues_router)


plugin = IssuesPlugin()

__all__ = ["IssuesPlugin", "plugin"]
