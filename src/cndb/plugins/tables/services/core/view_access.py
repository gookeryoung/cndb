"""视图级访问控制 —— 全部视图接口的**唯一**判定入口.

本模块是 ADR 0003 的 P0 落地：把原先散落在 ``routers/views.py`` 各处的可见性判断
收敛成一个函数与一个查询条件，先修掉越权读取/写入，再为 P2 的 ``visibility``
三档模型预留同一个替换点。

现状可见性仍是**二元**的（暂无 ``visibility`` 列）:

- ``owner_id IS NULL``     → **公共视图**: 表内所有具备 ``READ`` 者可读、可查询
- ``owner_id IS NOT NULL`` → **个人视图**: **仅创建者**可见; 对其他人（含表 owner /
  工作区 OWNER / 超管）一律视同"不存在"（决策 D2）

不变量（``docs/adr/0003-view-visibility-permission-model.md``）:

- **I1 天花板**: 看不到表 ⇒ 看不到任何视图，视图权限永不超过表权限。
- **I5 判定单一**: ``list / get / rows / kanban / calendar / export / reorder / 表详情``
  共用本模块，不再各写各的。
- **I6 无泄露**: 不可见一律 **404**（不暴露存在性）; 可见但无权执行该动作才 **403**。
- **I7 权级单调**: 放宽可见性只增加"谁能看"，不改变"谁能改" ——
  改他人视图的硬门槛恒为表 ``EDIT_VIEWS``。
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, DataView
from cndb.plugins.tables.services.core.access import TableAction, check_action


class ViewAction(StrEnum):
    """视图级动作枚举."""

    VIEW_READ = "VIEW_READ"  # 查看/使用: 列表可见、get、rows/kanban/calendar/export
    VIEW_EDIT = "VIEW_EDIT"  # 改配置: name/filters/sortings/field_options/view_options
    VIEW_MANAGE = "VIEW_MANAGE"  # 删除、设默认、公开分享等管理动作


#: 不可见视图的统一响应文案（404 同时用于"不存在"与"不可见"，避免泄露存在性）
NOT_FOUND_DETAIL = "视图不存在"
#: 可见但无权执行该动作的响应文案
FORBIDDEN_DETAIL = "视图权限不足"


def visible_view_filter(user_id: int) -> ColumnElement[bool]:
    """可见性 SQL 条件 —— 列表/导出/重排/统计等**查询场景**共用.

    与 :func:`is_view_visible` 语义必须保持一致（后者用于已加载对象的 Python 侧过滤）.
    """
    return or_(DataView.owner_id.is_(None), DataView.owner_id == user_id)


def is_view_visible(view: DataView, user_id: int) -> bool:
    """Python 侧可见性判定（用于已经加载好的对象，如 ``dt.views`` 关系属性）."""
    return view.owner_id is None or view.owner_id == user_id


def resolve_view_action(
    db: Session,
    table: DataTable,
    view: DataView,
    user: User,
    action: ViewAction,
) -> bool:
    """判定用户对某个视图能否执行某动作（唯一入口，I5）.

    判定顺序即优先级，不可调换:

    1. **表 READ 天花板**（I1）—— 看不到表就看不到它的任何视图，含自己建的。
    2. **个人视图**（``owner_id`` 非空）—— 仅创建者可通过; 其他人（**含表 owner /
       工作区 OWNER / 超管**）一律 ``False``。这一步必须在任何管理豁免**之前**，
       否则"有 ``EDIT_VIEWS`` 即可改删他人私有视图"（缺陷 ⑤）会复活。
    3. **公共视图** —— 读即表 ``READ``（已由第 1 步保证）; 改/管理需表 ``EDIT_VIEWS``,
       保证放宽"可见性"不会顺手放宽"可改性"（I7）。
    """
    # 1) 天花板
    if not check_action(db, table, user, TableAction.READ):
        return False
    # 2) 个人视图: 只有创建者可见可改（D2）
    if view.owner_id is not None:
        return view.owner_id == user.id
    # 3) 公共视图
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


__all__ = [
    "FORBIDDEN_DETAIL",
    "NOT_FOUND_DETAIL",
    "ViewAction",
    "get_view_or_404",
    "is_view_visible",
    "resolve_view_action",
    "visible_view_filter",
]
