"""导出侧数据表引用解析（ADR 0045 / ADR 0051）.

文档正文里的 ``{{table:<表ID>|view=<视图ID>|limit=<n>|width=<n>}}`` 独占段落，
预览由前端 ``TableEmbed`` 渲染，导出则由本模块在服务端解析为真实表格：

- 语法与 ``frontend/src/components/Document/tableRef.ts`` 同构（段落级、数字 ID、键值参数）；
- ``width`` 只影响 DOCX / PDF 表格宽度（正文可用宽度 × n%），Markdown 不改写语法；
- 取数复用表 / 视图权限判定与 ``list_rows``（行级权限 + 角色字段隐藏），按**导出发起人**收敛；
- 单个坏引用降级为占位文字，不影响整篇导出。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from cndb.core.errors import CndbError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.services.export.ref_width import DEFAULT_REF_WIDTH, parse_ref_width
from cndb.plugins.tables.services.core.access import (
    TableAction,
    get_hidden_field_names,
    get_table_or_404,
)
from cndb.plugins.tables.services.core.records import list_rows
from cndb.plugins.tables.services.core.view_access import ViewAction, get_view_or_404

#: 导出安全上限（与视图行查询端点 ``limit <= 5000`` 同量级）
MAX_EXPORT_TABLE_ROWS = 5000

#: 与前端同构的段落级占位符正则
TABLE_REF_RE = re.compile(r"^\{\{table:(\d+)((?:\|[a-zA-Z]+=[^|}]*)*)\}\}$")

#: 单个 ``key=value`` 参数
_PARAM_RE = re.compile(r"\|([a-zA-Z]+)=([^|}]*)")


@dataclass(frozen=True)
class TableRefSpec:
    """解析后的数据表引用（``view_id`` 为空表示整表）."""

    table_id: int
    view_id: int | None = None
    width: int = DEFAULT_REF_WIDTH


@dataclass
class ResolvedTable:
    """导出渲染所需的数据表快照；``error`` 非空时降级为占位文字."""

    table_name: str = ""
    view_name: str | None = None
    header: list[str] | None = None
    rows: list[list[str]] | None = None
    total: int = 0
    truncated: bool = False
    error: str | None = None

    @property
    def caption(self) -> str:
        """说明行：``表名 · 视图名 · 共 N 行``，截断时追加提示."""
        parts = [self.table_name]
        if self.view_name:
            parts.append(self.view_name)
        parts.append(f"共 {self.total} 行")
        caption = " · ".join(parts)
        if self.truncated:
            caption += f"（仅导出前 {MAX_EXPORT_TABLE_ROWS} 行）"
        return caption


#: 一次导出内复用的解析器（按 ``(table_id, view_id)`` 记忆化）
TableResolver = Callable[[TableRefSpec], ResolvedTable]


def parse_table_ref_line(line: str) -> TableRefSpec | None:
    """解析独占一行的占位符；不合法返回 None.

    未知参数忽略；``view`` 非数字 / 小于 1 时按整表处理（与前端一致）；
    ``width`` 缺省 / 非整数 / 越界回退 75。
    """
    m = TABLE_REF_RE.match(line.strip())
    if not m:
        return None

    view_id: int | None = None
    width = DEFAULT_REF_WIDTH
    for key, value in _PARAM_RE.findall(m.group(2) or ""):
        if key == "view":
            try:
                parsed = int(value)
            except ValueError:
                continue
            if parsed >= 1:
                view_id = parsed
        elif key == "width":
            width = parse_ref_width(value)
    return TableRefSpec(table_id=int(m.group(1)), view_id=view_id, width=width)


def _cell_text(value: Any) -> str:
    """单元格基础文本化（与预览展示口径一致）."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _markdown_cell(value: Any) -> str:
    """Markdown 单元格：转义 ``|``，换行转 ``<br>``（防止表格结构被破坏）."""
    return _cell_text(value).replace("|", "\\|").replace("\n", "<br>")


def _plain_cell(value: Any) -> str:
    """DOCX / PDF 单元格：换行转空格（由排版器自行折行）."""
    return _cell_text(value).replace("\n", " ")


def _markdown_table(resolved: ResolvedTable) -> str:
    """把解析结果渲染为静态 GFM 表格（含说明行）."""
    header = resolved.header or []
    rows = resolved.rows or []
    lines = [f"*{resolved.caption}*", ""]
    lines.append("| " + " | ".join(_markdown_cell(h) for h in header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_markdown_cell(c) for c in row) + " |")
    return "\n".join(lines)


def _resolve_one(db: Session, workspace_id: int, user: User, spec: TableRefSpec) -> ResolvedTable:
    """按权限取表 / 视图 / 行，归并为可渲染快照（失败降级）."""
    try:
        table = get_table_or_404(spec.table_id, workspace_id, db, user, TableAction.READ)
    except (HTTPException, CndbError):
        return ResolvedTable(error=f"[数据表引用无效：表 #{spec.table_id} 不存在或无访问权限]")

    view = None
    if spec.view_id is not None:
        try:
            view = get_view_or_404(db, table, user, spec.view_id, ViewAction.VIEW_READ)
        except HTTPException:
            return ResolvedTable(error=f"[数据表引用无效：视图 #{spec.view_id} 不存在或无访问权限]")

    hidden = get_hidden_field_names(db, table, user)
    fields = [f for f in table.fields if not f.trashed and not f.hidden and f.name not in hidden]
    fields.sort(key=lambda f: (f.order, f.id))
    if not fields:
        return ResolvedTable(error=f"[数据表引用无效：表 #{spec.table_id} 无可显示字段]")

    header = [f.name for f in fields]
    filters = list(view.filters) if view is not None and view.filters else None
    sorts = list(view.sortings) if view is not None and view.sortings else None
    rows, total = list_rows(
        db.get_bind(),
        table,
        filters=filters,
        filter_logic=view.filter_type if view is not None else "AND",
        sorts=sorts,
        limit=MAX_EXPORT_TABLE_ROWS + 1,
        offset=0,
        db=db,
        user=user,
    )
    truncated = len(rows) > MAX_EXPORT_TABLE_ROWS
    if truncated:
        rows = rows[:MAX_EXPORT_TABLE_ROWS]

    return ResolvedTable(
        table_name=table.name,
        view_name=view.name if view is not None else None,
        header=header,
        rows=[[_plain_cell(row.get(name)) for name in header] for row in rows],
        total=total,
        truncated=truncated,
    )


def make_table_resolver(db: Session, workspace_id: int, user: User) -> TableResolver:
    """构造带记忆化的解析器：同一篇文档内重复引用同一表 / 视图只查一次."""
    cache: dict[tuple[int, int | None], ResolvedTable] = {}

    def resolve(spec: TableRefSpec) -> ResolvedTable:
        key = (spec.table_id, spec.view_id)
        if key not in cache:
            cache[key] = _resolve_one(db, workspace_id, user, spec)
        return cache[key]

    return resolve


def rewrite_markdown_table_refs(content: str, resolver: TableResolver) -> str:
    """把正文中独占段落的占位符替换为静态 GFM 表格（Markdown 导出 / 归档复用）."""
    if not content:
        return content

    parts = re.split(r"(\n\n+)", content)
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            # 段落分隔符原样保留
            out.append(part)
            continue
        spec = parse_table_ref_line(part) if part else None
        if spec is None:
            out.append(part)
        else:
            resolved = resolver(spec)
            out.append(resolved.error or _markdown_table(resolved))
    return "".join(out)


__all__ = [
    "MAX_EXPORT_TABLE_ROWS",
    "ResolvedTable",
    "TableRefSpec",
    "TableResolver",
    "make_table_resolver",
    "parse_table_ref_line",
    "rewrite_markdown_table_refs",
]
