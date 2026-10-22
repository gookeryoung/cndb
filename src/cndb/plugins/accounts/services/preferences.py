"""用户偏好服务 —— 主页收藏视图与自定义排序（ADR 0021 P0）.

全部状态存放在 ``accounts_user.preferences`` JSON，按当前用户隔离：

- ``workspace_order``：主页「我的工作区」同组内的自定义顺序
- ``favorite_views``：主页「我的视图」收藏的视图 id，顺序即展示顺序

核心口径：

- **I1 可见性天花板**：收藏只对「视图可见 ∧ 表可读 ∧ 表未软删」成立，
  读取时剪枝失效 id，且不返回任何元数据；
- **I2 用户隔离**：读写只作用于当前用户；
- **I4 收藏无副作用**：不修改 ``DataView`` 的任何列。

无效 id 一律静默丢弃（不区分"不存在"与"无权限"），避免形成存在性提示。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, DataView
from cndb.plugins.tables.services.core.access import TableAction, get_table_or_404
from cndb.plugins.tables.services.core.view_access import visible_view_filter
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember

#: 收藏视图数量上限：避免 preferences JSON 无界增长，也约束主页首屏聚合成本
MAX_FAVORITE_VIEWS = 50

#: 偏好中需要保持有序数组结构的键
ORDER_KEYS = ("workspace_order", "favorite_views")


def normalize_ids(raw: Iterable[Any] | None) -> list[int]:
    """去重、保序、丢弃非正整数（容忍字符串数字，便于旧数据自愈）."""
    out: list[int] = []
    seen: set[int] = set()
    for value in raw or ():
        try:
            item = int(value)
        except (TypeError, ValueError):
            continue
        if item <= 0 or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def ensure_preferences(user: User) -> None:
    """确保 ``user.preferences`` 含基础结构，缺失 / 类型错误时自动补齐."""
    changed = not isinstance(user.preferences, dict)
    if changed:
        user.preferences = {}
    prefs = user.preferences
    if not isinstance(prefs.get("active_views"), dict):
        prefs["active_views"] = dict[str, Any]()
        changed = True
    for key in ORDER_KEYS:
        if not isinstance(prefs.get(key), list):
            prefs[key] = []
            changed = True
    if changed:
        flag_modified(user, "preferences")


def read_ordered_ids(user: User, key: str) -> list[int]:
    """读取偏好中的有序 id 列表（规范化后返回，不回写）."""
    ensure_preferences(user)
    return normalize_ids(user.preferences.get(key) or [])


# ── 工作区顺序 ────────────────────────────────────────


def set_workspace_order(db: Session, user: User, raw: Iterable[Any] | None) -> list[int]:
    """全量替换工作区顺序；只保留当前用户仍是成员的工作区 id."""
    ids = normalize_ids(raw)
    member_ids: set[int] = set()
    if ids:
        member_ids = {
            int(row[0])
            for row in (
                db.query(WorkspaceMember.workspace_id)
                .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id.in_(ids))
                .all()
            )
        }
    ordered = [item for item in ids if item in member_ids]
    ensure_preferences(user)
    user.preferences["workspace_order"] = ordered
    flag_modified(user, "preferences")
    db.commit()
    return ordered


# ── 收藏视图 ──────────────────────────────────────────


def _readable_table_ids(db: Session, user: User, rows: list[tuple[DataView, DataTable]]) -> set[int]:
    """批量判定收藏候选的表可读性（每个表只判一次）.

    收藏上限 50，这里的 N+1 有界；表权限判定复用 ``get_table_or_404``，
    与所有表接口保持同一口径（工作区角色 / 表成员 / 表级读写门槛）。
    """
    checked: dict[int, bool] = {}
    readable: set[int] = set()
    for _view, table in rows:
        tid = int(table.id)
        if tid not in checked:
            try:
                get_table_or_404(tid, int(table.workspace_id), db, user=user, action=TableAction.READ)
                checked[tid] = True
            except HTTPException:
                checked[tid] = False
        if checked[tid]:
            readable.add(tid)
    return readable


def _visible_view_rows(db: Session, user: User, view_ids: list[int]) -> list[tuple[DataView, DataTable]]:
    """按可见性 + 表未软删取候选视图（SQL 层过滤，不泄露他人私有视图）."""
    if not view_ids:
        return []
    rows = (
        db.query(DataView, DataTable)
        .join(DataTable, DataTable.id == DataView.table_id)
        .filter(
            DataView.id.in_(view_ids),
            DataTable.trashed_at.is_(None),
            visible_view_filter(user.id),
        )
        .all()
    )
    return [(view, table) for view, table in rows]


def filter_favorite_view_ids(db: Session, user: User, view_ids: list[int]) -> list[int]:
    """过滤出「可见 ∧ 表可读」的收藏 id，保持传入顺序."""
    rows = _visible_view_rows(db, user, view_ids)
    readable = _readable_table_ids(db, user, rows)
    valid = {int(view.id) for view, table in rows if int(table.id) in readable}
    return [item for item in view_ids if item in valid]


def set_favorite_views(db: Session, user: User, raw: Iterable[Any] | None) -> list[int]:
    """全量替换收藏视图；无效 id 静默丢弃，超上限 400."""
    ids = normalize_ids(raw)
    if len(ids) > MAX_FAVORITE_VIEWS:
        raise HTTPException(status_code=400, detail=f"最多收藏 {MAX_FAVORITE_VIEWS} 个视图")
    stored = filter_favorite_view_ids(db, user, ids)
    ensure_preferences(user)
    user.preferences["favorite_views"] = stored
    flag_modified(user, "preferences")
    db.commit()
    return stored


def prune_favorite_views(db: Session, user: User) -> list[int]:
    """读取时剪枝失效收藏（视图删除 / 转私有 / 表软删 / 失去表读权限），并回写."""
    raw = read_ordered_ids(user, "favorite_views")
    stored = filter_favorite_view_ids(db, user, raw)
    if stored != raw:
        user.preferences["favorite_views"] = stored
        flag_modified(user, "preferences")
        db.commit()
    return stored


def _count_rules(value: Any) -> int:
    """视图 filters / sortings 的条数（兼容 list / dict / 空值）."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return 0


def load_favorite_view_summaries(db: Session, user: User) -> list[dict[str, Any]]:
    """按收藏顺序返回视图摘要（含表 / 工作区名与筛选排序条数）."""
    ids = prune_favorite_views(db, user)
    if not ids:
        return []
    rows = (
        db.query(DataView, DataTable, Workspace)
        .join(DataTable, DataTable.id == DataView.table_id)
        .join(Workspace, Workspace.id == DataTable.workspace_id)
        .filter(
            DataView.id.in_(ids),
            DataTable.trashed_at.is_(None),
            visible_view_filter(user.id),
        )
        .all()
    )
    readable = _readable_table_ids(db, user, [(view, table) for view, table, _ws in rows])
    by_id: dict[int, dict[str, Any]] = {}
    for view, table, workspace in rows:
        if int(table.id) not in readable:
            continue
        by_id[int(view.id)] = {
            "view_id": int(view.id),
            "name": view.name,
            "view_type": view.view_type,
            "is_default": bool(view.is_default),
            "visibility": view.visibility,
            "filter_count": _count_rules(view.filters),
            "sort_count": _count_rules(view.sortings),
            "table_id": int(table.id),
            "table_name": table.name,
            "workspace_id": int(table.workspace_id),
            "workspace_name": workspace.name,
            "updated_at": view.updated_at,
        }
    return [by_id[item] for item in ids if item in by_id]


__all__ = [
    "MAX_FAVORITE_VIEWS",
    "ensure_preferences",
    "filter_favorite_view_ids",
    "load_favorite_view_summaries",
    "normalize_ids",
    "prune_favorite_views",
    "read_ordered_ids",
    "set_favorite_views",
    "set_workspace_order",
]
