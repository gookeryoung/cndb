"""表级访问控制：拥有者 + 工作区角色 + 表成员 + TablePermission.

策略优先级：表拥有者 > 工作区 OWNER > 表成员授权 > TablePermission 角色阈值 > 工作区角色默认.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, TableMember, TablePermission
from cndb.plugins.workspaces.models import ROLE_RANK, Role, Workspace, WorkspaceRole

logger = logging.getLogger(__name__)


class TableAction(StrEnum):
    """表级动作枚举."""

    READ = "READ"
    EDIT_RECORDS = "EDIT_RECORDS"
    EDIT_VIEWS = "EDIT_VIEWS"
    EDIT_SCHEMA = "EDIT_SCHEMA"
    MANAGE_DATA = "MANAGE_DATA"


# 动作 -> TablePermission 字段映射
_ACTION_PERMISSION_FIELD: dict[TableAction, str] = {
    TableAction.READ: "read_role",
    TableAction.EDIT_RECORDS: "edit_records_role",
    TableAction.EDIT_VIEWS: "edit_views_role",
    TableAction.EDIT_SCHEMA: "edit_schema_role",
    TableAction.MANAGE_DATA: "manage_data_role",
}

# 动作 -> 默认工作区角色（表级 permission 为空时回退）
_ACTION_DEFAULT_ROLE: dict[TableAction, WorkspaceRole] = {
    TableAction.READ: WorkspaceRole.VIEWER,
    TableAction.EDIT_RECORDS: WorkspaceRole.EDITOR,
    TableAction.EDIT_VIEWS: WorkspaceRole.EDITOR,
    TableAction.EDIT_SCHEMA: WorkspaceRole.EDITOR,
    TableAction.MANAGE_DATA: WorkspaceRole.EDITOR,
}


# 内置表成员角色（TableMember.role 硬编码值）→ 动作集合
_BUILTIN_MEMBER_ACTIONS: dict[str, set[TableAction]] = {
    "write": {TableAction.READ, TableAction.EDIT_RECORDS, TableAction.EDIT_VIEWS},
    "read": {TableAction.READ},
}


def _resolve_member_role_permissions(
    db: Session,
    member: TableMember,
) -> set[TableAction] | None:
    """解析 TableMember.role 为具体允许动作集合.

    返回 None 表示既不是内置 read/write 也不是合法 Role.code，
    调用方按"无成员授权"继续往下走.
    """
    builtin = _BUILTIN_MEMBER_ACTIONS.get(member.role)
    if builtin is not None:
        return builtin
    role = db.query(Role).filter(Role.code == member.role).first()
    if role is None:
        return None
    allowed: set[TableAction] = set()
    for action in TableAction:
        if role.has_action(action.value):
            allowed.add(action)
    return allowed


_MISSING: Any = object()


class TableAccessPreload:
    """批量判定用的预取上下文（避免逐表查 TableMember / TablePermission）.

    列表接口有几十张表，逐张 ``check_action`` 会各产生 ~3 次查询；
    这里一次性把「当前用户的表成员记录」「各表权限行」取回来，
    再对每张表做**纯计算**判定，语义与 ``check_action`` 完全一致。
    """

    def __init__(
        self,
        *,
        member_role: WorkspaceRole | None,
        members: dict[int, Any],
        perms: dict[int, Any],
    ) -> None:
        self.member_role = member_role
        self.members = members
        self.perms = perms

    def check(self, db: Session, table: DataTable, user: User, action: TableAction) -> bool:
        return check_action(
            db,
            table,
            user,
            action,
            self.member_role,
            member=self.members.get(table.id, None),
            perm=self.perms.get(table.id, None),
        )

    def read_role(self, table_id: int) -> str:
        """该表配置的读取门槛（"" 表示未配置，走默认）。"""
        perm = self.perms.get(table_id)
        return str(getattr(perm, "read_role", "") or "") if perm is not None else ""


def preload_table_access(db: Session, tables: Sequence[DataTable], user: User) -> TableAccessPreload:
    """一次查询取回批量判定所需的成员/权限数据."""
    ids = [t.id for t in tables]
    member_role: WorkspaceRole | None = None
    members: dict[int, Any] = {}
    perms: dict[int, Any] = {}
    if not ids:
        return TableAccessPreload(member_role=None, members=members, perms=perms)

    from cndb.plugins.workspaces.models import Workspace
    from cndb.plugins.workspaces.permissions import get_member_role

    workspace_id = tables[0].workspace_id
    ws = db.get(Workspace, workspace_id)
    if ws is not None:
        member_role = get_member_role(user, ws, db)

    for m in db.query(TableMember).filter(TableMember.table_id.in_(ids), TableMember.user_id == user.id).all():
        members[int(m.table_id)] = m
    for perm in db.query(TablePermission).filter(TablePermission.table_id.in_(ids)).all():
        perms[int(perm.table_id)] = perm
    return TableAccessPreload(member_role=member_role, members=members, perms=perms)


def check_action(
    db: Session,
    table: DataTable,
    user: User,
    action: TableAction,
    member_role: WorkspaceRole | None = None,
    *,
    member: Any = _MISSING,
    perm: Any = _MISSING,
) -> bool:
    """判定用户是否可以在该表上执行某动作.

    优先级：
      1. 表拥有者（owner_id == user.id）→ 拥有全部动作，包括 EDIT_SCHEMA
      2. 工作区 OWNER → 拥有全部动作
      3. 表成员授权（TableMember）→ read/write 两级，见 _READ_MEMBER_ACTIONS / _WRITE_MEMBER_ACTIONS
      4. TablePermission 角色阈值（仅当用户未通过成员授权时生效）
      5. 工作区角色默认
    """
    # ── 1. 表拥有者 ──
    if table.owner_id is not None and table.owner_id == user.id:
        return True

    # ── 2. 工作区 OWNER ──
    user_role = member_role or _get_member_role(db, table, user)
    if user_role is None:
        # 工作区成员都不是，只有 owner 可能放行；owner 检查已通过
        return False
    if user_role == WorkspaceRole.OWNER:
        return True

    # ── 3. 表成员授权 ──
    if member is _MISSING:
        member = db.query(TableMember).filter(TableMember.table_id == table.id, TableMember.user_id == user.id).first()
    if member is not None:
        allowed = _resolve_member_role_permissions(db, member)
        if allowed is None:
            # 角色 code 无效或未定义，忽略成员记录，继续走阈值判定
            pass
        else:
            return action in allowed

    # ── 4. TablePermission 阈值 ──
    # 按 table_id 查（主键是自增 id，用 db.get(..., table.id) 会取到别的表 → 权限错位）
    if perm is _MISSING:
        perm = db.query(TablePermission).filter(TablePermission.table_id == table.id).first()
    if perm is not None:
        field_name = _ACTION_PERMISSION_FIELD[action]
        required_role_str = getattr(perm, field_name, "")
        if required_role_str:
            try:
                # 角色值统一小写（WorkspaceRole 的 value 是 owner/editor/viewer）。
                # 大小写不归一的话，"OWNER" 会解析失败 → 静默返回 False，
                # 表现为"权限配置了但所有人（含管理员）都被拒"这种难以排查的现象。
                required = WorkspaceRole(str(required_role_str).strip().lower())
            except ValueError:
                logger.warning(
                    "表 %s 的 %s 配置了无效角色 %r（已按拒绝处理），应为 owner/editor/viewer",
                    table.id,
                    field_name,
                    required_role_str,
                )
                return False
            return ROLE_RANK[user_role] >= ROLE_RANK[required]

    # ── 5. 工作区角色默认 ──
    default_required = _ACTION_DEFAULT_ROLE[action]
    return ROLE_RANK[user_role] >= ROLE_RANK[default_required]


def check_workspace_permission(
    db: Session,
    workspace_id: int,
    user: User,
    min_role: WorkspaceRole,
) -> Workspace:
    """工作区级角色最低门槛检查.

    工作区不存在 → HTTPException 404；角色缺失或低于 min_role → HTTPException 403；
    通过则返回该 Workspace（部分调用点需要 workspace 对象）.
    """
    from cndb.plugins.workspaces.permissions import get_member_role

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    role = get_member_role(user, ws, db)
    if role is None or ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise HTTPException(status_code=403, detail="权限不足")
    return ws


def get_table_or_404(
    table_id: int,
    workspace_id: int,
    db: Session,
    user: User | None = None,
    action: TableAction | None = None,
) -> DataTable:
    """按 workspace_id + table_id 查数据表，可选同时做表级动作权限检查.

    Args:
        table_id: 数据表 ID
        workspace_id: 工作区 ID
        db: 数据库会话
        user: 当前用户；提供了则配合 action 做 check_action 校验
        action: 需要校验的表级动作；仅当 user 非 None 时生效

    Raises:
        HTTPException(401): 需要认证但 user 为 None
        HTTPException(404): 表不存在或工作区不匹配
        HTTPException(403): 表级权限不足（由 check_action 判定）
    """
    dt = db.query(DataTable).filter(DataTable.id == table_id, DataTable.workspace_id == workspace_id).first()
    if dt is None:
        raise HTTPException(status_code=404, detail="表不存在")
    if action is not None:
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="需要认证",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not check_action(db, dt, user, action):
            raise HTTPException(status_code=403, detail="表级权限不足")
    return dt


def get_row_scope(db: Session, table: DataTable) -> list[dict[str, Any]]:
    """获取表级行级过滤规则（空列表 = 无限制）.

    返回 TablePermission.row_filters 中的条件列表，由上层 query 编译.
    """
    # 按 table_id 查（主键是自增 id，用 db.get(..., table.id) 会取到别的表 → 权限错位）
    perm = db.query(TablePermission).filter(TablePermission.table_id == table.id).first()
    if perm is None or not perm.row_filters:
        return []
    return list(perm.row_filters)


def row_filter_conjunction(db: Session, table: DataTable) -> str:
    """行级过滤条件的连接方式：AND（默认）或 OR."""
    # 按 table_id 查（主键是自增 id，用 db.get(..., table.id) 会取到别的表 → 权限错位）
    perm = db.query(TablePermission).filter(TablePermission.table_id == table.id).first()
    if perm is None:
        return "AND"
    conj = perm.row_filter_type.upper()
    return conj if conj in ("AND", "OR") else "AND"


def get_hidden_field_names(db: Session, table: DataTable, user: User) -> set[str]:
    """获取用户在该表不可见的字段名集合.

    hidden_fields dict 键 = 角色名，值 = 隐藏字段列表.
    当前用户角色对应的列表即为隐藏字段.
    """
    # 按 table_id 查（主键是自增 id，用 db.get(..., table.id) 会取到别的表 → 权限错位）
    perm = db.query(TablePermission).filter(TablePermission.table_id == table.id).first()
    if perm is None or not perm.hidden_fields:
        return set()
    user_role = _get_member_role(db, table, user)
    if user_role is None:
        return set()
    # 键兼容大小写：历史配置里出现过 "VIEWER"（枚举名）与 "viewer"（枚举值）两种写法
    hidden = perm.hidden_fields.get(user_role.value) or perm.hidden_fields.get(user_role.name) or []
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
    from cndb.plugins.workspaces.models import Workspace
    from cndb.plugins.workspaces.permissions import get_member_role as _gmr

    ws = db.get(Workspace, table.workspace_id)
    if ws is None:
        return None
    return _gmr(user, ws, db)


def row_filters_bypass(db: Session, table: DataTable, user: User | None) -> bool:
    """表所有者 / 工作区 OWNER / 超管不受 `TablePermission.row_filters` 限制.

    **口径统一**：`check_action` 的优先级链（表拥有者 → 工作区 OWNER → 表成员授权 →
    角色阈值 → 工作区默认）以及 `hidden_fields`（按角色键，未给 owner 键则不隐藏）都体现
    "所有者拥有全部权限"，而 `row_filters` 原先没有角色维度、对所有人（含 OWNER）生效。
    这里统一为：所有者/超管豁免行过滤，其余成员仍受行级规则约束。

    ``user is None``（内部/后台调用）保持"过滤仍然生效"，避免改变既有内部行为。
    """
    if user is None:
        return False
    if getattr(user, "is_superuser", False):
        return True
    if table.owner_id is not None and table.owner_id == user.id:
        return True
    return _get_member_role(db, table, user) == WorkspaceRole.OWNER


__all__ = [
    "TableAccessPreload",
    "TableAction",
    "apply_field_hiding",
    "apply_field_hiding_rows",
    "check_action",
    "check_workspace_permission",
    "get_hidden_field_names",
    "get_row_scope",
    "get_table_or_404",
    "preload_table_access",
    "row_filter_conjunction",
    "row_filters_bypass",
]
