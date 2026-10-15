"""认证相关 Pydantic schema: 注册 / 登录 / Token 响应 / 认证模式."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cndb.plugins.accounts.models import UserRole


class RegisterRequest(BaseModel):
    """公开注册请求体 —— 仅普通用户，不接受角色参数.

    公开注册入口收窄为"只允许普通用户"，因此 role 字段已移除。
    角色由 User 模型默认值（user）自动填充。
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    username: str = Field(min_length=2, max_length=150, description="用户名")
    email: str | None = Field(default=None, max_length=255, description="邮箱（可选）")
    nickname: str = Field(default="", max_length=150, description="昵称")
    password: str = Field(min_length=6, max_length=128, description="明文密码")


class AdminRegisterRequest(RegisterRequest):
    """管理员创建用户请求体 —— role 字段强制必填（三员 + user 任意）."""

    model_config = ConfigDict(strict=True, extra="forbid")
    role: str = Field(description="用户角色: system_admin / security_admin / audit_admin / user")


class ProfileUpdateRequest(BaseModel):
    """个人资料更新请求体 —— 当前用户自助修改昵称/邮箱.

    两个字段均可选，仅提交的字段会被更新；username/角色等不开放自助修改。
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    nickname: str | None = Field(default=None, max_length=150, description="昵称")
    email: str | None = Field(default=None, max_length=255, description="邮箱（传空字符串表示清空）")


class LoginRequest(BaseModel):
    """用户登录请求体（支持用户名或邮箱）."""

    model_config = ConfigDict(strict=True)

    login: str = Field(min_length=1, max_length=255, description="用户名或邮箱")
    password: str = Field(min_length=1, max_length=128, description="明文密码")


class TokenResponse(BaseModel):
    """登录 / 刷新令牌响应.

    ``refresh_token`` 为**不透明随机串**（服务端只存哈希，可吊销）；access token 为无状态 JWT，
    因此 ``refresh_token`` 是会话延续与注销能力的载体。
    """

    access_token: str = Field(description="JWT 访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    refresh_token: str | None = Field(default=None, description="刷新令牌（不透明随机串）")
    expires_in: int | None = Field(default=None, description="访问令牌有效期（秒）")


class RefreshRequest(BaseModel):
    """刷新令牌请求体."""

    model_config = ConfigDict(strict=True, extra="forbid")

    refresh_token: str = Field(min_length=8, max_length=512, description="刷新令牌")


class LogoutRequest(BaseModel):
    """登出请求体.

    - 传 ``refresh_token``：吊销该会话（access token 过期后也能登出）；
    - ``all=true``：吊销当前用户**全部**会话（需要携带有效 access token 认证）。
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    refresh_token: str | None = Field(default=None, max_length=512, description="要吊销的刷新令牌")
    all: bool = Field(default=False, description="是否吊销全部会话")


class PasswordChangeRequest(BaseModel):
    """修改自己的密码（需校验当前密码）."""

    model_config = ConfigDict(strict=True, extra="forbid")

    current_password: str = Field(min_length=1, max_length=128, description="当前密码")
    new_password: str = Field(min_length=6, max_length=128, description="新密码（至少 6 位）")


class SessionOut(BaseModel):
    """会话（刷新令牌）公开信息."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: object = Field(description="创建时间")
    expires_at: object = Field(description="过期时间")
    revoked_reason: str | None = Field(default=None, description="吊销原因（有效会话为 null）")


class AuthModeResponse(BaseModel):
    """认证模式响应（无认证端点，前端启动时探测）.

    local = 单机免登录模式（LOCAL_MODE=True）；jwt = 常规 JWT 认证.
    """

    mode: Literal["local", "jwt"] = Field(description="认证模式")


class UserResponse(BaseModel):
    """用户公开信息响应（不含密码）."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None = None
    nickname: str
    role: str = Field(default=UserRole.USER.value, description="用户角色")
    is_active: bool
    is_superuser: bool
