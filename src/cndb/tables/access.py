"""表级访问策略链：动作定义、策略协议与链式裁决.

策略链是表域权限的统一入口：动作（TableAction）声明"做什么"，
链上各策略（TableAccessPolicy）独立裁决"能否做"，任一环节拒绝即短路。
后续行级/字段级权限、Token 范围等以新策略环节接入，不改既有调用方.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto

from django.contrib.auth.models import AbstractBaseUser

from cndb.tables.models import DataTable, TablePermission
from cndb.tables.query import RowQuery, compile_filters
from cndb.workspaces.models import Workspace, WorkspaceMember
from cndb.workspaces.permissions import get_member_role, has_role


class TableAction(Enum):
    """表级动作集合：读写分离，为后续行级/字段级扩展预留粒度."""

    READ = auto()
    EDIT_RECORDS = auto()
    EDIT_VIEWS = auto()
    EDIT_SCHEMA = auto()


@dataclass(frozen=True)
class AccessVerdict:
    """策略裁决结果：拒绝时 reason 为对外可见的原因."""

    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class AccessContext:
    """访问上下文：工作区必有，动作落在具体表时才有表."""

    workspace: Workspace
    table: DataTable | None = None


class TableAccessPolicy(ABC):
    """访问策略协议：链上每一环独立裁决."""

    @abstractmethod
    def check(self, user: AbstractBaseUser | None, context: AccessContext, action: TableAction) -> AccessVerdict:
        """对给定用户、上下文与动作给出裁决."""


class WorkspaceRolePolicy(TableAccessPolicy):
    """工作区角色策略：动作须达到该动作的最低角色."""

    _MIN_ROLE: dict[TableAction, str] = {
        TableAction.READ: WorkspaceMember.Role.VIEWER,
        TableAction.EDIT_RECORDS: WorkspaceMember.Role.EDITOR,
        TableAction.EDIT_VIEWS: WorkspaceMember.Role.EDITOR,
        TableAction.EDIT_SCHEMA: WorkspaceMember.Role.EDITOR,
    }
    _DENY_REASON: dict[TableAction, str] = {
        TableAction.READ: "需要工作区成员身份",
        TableAction.EDIT_RECORDS: "需要编辑者及以上权限",
        TableAction.EDIT_VIEWS: "需要编辑者及以上权限",
        TableAction.EDIT_SCHEMA: "需要编辑者及以上权限",
    }

    def check(self, user: AbstractBaseUser | None, context: AccessContext, action: TableAction) -> AccessVerdict:
        """按动作最低角色裁决，非成员一律拒绝."""
        minimum = self._MIN_ROLE[action]
        if has_role(user, context.workspace, minimum):
            return AccessVerdict(True)
        return AccessVerdict(False, self._DENY_REASON[action])


class TableOverridePolicy(TableAccessPolicy):
    """表级角色覆盖策略：表权限对象对动作收紧最低角色，OWNER 豁免."""

    _OVERRIDE_FIELD: dict[TableAction, str] = {
        TableAction.READ: "read_role",
        TableAction.EDIT_RECORDS: "edit_records_role",
        TableAction.EDIT_VIEWS: "edit_views_role",
        TableAction.EDIT_SCHEMA: "edit_schema_role",
    }

    def check(self, user: AbstractBaseUser | None, context: AccessContext, action: TableAction) -> AccessVerdict:
        """表无权限对象或动作未覆盖时放行；覆盖则按覆盖角色裁决，OWNER 豁免."""
        table = context.table
        if table is None:
            return AccessVerdict(True)
        if get_member_role(user, context.workspace) == WorkspaceMember.Role.OWNER:
            return AccessVerdict(True)
        permission = TablePermission.objects.filter(table=table).only(*self._OVERRIDE_FIELD.values()).first()
        if permission is None:
            return AccessVerdict(True)
        override = str(getattr(permission, self._OVERRIDE_FIELD[action]) or "")
        if not override:
            return AccessVerdict(True)
        if has_role(user, context.workspace, override):
            return AccessVerdict(True)
        return AccessVerdict(False, "当前角色不足以访问该表")


# 策略链：按序裁决，任一环节拒绝即短路；后续权限维度以新环节追加
POLICIES: list[TableAccessPolicy] = [WorkspaceRolePolicy(), TableOverridePolicy()]


def check_access(user: AbstractBaseUser | None, context: AccessContext, action: TableAction) -> AccessVerdict:
    """链式裁决入口：遍历策略链，首个拒绝环节的结果即最终结果."""
    for policy in POLICIES:
        verdict = policy.check(user, context, action)
        if not verdict.allowed:
            return verdict
    return AccessVerdict(True)


def check_table_access(user: AbstractBaseUser | None, table: DataTable, action: TableAction) -> AccessVerdict:
    """表级动作裁决便捷入口."""
    return check_access(user, AccessContext(workspace=table.workspace, table=table), action)  # type: ignore[bad-argument-type]


def check_workspace_access(user: AbstractBaseUser | None, workspace: Workspace, action: TableAction) -> AccessVerdict:
    """工作区级动作裁决便捷入口（如建表，表尚不存在）."""
    return check_access(user, AccessContext(workspace=workspace), action)


def _table_permission(table: DataTable) -> TablePermission | None:
    """读取表权限对象，无则返回 None."""
    return TablePermission.objects.filter(table=table).first()


def row_scope(user: AbstractBaseUser | None, table: DataTable) -> RowQuery | None:
    """行级访问范围：表权限配置了行级过滤时编译为 RowQuery（AND 并入业务查询）.

    OWNER 不受行级过滤限制；规则编译失败视为无限制（保存期已校验，此处仅防御）.
    """
    permission = _table_permission(table)
    if permission is None or not permission.row_filters:
        return None
    if get_member_role(user, table.workspace) == WorkspaceMember.Role.OWNER:  # type: ignore[bad-argument-type]
        return None
    where, params = compile_filters(table, permission.row_filters, str(permission.row_filter_type))  # type: ignore[bad-argument-type]
    return RowQuery(where=where, params=params)


def hidden_field_names(user: AbstractBaseUser | None, table: DataTable) -> set[str]:
    """字段级隐藏：返回当前用户角色不可见的字段名集合（OWNER 全可见）."""
    permission = _table_permission(table)
    if permission is None or not permission.hidden_fields:
        return set()
    role = get_member_role(user, table.workspace)  # type: ignore[bad-argument-type]
    if role == WorkspaceMember.Role.OWNER:
        return set()
    hidden: set[str] = set()
    for field_name, minimum in permission.hidden_fields.items():
        if role is None or not has_role(user, table.workspace, str(minimum)):  # type: ignore[bad-argument-type]
            hidden.add(str(field_name))
    return hidden
