"""渲染上下文装配：表记录读取、link/lookup 扁平化与渲染超时保护。"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User

# 渲染超时保护（秒）
RENDER_TIMEOUT = 10


# ── 渲染器签名：renderer(rendered_text: str, ctx: dict[str, Any]) -> bytes ──


def _flatten_for_report(records: list[dict[str, Any]], table: Any) -> None:
    """把行记录中 link/lookup 等展示型字段扁平化为可读字符串（原地修改）.

    list_rows 返回的 link 字段是 [{"id", "value"}] 摘要列表、lookup 字段可能是列表，
    前端网格 UI 需要这个结构，但 Jinja2 模板里 `{{ row.部门 }}` 直接渲染对象会出
    `[object Object]`。这里把它们展开：link 取 .value 用逗号拼接，lookup 列表同样拼接。
    """
    from cndb.plugins.tables.services.core.links import is_link_field

    link_names = {f.name for f in table.active_fields() if is_link_field(f)}
    lookup_names = {f.name for f in table.active_fields() if f.field_type == "lookup"}
    if not link_names and not lookup_names:
        return
    for row in records:
        for name in link_names:
            raw = row.get(name)
            if isinstance(raw, list):
                parts = [str(item.get("value", f"#{item.get('id')}")) for item in raw if isinstance(item, dict)]
                row[name] = ", ".join(parts) if parts else ""
        for name in lookup_names:
            raw = row.get(name)
            if isinstance(raw, list):
                row[name] = ", ".join(str(v) for v in raw if v is not None)


def _load_table_records(
    db: Session,
    table_id: int,
    user: User,
    view: Any | None = None,
) -> tuple[Any, list[dict[str, Any]]]:
    """加载指定表的元数据和行数据（带 READ 权限校验 + 字段隐藏）.

    list_rows 默认 limit=100，报表必须拿到完整数据，这里按页循环取全量。
    view 非 None 时按该视图的 filters/filter_type/sortings 取数（动态报表数据源）；
    view 为 None 时取全表数据（保持旧行为）。
    返回 (DataTable, records_list)，records 是扁平 dict 列表，link/lookup 字段已展开为可读字符串。
    """
    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.tables.services.core.access import TableAction, check_action
    from cndb.plugins.tables.services.core.records import list_rows

    table = db.get(DataTable, table_id)
    if not table:
        raise HTTPException(status_code=404, detail=f"数据表不存在 id={table_id}")
    if not check_action(db, table, user, TableAction.READ):
        raise HTTPException(status_code=403, detail="无权访问该数据表")
    page_size = 500
    offset = 0
    records: list[dict[str, Any]] = []
    while True:
        rows, total = list_rows(
            db.bind,
            table,
            include_trashed=False,
            filters=(view.filters or None) if view is not None else None,
            filter_logic=view.filter_type if view is not None else "AND",
            sorts=(view.sortings or None) if view is not None else None,
            offset=offset,
            limit=page_size,
            db=db,
            user=user,
        )
        records.extend(r.get("data", r) for r in rows)
        offset += len(rows)
        if not rows or offset >= total:
            break
    _flatten_for_report(records, table)
    return table, records


# ── 超时保护 ─────────────────────────────────────────


def _render_with_timeout(jinja_tmpl: Any, ctx: dict[str, Any], timeout: int = RENDER_TIMEOUT) -> str:
    """在线程中执行 Jinja2 渲染，支持超时中断.

    注意：Python 无法真正中断线程，超时后返回 TimeoutError 标记，
    但线程会继续运行到自然结束（这是 GIL 限制）。此处配合 SandboxedEnvironment
    保证即使超时线程也无法访问危险资源。
    """
    result: dict[str, str | Exception] = {}

    def _run() -> None:
        try:
            result["ok"] = jinja_tmpl.render(**ctx)
        except Exception as exc:  # pragma: no cover - 异常由调用方处理
            result["err"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        raise TimeoutError(f"模板渲染超时（{timeout}s），可能存在无限循环")
    if "err" in result:
        exc = result["err"]
        if isinstance(exc, Exception):
            raise exc
        raise RuntimeError(str(exc))
    return str(result.get("ok", ""))
