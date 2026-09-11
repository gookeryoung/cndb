"""表级访问控制：角色覆盖 + 行级过滤 + 字段隐藏.

对齐旧项目 tables/access.py 和 permission_rules.py.
策略优先级：表级 TablePermission 覆盖 > 工作区 WorkspaceRole 默认.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, TablePermission
from cndb.plugins.workspaces.models import ROLE_RANK, WorkspaceRole


class TableAction(StrEnum):
    """表级动作枚举."""

    READ = "READ"
    EDIT_RECORDS = "EDIT_RECORDS"
    EDIT_VIEWS = "EDIT_VIEWS"
    EDIT_SCHEMA = "EDIT_SCHEMA"
    COMMENT = "COMMENT"


# 动作 -> TablePermission 字段映射
_ACTION_PERMISSION_FIELD: dict[TableAction, str] = {
    TableAction.READ: "read_role",
    TableAction.EDIT_RECORDS: "edit_records_role",
    TableAction.EDIT_VIEWS: "edit_views_role",
    TableAction.EDIT_SCHEMA: "edit_schema_role",
    TableAction.COMMENT: "comment_role",
}

# 动作 -> 默认工作区角色（表级 permission 为空时回退）
_ACTION_DEFAULT_ROLE: dict[TableAction, WorkspaceRole] = {
    TableAction.READ: WorkspaceRole.VIEWER,
    TableAction.EDIT_RECORDS: WorkspaceRole.EDITOR,
    TableAction.EDIT_VIEWS: WorkspaceRole.EDITOR,
    TableAction.EDIT_SCHEMA: WorkspaceRole.ADMIN,
    TableAction.COMMENT: WorkspaceRole.VIEWER,
}


def check_action(
    db: Session,
    table: DataTable,
    user: User,
    action: TableAction,
    member_role: WorkspaceRole | None = None,
) -> bool:
    """判定用户是否可以在该表上执行某动作.

    优先级：表级 TablePermission 覆盖 > 工作区 WorkspaceRole 默认.
    TablePermission 字段为空字符串时视为未设置，回退工作区角色.
    """
    # 1. 表级 permission 覆盖
    perm = db.get(TablePermission, table.id)
    if perm is not None:
        field_name = _ACTION_PERMISSION_FIELD[action]
        required_role_str = getattr(perm, field_name, "")
        if required_role_str:
            # 表级指定了角色 — 用户必须达到该角色
            try:
                required = WorkspaceRole(required_role_str)
            except ValueError:
                return False
            user_role = member_role or _get_member_role(db, table, user)
            if user_role is None:
                return False
            return ROLE_RANK[user_role] >= ROLE_RANK[required]

    # 2. 回退到工作区默认角色
    default_required = _ACTION_DEFAULT_ROLE[action]
    user_role = member_role or _get_member_role(db, table, user)
    if user_role is None:
        return False
    return ROLE_RANK[user_role] >= ROLE_RANK[default_required]


def get_row_scope(db: Session, table: DataTable) -> list[dict[str, Any]]:
    """获取表级行级过滤规则（空列表 = 无限制）.

    返回 TablePermission.row_filters 中的条件列表，由上层 query 编译.
    """
    perm = db.get(TablePermission, table.id)
    if perm is None or not perm.row_filters:
        return []
    return list(perm.row_filters)


def row_filter_conjunction(db: Session, table: DataTable) -> str:
    """行级过滤条件的连接方式：AND（默认）或 OR."""
    perm = db.get(TablePermission, table.id)
    if perm is None:
        return "AND"
    conj = perm.row_filter_type.upper()
    return conj if conj in ("AND", "OR") else "AND"


def get_hidden_field_names(db: Session, table: DataTable, user: User) -> set[str]:
    """获取用户在该表不可见的字段名集合.

    hidden_fields dict 键 = 角色名，值 = 隐藏字段列表.
    当前用户角色对应的列表即为隐藏字段.
    """
    perm = db.get(TablePermission, table.id)
    if perm is None or not perm.hidden_fields:
        return set()
    user_role = _get_member_role(db, table, user)
    if user_role is None:
        return set()
    hidden = perm.hidden_fields.get(user_role.value, [])
    return set(hidden)


def apply_field_hiding(
    row: dict[str, Any],
    hidden: Sequence[str] | set[str],
) -> dict[str, Any]:
    """从单行字典中移除隐藏字段（in-place 并返回）."""
    for fname in hidden:
        row.pop(fname, None)
    return row


def apply_field_hiding_rows(
    rows: list[dict[str, Any]],
    hidden: Sequence[str] | set[str],
) -> list[dict[str, Any]]:
    """批量移除多行字典中的隐藏字段."""
    hidden_set = set(hidden)
    for row in rows:
        apply_field_hiding(row, hidden_set)
    return rows


# ── 内部 ──────────────────────────────────────────────


def _get_member_role(db: Session, table: DataTable, user: User) -> WorkspaceRole | None:
    """查询用户在表所属工作区的角色."""
    from cndb.plugins.workspaces.permissions import get_member_role as _gmr

    ws = db.query(table.__class__.__bases__[0]).filter_by(id=table.workspace_id).first() if False else None
    # 直接查 workspace
    from cndb.plugins.workspaces.models import Workspace

    ws = db.get(Workspace, table.workspace_id)
    if ws is None:
        return None
    role = _gmr(user, ws, db)
    return role


__all__ = [
    "TableAction",
    "apply_field_hiding",
    "apply_field_hiding_rows",
    "check_action",
    "get_hidden_field_names",
    "get_row_scope",
    "row_filter_conjunction",
]
