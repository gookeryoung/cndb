"""wechat_auth schemas package."""

from cndb.plugins.wechat_auth.schemas.auth import (
    WechatLoginRequest,
    WechatLoginResponse,
)

__all__ = ["WechatLoginRequest", "WechatLoginResponse"]
