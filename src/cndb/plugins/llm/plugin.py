"""llm 插件 —— 大模型能力平台（ADR 0020 P0）.

平台级能力归属：
- 个人连接（``llm_user_config``）/ OpenAI 兼容客户端 / 调用网关 / 动作注册表 / 调用留痕（``llm_run``）；
- 端点（``/api/v1/llm``）：``GET|PUT /config``、``POST /config/test``、``GET /actions``、``GET /runs``；
- 不注册侧边导航与 APP 入口（配置入口在「个人设置 → 大模型」）。

依赖方向：本插件只依赖 ``cndb.core`` 与 ``accounts.models.User``（FK / 类型），**不得** import
任何领域插件；领域插件通过 ``services.gateway`` / ``services.client`` 使用本能力。
"""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase


class LlmPlugin(PluginBase):
    """大模型能力平台插件：个人连接 + 兼容客户端 + 网关 + 动作目录 + 调用留痕."""

    name = "llm"
    version = "0.1.0"
    description = "大模型能力平台：个人连接 / OpenAI 兼容客户端 / 调用网关 / 能力目录 / 调用留痕"
    icon = "RobotOutlined"

    @override
    def register_models(self) -> None:
        """导入 models 确保 Base.metadata 包含 llm_user_config / llm_run."""
        from cndb.plugins.llm import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """挂载 /api/v1/llm 下三组路由."""
        from cndb.plugins.llm.routers import router as llm_router

        router.include_router(llm_router)


plugin = LlmPlugin()

__all__ = ["LlmPlugin", "plugin"]
