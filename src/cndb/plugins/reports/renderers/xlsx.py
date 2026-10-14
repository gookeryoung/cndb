"""XLSX 渲染器：按 records_by_table 中每张表创建独立 Sheet。"""

from __future__ import annotations

import io
from typing import Any, cast

from cndb.plugins.reports.models import ThemeStyle


def _render_xlsx(rendered_text: str, ctx: dict[str, Any], theme: str = ThemeStyle.MINIMAL.value) -> bytes:
    """XLSX 渲染：按 records_by_table 中每张表创建独立 Sheet.

    theme 参数保留签名统一；XLSX 为数据导向，不应用主题样式.
    """
    _ = theme
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.worksheet.worksheet import Worksheet

    wb = Workbook()
    sheet_created = False
    used_names: set[str] = set()
    sheets: list[tuple[str, list[dict[str, Any]]]] = []

    # 收集所有表的数据：主表 + extra 表（list 而非 dict，避免同名表互相覆盖丢数据）
    # 即使 records 为空也要创建 Sheet（表名有意义时）
    records = ctx.get("records", [])
    table_name = ctx.get("table_name", "Sheet1")
    if table_name and table_name != "Sheet1":
        sheets.append((table_name, records))

    for tname, trecords in ctx.get("records_by_table", {}).items():
        sheets.append((tname, trecords))

    # 去非法 Sheet 名字符，截断到 31 字符
    def _safe_sheet_name(name: str) -> str:
        safe = "".join(c for c in name if c not in "*?:/\\[]").strip()
        return safe[:31] or "Sheet"

    # 同名表（如跨工作区）追加序号后缀，保证不重名也不丢数据
    def _unique_sheet_name(name: str) -> str:
        base = _safe_sheet_name(name)
        candidate = base
        n = 1
        while candidate in used_names:
            suffix = str(n)
            candidate = f"{base[: 31 - len(suffix)]}{suffix}"
            n += 1
        used_names.add(candidate)
        return candidate

    for raw_name, rows_data in sheets:
        sheet_name = _unique_sheet_name(raw_name)
        if not sheet_created:
            ws = cast(Worksheet, wb.active)  # Workbook 始终有 active sheet
            ws.title = _safe_sheet_name(sheet_name)
            sheet_created = True
        else:
            ws = wb.create_sheet(title=_safe_sheet_name(sheet_name))

        # 收集所有字段名
        field_names: list[str] = []
        for r in rows_data:
            for k in r:
                if k not in field_names:
                    field_names.append(k)
        # 过滤系统字段
        skip_keys = {"id", "created_at", "updated_at", "created_by", "updated_by"}
        field_names = [f for f in field_names if f not in skip_keys]

        # 写表头
        for col_idx, fname in enumerate(field_names, start=1):
            cell = ws.cell(row=1, column=col_idx, value=fname)
            cell.font = Font(bold=True)
        # 冻结首行
        ws.freeze_panes = "A2"

        # 写数据
        for row_idx, row_data in enumerate(rows_data, start=2):
            for col_idx, fname in enumerate(field_names, start=1):
                value = row_data.get(fname, "")
                # reportlab/openpyxl 不接受 None，转空串
                if value is None:
                    value = ""
                elif isinstance(value, (list, dict)):
                    value = str(value)
                ws.cell(row=row_idx, column=col_idx, value=value)

        # 自动列宽（估算）
        for col_idx, fname in enumerate(field_names, start=1):
            max_len = len(str(fname))
            for row_data in rows_data:
                v = row_data.get(fname, "")
                if v is not None:
                    vlen = len(str(v))
                    max_len = max(max_len, vlen)
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 60)  # type: ignore[union-attr]

    # 如果没有任何数据，保留默认 Sheet
    if not sheet_created:
        ws = cast(Worksheet, wb.active)  # Workbook 始终有 active sheet
        ws.cell(row=1, column=1, value=rendered_text)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()
