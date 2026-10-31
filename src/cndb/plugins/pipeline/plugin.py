"""pipeline 插件 —— 流水线质量检查（ADR 0076 P0）.

模块职责：

- ``models.py``：``pipeline_workflow`` / ``pipeline_run`` / ``pipeline_finding`` 三表；
- ``services/dsl/``：YAML 子集 → 校验过的 IR（唯一真相源为 YAML 原文）；
- ``services/checks/``：检查动作注册表 + ``table/*`` / ``document/*`` 内置动作；
- ``services/runner.py``：DAG 执行器（手动触发、单飞、结论推导）；
- ``routers/``：定义 CRUD / 校验 / 检查目录 / 触发 / 运行与发现物查询。

扩展点唯一：检查动作注册表（``域/动作`` 命名空间 + 输入 schema），耗材新格式零引擎改动。
"""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase


class PipelinePlugin(PluginBase):
    """质量检查插件：声明式 DSL + 检查动作注册表 + DAG 执行器."""

    name = "pipeline"
    version = "0.1.0"
    description = "流水线质量检查：数据表 / 文档检测的 YAML DSL、可扩展检查动作与结构化发现物"
    icon = "ExperimentOutlined"
    route_prefix = "workspaces"

    @override
    def register_models(self) -> None:
        """导入 models 确保 Base.metadata 包含 pipeline_* 三表."""
        from cndb.plugins.pipeline import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """挂载定义路由与运行 / 发现物路由."""
        from cndb.plugins.pipeline.routers import runs_router, workflows_router

        router.include_router(workflows_router)
        router.include_router(runs_router)


plugin = PipelinePlugin()

__all__ = ["PipelinePlugin", "plugin"]
