"""acquisition 插件 —— 规则驱动的数据表 / 文档迭代获取（ADR 0085）.

模块职责：

- ``models.py``：策略 / 运行 / 轮次 / 条目台账四表；
- ``services/rules/``：表达式 / 筛选打分 / 去重（纯函数）；
- ``services/channels.py``：渠道声明 → 内存 ``SyncJobSpec``（复用既有 job，不复制）；
- ``services/targets.py``：表落点（upsert）+ 台账；
- ``services/runner.py``：唯一执行入口（租约 / 轮次 / 状态机 / 留痕）；
- ``routers/strategies.py``：策略 CRUD / 运行 / 预览 / 运行历史。

端点：``/api/v1/workspaces/{wid}/acquisition``（策略与运行）。
CLI：``cndb acquisition list|run|preview``。
"""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.acquisition.routers import router as acquisition_router
from cndb.plugins.base import PluginBase

router = acquisition_router


class AcquisitionPlugin(PluginBase):
    """采集策略插件：四段规则 + 轮次编排 + 双落点（本期表落点）。"""

    name = "acquisition"
    version = "0.1.0"
    description = "规则驱动的自动获取：多渠道抓取、跨轮去重与筛选、迭代扩展与可追溯落点"
    icon = "RadarChartOutlined"
    # 与 tables / datasource 同层级：/api/v1/workspaces/{wid}/acquisition/...
    route_prefix = "workspaces"
    direct_router = router

    @override
    def register_models(self) -> None:
        """导入 models 确保 Base.metadata 包含 acquisition_* 四表."""
        from cndb.plugins.acquisition import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """注册路由（``direct_router`` 优先，本方法为 fallback）."""


plugin = AcquisitionPlugin()

__all__ = ["AcquisitionPlugin", "plugin", "router"]
