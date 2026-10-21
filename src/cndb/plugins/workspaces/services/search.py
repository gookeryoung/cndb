"""工作区统一检索 —— 文档全文（FTS5）+ 数据表行/表名.

顶栏搜索框的唯一数据源：一次请求同时给出「数据表」与「文档」两路结果，
由前端按 scope 分组渲染。

数据表侧口径（默认按视图收敛）：
- 调用方带 ``table_id`` + ``view_id``（当前激活的表与视图）时，**只在当前视图范围内检索**：
  视图的 filters 以原逻辑（AND / OR）作为前置条件，再与关键词条件 AND 组合；
- 未带视图上下文时，退化为「工作区全部可读表」，逐表限量扫描；
- 表名 / 描述命中的表单独成一项（前端「数据表」分组里的表级结果）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

#: 单次检索最多扫描的数据表数（避免大工作区把一次搜索放大成 N 次动态表查询）
MAX_TABLES_SCAN = 8
#: 每张表最多返回几行命中
ROWS_PER_TABLE = 3
#: 无视图上下文时，表名命中与行命中共用一个上限
MAX_ROWS_TOTAL = 20


def _readable_tables(db: Session, workspace_id: int, user: Any) -> list[Any]:
    """工作区内当前用户可读的表（与 /tables 列表同口径：批量预取后纯计算判定）."""
    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.tables.services.core.access import TableAction, preload_table_access

    candidates = (
        db.query(DataTable)
        .filter(DataTable.workspace_id == workspace_id, DataTable.trashed == False)  # noqa: E712
        .order_by(DataTable.order, DataTable.id)
        .all()
    )
    if not candidates:
        return []
    preload = preload_table_access(db, candidates, user)
    return [t for t in candidates if preload.check(db, t, user, TableAction.READ)]


def _contains(text: str | None, keyword: str) -> bool:
    return bool(text) and keyword.lower() in str(text).lower()


def _row_title(table: Any, row: dict[str, Any]) -> str:
    """行标题 —— 取字段顺序上第一个非空文本值（与网格首列观感一致）."""
    fields = sorted(
        (f for f in table.fields if not f.trashed),
        key=lambda f: (f.order, f.id),
    )
    for field in fields:
        value = row.get(field.name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    row_id = row.get("id")
    return f"#{row_id}" if row_id is not None else ""


def _row_snippet(table: Any, row: dict[str, Any], keyword: str) -> str:
    """命中片段 —— 优先返回包含关键词的字段值（截断到 80 字符）."""
    for field in sorted(table.fields, key=lambda f: (f.order, f.id)):
        if field.trashed:
            continue
        value = row.get(field.name)
        if isinstance(value, str) and _contains(value, keyword):
            text = value.strip()
            return text if len(text) <= 80 else f"{text[:77]}…"
    return _row_title(table, row)


def _view_scope_filters(db: Session, table: Any, view_id: int, user: Any) -> tuple[list[dict[str, Any]], str, str]:
    """读取当前视图的筛选条件，返回 (filters, logic, 视图名).

    视图不可见 / 不属于该表 / 无筛选条件时返回空条件（等价于整表检索），
    检索不应因视图参数失效而整体报错。
    """
    from cndb.plugins.tables.models import DataView
    from cndb.plugins.tables.services.core.view_access import grants_for_user, is_view_visible

    view = db.get(DataView, view_id)
    if view is None or view.table_id != table.id:
        return [], "AND", ""
    granted = grants_for_user(db, [view.id], user.id)
    if not is_view_visible(view, user.id, granted.keys()):
        return [], "AND", ""
    filters = view.filters or []
    if isinstance(filters, dict):
        filters = [filters]
    logic = (view.filter_type or "AND").upper()
    return [f for f in filters if isinstance(f, dict)], logic, view.name


def _combine_filters(
    view_filters: list[dict[str, Any]],
    view_logic: str,
    keyword: str,
) -> list[dict[str, Any]]:
    """视图条件（保持原 AND/OR 语义）+ 关键词条件，两者 AND 组合."""
    combined: list[dict[str, Any]] = []
    if view_filters:
        combined.append({"__or__" if view_logic == "OR" else "__and__": view_filters})
    combined.append({"field_name": "$query", "value": keyword})
    return combined


def _search_rows_in_table(
    db: Session,
    table: Any,
    keyword: str,
    *,
    user: Any,
    view_id: int | None,
) -> tuple[list[dict[str, Any]], str]:
    """在单张表内检索关键词，返回 (行命中列表, 生效的视图名)."""
    from cndb.plugins.tables.services.core.records import list_rows

    view_filters: list[dict[str, Any]] = []
    view_logic = "AND"
    view_name = ""
    if view_id is not None:
        view_filters, view_logic, view_name = _view_scope_filters(db, table, view_id, user)

    filters = _combine_filters(view_filters, view_logic, keyword)
    try:
        rows, _total = list_rows(
            db.get_bind(),
            table,
            filters=filters,
            # 视图条件已用嵌套分组包好，外层恒 AND
            filter_logic="AND",
            limit=ROWS_PER_TABLE,
            db=db,
            user=user,
        )
    except Exception:  # pragma: no cover - 单表异常不应让整体检索失败
        return [], view_name

    hits = [
        {
            "table_id": table.id,
            "table_name": table.name,
            "row_id": row.get("id"),
            "title": _row_title(table, row),
            "snippet": _row_snippet(table, row, keyword),
        }
        for row in rows
    ]
    return hits, view_name


def search_workspace(
    db: Session,
    workspace_id: int,
    user: Any,
    keyword: str,
    *,
    scope: str = "all",
    table_id: int | None = None,
    view_id: int | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """统一检索入口.

    Args:
        keyword: 关键词（已去空白，非空）。
        scope: ``all`` / ``documents`` / ``tables`` —— 决定跑哪几路。
        table_id / view_id: 当前激活的表与视图；给定时数据表侧只在该视图范围内检索。
        limit: 文档与表级结果各自的上限。
    """
    result: dict[str, Any] = {
        "query": keyword,
        "documents": [],
        "tables": [],
        "rows": [],
        "view": None,
    }

    if scope in ("all", "documents"):
        result["documents"] = _search_documents(db, workspace_id, user, keyword, limit=limit)

    if scope in ("all", "tables"):
        result.update(_search_tables(db, workspace_id, user, keyword, table_id=table_id, view_id=view_id, limit=limit))

    return result


def _search_documents(
    db: Session,
    workspace_id: int,
    user: Any,
    keyword: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    from cndb.plugins.documents.services import search as doc_search
    from cndb.plugins.documents.services.visibility import is_document_admin

    doc_search.ensure_fts_schema(db)
    items, _total = doc_search.search_documents(
        db,
        keyword,
        workspace_id=workspace_id,
        limit=limit,
        viewer_id=user.id,
        # 可见性口径与文档全文搜索一致：非管理员搜不到他人未发布内容
        is_admin=is_document_admin(db, workspace_id, user),
    )
    return [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "title_hit": item.get("title_hit"),
            "summary_hit": item.get("summary_hit"),
            "status": item.get("status"),
            "updated_at": item.get("updated_at"),
        }
        for item in items
    ]


def _search_tables(
    db: Session,
    workspace_id: int,
    user: Any,
    keyword: str,
    *,
    table_id: int | None,
    view_id: int | None,
    limit: int,
) -> dict[str, Any]:
    tables = _readable_tables(db, workspace_id, user)
    if not tables:
        return {"tables": [], "rows": [], "view": None}

    # 当前激活表（表上下文）：数据表侧收敛到该表；否则按表名命中 + 限量全表扫描
    active = next((t for t in tables if table_id is not None and t.id == table_id), None)
    targets = [active] if active is not None else tables[:MAX_TABLES_SCAN]

    table_hits = [
        {"id": t.id, "name": t.name, "description": t.description or ""}
        for t in tables
        if _contains(t.name, keyword) or _contains(t.description, keyword)
    ][:limit]

    row_hits: list[dict[str, Any]] = []
    view_name = ""
    for table in targets:
        hits, name = _search_rows_in_table(
            db,
            table,
            keyword,
            user=user,
            # 只有当前激活表才按视图收敛；顺带扫描的其他表没有视图上下文
            view_id=view_id if active is not None else None,
        )
        if name:
            view_name = name
        row_hits.extend(hits)
        if len(row_hits) >= MAX_ROWS_TOTAL:
            break

    if active is not None:
        view_scope: dict[str, Any] | None = {
            "id": view_id if view_name else None,
            "name": view_name,
            "table_id": active.id,
            "table_name": active.name,
        }
    else:
        view_scope = None

    return {
        "tables": table_hits,
        "rows": row_hits[:MAX_ROWS_TOTAL],
        "view": view_scope,
    }
