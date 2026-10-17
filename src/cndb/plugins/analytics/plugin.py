"""analytics 插件 —— 数据分析（独立工作区模块，数据源为工作区内任意数据表）.

模块职责：
- 自定义计算模板的持久化（含公式表达式）；
- 受限公式表达式引擎（`services/formula.py`）：字段引用 + 四则运算 + 白名单函数，
  以「逐行求值、聚合函数看整列」的语义计算派生指标；
- 求值接口：按数据表计算派生指标列，供前端可视化与统计。
"""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase


class AnalyticsPlugin(PluginBase):
    """数据分析插件：统计学分析工具 + 自定义计算模板（公式引擎）+ 可视化."""

    name = "analytics"
    version = "0.1.0"
    description = "数据分析：描述统计与分布分析工具、自定义计算模板（公式引擎）、可视化图表"
    icon = "BarChartOutlined"
    route_prefix = "workspaces"

    @override
    def register_models(self) -> None:
        """导入 models 确保 Base.metadata 包含 analytics_template."""
        from cndb.plugins.analytics import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """挂载 analytics 路由（模板 CRUD + 求值）."""
        from cndb.plugins.analytics.routers.run import router as run_router
        from cndb.plugins.analytics.routers.templates import router as templates_router

        router.include_router(templates_router)
        router.include_router(run_router)

    # 不注册 register_navigation / register_apps：分析功能经工作区页签「数据分析」进入


plugin = AnalyticsPlugin()

__all__ = ["AnalyticsPlugin", "plugin"]
