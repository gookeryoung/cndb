"""认证相关 Pydantic schema: 注册 / 登录 / Token 响应."""

from __future__ import annotations

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
    role: str = Field(default=UserRole.USER.value, description="用户角色")
    is_active: bool
    is_superuser: bool
