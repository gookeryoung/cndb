"""分析复合数据源（ADR 0159 P1）：跨工作区关联（left / inner join）.

口径（与 ADR 0159 一致，H62 是核心风险点）：

- **左表驱动**：`left` / `inner` 都由左行集迭代，右表未匹配行**不会**出现在结果里
  （否则「右表某行是否存在」会被反推出来）；
- **两侧各自同权**：左 / 右分别经表 `READ` 或 `resolve_link` + 行级 + 字段隐藏，
  任一不可读 → 整体 fail-closed（H61）；
- **关联键必须可见**：隐藏字段作键 → 400（防侧信道，D7）；
- **列名**：同名冲突时左 `left.字段` / 右 `right.字段`；右表关联键列不重复输出（L4）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status

from cndb.plugins.analytics.services.compute import scan_limit

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from cndb.plugins.accounts.models import User
    from cndb.plugins.analytics.schemas import AnalyticsSource, JoinSide

LEFT_PREFIX = "left."
RIGHT_PREFIX = "right."


def _side_parts(side: JoinSide) -> tuple[str, int]:
    """(kind, id)：`table` / `link` 二选一（schema 已校验）."""
    if side.table_id is not None:
        return "table", int(side.table_id)
    return "link", int(side.link_id or 0)


def _side_rows(
    db: Session,
    user: User,
    workspace_id: int,
    side: JoinSide,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """取一侧的行与可见字段；链接侧经 `resolve_link`（失效 404 / 无读权 403）."""
    kind, ident = _side_parts(side)
    if kind == "table":
        from cndb.plugins.analytics.services.compute import scan_rows
        from cndb.plugins.tables.services.core.access import (
            TableAction,
            get_hidden_field_names,
            get_table_or_404,
        )

        table = get_table_or_404(ident, workspace_id, db, user=user, action=TableAction.READ)
        rows, total, truncated = scan_rows(db, table, user)
        # 表侧同样按字段隐藏裁剪（与链接侧同一口径，H58 / ADR 0159 C3）
        hidden = get_hidden_field_names(db, table, user)
        fields = [field.name for field in table.active_fields() if field.name not in hidden]
        return rows[:limit], fields, truncated or total > limit

    from cndb.plugins.workspaces.services.links import link_fields, link_rows, resolve_link

    resolved = resolve_link(db, user, workspace_id=workspace_id, link_id=ident)
    fields = [field["name"] for field in link_fields(db, user, resolved)]
    payload = link_rows(db, user, resolved, limit=limit)
    rows = payload.get("rows") or []
    truncated = int(payload.get("total") or 0) > len(rows)
    return rows, fields, truncated


def validate_join_source(db: Session, user: User, workspace_id: int, source: AnalyticsSource) -> list[str]:
    """校验 join 数据源，返回**输出字段清单**（左字段 + 右字段，冲突加前缀）.

    Raises:
        HTTPException: 结构非法 400；两侧不可读 404/403（fail-closed）。
    """
    if source.left is None or source.right is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="关联数据源需要左右两侧")
    if not source.on:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="关联数据源至少需要一个关联键")
    if source.join_type not in ("left", "inner"):  # pragma: no cover - schema Literal 已收窄
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="关联类型只支持 left / inner")

    left_rows, left_fields, _ = _side_rows(db, user, workspace_id, source.left, limit=1)
    right_rows, right_fields, _ = _side_rows(db, user, workspace_id, source.right, limit=1)
    del left_rows, right_rows  # 仅为取字段（行在 join_rows 里重新取）

    for key in source.on:
        if key.left_field not in left_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"左表关联键不可用（不存在或被隐藏）: {key.left_field}",
            )
        if key.right_field not in right_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"右表关联键不可用（不存在或被隐藏）: {key.right_field}",
            )
    return output_fields(left_fields, right_fields, [key.right_field for key in source.on])


def output_fields(left_fields: list[str], right_fields: list[str], right_key_fields: list[str]) -> list[str]:
    """输出字段清单（L4）：冲突列双侧加前缀；右表关联键列不重复输出."""
    conflicts = set(left_fields) & set(right_fields)
    names = [f"{LEFT_PREFIX}{name}" if name in conflicts else name for name in left_fields]
    for name in right_fields:
        if name in right_key_fields:
            continue  # 关联键只保留左表列（值相等，避免重复）
        names.append(f"{RIGHT_PREFIX}{name}" if name in conflicts else name)
    return names


def join_rows(
    db: Session,
    user: User,
    workspace_id: int,
    source: AnalyticsSource,
) -> tuple[list[dict[str, Any]], list[str], int, bool]:
    """执行 left / inner join，返回 (rows, field_names, total, truncated).

    - 左表驱动：只迭代左行，右表未匹配行不会出现；`left` 未匹配时右列补 ``None``；
    - 扫描额度共享：左 / 右各自最多取 ``scan_limit()``，任一被截断即标 truncated。
    """
    field_names = validate_join_source(db, user, workspace_id, source)
    assert source.left is not None and source.right is not None
    budget = scan_limit()

    left_rows, left_fields, left_truncated = _side_rows(db, user, workspace_id, source.left, limit=budget)
    right_rows, right_fields, right_truncated = _side_rows(db, user, workspace_id, source.right, limit=budget)

    conflicts = set(left_fields) & set(right_fields)
    right_key_fields = [key.right_field for key in (source.on or [])]

    def left_name(name: str) -> str:
        return f"{LEFT_PREFIX}{name}" if name in conflicts else name

    def right_name(name: str) -> str:
        return f"{RIGHT_PREFIX}{name}" if name in conflicts else name

    keys = source.on or []
    index: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in right_rows:
        signature = tuple(row.get(key.right_field) for key in keys)
        index.setdefault(signature, []).append(row)

    out: list[dict[str, Any]] = []
    next_id = 1
    inner = source.join_type == "inner"
    for left_row in left_rows:
        signature = tuple(left_row.get(key.left_field) for key in keys)
        matches = index.get(signature) or []
        if not matches:
            if inner:
                continue
            item: dict[str, Any] = {"id": next_id}
            for name in left_fields:
                item[left_name(name)] = left_row.get(name)
            for name in right_fields:
                if name in right_key_fields:
                    continue
                item[right_name(name)] = None
            next_id += 1
            out.append(item)
            continue
        for right_row in matches:
            item = {"id": next_id}
            for name in left_fields:
                item[left_name(name)] = left_row.get(name)
            for name in right_fields:
                if name in right_key_fields:
                    continue
                item[right_name(name)] = right_row.get(name)
            next_id += 1
            out.append(item)
    return out, field_names, len(out), left_truncated or right_truncated


__all__ = [
    "LEFT_PREFIX",
    "RIGHT_PREFIX",
    "join_rows",
    "output_fields",
    "validate_join_source",
]
