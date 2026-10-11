"""表单级权限判定：三阈值（use/edit/delete）与表级权限取交集.

不变量：表单权限只能收紧、不能放宽表级限制。
表级判定由 tables.access.check_action 在路由层完成（get_table_or_404），
本模块只负责表单阈值判定——两者同时通过才允许操作。

阈值语义（FormDefinition.<action>_role 列）：
    ""   = 未配置，直接放行（回退纯表级判定）
    非空 = 工作区角色名，要求当前用户工作区角色 ROLE_RANK 达到该阈值
表成员授权（TableMember / 自定义 Role）不豁免表单阈值——
与 TablePermission 阈值列同为工作区角色比较，语义同构。
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.forms.models import FormDefinition
from cndb.plugins.workspaces.models import ROLE_RANK, Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role


class FormAction(StrEnum):
    """表单使用动作枚举."""

    USE = "use"  # 打开表单 / 查看行列表 / 提交新建
    EDIT = "edit"  # 表单内编辑已有行
    DELETE = "delete"  # 表单内删除行


def check_form_access(
    db: Session,
    form: FormDefinition,
    user: User,
    action: FormAction,
) -> bool:
    """判定用户是否满足表单阈值.

    Args:
        db: 数据库会话
        form: 表单定义
        user: 当前用户
        action: 表单动作（决定取哪个阈值列）

    Returns:
        True 表示阈值通过（或未配置阈值）。
    """
    threshold = getattr(form, f"{action.value}_role", "")
    if not threshold:
        return True  # 未配置 → 回退表级判定（路由层已做 check_action）
    try:
        required = WorkspaceRole(threshold)
    except ValueError:
        return False  # 非法阈值配置 → 拒绝（fail-closed）
    ws = db.get(Workspace, form.workspace_id)
    if ws is None:  # pragma: no cover - workspace FK CASCADE 保证存在
        return False
    role = get_member_role(user, ws, db)
    if role is None:
        return False
    return ROLE_RANK[role] >= ROLE_RANK[required]


def ensure_form_access(
    db: Session,
    form: FormDefinition,
    user: User,
    action: FormAction,
) -> None:
    """表单阈值不满足时抛 HTTPException 403."""
    if not check_form_access(db, form, user, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="表单权限不足",
        )


def get_form_or_404(db: Session, form_id: int, workspace_id: int) -> FormDefinition:
    """按 id + workspace 查表单，不存在或已软删返回 404."""
    form = (
        db.query(FormDefinition)
        .filter(
            FormDefinition.id == form_id,
            FormDefinition.workspace_id == workspace_id,
            FormDefinition.trashed.is_(False),
        )
        .first()
    )
    if form is None:
        raise HTTPException(status_code=404, detail="表单不存在")
    return form


__all__ = [
    "FormAction",
    "check_form_access",
    "ensure_form_access",
    "get_form_or_404",
]
