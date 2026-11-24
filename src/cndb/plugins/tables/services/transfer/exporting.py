"""行导出序列化 — JSON/CSV/XLSX 导出、link 值序列化、公式注入防护."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping
from typing import Any, cast

from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.core.links import is_link_field


def _serialize_link_value(value: Any, *, use_business_key: bool = False) -> Any:
    """导出时把 link 摘要列表压成分号分隔串，其余原样.

    use_business_key=False（默认）压成分号分隔的行 id，保持既有行为；
    use_business_key=True 改用摘要里的业务文本，让导出文件可读、可回灌 ——
    link 摘要项含 ``match``（匹配字段值，导入解析依据）与 ``value``（显示字段值），
    优先取 ``match``：这样「导出→修改→导入」按匹配字段回灌不会错位。
    """
    if isinstance(value, list) and value and isinstance(value[0], dict):
        parts: list[str] = []
        for item in value:
            raw = None
            if use_business_key:
                raw = item.get("match")
                if raw is None or raw == "":
                    raw = item.get("value")
            if raw is None or raw == "":
                raw = item.get("id", "")
            parts.append(str(raw))
        return ";".join(parts)
    return value


#: 导出口径排除的系统 / 派生键：并发版本与软删元数据不进导出（ADR 0140 C7 / ADR 0139）
_EXPORT_EXCLUDED_KEYS = frozenset({"_etag", "_rev", "_trashed", "_trashed_at", "_trashed_by", "_trashed_by_name"})


def _strip_export_excluded(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """剔出系统 / 派生键（`_etag` / `_rev` / 软删元数据），其余原样（ADR 0140 C7）."""
    return [{k: v for k, v in row.items() if k not in _EXPORT_EXCLUDED_KEYS} for row in rows]


def _exportable_rows(
    rows: list[dict[str, Any]],
    link_display: Mapping[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """行响应统一做导出序列化.

    link_display 为 {字段名: 是否导出业务文本} 映射；缺省（None）时 link 列仍导出 id，
    与历史行为一致。仅对映射里为 True 的列改用业务文本（匹配字段值）。
    """
    display = link_display or {}
    return [
        {
            k: _serialize_link_value(v, use_business_key=bool(display.get(k)))
            for k, v in row.items()
            if k not in _EXPORT_EXCLUDED_KEYS
        }
        for row in rows
    ]


def _ordered_fieldnames(
    rows: list[dict[str, Any]],
    columns: list[str] | None,
) -> list[str]:
    """按数据表字段展示顺序（``DataField.order``）排列导出头.

    ``columns`` 由调用方传入 ``table.active_fields()`` 的字段名；只保留当前行真实
    存在的列（隐藏字段、无物理列的派生列可能不在行里），其余未声明的键追加在末尾，
    不静默丢列。``columns`` 缺省时回退行内原有顺序（保持旧行为）。
    """
    if not rows:
        return []
    present = list(rows[0].keys())
    if not columns:
        return present
    present_set = set(present)
    ordered = [name for name in columns if name in present_set]
    ordered_set = set(ordered)
    ordered.extend(name for name in present if name not in ordered_set)
    return ordered


def _ordered_rows(
    rows: list[dict[str, Any]],
    columns: list[str] | None,
) -> list[dict[str, Any]]:
    """按字段展示顺序重建行 dict（JSON 导出用；dict 插入顺序即 JSON 键顺序）."""
    if not columns or not rows:
        return rows
    fieldnames = _ordered_fieldnames(rows, columns)
    return [{name: row[name] for name in fieldnames if name in row} for row in rows]


def _parse_link_import_value(
    table: DataTable,
    row: dict[str, Any],
    link_names: set[str] | None = None,
) -> dict[str, Any]:
    """导入时把 link 列的字符串/单值归一为 id 列表.

    ``link_names`` 可由批量调用方预先计算，避免逐行扫描字段表。
    """
    if link_names is None:
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


def export_rows_to_json(
    rows: list[dict[str, Any]],
    *,
    link_display: Mapping[str, bool] | None = None,
    columns: list[str] | None = None,
) -> str:
    """把行列表序列化为 JSON 字符串.

    link_display 指定哪些 link 列导出业务文本；缺省时保持结构化原值（[{id,value}]）。
    columns 指定导出列顺序（字段展示顺序）；缺省时保持行内原顺序。
    """
    # 始终过滤：系统 / 派生键（`_etag` / `_rev` / 软删元数据）不进任何导出（ADR 0140 C7）；
    # link 结构化保留原口径——只有显式要求业务文本时才压成分号串
    if link_display:
        rows = _exportable_rows(rows, link_display)
    else:
        rows = _strip_export_excluded(rows)
    if columns:
        rows = _ordered_rows(rows, columns)
    return json.dumps(rows, ensure_ascii=False, indent=2, default=str)


# ── 公式注入防护 ──────────────────────────────────────

# Excel/WPS 打开 CSV 时会把以这些前缀开头的单元格当作公式求值（OWASP 缓解：前缀 '）
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_csv_cell(value: Any) -> Any:
    """CSV 公式注入防护：以危险前缀开头的字符串值前加 ``'`` 前缀.

    仅处理 str —— int/float/bool/date 等序列化后为纯字面量，不会被当作公式.
    """
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def _fix_xlsx_formula_cells(ws: Any, row_idx: int) -> None:
    """把 XLSX 某行中以 ``=`` 开头被 openpyxl 判为公式的单元格强制回字符串类型.

    openpyxl 对 ``=`` 开头字符串自动设 ``data_type='f'``，Excel 打开即执行；
    赋值后强制 ``data_type='s'`` 值原样保留。``+``/``-``/``@`` 开头在 XLSX 中
    本就存为字符串类型，无需处理.
    """
    for cell in ws[row_idx]:
        if isinstance(cell.value, str) and cell.value.startswith("="):
            cell.data_type = "s"


def export_rows_to_csv(
    rows: list[dict[str, Any]],
    *,
    link_display: Mapping[str, bool] | None = None,
    columns: list[str] | None = None,
) -> str:
    """把行列表转为 CSV 字符串（link 摘要序列化为分号分隔串）.

    columns 指定导出列顺序（字段展示顺序）；缺省时保持行内原顺序。
    空行列表 + columns 时只输出表头（空表导出仍有列结构）。
    公式注入防护：以 ``=``/``+``/``-``/``@``/Tab/CR 开头的字符串单元格（含表头）
    前加 ``'`` 前缀，避免 Excel/WPS 打开时被当作公式求值.
    """
    rows = _exportable_rows(rows, link_display)
    if not rows:
        # 空表也要输出表头：列结构可见，导出的文件还能直接当回灌模板
        if not columns:
            return ""
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=[_sanitize_csv_cell(c) for c in columns])
        writer.writeheader()
        return buf.getvalue()
    fieldnames = _ordered_fieldnames(rows, columns)
    buf = io.StringIO()
    # 表头一并转义；已知列名同步替换为转义后列名，未知列名保留交由 extrasaction 处理
    key_map = {k: _sanitize_csv_cell(k) for k in fieldnames}
    writer = csv.DictWriter(buf, fieldnames=list(key_map.values()))
    writer.writeheader()
    for row in rows:
        writer.writerow({key_map.get(k, k): _sanitize_csv_cell(v) for k, v in row.items()})
    return buf.getvalue()


def _to_excel_value(value: Any) -> Any:
    """把任意 Python 值安全转为 openpyxl 可接受的单元格值.

    openpyxl 仅接受 ``int``/``float``/``str``/``bool``/``None``/``datetime``/
    ``date``/``Decimal``；其他类型（``list``/``set``/``tuple``/``dict``/``UUID``
    等）在此做降级序列化：

    - list/set/tuple → 分号分隔字符串（multiselect、link 等场景）
    - dict → JSON 字符串
    - UUID → str
    - 其余未知类型 → str(value) 兜底
    """
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import UUID

    if value is None or isinstance(value, (str, int, float, bool, datetime, date, Decimal)):
        return value
    if isinstance(value, (list, tuple, set)):
        if not value:
            return ""
        return ";".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def export_rows_to_xlsx(
    rows: list[dict[str, Any]],
    *,
    link_display: Mapping[str, bool] | None = None,
    columns: list[str] | None = None,
) -> bytes:
    """把行列表转为 XLSX 字节串（link 摘要序列化为分号分隔串）.

    columns 指定导出列顺序（字段展示顺序）；缺省时保持行内原顺序。
    空行列表 + columns 时只输出表头（空表导出仍有列结构）。
    公式注入防护：``=`` 开头字符串单元格强制回字符串类型，Excel 打开不被求值.
    类型归一：openpyxl 不接受的类型（list/set/tuple/dict/UUID 等）自动降级序列化.
    """
    from openpyxl import Workbook
    from openpyxl.worksheet.worksheet import Worksheet

    rows = _exportable_rows(rows, link_display)
    wb = Workbook()
    ws = cast(Worksheet, wb.active)  # Workbook 始终有 active sheet
    ws.title = "Data"
    if not rows:
        # 空表也要输出表头（与 CSV 口径一致）
        if columns:
            ws.append(list(columns))
            _fix_xlsx_formula_cells(ws, 1)
        return _wb_to_bytes(wb)
    # Header
    fieldnames = _ordered_fieldnames(rows, columns)
    ws.append(fieldnames)
    _fix_xlsx_formula_cells(ws, 1)
    for r in rows:
        ws.append([_to_excel_value(r.get(k)) for k in fieldnames])
        _fix_xlsx_formula_cells(ws, ws.max_row)
    return _wb_to_bytes(wb)


def _wb_to_bytes(wb: Any) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
