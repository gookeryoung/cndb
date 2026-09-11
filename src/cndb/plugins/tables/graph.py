"""表关系图 —— 工作区内 DataTable 之间的 link 字段依赖关系.

核心函数：
- build_table_graph: 构建 {table_id: {依赖的表id集合}} 依赖图
- topological_sort: Kahn 拓扑排序
- get_workspace_dependencies: 工作区依赖详情（含反向依赖）

这些是纯函数，不涉及 HTTP 层.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.tables.models import DataTable

logger = logging.getLogger(__name__)


def build_table_graph(db: Session, workspace_id: int | None = None) -> dict[int, set[int]]:
    """构建表依赖图 {table_id: {依赖的表id集合}}.

    link 字段的 config.target_table_id 就是依赖. 如果 workspace_id 给了只扫描该工作区,
    否则全库扫描.
    """
    query = db.query(DataTable)
    if workspace_id is not None:
        query = query.filter(DataTable.workspace_id == workspace_id, DataTable.trashed.is_(False))
    else:
        query = query.filter(DataTable.trashed.is_(False))

    tables = query.all()
    graph: dict[int, set[int]] = {t.id: set() for t in tables}

    for table in tables:
        for field in table.fields:
            if field.trashed or field.field_type != "link":
                continue
            target_tid = field.config.get("target_table_id") if field.config else None
            if target_tid is not None and target_tid in graph:
                graph[table.id].add(target_tid)

    return graph


def topological_sort(graph: dict[int, set[int]]) -> list[int]:
    """Kahn 拓扑排序，返回安全复制顺序（被依赖的先返回）.

    检测到环时返回空列表并记录 warning.
    """
    in_degree: dict[int, int] = dict.fromkeys(graph, 0)
    reverse: dict[int, set[int]] = defaultdict(set)

    for node, deps in graph.items():
        for dep in deps:
            if dep in graph:
                reverse[dep].add(node)
                in_degree[node] += 1

    queue: deque[int] = deque(node for node, deg in in_degree.items() if deg == 0)
    result: list[int] = []

    while queue:
        node = queue.popleft()
        result.append(node)
        for dependent in reverse[node]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(graph):
        logger.warning("拓扑排序检测到环")
        return []

    return result


def get_workspace_dependencies(db: Session, workspace_id: int) -> dict[str, Any]:
    """返回工作区依赖详情."""
    graph = build_table_graph(db, workspace_id)

    reverse: dict[int, set[int]] = {tid: set() for tid in graph}
    for tid, deps in graph.items():
        for dep in deps:
            if dep in reverse:
                reverse[dep].add(tid)

    link_fields: list[dict[str, Any]] = []
    tables = (
        db.query(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed.is_(False),
        )
        .all()
    )

    for table in tables:
        for field in table.fields:
            if field.trashed or field.field_type != "link":
                continue
            target_tid = field.config.get("target_table_id") if field.config else None
            link_fields.append(
                {
                    "table_id": table.id,
                    "table_name": table.name,
                    "field_id": field.id,
                    "field_name": field.name,
                    "target_table_id": target_tid,
                }
            )

    return {
        "forward": {tid: sorted(deps) for tid, deps in graph.items()},
        "reverse": {tid: sorted(deps) for tid, deps in reverse.items()},
        "link_fields": link_fields,
    }


__all__ = [
    "build_table_graph",
    "get_workspace_dependencies",
    "topological_sort",
]
