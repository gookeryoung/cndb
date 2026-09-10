"""accounts 插件 —— 用户认证与 ApiToken 管理.

功能：
- 用户注册 / JWT 登录 / 当前用户查询
- ApiToken 签发 / 列表 / 撤销（cndb_ 前缀 + SHA-256 摘要）

路由挂载：/api/v1/auth/* 和 /api/v1/tokens/*
"""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.accounts.routers.auth import router as auth_router
from cndb.plugins.accounts.routers.tokens import router as tokens_router
from cndb.plugins.base import PluginBase


class AccountsPlugin(PluginBase):
    """账户与认证插件."""

    name = "accounts"
    version = "0.1.0"
    description = "用户注册 / JWT 登录 / ApiToken 管理"
    icon = "UserOutlined"

    @override
    def register_models(self) -> None:
        """导入 models 确保 SQLAlchemy Base.metadata 包含 User / ApiToken."""
        from cndb.plugins.accounts import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        """注册 auth 和 tokens 两组路由."""
        router.include_router(auth_router)
        router.include_router(tokens_router)
