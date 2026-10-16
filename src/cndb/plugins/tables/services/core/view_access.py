"""视图级访问控制 —— 全部视图接口的**唯一**判定入口（ADR 0003 P2 落地）.

可见性三档（``DataView.visibility``，新建默认 ``private``）:

- ``table``   继承表权限（表内公开）：读 = 表 ``READ``，改/管理 = 表 ``EDIT_VIEWS``
- ``shared``  指定成员：仅 ``tables_dataviewpermission`` 名单内可见（viewer/editor）
- ``private`` 仅创建者可见；对**一切**非创建者（含表 owner / 工作区 OWNER / 超管）
  一律视同"不存在"（决策 D2）

不变量（``docs/adr/0003-view-visibility-permission-model.md``）:

- **I1 天花板**：看不到表 ⇒ 看不到任何视图，视图权限永不超过表权限。
- **I2 默认收紧**：新建视图默认 ``private``，主动开放才扩大范围。
- **I5 判定单一**：``list / get / rows / kanban / calendar / export / reorder / 表详情``
  共用本模块，不再各写各的。
- **I6 无泄露**：不可见一律 **404**（不暴露存在性）; 可见但无权执行该动作才 **403**。
- **I7 权级单调**：放宽可见性只增加"谁能看"，不改变"谁能改" ——
  改他人视图的硬门槛恒为表 ``EDIT_VIEWS``。
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from enum import StrEnum
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import (
    DataTable,
    DataView,
    DataViewPermission,
    ViewGrantRole,
    ViewGrantSubject,
    ViewVisibility,
)
from cndb.plugins.tables.services.core.access import TableAction, check_action
from cndb.plugins.workspaces.models import WorkspaceRole


class ViewAction(StrEnum):
    """视图级动作枚举."""

    VIEW_READ = "VIEW_READ"  # 查看/使用: 列表可见、get、rows/kanban/calendar/export
    VIEW_EDIT = "VIEW_EDIT"  # 改配置: name/filters/sortings/field_options/view_options/order
    VIEW_MANAGE = "VIEW_MANAGE"  # 改可见性、授权名单、删除、设默认


#: 不可见视图的统一响应文案（404 同时用于"不存在"与"不可见"，避免泄露存在性）
NOT_FOUND_DETAIL = "视图不存在"
#: 可见但无权执行该动作的响应文案
FORBIDDEN_DETAIL = "视图权限不足"
#: 违反 D1 硬约束（每表至少一个 table 档视图）的响应文案
LAST_TABLE_VIEW_DETAIL = "每张表需至少保留一个表内可见视图"

#: 授权角色强弱（同名 subject 多行时取最大）
_GRANT_RANK: dict[str, int] = {ViewGrantRole.VIEWER: 1, ViewGrantRole.EDITOR: 2}

#: 标记"未预取"的哨兵（与"预取结果为 None"区分）
_UNSET: Any = object()


# ── 角色与管理视角 ────────────────────────────────────


def role_codes_for_workspace(db: Session, workspace_id: int, user: User) -> list[str]:
    """当前用户在指定工作区的角色 code（供 ``subject_type='role'`` 的授权匹配）.

    ``shared`` 档的 role 型授权按**工作区角色值**匹配（``owner``/``editor``/``viewer``）——
    与表级 ``TableMember.role`` 的自定义 code 无关，保证批量路径（表列表）只需一次查询。
    """
    from cndb.plugins.workspaces.models import Workspace
    from cndb.plugins.workspaces.permissions import get_member_role

    ws = db.get(Workspace, workspace_id)
    if ws is None:
        return []
    role = get_member_role(user, ws, db)
    return [role.value] if role is not None else []


def is_table_admin(db: Session, table: DataTable, user: User) -> bool:
    """超管 / 表 owner / 工作区 OWNER —— 管理视角（**仅对非 private 档生效**，D2）."""
    if getattr(user, "is_superuser", False):
        return True
    if table.owner_id is not None and table.owner_id == user.id:
        return True
    return _workspace_role_value(db, table.workspace_id, user) == WorkspaceRole.OWNER.value


def _workspace_role_value(db: Session, workspace_id: int, user: User) -> str | None:
    """当前用户在指定工作区的角色值（``owner``/``editor``/``viewer``/``None``）."""
    from cndb.plugins.workspaces.models import Workspace
    from cndb.plugins.workspaces.permissions import get_member_role

    ws = db.get(Workspace, workspace_id)
    if ws is None:
        return None
    role = get_member_role(user, ws, db)
    return role.value if role is not None else None


# ── 可见性查询条件（列表/导出/重排/统计等查询场景） ────


def visible_view_filter(user_id: int, role_codes: Collection[str] = ()) -> ColumnElement[bool]:
    """可见性 SQL 条件（纯函数，无 DB 访问）.

    与 :func:`is_view_visible` 语义必须保持一致（后者用于已加载对象的 Python 侧过滤）:

    - ``table``   档恒可见（调用方已保证表 ``READ``）
    - ``shared``  档需命中名单（``subject_type='user'`` 且 id 相符，或 ``role`` 型命中角色 code）
    - ``private`` 档仅创建者
    """
    grant_exists = exists().where(
        DataViewPermission.view_id == DataView.id,
        or_(
            and_(
                DataViewPermission.subject_type == ViewGrantSubject.USER,
                DataViewPermission.subject_id == str(user_id),
            ),
            and_(
                DataViewPermission.subject_type == ViewGrantSubject.ROLE,
                DataViewPermission.subject_id.in_(list(role_codes)),
            ),
        ),
    )
    return or_(
        DataView.visibility == ViewVisibility.TABLE,
        and_(DataView.visibility == ViewVisibility.SHARED, grant_exists),
        and_(DataView.visibility == ViewVisibility.PRIVATE, DataView.owner_id == user_id),
    )


def view_visibility_filter(db: Session, table: DataTable, user: User) -> ColumnElement[bool]:
    """按 (表, 用户) 求可见性条件 —— 单表场景的便捷入口.

    批量场景（表列表）请复用已预取的工作区角色，直接调用 :func:`visible_view_filter`，
    避免为每个表重复解析角色（N+1）。
    """
    return visible_view_filter(user.id, role_codes_for_workspace(db, table.workspace_id, user))


def is_view_visible(view: DataView, user_id: int, granted_view_ids: Collection[int] = ()) -> bool:
    """Python 侧可见性判定（用于已经加载好的对象，如 ``dt.views`` 关系属性）.

    ``granted_view_ids`` 为当前用户被显式授权（``shared`` 档名单内）的视图 id 集合，
    由 :func:`grants_for_user` 批量预取 —— 缺省空集合即"未授权任何 shared 视图".
    """
    if view.visibility == ViewVisibility.TABLE:
        return True
    if view.visibility == ViewVisibility.PRIVATE:
        return view.owner_id == user_id
    return view.id in granted_view_ids


# ── 授权名单读取 ──────────────────────────────────────


def grants_for_user(
    db: Session,
    view_ids: Sequence[int],
    user_id: int,
    role_codes: Collection[str] = (),
) -> dict[int, str]:
    """批量取「该用户在哪些视图上有授权、角色是什么」→ ``{view_id: 'viewer'|'editor'}``.

    同名主体多行时取最强角色。一次查询，供列表/详情/重排等批量场景复用。
    """
    ids = list(view_ids)
    if not ids:
        return {}
    conds = [
        and_(
            DataViewPermission.subject_type == ViewGrantSubject.USER,
            DataViewPermission.subject_id == str(user_id),
        )
    ]
    if role_codes:
        conds.append(
            and_(
                DataViewPermission.subject_type == ViewGrantSubject.ROLE,
                DataViewPermission.subject_id.in_(list(role_codes)),
            )
        )
    out: dict[int, str] = {}
    rows = db.query(DataViewPermission).filter(DataViewPermission.view_id.in_(ids), or_(*conds)).all()
    for g in rows:
        cur = out.get(int(g.view_id))
        if cur is None or _GRANT_RANK.get(str(g.role), 0) > _GRANT_RANK.get(cur, 0):
            out[int(g.view_id)] = str(g.role)
    return out


def grant_role_for_view(
    db: Session,
    view_id: int,
    user_id: int,
    role_codes: Collection[str] = (),
) -> str | None:
    """单视图的授权角色（``None`` = 名单内没有此人）."""
    return grants_for_user(db, [view_id], user_id, role_codes).get(view_id)


# ── 单一判定入口 ──────────────────────────────────────


def resolve_view_action(
    db: Session,
    table: DataTable,
    view: DataView,
    user: User,
    action: ViewAction,
    *,
    grant_role: Any = _UNSET,
    is_admin: bool | None = None,
) -> bool:
    """判定用户对某个视图能否执行某动作（唯一入口，I5）.

    判定顺序即优先级，不可调换:

    1. **表 READ 天花板**（I1）—— 看不到表就看不到它的任何视图，含自己建的。
    2. **创建者对自己的视图** —— 读写在 0 处已保证可读，此处补齐改/管理。
    3. **私有档对一切非创建者不存在**（D2）—— 含表 owner / 工作区 OWNER / 超管。
       这一步必须在任何管理豁免**之前**，否则"有 ``EDIT_VIEWS`` 即可改删他人私有视图"
       （缺陷 ⑤）会复活。孤儿视图（``private`` + ``owner_id IS NULL``）同样在此判 False。
    4. **管理视角** —— 超管 / 表 owner / 工作区 OWNER，仅对非私有档生效。
    5. **指定共享** —— 名单内 viewer 可读；editor 还需表 ``EDIT_VIEWS`` 才能改。
    6. **继承表权限** —— 读即表 ``READ``（已由第 1 步保证）; 改/管理需表 ``EDIT_VIEWS``（I7）。

    ``grant_role`` / ``is_admin`` 为批量场景的预取出口（避免逐视图重复查询）,
    缺省时各自按需查询，语义完全一致。
    """
    # 1) 天花板
    if not check_action(db, table, user, TableAction.READ):
        return False
    # 2) 创建者
    if view.owner_id is not None and view.owner_id == user.id:
        return True
    # 3) 私有档（D2）
    if view.visibility == ViewVisibility.PRIVATE:
        return False
    # 4) 管理视角（仅非私有档）
    admin = is_table_admin(db, table, user) if is_admin is None else is_admin
    if admin:
        return True
    # 5) 指定共享
    if view.visibility == ViewVisibility.SHARED:
        codes = role_codes_for_workspace(db, table.workspace_id, user)
        grant = grant_role_for_view(db, int(view.id), user.id, codes) if grant_role is _UNSET else grant_role
        if action == ViewAction.VIEW_READ:
            return grant is not None
        if action in (ViewAction.VIEW_EDIT, ViewAction.VIEW_MANAGE):
            # editor 只是"多给了看"，不构成改权旁路（I7）
            return grant == ViewGrantRole.EDITOR and check_action(db, table, user, TableAction.EDIT_VIEWS)
        return False
    # 6) 继承表权限
    if action == ViewAction.VIEW_READ:
        return True
    return check_action(db, table, user, TableAction.EDIT_VIEWS)


def get_view_or_404(
    db: Session,
    table: DataTable,
    user: User,
    view_id: int,
    action: ViewAction = ViewAction.VIEW_READ,
) -> DataView:
    """按 ``view_id`` 取视图并校验动作权限.

    - 不存在 / 不可见 → **404**（统一文案，不区分"没有"与"看不到"，I6）
    - 可见但无权执行该动作 → **403**

    注意调用方须已确认用户对该表具备 ``READ``（通常由 ``get_table_or_404`` 完成），
    本函数仍会独立判定一次天花板，避免漏调用点。
    """
    view = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == table.id).first()
    if view is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
    if not resolve_view_action(db, table, view, user, ViewAction.VIEW_READ):
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
    if action != ViewAction.VIEW_READ and not resolve_view_action(db, table, view, user, action):
        raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)
    return view


# ── 开放范围校验（「最大可放宽至数据表范围内」的落地） ──


def require_can_publish_to_table(db: Session, table: DataTable, user: User, visibility: str) -> None:
    """开放为 ``table`` 档（表内所有人可见）需表 ``EDIT_VIEWS``（决策 D4）.

    ``shared`` / ``private`` 档不做额外校验（``shared`` 只需操作者是创建者，
    由 ``resolve_view_action(VIEW_MANAGE)`` 保证）。
    """
    if visibility != ViewVisibility.TABLE:
        return
    if check_action(db, table, user, TableAction.EDIT_VIEWS):
        return
    raise HTTPException(status_code=403, detail="将视图开放给表内所有人需表视图编辑权限")


def table_view_count(db: Session, table_id: int, exclude_view_id: int | None = None) -> int:
    """该表 ``table`` 档视图数量（可排除某个视图，用于"最后一个不可转私有"判定）."""
    q = db.query(func.count(DataView.id)).filter(
        DataView.table_id == table_id,
        DataView.visibility == ViewVisibility.TABLE,
    )
    if exclude_view_id is not None:
        q = q.filter(DataView.id != exclude_view_id)
    return int(q.scalar() or 0)


def assert_can_change_visibility(
    db: Session,
    table: DataTable,
    view: DataView,
    new_visibility: str,
) -> None:
    """可见性变更的目标档位校验（D1 硬约束：每表至少保留一个 ``table`` 档视图）.

    只有"把最后一个 ``table`` 档视图转走"会被拒绝；其余方向（开放、私有↔指定成员）
    一律放行。删除视图不受此约束（``DELETE`` 是显式销毁动作，与迁移/回导流程冲突）。
    """
    if view.visibility == new_visibility:
        return
    if view.visibility == ViewVisibility.TABLE and table_view_count(db, table.id, exclude_view_id=int(view.id)) == 0:
        raise HTTPException(status_code=400, detail=LAST_TABLE_VIEW_DETAIL)


__all__ = [
    "FORBIDDEN_DETAIL",
    "LAST_TABLE_VIEW_DETAIL",
    "NOT_FOUND_DETAIL",
    "ViewAction",
    "assert_can_change_visibility",
    "get_view_or_404",
    "grant_role_for_view",
    "grants_for_user",
    "is_table_admin",
    "is_view_visible",
    "require_can_publish_to_table",
    "resolve_view_action",
    "role_codes_for_workspace",
    "table_view_count",
    "view_visibility_filter",
    "visible_view_filter",
]
