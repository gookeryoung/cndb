"""datasource 插件 —— 周期性外部数据同步.

M1 阶段只提供领域无关的抓取管线（providers / services），**没有 API 端点**：
同步任务表、调度与 run/preview 端点在 M2 / M3 落地，届时把子 router
include 进本模块的 ``router`` 即可（挂载点已在 ``route_prefix`` 预留）。

调用入口（M1）：

    from cndb.plugins.datasource.providers.base import SyncJobSpec
    from cndb.plugins.datasource.services.pipeline import run_pipeline
    from cndb.plugins.datasource.services.write import upsert_rows
"""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase

router = APIRouter()


class DatasourcePlugin(PluginBase):
    """数据源同步插件：Provider 适配器 + 归一 + 抓取管线 + 幂等落表."""

    name = "datasource"
    version = "0.1.0"
    description = "周期性外部数据同步：声明式请求模板 / 分页 / 时间分片 / 增量游标 / 幂等落表"
    icon = "CloudDownloadOutlined"
    # 与 tables 同层级：/api/v1/workspaces/{wid}/datasource/...
    route_prefix = "workspaces"
    direct_router = router

    @override
    def register_models(self) -> None:
        """M1 无模型；M2 增加 sync_job / sync_run 后在此导入 models."""

    @override
    def register_routes(self, router: APIRouter) -> None:
        """注册路由（``direct_router`` 优先，本方法为 fallback）."""


__all__ = ["DatasourcePlugin", "router"]
