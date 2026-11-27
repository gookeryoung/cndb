"""数据表关联图聚合（需求 0187 P0）.

关系**不需要新表**：表间引用已由 ``link`` 字段完整表达
（``config.target_table_id`` 指向目标表，物理关系存独立关联表）。
本模块只读元数据，把它聚合成前端可直接渲染的 ``{nodes, edges}``：

- 节点 = 当前用户**可读**的非回收表（H64：判定复用 ``preload_table_access``，
  不可读的表既不建节点也不做边端点，否则等于泄漏表的存在性 H17）；
- 边 = 未回收的 ``link`` 字段（``lookup`` 是同一关系的投影列，不建边，只在边上
  记 ``reference_field_count`` —— 同一关系画两遍会让图变噪声）；
- 自关联（树 / WBS 的 ``parent_field``）不画自环，改标节点 ``self_loop=true``；
- 指向**其他工作区**或**本工作区已回收表**的边不返回目标表名，聚合为虚拟节点
  （负 id，与文档图谱 broken 虚拟节点同范式），避免跨区/回收站的存在性外泄；
- 节点上限默认 500，超出 ``truncated=true``；指向「可读但落在窗口外」的边计入
  ``edges_out_of_view``（0182 C2：不统计会让中心表看起来像孤岛）；
- 聚合结果按 ``(workspace_id, user_id, max_nodes)`` 缓存 30s，写路径显式失效
  （0182 C1：只靠 TTL 会让用户以为「刚建的关联没生效」）。
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable, TableGroup
from cndb.plugins.tables.services.core.access import TableAction, preload_table_access

#: 节点上限：与文档图谱（0168 C6）同量级，超过 500 张表的力导向图已读不出结论
LINK_GRAPH_MAX_NODES = 500

#: 聚合结果 TTL（秒）
_LINK_GRAPH_CACHE_TTL_SECONDS = 30.0
#: 缓存条目上限（过期即清理，防长跑进程累积）
_LINK_GRAPH_CACHE_MAX_ENTRIES = 256

#: 虚拟节点 id 基数：真实表 id 恒为正，负数留作虚拟节点，永不与真实节点冲突
_EXTERNAL_NODE_ID = -1
_TRASHED_NODE_ID = -2

LINK_FIELD_TYPE = "link"

#: 缓存：键 (workspace_id, user_id, max_nodes) → (写入时刻, payload)
_link_graph_cache: dict[tuple[int, int, int], tuple[float, dict[str, Any]]] = {}


# ── 缓存 ───────────────────────────────────────────────


def reset_link_graph_cache() -> None:
    """清空全部缓存（测试与运维用）."""
    _link_graph_cache.clear()


def invalidate_link_graph_cache(workspace_id: int) -> None:
    """按工作区失效缓存条目（不清整表）.

    一个工作区改字段不应把其他工作区的图缓存清空 —— 与文档图谱
    ``invalidate_link_graph_cache`` 同口径。
    """
    for key in [k for k in _link_graph_cache if k[0] == workspace_id]:
        _link_graph_cache.pop(key, None)


def _prune_link_graph_cache(now: float) -> None:
    """清过期条目，并兜底夹住条目上限."""
    for key in [k for k, (stamp, _) in _link_graph_cache.items() if now - stamp >= _LINK_GRAPH_CACHE_TTL_SECONDS]:
        _link_graph_cache.pop(key, None)
    while len(_link_graph_cache) > _LINK_GRAPH_CACHE_MAX_ENTRIES:
        oldest = min(_link_graph_cache, key=lambda k: _link_graph_cache[k][0])
        _link_graph_cache.pop(oldest, None)


# ── 聚合 ───────────────────────────────────────────────


def _readable_tables(db: Session, workspace_id: int, user: User) -> list[DataTable]:
    """工作区内当前用户可读的非回收表（按 order / id 排序，判定口径与表列表一致）."""
    candidates = list(
        db.execute(
            select(DataTable)
            .where(DataTable.workspace_id == workspace_id, DataTable.trashed.is_(False))
            .order_by(DataTable.order.asc(), DataTable.id.asc())
        )
        .scalars()
        .all()
    )
    if not candidates:
        return []
    preload = preload_table_access(db, candidates, user)
    return [t for t in candidates if preload.check(db, t, user, TableAction.READ)]


def _build_payload(
    db: Session,
    workspace_id: int,
    user: User,
    *,
    max_nodes: int,
) -> dict[str, Any]:
    readable = _readable_tables(db, workspace_id, user)
    total = len(readable)
    shown = readable[:max_nodes]
    truncated = total > len(shown)

    # 节点按 id 建索引：边只连「当前窗口内」的节点，窗口外走 edges_out_of_view
    node_ids = {t.id for t in shown}
    readable_ids = {t.id for t in readable}

    # 分组名：一次查回，避免逐表 N+1
    group_ids = {t.group_id for t in shown if t.group_id is not None}
    group_names: dict[int, str] = {}
    if group_ids:
        for gid, gname in db.execute(select(TableGroup.id, TableGroup.name).where(TableGroup.id.in_(group_ids))).all():
            # 「未分组」占位行不对外展示名字（与表列表口径一致）
            group_names[int(gid)] = "" if gname.startswith("__") else str(gname)

    # 字段：一次查回「窗口内表的全部未回收字段」。
    # 不查全库 link 字段 —— 关联目标只能从源表出发，窗口外的源表本来就不画。
    field_counts: dict[int, int] = {}
    link_fields: list[tuple[int, DataField]] = []
    lookup_ref_counts: dict[int, int] = {}
    if node_ids:
        for field in db.execute(
            select(DataField).where(
                DataField.trashed.is_(False),
                DataField.table_id.in_(node_ids),
            )
        ).scalars():
            field_counts[field.table_id] = field_counts.get(field.table_id, 0) + 1
            if field.field_type == LINK_FIELD_TYPE:
                link_fields.append((field.table_id, field))
            elif field.field_type == "lookup":
                via_id = (field.config or {}).get("via_link_field_id")
                if isinstance(via_id, int):
                    lookup_ref_counts[via_id] = lookup_ref_counts.get(via_id, 0) + 1

    # 目标表：跨工作区 / 已回收 / 不存在一律走虚拟节点，不返回名字
    target_ids = {
        fid for _, f in link_fields for fid in [(f.config or {}).get("target_table_id")] if isinstance(fid, int)
    }
    target_tables: dict[int, DataTable] = {}
    if target_ids:
        for t in db.execute(select(DataTable).where(DataTable.id.in_(target_ids))).scalars().all():
            target_tables[t.id] = t

    # lookup 引用字段计数：按 via_link_field_id 聚合（引用字段挂在关联字段下）
    ref_counts = lookup_ref_counts

    # 分组归属：节点带 group_id / group_name，供前端图例按分组着色
    table_group: dict[int, tuple[int | None, str]] = {
        t.id: (t.group_id, group_names.get(t.group_id, "") if t.group_id else "") for t in shown
    }

    edges: list[dict[str, Any]] = []
    self_loop_tables: set[int] = set()
    external_tables: set[int] = set()
    trashed_tables: set[int] = set()
    out_of_view = 0

    for source_id, field in link_fields:
        config = field.config or {}
        target_id = config.get("target_table_id")
        if not isinstance(target_id, int):
            continue
        ref_count = ref_counts.get(field.id, 0)
        multiple = bool(config.get("multiple", True))

        if target_id == source_id:
            # 自关联（树 / WBS 的父字段）：画自环没有信息量，改成节点徽标
            self_loop_tables.add(source_id)
            continue

        target = target_tables.get(target_id)
        if target is not None and target.workspace_id != workspace_id and not target.trashed:
            external_tables.add(source_id)
            edges.append(
                {
                    "id": field.id,
                    "field_name": field.name,
                    "source": source_id,
                    "target": _EXTERNAL_NODE_ID,
                    "multiple": multiple,
                    "reference_field_count": ref_count,
                    "target_state": "other_workspace",
                }
            )
            continue
        if target is None or target.trashed:
            trashed_tables.add(source_id)
            edges.append(
                {
                    "id": field.id,
                    "field_name": field.name,
                    "source": source_id,
                    "target": _TRASHED_NODE_ID,
                    "multiple": multiple,
                    "reference_field_count": ref_count,
                    "target_state": "trashed",
                }
            )
            continue
        # 目标表在本工作区且存活：可能不可读，也可能落在节点窗口外
        if target_id not in readable_ids:
            # 目标存在但当前用户读不到：按 H17 不暴露，聚合成虚拟节点
            trashed_tables.add(source_id)
            edges.append(
                {
                    "id": field.id,
                    "field_name": field.name,
                    "source": source_id,
                    "target": _TRASHED_NODE_ID,
                    "multiple": multiple,
                    "reference_field_count": ref_count,
                    "target_state": "restricted",
                }
            )
            continue
        if target_id not in node_ids:
            out_of_view += 1
            continue
        edges.append(
            {
                "id": field.id,
                "field_name": field.name,
                "source": source_id,
                "target": target_id,
                "multiple": multiple,
                "reference_field_count": ref_count,
                "target_state": "ok",
            }
        )

    in_degree: dict[int, int] = {}
    out_degree: dict[int, int] = {}
    for edge in edges:
        out_degree[edge["source"]] = out_degree.get(edge["source"], 0) + 1
        if edge["target"] > 0:
            in_degree[edge["target"]] = in_degree.get(edge["target"], 0) + 1

    nodes: list[dict[str, Any]] = [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "group_id": table_group.get(t.id, (None, ""))[0],
            "group_name": table_group.get(t.id, (None, ""))[1],
            "field_count": field_counts.get(t.id, 0),
            "in_degree": in_degree.get(t.id, 0),
            "out_degree": out_degree.get(t.id, 0),
            "self_loop": t.id in self_loop_tables,
            "virtual": False,
        }
        for t in shown
    ]

    # 虚拟节点按需追加：只有真的存在对应边时才画，避免空节点
    if external_tables:
        nodes.append(
            {
                "id": _EXTERNAL_NODE_ID,
                "name": "其他工作区的表",
                "description": "关联目标位于其他工作区，不展示表名",
                "group_id": None,
                "group_name": "",
                "field_count": 0,
                "in_degree": sum(1 for e in edges if e["target"] == _EXTERNAL_NODE_ID),
                "out_degree": 0,
                "self_loop": False,
                "virtual": True,
            }
        )
    if trashed_tables:
        nodes.append(
            {
                "id": _TRASHED_NODE_ID,
                "name": "已删除 / 不可访问的表",
                "description": "关联目标已进回收站、已删除或当前无权读取",
                "group_id": None,
                "group_name": "",
                "field_count": 0,
                "in_degree": sum(1 for e in edges if e["target"] == _TRASHED_NODE_ID),
                "out_degree": 0,
                "self_loop": False,
                "virtual": True,
            }
        )

    return {
        "nodes": nodes,
        "edges": edges,
        "total": total,
        "truncated": truncated,
        "edges_out_of_view": out_of_view,
    }


def build_link_graph(
    db: Session,
    workspace_id: int,
    user: User,
    *,
    max_nodes: int = LINK_GRAPH_MAX_NODES,
) -> dict[str, Any]:
    """工作区数据表关联图：可读表为节点、``link`` 字段为边（需求 0187 C1–C6）."""
    cache_key = (workspace_id, user.id, max_nodes)
    now = time.monotonic()
    cached = _link_graph_cache.get(cache_key)
    if cached is not None and now - cached[0] < _LINK_GRAPH_CACHE_TTL_SECONDS:
        return cached[1]

    payload = _build_payload(db, workspace_id, user, max_nodes=max_nodes)
    _prune_link_graph_cache(now)
    _link_graph_cache[cache_key] = (now, payload)
    return payload


__all__ = [
    "LINK_GRAPH_MAX_NODES",
    "build_link_graph",
    "invalidate_link_graph_cache",
    "reset_link_graph_cache",
]
