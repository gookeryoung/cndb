"""datasource 插件 —— 周期性外部数据同步.

M1：领域无关的抓取管线（providers / services）。
M2：同步任务表、四种游标、调度器（DB 租约）、CLI 与 run / preview 端点。
M3：前端任务页（适配器仅保留通用项：http_json / llm_prompt）。

端点（``/api/v1/workspaces/{wid}/datasource``）：

- ``GET  /providers``                        适配器清单 + 参数表单描述
- ``GET|POST /sync-jobs``                    列表 / 新建
- ``GET|PUT|DELETE /sync-jobs/{id}``         详情 / 修改 / 删除
- ``POST /sync-jobs/{id}/run``               立即运行（租约单飞）
- ``POST /sync-jobs/{id}/preview``           抓一次预览（不落库）
- ``GET  /sync-jobs/{id}/runs``              运行历史

CLI：``cndb sync list|run|tick|preview``
"""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase
from cndb.plugins.datasource.routers import router as datasource_router

router = datasource_router


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
        """导入 models 确保 Base.metadata 包含同步任务 / 运行记录两张表."""
        from cndb.plugins.datasource import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """注册路由（``direct_router`` 优先，本方法为 fallback）."""


__all__ = ["DatasourcePlugin", "router"]
