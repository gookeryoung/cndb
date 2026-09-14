"""导入导出 — CSV/XLSX 导入 + JSON/XLSX 导出.

link 字段约定：
- 导出：行响应中 link 值为 [{"id", "value"}] 摘要列表，序列化为分号分隔的目标行 id 串；
- 导入：CSV/XLSX 中 link 列的分号分隔 id 串（或单个 id）解析回列表写入关联表.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any

from cndb.plugins.tables import records as rec
from cndb.plugins.tables.ddl import create_table as ddl_create
from cndb.plugins.tables.links import is_link_field
from cndb.plugins.tables.models import DataField, DataTable

logger = logging.getLogger(__name__)

# ── 列类型推断正则 ──────────────────────────────────────

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")
_URL_RE = re.compile(r"^https?://[\w.-]+(?::\d+)?(?:/[\w./?#=&%+-]*)?$", re.IGNORECASE)
_PHONE_RE = re.compile(r"^[\d+\-() ]{7,20}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:[Z+\-]\d{2}:?\d{2})?$")


# ── CSV 列类型推断辅助 ──────────────────────────────────


def _is_boolean(value: str) -> bool:
    """判断值是否属于布尔值域."""
    low = value.strip().lower()
    return low in ("true", "false", "yes", "no", "是", "否", "1", "0", "on", "off")


def _is_integer(value: str) -> bool:
    """判断是否为整数（含负数、千分位逗号）."""
    stripped = value.strip().replace(",", "")
    if not stripped:
        return False
    if stripped.startswith("-"):
        stripped = stripped[1:]
    if not stripped.isdigit():
        return False
    return not (len(stripped) >= 11 and stripped.startswith("0"))


def _is_float(value: str) -> bool:
    """判断是否为小数."""
    stripped = value.strip().replace(",", "")
    if not stripped:
        return False
    try:
        float(stripped)
        return "." in stripped or "e" in stripped.lower()
    except ValueError:
        return False


def _check_phone(v: str) -> bool:
    """判断是否为**中国手机号**格式（含 +86 前缀、带/不带分隔符）.

    设计意图：
    - CSV 用户可能真在导入中国手机号数据 → 可以升为 phone 类型；
    - 但 API 自动建表遇到国际手机号（如 +1 (822) 340-2602）→ 一律降级为 text，
      因为 phone 字段类型的 validate_value 只接受中国 11 位格式。

    规则：剥掉所有分隔符和 +86 前缀后，为纯数字 11 位，以 1 开头，第二位 3-9.
    """
    stripped = v.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    # 去掉可选的中国区号前缀
    if stripped.startswith("+86"):
        stripped = stripped[3:]
    elif stripped.startswith("86") and len(stripped) > 11:
        stripped = stripped[2:]
    # 现在应该是纯数字 11 位
    return len(stripped) == 11 and stripped.isdigit() and stripped.startswith("1") and stripped[1] in "3456789"


def _infer_single_value(value: str) -> str:
    """推断单个值的类型 —— 表驱动式分支."""
    v = value.strip()
    if not v:
        return "empty"

    # 检查器列表：(检查函数, 结果类型)，按优先级排列
    checks: list[tuple[Any, str]] = [
        (_is_boolean, "boolean"),
        (lambda x: bool(_EMAIL_RE.match(x)), "email"),
        (lambda x: bool(_URL_RE.match(x)), "url"),
        (_check_percentage, "percentage"),
        (lambda x: bool(_ISO_DATETIME_RE.match(x)), "datetime"),
        (lambda x: bool(_ISO_DATE_RE.match(x)), "date"),
        (_check_phone, "phone"),
        (_check_long_integer, "text"),
        (_is_integer, "number"),
        (_is_float, "float"),
    ]
    for check_fn, result_type in checks:
        if check_fn(v):
            return result_type
    return "text"


def _check_percentage(v: str) -> bool:
    """判断是否为百分比字符串."""
    return v.endswith("%") and (_is_float(v[:-1]) or _is_integer(v[:-1]))


def _check_long_integer(v: str) -> bool:
    """判断是否为长数字串且前导零（应判为 text/phone）."""
    if not _is_integer(v):
        return False
    num_str = v.lstrip("-").replace(",", "")
    return len(num_str) >= 11 and num_str.startswith("0")


def _pick_inferred_type(type_counts: dict[str, int]) -> str:
    """从类型计数字典中取出现最多的类型."""
    if not type_counts:
        return "text"
    best_key = next(iter(type_counts))
    best_val = type_counts[best_key]
    for k, v in type_counts.items():
        if v > best_val:
            best_key, best_val = k, v
    return best_key


def _is_select_candidate(unique_values: list[str], inferred_type: str, non_empty_count: int) -> bool:
    """判断某列是否应被提升为 select 类型（低基数离散值启发式）.

    规则：
    - 唯一值数在 2~8 之间
    - 推断类型必须是 text（其他类型已各有归属：boolean/number/date/email/url 等）
    - 唯一值数 / 非空样本数 ≤ 0.5（保证至少一半重复值，避免小样本误伤）
    - 所有值都不在 boolean 值集中（避免把 "是/否" 这类被误推为 text 时仍保持 bool）
    """
    if inferred_type != "text":
        return False
    n = len(unique_values)
    if n < 2 or n > 8:
        return False
    # 唯一值占比不能太高：至少一半重复值才认为是离散分类
    if non_empty_count > 0 and n / non_empty_count > 0.5:
        return False
    # boolean 优先级更高：如果所有值都是 boolean 值域的字符串，不应转 select
    boolean_values = {"true", "false", "yes", "no", "是", "否", "1", "0", "on", "off"}
    return not all(v.strip().lower() in boolean_values for v in unique_values)


def _promote_to_select_if_low_cardinality(inferred_type: str, samples: list[str]) -> tuple[str, list[str]]:
    """对推断后的列类型做二次检查：若为 text 且低基数离散值则提升为 select.

    Returns:
        (最终字段类型, 唯一值列表 — 若最终为 select 则作为 options 使用, 否则为空列表)
    """
    seen: list[str] = []
    for v in samples:
        if v not in seen:
            seen.append(v)
    if _is_select_candidate(seen, inferred_type, len(samples)):
        return "select", seen
    return inferred_type, []


def analyze_csv_columns(csv_text: str, sample_rows: int = 100) -> tuple[list[dict[str, Any]], int]:
    """分析 CSV 文本，推断每列字段类型 + 空值占比 + 样本值.

    启发式增强：text 列若唯一值数 ≤ 8 且非 boolean 值域，则自动提升为 select 类型，
    并附带 options 列表（按首次出现顺序去重），供 create_table_from_csv 写入 config.

    Returns:
        (columns_info, total_rows) — columns_info 每项含 name/field_type/sample_values/null_ratio，
            若推断为 select 还会额外包含 options: list[str]
    """
    buf = io.StringIO(csv_text)
    reader = csv.DictReader(buf)
    fieldnames = reader.fieldnames or []

    sample_data: dict[str, list[str]] = {name: [] for name in fieldnames}
    null_counts: dict[str, int] = dict.fromkeys(fieldnames, 0)
    total_rows = 0

    for row in reader:
        total_rows += 1
        for name in fieldnames:
            value = (row.get(name) or "").strip()
            if not value:
                null_counts[name] += 1
            elif len(sample_data[name]) < sample_rows:
                sample_data[name].append(value)

    if total_rows == 0:
        columns = [{"name": n, "field_type": "text", "sample_values": [], "null_ratio": 0.0} for n in fieldnames]
        return columns, 0

    columns: list[dict[str, Any]] = []
    for name in fieldnames:
        samples = sample_data[name]
        null_ratio = null_counts[name] / total_rows

        if not samples:
            columns.append(
                {"name": name, "field_type": "text", "sample_values": [], "null_ratio": round(null_ratio, 4)}
            )
            continue

        type_counts: dict[str, int] = {}
        for v in samples:
            t = _infer_single_value(v)
            if t != "empty":
                type_counts[t] = type_counts.get(t, 0) + 1

        inferred = _pick_inferred_type(type_counts)
        inferred, select_options = _promote_to_select_if_low_cardinality(inferred, samples)

        col_info: dict[str, Any] = {
            "name": name,
            "field_type": inferred,
            "sample_values": samples[:5],
            "null_ratio": round(null_ratio, 4),
        }
        if select_options:
            col_info["options"] = select_options
        columns.append(col_info)

    return columns, total_rows


def create_table_from_csv(
    engine: Any,
    db: Any,
    workspace_id: int,
    table_name: str,
    csv_text: str,
    owner_id: int | None = None,
) -> tuple[DataTable, list[int]]:
    """从 CSV 自动建表 + 导入数据."""
    columns, _total = analyze_csv_columns(csv_text)

    if not columns:
        raise ValueError("CSV 没有有效列")

    dt = DataTable(workspace_id=workspace_id, owner_id=owner_id, name=table_name)
    dt.ensure_db_name()
    db.add(dt)
    db.commit()
    db.refresh(dt)

    for i, col in enumerate(columns):
        cfg: dict[str, Any] = {}
        if col["field_type"] == "select":
            cfg["options"] = col.get("options", [])
        f = DataField(table_id=dt.id, name=col["name"], field_type=col["field_type"], order=i, config=cfg)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)

    ddl_create(engine, dt)

    ids = import_rows_from_csv(engine, dt, csv_text, db=db)
    return dt, ids


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


# ── JSON 数组类型推断 ──────────────────────────────────


def _python_type_to_field_type(value: Any) -> str:
    """把 Python 对象直接映射到字段类型（JSON 推断的第一捷径）."""
    if value is None:
        return "empty"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        # 长整型 / 前导零风格数字 → text 交给字符串推断，但纯 int 直接判 number
        return "number"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        if not value.strip():
            return "empty"
        return _infer_single_value(value)
    if isinstance(value, (list, dict)):
        return "json"
    return "text"


def analyze_json_columns(
    rows: list[dict[str, Any]],
    sample_rows: int = 100,
) -> list[dict[str, Any]]:
    """分析 JSON 对象数组，推断每个字段的类型.

    Returns:
        列表每项同 analyze_csv_columns：
        {name, field_type, sample_values, null_ratio, options?}
    """
    # 收集所有出现过的 key（跨所有行）
    key_counts: dict[str, int] = {}  # 非空值计数
    null_counts: dict[str, int] = {}
    type_counts: dict[str, dict[str, int]] = {}
    samples: dict[str, list[str]] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, val in row.items():
            key_counts.setdefault(key, 0)
            null_counts.setdefault(key, 0)
            type_counts.setdefault(key, {})
            samples.setdefault(key, [])

            if val is None:
                null_counts[key] += 1
                continue
            if isinstance(val, str) and not val.strip():
                null_counts[key] += 1
                continue

            key_counts[key] += 1
            t = _python_type_to_field_type(val)
            if t == "empty":
                null_counts[key] += 1
                continue
            type_counts[key][t] = type_counts[key].get(t, 0) + 1

            # 样本收集（仅基础类型）
            if len(samples[key]) < sample_rows:
                if isinstance(val, (dict, list)):
                    import json as _json

                    try:
                        samples[key].append(_json.dumps(val, ensure_ascii=False))
                    except Exception:
                        samples[key].append(str(val))
                else:
                    samples[key].append(str(val))

    if not rows:
        return []

    total = len(rows)
    columns: list[dict[str, Any]] = []
    for key in key_counts:
        null_ratio = null_counts[key] / total if total else 0.0

        if not type_counts[key]:
            columns.append({"name": key, "field_type": "text", "sample_values": [], "null_ratio": round(null_ratio, 4)})
            continue

        inferred = _pick_inferred_type(type_counts[key])
        inferred, select_options = _promote_to_select_if_low_cardinality(inferred, samples[key])

        col_info: dict[str, Any] = {
            "name": key,
            "field_type": inferred,
            "sample_values": samples[key][:5],
            "null_ratio": round(null_ratio, 4),
        }
        if select_options:
            col_info["options"] = select_options
        columns.append(col_info)

    return columns


def create_table_from_json_data(
    engine: Any,
    db: Any,
    workspace_id: int,
    table_name: str,
    rows: list[dict[str, Any]],
    owner_id: int | None = None,
) -> tuple[DataTable, list[int]]:
    """从 JSON 对象数组自动建表 + 导入数据.

    与 create_table_from_csv 对称.
    """
    columns = analyze_json_columns(rows)

    if not columns:
        raise ValueError("JSON 没有有效字段")

    dt = DataTable(workspace_id=workspace_id, owner_id=owner_id, name=table_name)
    dt.ensure_db_name()
    db.add(dt)
    db.commit()
    db.refresh(dt)

    for i, col in enumerate(columns):
        cfg: dict[str, Any] = {}
        if col["field_type"] == "select":
            cfg["options"] = col.get("options", [])
        f = DataField(table_id=dt.id, name=col["name"], field_type=col["field_type"], order=i, config=cfg)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)

    ddl_create(engine, dt)

    # import_rows_from_json 需要 JSON 字符串，我们直接用对象数组
    valid = [_parse_link_import_value(dt, r) for r in rows if isinstance(r, dict)]
    ids = rec.bulk_create(engine, dt, valid, db=db)
    return dt, ids


def ingest_from_api(
    engine: Any,
    db: Any,
    workspace_id: int,
    table_name: str,
    *,
    api_url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    body: Any = None,
    data_path: str | None = None,
    timeout: float = 15.0,
    response_handler: str | Any = "json",
    encoding: str = "utf-8",
    query_interval: float | None = None,
    owner_id: int | None = None,
) -> tuple[DataTable, list[int], list[dict[str, Any]]]:
    """一站式：抓 API → 推断列 → 建表 → 导入.

    Args:
        response_handler: "json" (默认) / "tencent_stock" / 自定义 callable
        encoding: 响应编码，默认 utf-8（腾讯股票用 gbk）
        query_interval: 查询间隔秒数，None 时用 DEFAULT_QUERY_INTERVAL

    Returns:
        (DataTable, 新行 id 列表, 列信息)
    """
    from cndb.plugins.tables.api_fetch import (
        DEFAULT_QUERY_INTERVAL,
        FetchConfig,
        fetch_json,
        validate_query_interval,
    )

    qi = validate_query_interval(query_interval) if query_interval is not None else DEFAULT_QUERY_INTERVAL

    rows = fetch_json(
        FetchConfig(
            url=api_url,
            method=method,
            headers=headers or {},
            params=params or {},
            body=body,
            timeout=timeout,
            data_path=data_path,
            response_handler=response_handler,
            encoding=encoding,
            query_interval=qi,
        )
    )

    if not rows:
        raise ValueError("API 未返回有效对象数组")

    columns = analyze_json_columns(rows)
    dt, ids = create_table_from_json_data(engine, db, workspace_id, table_name, rows, owner_id=owner_id)
    return dt, ids, columns


__all__ = [
    "analyze_csv_columns",
    "analyze_json_columns",
    "create_table_from_csv",
    "create_table_from_json_data",
    "export_rows_to_csv",
    "export_rows_to_json",
    "export_rows_to_xlsx",
    "guess_format_from_filename",
    "import_rows_from_csv",
    "import_rows_from_json",
    "import_rows_from_xlsx",
    "ingest_from_api",
]
