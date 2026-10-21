"""工作区统一检索 —— 文档全文（FTS5）+ 数据表行/表名.

顶栏搜索框的唯一数据源：一次请求同时给出「数据表」与「文档」两路结果，
由前端按 scope 分组渲染。

数据表侧口径：
- ``scope=all``（工作区）：扫描**全部可读表**，不按当前视图收敛（当前表只做排序优先）；
- ``scope=tables``（数据表）：有表上下文时收敛到该表，并按激活视图收敛；
  无表上下文时扫描全部可读表；
- 结果走进程内短 TTL 缓存（见 ADR 0015），写路径通过统一事件 / 批量写入口失效。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from cndb.core.cache import cache_key, search_cache

#: 搜索结果缓存 TTL（秒）：单行写由事件即时失效，批量写用短 TTL 兜底
SEARCH_CACHE_TTL_SECONDS = 15
#: 每张表最多返回几行命中
ROWS_PER_TABLE = 3
#: 一次检索最多返回的行命中（面板展示预算）
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
    """统一检索入口（带进程内结果缓存）.

    Args:
        keyword: 关键词（已去空白，非空）。
        scope: ``all`` / ``documents`` / ``tables``。
        table_id: 当前激活表；仅 ``scope=tables`` 用于收敛，``scope=all`` 仅排序优先。
        view_id: 当前激活视图；仅 ``scope=tables`` 生效。
        limit: 文档与表级结果各自的上限。
    """
    # scope=all 时 view_id 不参与计算，键里归一为 0，避免无意义的缓存分片
    effective_view_id = view_id if scope == "tables" else None
    key = cache_key(
        "search",
        workspace_id,
        getattr(user, "id", 0),
        scope,
        table_id or 0,
        effective_view_id or 0,
        limit,
        keyword,
    )
    cached = search_cache.get(key)
    if cached is not None:
        return cached

    result = _search_workspace(
        db,
        workspace_id,
        user,
        keyword,
        scope=scope,
        table_id=table_id,
        view_id=effective_view_id,
        limit=limit,
    )
    # 空结果同样缓存：关键词无命中是全表扫描的最坏情况，最需要重用
    search_cache.set(key, result, SEARCH_CACHE_TTL_SECONDS)
    return result


def _search_workspace(
    db: Session,
    workspace_id: int,
    user: Any,
    keyword: str,
    *,
    scope: str,
    table_id: int | None,
    view_id: int | None,
    limit: int,
) -> dict[str, Any]:
    """实际检索（无缓存）."""
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
        result.update(
            _search_tables(
                db, workspace_id, user, keyword, table_id=table_id, view_id=view_id, limit=limit, scope=scope
            )
        )

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
    scope: str = "tables",
) -> dict[str, Any]:
    tables = _readable_tables(db, workspace_id, user)
    if not tables:
        return {"tables": [], "rows": [], "view": None}

    active = next((t for t in tables if table_id is not None and t.id == table_id), None)
    if scope == "tables" and active is not None:
        # 数据表范围：收敛到当前表，并按当前激活视图的筛选范围检索
        targets = [active]
        scoped_view_id = view_id
    else:
        # 工作区范围（或无表上下文）：覆盖全部可读表；当前表只排在最前，不做视图收敛，
        # 否则「没打开某个视图」时视图外的内容会整体搜不到（ADR 0015）
        targets = ([active] + [t for t in tables if t is not active]) if active is not None else tables
        scoped_view_id = None

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
            # 只有「数据表范围 + 当前激活表」才按视图收敛
            view_id=scoped_view_id if table is active else None,
        )
        if name:
            view_name = name
        row_hits.extend(hits)
        if len(row_hits) >= MAX_ROWS_TOTAL:
            break

    view_scope: dict[str, Any] | None = None
    if scope == "tables" and active is not None:
        view_scope = {
            "id": view_id if view_name else None,
            "name": view_name,
            "table_id": active.id,
            "table_name": active.name,
        }

    return {
        "tables": table_hits,
        "rows": row_hits[:MAX_ROWS_TOTAL],
        "view": view_scope,
    }
