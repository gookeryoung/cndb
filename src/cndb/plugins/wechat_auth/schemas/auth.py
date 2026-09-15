"""微信登录相关的 Pydantic schema."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WechatLoginRequest(BaseModel):
    """小程序端 POST /wechat-auth/login 请求体."""

    code: str = Field(..., min_length=1, description="wx.login() 返回的临时 code")
    nickname: str | None = Field(default=None, max_length=128, description="微信昵称（可选）")
    avatar_url: str | None = Field(default=None, max_length=512, description="微信头像 URL（可选）")


class WechatLoginResponse(BaseModel):
    """微信登录成功响应 —— 与 accounts TokenResponse 格式对齐."""

    access_token: str
    token_type: str = "bearer"
    user: dict[str, object]  # { id, username, nickname, role, is_superuser }


__all__ = ["WechatLoginRequest", "WechatLoginResponse"]
