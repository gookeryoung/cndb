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

        self._register_export_renderer()

    @staticmethod
    def _register_export_renderer() -> None:
        """向跨插件渲染注册表登记 docx / pdf 能力（ADR 0188 D10）.

        docx / pdf 渲染依赖本插件的图表内联与数据表引用能力，因此实现留在本插件，
        只通过 ``cndb.render.markdown_export`` 的注册表向其他插件（如 tables 的
        数据字典导出）暴露 —— 避免 tables 反向 import documents（H69）。
        """
        from cndb.render.markdown_export import register_renderer

        def _render(markdown_text: str, fmt: str, *, title: str = "", template: str | None = None) -> bytes:
            from cndb.plugins.documents import services
            from cndb.plugins.documents.services.export.templates import (
                BUILTIN_TEMPLATES,
                DEFAULT_TEMPLATE_KEY,
                ResolvedTemplate,
            )

            # 只接受内置模板 key（`builtin:xxx`）：注册表是跨插件入口，不持有 db / workspace
            # 上下文，因此**不解析工作区自定义模板**（那需要 db 与 workspace_id）。
            # 数据字典是结构文档，内置模板足够；非法 / 未知 ref 静默回落内置默认（与 H68 同侧）。
            resolved = None
            if template:
                key = template[len("builtin:") :] if template.startswith("builtin:") else template
                builtin = BUILTIN_TEMPLATES.get(key)
                if builtin is not None:
                    resolved = ResolvedTemplate(
                        ref=builtin.ref, name=builtin.name, source="builtin", config=builtin.config
                    )
            if resolved is None:
                default = BUILTIN_TEMPLATES[DEFAULT_TEMPLATE_KEY]
                resolved = ResolvedTemplate(ref=default.ref, name=default.name, source="builtin", config=default.config)
            return services.export.render_export(
                markdown_text,
                fmt,
                title=title,
                images=None,
                tables=None,
                template=resolved,
            )

        for fmt in ("docx", "pdf"):
            register_renderer(fmt, _render)

    @override
    def register_routes(self, router: APIRouter) -> None:
        """挂载 documents 路由."""
        from cndb.plugins.documents.routers import router as documents_router
        from cndb.plugins.documents.routers.attachments import router as attachments_router
        from cndb.plugins.documents.routers.change_requests import router as change_requests_router
        from cndb.plugins.documents.routers.charts import router as charts_router
        from cndb.plugins.documents.routers.content_templates import router as content_templates_router
        from cndb.plugins.documents.routers.file_import import router as file_import_router
        from cndb.plugins.documents.routers.issues import router as issues_router
        from cndb.plugins.documents.routers.share import share_router
        from cndb.plugins.documents.routers.tags import router as tags_router
        from cndb.plugins.documents.routers.templates import router as templates_router
        from cndb.plugins.documents.routers.vault import router as vault_router

        # 导入/导出路由先挂载：/import、/import/files、/export/vault 必须在 /{doc_id} 一族之前匹配；
        # /templates、/document-content-templates 同理（否则会被 /{doc_id} 吃掉），放在 documents_router 之前
        router.include_router(vault_router)
        router.include_router(file_import_router)
        router.include_router(templates_router)
        router.include_router(content_templates_router)
        # /attachments 同样必须先于 /{doc_id}
        router.include_router(attachments_router)
        router.include_router(documents_router)
        router.include_router(charts_router)
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
