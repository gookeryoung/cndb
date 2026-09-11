"""导入导出 — CSV/XLSX 导入 + JSON/XLSX 导出.

link 字段约定：
- 导出：行响应中 link 值为 [{"id", "value"}] 摘要列表，序列化为分号分隔的目标行 id 串；
- 导入：CSV/XLSX 中 link 列的分号分隔 id 串（或单个 id）解析回列表写入关联表.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

from cndb.plugins.tables import records as rec
from cndb.plugins.tables.links import is_link_field
from cndb.plugins.tables.models import DataTable

logger = logging.getLogger(__name__)


def _serialize_link_value(value: Any) -> Any:
    """导出时把 link 摘要列表压成分号分隔 id 串，其余原样."""
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return ";".join(str(item.get("id", "")) for item in value)
    return value


def _exportable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """行响应统一做导出序列化（目前仅 link 摘要列表）."""
    return [{k: _serialize_link_value(v) for k, v in row.items()} for row in rows]


def _parse_link_import_value(table: DataTable, row: dict[str, Any]) -> dict[str, Any]:
    """导入时把 link 列的字符串/单值归一为 id 列表."""
    link_names = {f.name for f in table.active_fields() if is_link_field(f)}
    if not link_names:
        return row
    result = dict(row)
    for name in link_names:
        value = result.get(name)
        if value is None:
            continue
        if isinstance(value, list):
            continue
        text = str(value).strip()
        if not text:
            result[name] = []
            continue
        try:
            result[name] = [int(part) for part in text.replace(",", ";").split(";")]
        except ValueError as exc:
            raise ValueError(f"link 字段 {name} 的导入值必须是分号分隔的行 id: {value!r}") from exc
    return result


def export_rows_to_json(rows: list[dict[str, Any]]) -> str:
    """把行列表序列化为 JSON 字符串."""
    import json

    return json.dumps(rows, ensure_ascii=False, indent=2, default=str)


def export_rows_to_csv(rows: list[dict[str, Any]]) -> str:
    """把行列表转为 CSV 字符串（link 摘要序列化为分号分隔 id）."""
    rows = _exportable_rows(rows)
    if not rows:
        return ""
    buf = io.StringIO()
    fieldnames = list(rows[0].keys())
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def export_rows_to_xlsx(rows: list[dict[str, Any]]) -> bytes:
    """把行列表转为 XLSX 字节串（link 摘要序列化为分号分隔 id）."""
    from openpyxl import Workbook

    rows = _exportable_rows(rows)
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
    db: Any = None,
) -> list[int]:
    """从 JSON 文本导入行数据，返回新行 id 列表."""
    import json

    rows = json.loads(json_text)
    if not isinstance(rows, list):
        raise ValueError("JSON 必须是对象数组")
    valid = [_parse_link_import_value(table, r) for r in rows if isinstance(r, dict)]
    return rec.bulk_create(engine, table, valid, db=db)


def import_rows_from_csv(
    engine: Any,
    table: DataTable,
    csv_text: str,
    db: Any = None,
) -> list[int]:
    """从 CSV 文本导入行数据，返回新行 id 列表."""
    buf = io.StringIO(csv_text)
    reader = csv.DictReader(buf)
    rows = [_parse_link_import_value(table, dict(r)) for r in reader]
    return rec.bulk_create(engine, table, rows, db=db)


def import_rows_from_xlsx(
    engine: Any,
    table: DataTable,
    xlsx_bytes: bytes,
    db: Any = None,
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
    data = [
        _parse_link_import_value(table, dict(zip(header, row, strict=False)))
        for row in rows[1:]
        if any(c is not None for c in row)
    ]
    return rec.bulk_create(engine, table, data, db=db)


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
