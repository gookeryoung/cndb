"""tables 插件 —— 数据表元数据、字段类型、DDL 引擎、行 CRUD、查询编译.

子模块：
- models.py          DataTable / DataField / DataView / TablePermission
- field_types/       字段类型系统（registry + 9 内置 + link_to_table）
- ddl.py             动态 DDL 引擎（sa.Table / CREATE TABLE / ALTER）
- records.py         行 CRUD + bulk
- query.py           查询编译（筛选/排序/聚合）
- view_rules.py      视图规则归一化
- permission_rules.py 权限规则归一化
- access.py          权限判定链
- transfer.py        导入导出
- routers/           按资源拆分 router
"""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase
from cndb.plugins.tables.routers import router as tables_router


class TablesPlugin(PluginBase):
    """数据表插件：元数据 + 动态 DDL + 行数据 + 视图规则."""

    name = "tables"
    version = "0.1.0"
    description = "数据表元数据、字段类型、动态 DDL、行 CRUD、查询编译"
    icon = "UnorderedListOutlined"
    route_prefix = "workspaces"  # 路由挂载到 workspaces 下: /api/v1/workspaces/{wid}/tables/...
    direct_router = tables_router

    @override
    def register_models(self) -> None:
        """导入 models 确保 Base.metadata 包含所有表."""
        from cndb.plugins.tables import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """注册路由（当 direct_router 未设置时的 fallback）."""
        # direct_router 由 mount_routes 优先使用，这里保留空实现


__all__ = ["TablesPlugin"]
