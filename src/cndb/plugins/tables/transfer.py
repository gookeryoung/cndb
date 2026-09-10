"""导入导出 — CSV/XLSX 导入 + JSON/XLSX 导出."""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

from cndb.plugins.tables import records as rec
from cndb.plugins.tables.models import DataTable

logger = logging.getLogger(__name__)


def export_rows_to_json(rows: list[dict[str, Any]]) -> str:
    """把行列表序列化为 JSON 字符串."""
    import json

    return json.dumps(rows, ensure_ascii=False, indent=2, default=str)


def export_rows_to_csv(rows: list[dict[str, Any]]) -> str:
    """把行列表转为 CSV 字符串."""
    if not rows:
        return ""
    buf = io.StringIO()
    fieldnames = list(rows[0].keys())
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def export_rows_to_xlsx(rows: list[dict[str, Any]]) -> bytes:
    """把行列表转为 XLSX 字节串."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Data"
    if not rows:
        return _wb_to_bytes(wb)
    # Header
    fieldnames = list(rows[0].keys())
    ws.append(fieldnames)
    for r in rows:
        ws.append([r.get(k) for k in fieldnames])
    return _wb_to_bytes(wb)


def _wb_to_bytes(wb: Any) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def import_rows_from_json(
    engine: Any,
    table: DataTable,
    json_text: str,
) -> list[int]:
    """从 JSON 文本导入行数据，返回新行 id 列表."""
    import json

    rows = json.loads(json_text)
    if not isinstance(rows, list):
        raise ValueError("JSON 必须是对象数组")
    valid = [r for r in rows if isinstance(r, dict)]
    return rec.bulk_create(engine, table, valid)


def import_rows_from_csv(
    engine: Any,
    table: DataTable,
    csv_text: str,
) -> list[int]:
    """从 CSV 文本导入行数据，返回新行 id 列表."""
    buf = io.StringIO(csv_text)
    reader = csv.DictReader(buf)
    rows = [dict(r) for r in reader]
    return rec.bulk_create(engine, table, rows)


def import_rows_from_xlsx(
    engine: Any,
    table: DataTable,
    xlsx_bytes: bytes,
) -> list[int]:
    """从 XLSX 字节导入行数据，返回新行 id 列表."""
    from openpyxl import load_workbook

    buf = io.BytesIO(xlsx_bytes)
    wb = load_workbook(buf)
    ws = wb.active
    assert ws is not None
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(c) for c in rows[0]]
    data = [dict(zip(header, row, strict=False)) for row in rows[1:] if any(c is not None for c in row)]
    return rec.bulk_create(engine, table, data)


def guess_format_from_filename(filename: str) -> str:
    """根据文件名推断格式（json/csv/xlsx）."""
    lower = filename.lower()
    if lower.endswith(".xlsx"):
        return "xlsx"
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith(".json"):
        return "json"
    raise ValueError(f"无法从文件名推断格式: {filename}")


__all__ = [
    "export_rows_to_csv",
    "export_rows_to_json",
    "export_rows_to_xlsx",
    "guess_format_from_filename",
    "import_rows_from_csv",
    "import_rows_from_json",
    "import_rows_from_xlsx",
]
