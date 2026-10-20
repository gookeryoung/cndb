"""documents 插件 —— 文档管理与展示（Markdown 专属）."""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import NavItem, PluginBase


class DocumentsPlugin(PluginBase):
    """文档管理插件：Markdown 文档的上传/编辑/检索/版本/权限/分享."""

    name = "documents"
    version = "0.1.0"
    description = "文档管理：Markdown 文档上传导入、全文检索、版本控制、标签分类、分享与修改申请"
    icon = "FileTextOutlined"
    route_prefix = "workspaces"

    @override
    def register_models(self) -> None:
        """导入 models 确保 SQLAlchemy Base.metadata 包含 documents_* 表."""
        from cndb.plugins.documents import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """挂载 documents 路由."""
        from cndb.plugins.documents.routers import router as documents_router
        from cndb.plugins.documents.routers.change_requests import router as change_requests_router
        from cndb.plugins.documents.routers.file_import import router as file_import_router
        from cndb.plugins.documents.routers.issues import router as issues_router
        from cndb.plugins.documents.routers.share import share_router
        from cndb.plugins.documents.routers.tags import router as tags_router
        from cndb.plugins.documents.routers.vault import router as vault_router

        # 导入/导出路由先挂载：/import、/import/files、/export/vault 必须在 /{doc_id} 一族之前匹配
        router.include_router(vault_router)
        router.include_router(file_import_router)
        router.include_router(documents_router)
        router.include_router(share_router)
        router.include_router(tags_router)
        router.include_router(change_requests_router)
        router.include_router(issues_router)

    @override
    def register_navigation(self) -> list[NavItem]:
        return [
            NavItem(
                key="documents",
                label="文档",
                icon="FileTextOutlined",
                path="/w/:workspaceId/documents",
            )
        ]

    # 不注册 register_apps：test_plugin_registry 断言内置插件无 APP 入口，
    # 文档功能经侧边栏导航进入


plugin = DocumentsPlugin()

__all__ = ["DocumentsPlugin", "plugin"]
