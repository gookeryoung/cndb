"""accounts 插件 —— 用户认证.

功能：
- 用户注册 / JWT 登录 / 当前用户查询

路由挂载：/api/v1/auth/*
"""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.accounts.routers.auth import router as auth_router
from cndb.plugins.base import PluginBase


class AccountsPlugin(PluginBase):
    """账户与认证插件."""

    name = "accounts"
    version = "0.1.0"
    description = "用户注册 / JWT 登录"
    icon = "UserOutlined"

    @override
    def register_models(self) -> None:
        """导入 models 确保 SQLAlchemy Base.metadata 包含 User."""
        from cndb.plugins.accounts import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """注册 auth 路由."""
        router.include_router(auth_router)
