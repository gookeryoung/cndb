"""认证相关 Pydantic schema: 注册 / 登录 / Token 响应."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    """用户注册请求体."""

    model_config = ConfigDict(strict=True)

    username: str = Field(min_length=2, max_length=150, description="用户名")
    email: str | None = Field(default=None, max_length=255, description="邮箱（可选）")
    nickname: str = Field(default="", max_length=150, description="昵称")
    password: str = Field(min_length=6, max_length=128, description="明文密码")


class LoginRequest(BaseModel):
    """用户登录请求体（支持用户名或邮箱）."""

    model_config = ConfigDict(strict=True)

    login: str = Field(min_length=1, max_length=255, description="用户名或邮箱")
    password: str = Field(min_length=1, max_length=128, description="明文密码")


class TokenResponse(BaseModel):
    """JWT 登录令牌响应."""

    access_token: str = Field(description="JWT 访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")


class UserResponse(BaseModel):
    """用户公开信息响应（不含密码）."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None = None
    nickname: str
    is_active: bool
    is_superuser: bool
