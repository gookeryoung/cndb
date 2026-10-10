"""用户管理 Pydantic schema: 编辑 / 批量操作 / 操作日志查询.

FastAPI 为类型真理源，前端 frontend/src/api/types.ts 需同步维护。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from cndb.plugins.accounts.models import UserRole


class UserAdminResponse(BaseModel):
    """管理员视角用户响应（UserResponse 基础上补充 phone 与创建时间）."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None = None
    phone: str | None = None
    nickname: str
    role: str = Field(default=UserRole.USER.value, description="用户角色")
    is_active: bool
    is_superuser: bool
    created_at: datetime | None = None


class UserAdminUpdateRequest(BaseModel):
    """管理员编辑用户请求体 —— 仅提交的字段会被更新.

    email/phone 传空字符串表示清空（置 NULL）；role 变更即提权/降权。
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    username: str | None = Field(default=None, min_length=2, max_length=150, description="用户名")
    email: str | None = Field(default=None, max_length=255, description="邮箱（空字符串表示清空）")
    phone: str | None = Field(default=None, max_length=32, description="联系电话（空字符串表示清空）")
    nickname: str | None = Field(default=None, max_length=150, description="昵称")
    role: str | None = Field(default=None, description="新角色: system_admin / security_admin / audit_admin / user")
    is_active: bool | None = Field(default=None, description="启用（true）/ 禁用（false）")


class BatchUserActionRequest(BaseModel):
    """批量操作请求体：启用 / 禁用 / 设置角色."""

    model_config = ConfigDict(strict=True, extra="forbid")

    action: Literal["activate", "deactivate", "set_role"] = Field(description="批量动作")
    user_ids: list[int] = Field(min_length=1, description="目标用户 ID 列表")
    role: str | None = Field(default=None, description="action=set_role 时必填")


class BatchUserItemResult(BaseModel):
    """批量操作单项结果."""

    user_id: int
    username: str
    success: bool
    error: str | None = Field(default=None, description="失败原因（中文明细）")


class BatchUserActionResponse(BaseModel):
    """批量操作汇总响应."""

    total: int = Field(description="提交的目标数量")
    succeeded: int = Field(description="成功数量")
    failed: int = Field(description="失败数量")
    results: list[BatchUserItemResult]


class UserAuditLogResponse(BaseModel):
    """用户管理操作日志条目."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str = Field(description="动作: update / role_change / activate / deactivate / batch")
    actor_id: int | None = Field(default=None, description="操作人 ID")
    target_user_id: int | None = Field(default=None, description="被操作用户 ID")
    detail: dict[str, Any] = Field(description="变更详情（before/after 快照、批量摘要）")
    created_at: datetime | None = None


class UserAuditLogPage(BaseModel):
    """操作日志分页响应."""

    total: int = Field(description="符合条件的日志总数")
    items: list[UserAuditLogResponse]


class UserListPage(BaseModel):
    """用户列表分页响应."""

    total: int = Field(description="符合条件的用户总数")
    items: list[UserAdminResponse]
