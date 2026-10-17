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
from cndb.plugins.tables.services.core.access import TableAccessPreload, TableAction, check_action
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

#: 标记"未预取"的哨兵（与"预取结果为 None"区分）
_UNSET: Any = object()


# ── 管理视角 ──────────────────────────────────────────


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


def visible_view_filter(user_id: int) -> ColumnElement[bool]:
    """可见性 SQL 条件（纯函数，无 DB 访问）.

    与 :func:`is_view_visible` 语义必须保持一致（后者用于已加载对象的 Python 侧过滤）:

    - **创建者**对自己的视图恒可见（I4）—— 必须显式列出：``shared`` 档的创建者不在
      自己的授权名单里，只按"名单命中"判定会让创建者看不到自己刚共享出去的视图
    - ``table``   档恒可见（调用方已保证表 ``READ``）
    - ``shared``  档需命中名单（``subject_type='user'`` 且 id 相符）
    - ``private`` 档仅创建者（由第一条覆盖；孤儿视图 ``owner_id IS NULL`` 对所有人不可见）
    """
    user_grant_exists = exists().where(
        DataViewPermission.view_id == DataView.id,
        DataViewPermission.subject_type == ViewGrantSubject.USER,
        DataViewPermission.subject_id == str(user_id),
    )
    return or_(
        DataView.owner_id == user_id,
        DataView.visibility == ViewVisibility.TABLE,
        and_(DataView.visibility == ViewVisibility.SHARED, user_grant_exists),
    )


def is_view_visible(view: DataView, user_id: int, granted_view_ids: Collection[int] = ()) -> bool:
    """Python 侧可见性判定（用于已经加载好的对象，如 ``dt.views`` 关系属性）.

    ``granted_view_ids`` 为当前用户被显式授权（``shared`` 档名单内）的视图 id 集合，
    由 :func:`grants_for_user` 批量预取 —— 缺省空集合即"未授权任何 shared 视图".
    语义与 :func:`visible_view_filter` 一致：**创建者优先**，其后才是档位与名单。
    """
    if view.owner_id is not None and view.owner_id == user_id:
        return True
    if view.visibility == ViewVisibility.TABLE:
        return True
    if view.visibility == ViewVisibility.PRIVATE:
        return False  # 非创建者的 private（含孤儿）一律不可见（D2）
    return view.id in granted_view_ids


# ── 授权名单读取 ──────────────────────────────────────


def grants_for_user(db: Session, view_ids: Sequence[int], user_id: int) -> dict[int, str]:
    """批量取「该用户在哪些视图上有授权、角色是什么」→ ``{view_id: 'viewer'|'editor'}``.

    一次查询，供列表/详情/重排等批量场景复用。唯一键 ``(view_id, subject_type, subject_id)``
    保证每个视图至多命中一条记录，因此无需再比较角色强弱。
    """
    ids = list(view_ids)
    if not ids:
        return {}
    rows = (
        db.query(DataViewPermission)
        .filter(
            DataViewPermission.view_id.in_(ids),
            DataViewPermission.subject_type == ViewGrantSubject.USER,
            DataViewPermission.subject_id == str(user_id),
        )
        .all()
    )
    return {int(g.view_id): str(g.role) for g in rows}


def grant_role_for_view(db: Session, view_id: int, user_id: int) -> str | None:
    """单视图的授权角色（``None`` = 名单内没有此人）."""
    return grants_for_user(db, [view_id], user_id).get(view_id)


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
        grant = grant_role_for_view(db, int(view.id), user.id) if grant_role is _UNSET else grant_role
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


# ── 共享名单（``shared`` 档，ADR 0003 §4 / §6） ─────────


def assert_grantee_in_table_scope(
    db: Session,
    table: DataTable,
    operator: User,
    target_user: User | None,
    role: str,
) -> None:
    """校验授权对象是否落在「数据表范围内」（ADR 0003 §4，逐条校验、任一不过即 422）.

    这是"最大可放宽至数据表范围内"的落地：共享只能给**本工作区成员**，且对方必须
    对该表有 ``READ``；想把编辑权给出去，对方还必须先有该表 ``EDIT_VIEWS`` ——
    即生效权 = min(视图授权, 表权限)，名单本身永不构成提权旁路（I1 / I7）。
    """
    if target_user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if int(target_user.id) == int(operator.id):
        raise HTTPException(status_code=400, detail="无需给自己授权（创建者天然可见）")
    if not _is_workspace_member(db, table.workspace_id, int(target_user.id)):
        raise HTTPException(status_code=422, detail="只能共享给本工作区成员")
    if not check_action(db, table, target_user, TableAction.READ):
        raise HTTPException(status_code=422, detail="该成员无此表查看权限，无法共享视图")
    if str(role) == ViewGrantRole.EDITOR and not check_action(db, table, target_user, TableAction.EDIT_VIEWS):
        raise HTTPException(status_code=422, detail="该成员无此表视图编辑权限")


def _is_workspace_member(db: Session, workspace_id: int, user_id: int) -> bool:
    from cndb.plugins.workspaces.models import WorkspaceMember

    return (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
        .first()
        is not None
    )


def _access_preloads_for_users(
    db: Session,
    table: DataTable,
    user_ids: Sequence[int],
) -> dict[int, TableAccessPreload]:
    """为一批用户各建一份**预取好**的表权限上下文（3 次查询，与人数无关）.

    用于共享名单 / 可授权成员列表：需要逐人判定表 ``READ`` / ``EDIT_VIEWS``，
    但绝不能逐人 ``check_action``（每人 ~3 次查询 → N+1）。
    """
    from cndb.plugins.tables.models import TableMember, TablePermission
    from cndb.plugins.workspaces.models import WorkspaceMember

    ids = [int(i) for i in user_ids]
    if not ids:
        return {}
    roles: dict[int, Any] = {
        int(uid): role
        for uid, role in db.query(WorkspaceMember.user_id, WorkspaceMember.role)
        .filter(WorkspaceMember.workspace_id == table.workspace_id, WorkspaceMember.user_id.in_(ids))
        .all()
    }
    members: dict[int, Any] = {
        int(m.user_id): m
        for m in db.query(TableMember).filter(TableMember.table_id == table.id, TableMember.user_id.in_(ids)).all()
    }
    perm = db.query(TablePermission).filter(TablePermission.table_id == table.id).first()
    perms = {int(table.id): perm} if perm is not None else {}
    out: dict[int, TableAccessPreload] = {}
    for uid in ids:
        member = members.get(uid)
        out[uid] = TableAccessPreload(
            member_role=roles.get(uid),
            members={int(table.id): member} if member is not None else {},
            perms=perms,
        )
    return out


def _load_users(db: Session, user_ids: Sequence[int]) -> dict[int, User]:
    ids = [int(i) for i in user_ids]
    if not ids:
        return {}
    return {int(u.id): u for u in db.query(User).filter(User.id.in_(ids)).all()}


def _parse_user_id(subject_id: str) -> int | None:
    try:
        return int(subject_id)
    except (TypeError, ValueError):
        return None


def grantee_counts(db: Session, view_ids: Sequence[int]) -> dict[int, int]:
    """批量取每个视图的授权人数 → ``{view_id: n}``（列表页展示「已共享 N 人」）."""
    ids = [int(i) for i in view_ids]
    if not ids:
        return {}
    rows = (
        db.query(DataViewPermission.view_id, func.count(DataViewPermission.id))
        .filter(DataViewPermission.view_id.in_(ids))
        .group_by(DataViewPermission.view_id)
        .all()
    )
    return {int(r[0]): int(r[1]) for r in rows}


def list_view_grants(db: Session, table: DataTable, view: DataView) -> list[dict[str, Any]]:
    """该视图的授权名单（含用户信息与当前是否仍有效）.

    名单主体只有**成员**一种（``subject_type='user'``）—— 按工作区角色共享的
    ``role`` 型授权已于 ADR 0003 D6 移除（从未有写入端点，生产数据零依赖）。
    """
    rows = (
        db.query(DataViewPermission)
        .filter(
            DataViewPermission.view_id == view.id,
            DataViewPermission.subject_type == ViewGrantSubject.USER,
        )
        .all()
    )
    parsed: list[tuple[DataViewPermission, int]] = []
    for g in rows:
        uid = _parse_user_id(str(g.subject_id))
        if uid is not None:
            parsed.append((g, uid))
    if not parsed:
        return []
    users = _load_users(db, [uid for _, uid in parsed])
    preloads = _access_preloads_for_users(db, table, list(users))
    out: list[dict[str, Any]] = []
    for g, uid in parsed:
        user = users.get(uid)
        available = (
            user is not None
            and uid in preloads
            and preloads[uid].check(db, table, user, TableAction.READ)
            and (str(g.role) != ViewGrantRole.EDITOR or preloads[uid].check(db, table, user, TableAction.EDIT_VIEWS))
        )
        out.append(
            {
                "user_id": uid,
                "username": user.username if user is not None else "",
                "nickname": (user.nickname or "") if user is not None else "",
                "role": str(g.role),
                # editor 授权在对方失去表 EDIT_VIEWS 后自动降级为"不可改"（实时求值）
                "available": bool(available),
            }
        )
    # editor 优先，再按用户名，最后按 id（稳定排序，便于前端 diff）
    out.sort(key=lambda r: (r["role"] != ViewGrantRole.EDITOR, r["username"], r["user_id"]))
    return out


def set_view_grant(
    db: Session,
    table: DataTable,
    view: DataView,
    operator: User,
    target_user: User,
    role: str,
) -> DataViewPermission:
    """新增 / 更新一条成员授权（不含 commit）.

    调用方须已确认 ``VIEW_MANAGE`` 且视图当前为 ``shared`` 档。
    """
    if str(role) not in tuple(ViewGrantRole):
        raise HTTPException(status_code=422, detail="授权角色只能是 viewer 或 editor")
    assert_grantee_in_table_scope(db, table, operator, target_user, role)

    row = (
        db.query(DataViewPermission)
        .filter(
            DataViewPermission.view_id == view.id,
            DataViewPermission.subject_type == ViewGrantSubject.USER,
            DataViewPermission.subject_id == str(target_user.id),
        )
        .first()
    )
    if row is None:
        row = DataViewPermission(
            view_id=int(view.id),
            subject_type=ViewGrantSubject.USER,
            subject_id=str(int(target_user.id)),
            role=str(role),
            granted_by_id=int(operator.id),
        )
        db.add(row)
    else:
        row.role = str(role)
        row.granted_by_id = int(operator.id)
    return row


def revoke_view_grant(db: Session, view: DataView, target_user_id: int) -> bool:
    """收回一条成员授权；返回是否确有删除（不含 commit）."""
    row = (
        db.query(DataViewPermission)
        .filter(
            DataViewPermission.view_id == view.id,
            DataViewPermission.subject_type == ViewGrantSubject.USER,
            DataViewPermission.subject_id == str(int(target_user_id)),
        )
        .first()
    )
    if row is None:
        return False
    db.delete(row)
    return True


def replace_view_grants(
    db: Session,
    table: DataTable,
    view: DataView,
    operator: User,
    members: Sequence[Any],
) -> None:
    """全量替换共享名单（``POST /views/{id}/visibility`` 的 ``members`` 语义）.

    ``members`` 为 ``ViewMemberInput`` 序列（``user_id`` / ``role``）。**先逐条校验再
    落库**：任何一条不合法（非本工作区成员 / 无表 ``READ`` / editor 无表 ``EDIT_VIEWS``）
    即 422，不做部分写入。未出现在名单里的既有授权会被收回 —— 这是"全量替换"的定义。
    """
    wanted: dict[int, str] = {}
    for item in members:
        uid = int(item.user_id if hasattr(item, "user_id") else item[0])
        role = str(item.role if hasattr(item, "role") else item[1])
        wanted[uid] = role

    users = _load_users(db, list(wanted))
    for uid, role in wanted.items():
        assert_grantee_in_table_scope(db, table, operator, users.get(uid), role)

    # 收回不在新名单里的
    for g in (
        db.query(DataViewPermission)
        .filter(
            DataViewPermission.view_id == view.id,
            DataViewPermission.subject_type == ViewGrantSubject.USER,
        )
        .all()
    ):
        uid = _parse_user_id(str(g.subject_id))
        if uid is None or uid not in wanted:
            db.delete(g)

    for uid, role in wanted.items():
        set_view_grant(db, table, view, operator, users[uid], role)


def shareable_members(
    db: Session,
    table: DataTable,
    operator: User,
    view: DataView | None = None,
) -> list[dict[str, Any]]:
    """可被授权者的精简列表（成员选择器数据源，ADR 0003 §4）.

    = 本工作区成员 ∧ 对该表有 ``READ``，排除操作者本人与视图创建者（二者本就全权）。
    只暴露"谁可以被授权"（id / 昵称 / 是否有表 ``EDIT_VIEWS``），不暴露任何视图，
    因此与 D2「私有视图对一切非创建者不可见」不冲突。
    """
    from cndb.plugins.workspaces.models import WorkspaceMember

    rows = (
        db.query(WorkspaceMember.user_id, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .filter(WorkspaceMember.workspace_id == table.workspace_id, User.is_active.is_(True))
        .all()
    )
    users: dict[int, User] = {int(uid): u for uid, u in rows}
    # 表 owner 若不在工作区成员表里（历史数据），仍应可选 —— 他天然拥有全部表权限
    if table.owner_id is not None and int(table.owner_id) not in users:
        users.update(_load_users(db, [int(table.owner_id)]))

    preloads = _access_preloads_for_users(db, table, list(users))
    excluded = {int(operator.id)}
    if view is not None and view.owner_id is not None:
        excluded.add(int(view.owner_id))

    out: list[dict[str, Any]] = []
    for uid, user in users.items():
        if uid in excluded:
            continue
        preload = preloads.get(uid)
        if preload is None or not preload.check(db, table, user, TableAction.READ):
            continue
        out.append(
            {
                "user_id": uid,
                "username": user.username,
                "nickname": user.nickname or "",
                "can_edit_views": preload.check(db, table, user, TableAction.EDIT_VIEWS),
            }
        )
    out.sort(key=lambda r: (r["username"], r["user_id"]))
    return out


__all__ = [
    "FORBIDDEN_DETAIL",
    "LAST_TABLE_VIEW_DETAIL",
    "NOT_FOUND_DETAIL",
    "ViewAction",
    "assert_can_change_visibility",
    "assert_grantee_in_table_scope",
    "get_view_or_404",
    "grant_role_for_view",
    "grantee_counts",
    "grants_for_user",
    "is_table_admin",
    "is_view_visible",
    "list_view_grants",
    "replace_view_grants",
    "require_can_publish_to_table",
    "resolve_view_action",
    "revoke_view_grant",
    "set_view_grant",
    "shareable_members",
    "table_view_count",
    "visible_view_filter",
]
