"""数据导入导出：行数据与 CSV/JSON 格式互转.

CSV 约定：首行为字段名表头，值以文本表示——
空串表示空值，布尔用 true/false，多选以分号分隔，日期用 ISO 格式；
导入时文本经字段类型 parse 钩子还原为原生值再走行数据校验。
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from cndb.tables import records
from cndb.tables.field_types import FieldTypeError, get_field_type
from cndb.tables.models import DataField, DataTable

# 多选字段在 CSV 中的分隔符
MULTI_DELIMITER = ";"
# 错误行报告上限（防止超大坏文件刷屏）
_MAX_ERRORS = 100


class InvalidImportError(Exception):
    """导入结构非法（空文件/表头未知或不可见字段）."""


@dataclass(frozen=True)
class ImportResult:
    """导入结果：成功行数与错误行报告（行号从 1 起，仅数据行）."""

    created: int
    errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedImport:
    """CSV 解析结果：可校验行（附原始行号）与解析期错误行报告."""

    rows: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


def _to_csv_text(value: Any) -> str:
    """把行值序列化为 CSV 单元格文本."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return MULTI_DELIMITER.join(str(item) for item in value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def export_csv(rows: Sequence[Mapping[str, Any]], field_names: Sequence[str]) -> str:
    """行列表导出为 CSV 文本（首行为字段名表头）."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(field_names)
    for row in rows:
        writer.writerow([_to_csv_text(row.get(name)) for name in field_names])
    return buffer.getvalue()


def export_json(rows: Sequence[Mapping[str, Any]], field_names: Sequence[str]) -> list[dict[str, Any]]:
    """行列表导出为 JSON 结构：仅保留导出字段，值保持原生类型."""
    return [{name: row.get(name) for name in field_names} for row in rows]


def parse_csv(text: str) -> list[dict[str, str | None]]:
    """解析 CSV 文本为字典列表（首行为表头），短行缺失列值为 None."""
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _parse_cell(text: str, field: DataField) -> Any:
    """把 CSV 单元格文本还原为可校验的原生值（多选拆分，其余走类型解析钩子）."""
    field_type = get_field_type(str(field.field_type))
    if str(field.field_type) == "multi_select":
        return [item for item in text.split(MULTI_DELIMITER) if item]
    return field_type.parse_query_value(text, field.config)  # type: ignore[bad-argument-type]


def parse_import_rows(table: DataTable, text: str, allowed: set[str]) -> ParsedImport:
    """解析 CSV 文本并还原为原生值行.

    表头未知或不可见字段整体拒绝；行内值解析失败记为该行错误并跳过。
    """
    if not text.strip():
        raise InvalidImportError("导入文件为空")
    raw_rows = parse_csv(text)
    if not raw_rows:
        raise InvalidImportError("导入文件没有数据行")
    header = set(raw_rows[0])
    fields_by_name = {str(f.name): f for f in table.active_fields()}
    for name in header:
        if name is None or str(name) not in allowed:
            raise InvalidImportError(f"表头包含未知或不可见字段: {name}")
    rows: list[tuple[int, dict[str, Any]]] = []
    errors: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rows, start=1):
        parsed: dict[str, Any] = {}
        try:
            for name, cell in raw.items():
                if name is None or cell is None or cell == "":
                    continue
                parsed[str(name)] = _parse_cell(cell, fields_by_name[str(name)])
        except FieldTypeError as exc:
            if len(errors) < _MAX_ERRORS:
                errors.append({"row": index, "detail": str(exc)})
            continue
        rows.append((index, parsed))
    return ParsedImport(rows=rows, errors=errors)


def import_rows(table: DataTable, parsed_rows: Sequence[tuple[int, Mapping[str, Any]]]) -> ImportResult:
    """逐行校验并批量插入：错误行跳过并报告（原始行号+原因），成功行一次批量落库."""
    errors: list[dict[str, Any]] = []
    cleaned_rows: list[dict[str, Any]] = []
    for row_number, parsed in parsed_rows:
        if not parsed:
            continue
        try:
            cleaned_rows.append(records.clean_row(table, parsed, partial=True))
        except records.InvalidRowError as exc:
            if len(errors) < _MAX_ERRORS:
                errors.append({"row": row_number, "detail": str(exc)})
    ids = records.insert_rows(table, cleaned_rows)
    return ImportResult(created=len(ids), errors=errors)


def parse_json_import(table: DataTable, payload: Any, allowed: set[str]) -> list[tuple[int, dict[str, Any]]]:
    """校验 JSON 导入结构：必须是行数组，字段须已知且可见，值保持原生类型（附行号）."""
    if not isinstance(payload, list) or not payload:
        raise InvalidImportError("JSON 导入必须是非空行数组")
    known = {str(f.name) for f in table.active_fields()}
    rows: list[tuple[int, dict[str, Any]]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            raise InvalidImportError("JSON 导入的每一行必须是对象")
        for name in item:
            if name not in known or name not in allowed:
                raise InvalidImportError(f"行数据包含未知或不可见字段: {name}")
        rows.append((len(rows) + 1, dict(item)))
    return rows
