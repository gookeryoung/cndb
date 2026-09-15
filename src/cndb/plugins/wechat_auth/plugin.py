"""wechat_auth 插件入口 —— 被 plugin_registry 自动发现."""

from __future__ import annotations

from typing import override

from fastapi import APIRouter

from cndb.plugins.base import PluginBase
from cndb.plugins.wechat_auth.routers.login import router as login_router


class WechatAuthPlugin(PluginBase):
    """微信小程序登录（code → openid → JWT）."""

    name = "wechat_auth"
    version = "0.1.0"
    description = "微信小程序一键登录，自动关联 cndb User 并签发 JWT"
    icon = "WechatOutlined"
    route_prefix = "wechat-auth"

    @override
    def register_models(self) -> None:
        """导入 models 确保 SQLAlchemy Base.metadata 包含 WechatAccount."""
        from cndb.plugins.wechat_auth import models  # noqa: F401

    @override
    def register_routes(self, router: APIRouter) -> None:
        router.include_router(login_router)
