"""列分析与建表导入编排 — CSV/JSON 列分析、自动建表、行批量导入."""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any

from cndb.plugins.tables.models import DataField, DataTable, ensure_default_view
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core.ddl import create_table as ddl_create
from cndb.plugins.tables.services.core.ddl import drop_table as ddl_drop
from cndb.plugins.tables.services.transfer.exporting import _parse_link_import_value
from cndb.plugins.tables.services.transfer.normalize import (
    _coerce_long_numeric_to_text,
    _infer_single_value,
    _pick_inferred_type,
    _promote_to_longtext_if_chunky,
    _promote_to_multiselect_if_list_like,
    _promote_to_select_if_low_cardinality,
    _promote_to_timestamp_if_epoch_like,
    _python_type_to_field_type,
    _split_json_array_like,
    promote_inferred_column_type,
)
from cndb.plugins.tables.services.transfer.options import (
    _dedupe_samples,
    _infer_decimals_config,
    _options_strings_to_dicts,
)
from cndb.plugins.tables.services.transfer.spreadsheet import (
    _check_csv_row_overflow,
    _check_xlsx_row_overflow,
    _validate_csv_structure,
    _validate_xlsx_header,
    parse_file_to_rows,
)

logger = logging.getLogger(__name__)


def analyze_csv_columns(csv_text: str, sample_rows: int = 100) -> tuple[list[dict[str, Any]], int]:
    """分析 CSV 文本，推断每列字段类型 + 空值占比 + 样本值（按首次出现去重）.

    启发式增强：text 列若唯一值数 ≤ 8 且非 boolean 值域，则自动提升为 select 类型，
    并附带 options 列表（按首次出现顺序去重），供 create_table_from_csv 写入 config.

    Returns:
        (columns_info, total_rows) — columns_info 每项含 name/field_type/sample_values/null_ratio，
            若推断为 select 还会额外包含 options: list[str]
    """
    buf = io.StringIO(csv_text)
    reader = csv.DictReader(buf)
    fieldnames = reader.fieldnames or []
    _validate_csv_structure(fieldnames)

    sample_data: dict[str, list[str]] = {name: [] for name in fieldnames}
    null_counts: dict[str, int] = dict.fromkeys(fieldnames, 0)
    total_rows = 0

    for row in reader:
        total_rows += 1
        _check_csv_row_overflow(row, reader.line_num, len(fieldnames))
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
        # 完整提升链统一收口：timestamp → longtext → multiselect → select
        inferred, promote_options = promote_inferred_column_type(inferred, samples)

        col_info: dict[str, Any] = {
            "name": name,
            "field_type": inferred,
            "sample_values": _dedupe_samples(samples),
            "null_ratio": round(null_ratio, 4),
        }
        if promote_options:
            col_info["options"] = promote_options
        columns.append(col_info)

    return columns, total_rows


def analyze_json_columns(
    rows: list[dict[str, Any]],
    sample_rows: int = 100,
) -> list[dict[str, Any]]:
    """分析 JSON 对象数组，推断每个字段的类型.

    启发式与 analyze_csv_columns 对称：text 列低基数提升 select；
    text 列分隔符串值或 json 列标量数组值（高复用）提升 multiselect，
    含 dict 编码样本的列不做列表提升。

    Returns:
        列表每项同 analyze_csv_columns：
        {name, field_type, sample_values, null_ratio, options?}（sample_values 按首次出现去重）
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
                    # date/datetime 对象输出 ISO 串，避免 "00:00:00" 尾巴混入 options
                    from cndb.plugins.tables.services.transfer.normalize import _format_date_like_sample

                    formatted = _format_date_like_sample(val)
                    samples[key].append(formatted if formatted is not None else str(val))

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
        # timestamp/longtext 提升在 multiselect/select 之前；样本统一按 str 处理
        col_samples = samples[key]
        inferred = _promote_to_timestamp_if_epoch_like(inferred, col_samples)
        inferred = _promote_to_longtext_if_chunky(inferred, col_samples)
        # multiselect 提升须在 select 之前；含 dict 编码样本的列不做列表提升
        # （dict 行落 multiselect 会把 "{'a': 1, 'b': 2}" 拆出垃圾选项）
        promote_options: list[str] = []
        if not any(s.lstrip().startswith("{") for s in col_samples):
            parser = _split_json_array_like if inferred == "json" else None
            inferred, promote_options = _promote_to_multiselect_if_list_like(inferred, col_samples, parser)
        if not promote_options:
            inferred, promote_options = _promote_to_select_if_low_cardinality(inferred, col_samples)

        col_info: dict[str, Any] = {
            "name": key,
            "field_type": inferred,
            "sample_values": _dedupe_samples(col_samples),
            "null_ratio": round(null_ratio, 4),
        }
        if promote_options:
            col_info["options"] = promote_options
        columns.append(col_info)

    return columns


def _cleanup_partial_table(engine: Any, db: Any, dt: DataTable) -> None:
    """清理"已创建元数据但导入失败"的半残表 —— 先删物理表（含 link 表），再删 ORM 元数据.

    DataTable.relationship 已配置 cascade="all, delete-orphan"，
    ``db.delete(dt)`` 会级联删除 DataField / DataView / TablePermission / TableMember 等子记录.
    """
    # 1. 物理层：先删 link 关联表（ddl_drop 对不存在的表幂等），再删主表
    for field in dt.fields:
        if field.field_type == "link":
            ddl_drop(engine, field.link_table_name)
    ddl_drop(engine, dt.db_table_name)

    # 2. 元数据层：级联删除 DataTable 即删光子记录
    db.delete(dt)
    db.commit()
    logger.info("已清理导入失败残留的表 %s (id=%s)", dt.name, dt.id)


def create_table_from_csv(
    engine: Any,
    db: Any,
    workspace_id: int,
    table_name: str,
    csv_text: str,
    owner_id: int | None = None,
) -> tuple[DataTable, list[int]]:
    """从 CSV 自动建表 + 导入数据.

    建表与导入包在同一 try/except 中，若数据导入失败则自动清理已创建的
    DataTable / DataField 元数据及物理表，避免残留空壳。
    """
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
        if col["field_type"] in ("select", "multiselect"):
            cfg["options"] = _options_strings_to_dicts(col.get("options", []))
        else:
            cfg.update(_infer_decimals_config(col["field_type"], col.get("sample_values", [])))
        f = DataField(table_id=dt.id, name=col["name"], field_type=col["field_type"], order=i, config=cfg)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)

    try:
        ddl_create(engine, dt)
        ensure_default_view(db, dt, owner_id=owner_id, commit=True)
        ids = import_rows_from_csv(engine, dt, csv_text, db=db)
    except Exception:
        _cleanup_partial_table(engine, db, dt)
        raise
    return dt, ids


def _prefill_before_bulk(db: Any, table: DataTable, rows: list[dict[str, Any]]) -> None:
    """bulk_create 前：从待导入行预填充 select/multiselect options，让后续值校验通过.

    db 可为 None（纯 engine 场景），此时跳过不报错.
    """
    if not db or not rows:
        return
    try:
        from cndb.plugins.tables.services.fields.field_ops import prefill_select_options_from_rows

        prefill_select_options_from_rows(db, table, rows)
    except Exception as exc:  # pragma: no cover - 补全失败不阻断主流程
        logger.warning("[transfer] prefill select options 失败，不影响主流程: %s", exc)


def _sync_after_bulk(db: Any, table: DataTable) -> None:
    """bulk_create 后：从物理表补全 select/multiselect options（覆盖存量行值）.

    db 可为 None（纯 engine 场景），此时跳过不报错.
    """
    if not db:
        return
    try:
        from cndb.plugins.tables.services.fields.field_ops import sync_select_options_from_table

        sync_select_options_from_table(db, table)
    except Exception as exc:  # pragma: no cover - 补全失败不阻断主流程
        logger.warning("[transfer] sync select options 失败，不影响已导入数据: %s", exc)


def import_rows_from_json(
    engine: Any,
    table: DataTable,
    json_text: str,
    db: Any = None,
) -> list[int]:
    """从 JSON 文本导入行数据，返回新行 id 列表."""
    rows = json.loads(json_text)
    if not isinstance(rows, list):
        raise ValueError("JSON 必须是对象数组")
    valid = [_parse_link_import_value(table, r) for r in rows if isinstance(r, dict)]
    _prefill_before_bulk(db, table, valid)
    ids = rec.bulk_create(engine, table, valid, db=db)
    _sync_after_bulk(db, table)
    return ids


def import_rows_from_csv(
    engine: Any,
    table: DataTable,
    csv_text: str,
    db: Any = None,
) -> list[int]:
    """从 CSV 文本导入行数据，返回新行 id 列表."""
    buf = io.StringIO(csv_text)
    reader = csv.DictReader(buf)
    _validate_csv_structure(reader.fieldnames or [])
    header_len = len(reader.fieldnames or [])
    # 把 CSV 空单元格（空字符串或仅空白）归一为 None — 否则 number/date 等类型校验会因 '' 抛 ValueError
    rows = []
    for r in reader:
        _check_csv_row_overflow(r, reader.line_num, header_len)
        cleaned: dict[str, Any] = {}
        for k, v in r.items():
            if isinstance(v, str):
                stripped = v.strip()
                cleaned[k] = None if stripped == "" else stripped
            else:
                cleaned[k] = v
        rows.append(_parse_link_import_value(table, cleaned))
    _prefill_before_bulk(db, table, rows)
    ids = rec.bulk_create(engine, table, rows, db=db)
    _sync_after_bulk(db, table)
    return ids


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
    header = [str(c) if c is not None else "" for c in rows[0]]
    _validate_xlsx_header(header)
    # 长数字保护：对每个单元格值做精度保护转换
    data = []
    for sheet_row, row in enumerate(rows[1:], start=2):
        if not any(c is not None for c in row):
            continue
        # 行溢出明确报错（zip 静默截断会丢数据）；短行按缺列补 None 空值语义
        _check_xlsx_row_overflow(row, sheet_row, len(header))
        data.append(
            _parse_link_import_value(
                table,
                {k: _coerce_long_numeric_to_text(v) for k, v in zip(header, row, strict=False)},
            )
        )
    _prefill_before_bulk(db, table, data)
    ids = rec.bulk_create(engine, table, data, db=db)
    _sync_after_bulk(db, table)
    return ids


def create_table_from_json_data(
    engine: Any,
    db: Any,
    workspace_id: int,
    table_name: str,
    rows: list[dict[str, Any]],
    owner_id: int | None = None,
) -> tuple[DataTable, list[int]]:
    """从 JSON 对象数组自动建表 + 导入数据.

    与 create_table_from_csv 对称；导入失败时同样清理残留元数据与物理表.
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
        if col["field_type"] in ("select", "multiselect"):
            cfg["options"] = _options_strings_to_dicts(col.get("options", []))
        else:
            cfg.update(_infer_decimals_config(col["field_type"], col.get("sample_values", [])))
        f = DataField(table_id=dt.id, name=col["name"], field_type=col["field_type"], order=i, config=cfg)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)

    try:
        ddl_create(engine, dt)
        ensure_default_view(db, dt, owner_id=owner_id, commit=True)
        valid = [_parse_link_import_value(dt, r) for r in rows if isinstance(r, dict)]
        _prefill_before_bulk(db, dt, valid)
        ids = rec.bulk_create(engine, dt, valid, db=db)
        _sync_after_bulk(db, dt)
    except Exception:
        _cleanup_partial_table(engine, db, dt)
        raise
    return dt, ids


def _analyze_dict_rows_as_csv(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 list[dict] 行转为 csv 文本再调用 analyze_csv_columns，复用成熟的启发式."""
    if not rows:
        return []
    # 收集全部列名（跨所有行）
    all_cols: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                all_cols.append(k)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=all_cols)
    writer.writeheader()
    for r in rows:
        # 把 None 转空串，把 bool/number 转字符串（CSV 世界没有原生类型）
        normalized: dict[str, Any] = {}
        for k in all_cols:
            v = r.get(k)
            if v is None:
                normalized[k] = ""
            elif isinstance(v, bool):
                normalized[k] = "是" if v else "否"  # 让 boolean 推断触发
            elif isinstance(v, (int, float)):
                normalized[k] = str(v)
            else:
                normalized[k] = str(v) if v is not None else ""
        writer.writerow(normalized)
    columns, _total = analyze_csv_columns(buf.getvalue())
    return columns


def analyze_file_columns(
    content: bytes | str | None = None,
    *,
    format: str | None = None,
    filename: str | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int, str]:
    """通用列类型推断 — 自动识别格式，复用 csv / json 分析器.

    Args:
        content: 文件原始字节或文本. 若传 rows 可跳过解析.
        format: 显式指定格式（csv / tsv / delimited / json / xlsx）.
        filename: 文件名（用于格式推断）.
        rows: 已解析好的对象数组 — 直接走 JSON 路径推断.

    Returns:
        (columns_info, total_rows, actual_format) — columns_info 每项同 analyze_csv_columns.
    """
    if rows is None:
        if content is None:
            raise ValueError("必须提供 content 或 rows")
        rows, _cols, actual_fmt = parse_file_to_rows(content, format, filename=filename)
    else:
        # rows 由调用方提供 —— 无法推断 format，默认 json 路径
        actual_fmt = format or "json"

    if actual_fmt in ("json", "xlsx"):
        # xlsx 解析后也是对象数组，走 JSON 推断路径（支持 Python 原生 bool/int/float 类型信息）
        columns = analyze_json_columns(rows)
    else:
        # csv / tsv / delimited — 把行重新序列化为 csv 文本走原有分析
        # 或直接把 dict 的值转字符串后复用 analyze_csv_columns 的逻辑
        columns = _analyze_dict_rows_as_csv(rows)

    return columns, len(rows), actual_fmt


def _apply_column_overrides(
    columns: list[dict[str, Any]],
    column_overrides: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """用前端回传的 column_overrides 覆盖自动推断的列信息，返回新列表.

    Args:
        columns: analyze 阶段产出的原始列列表（name/field_type/sample_values/...）
        column_overrides: {列名: {field_type, options?}} — 前端调整后的类型声明
    """
    if not column_overrides:
        return columns
    overridden: list[dict[str, Any]] = []
    for col in columns:
        new_col = dict(col)
        ov = column_overrides.get(col["name"])
        if ov:
            if "field_type" in ov:
                new_col["field_type"] = ov["field_type"]
            if "options" in ov:
                new_col["options"] = ov["options"] or []
            elif ov.get("field_type") not in ("select", "multiselect"):
                # 前端把 select 改成其他类型 → 清掉 options
                new_col.pop("options", None)
        overridden.append(new_col)
    return overridden


def create_table_from_file(
    engine: Any,
    db: Any,
    workspace_id: int,
    table_name: str,
    content: bytes | str,
    *,
    format: str | None = None,
    filename: str | None = None,
    owner_id: int | None = None,
    column_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[DataTable, list[int], list[dict[str, Any]]]:
    """从任意支持的文件自动建表 + 导入数据 + 返回列信息（一站式入口）.

    Args:
        column_overrides: 前端回传的字段调整映射 —— 格式为
            ``{列名: {field_type, options?}}``，覆盖自动推断结果.
            例如 ``{"状态": {"field_type": "select", "options": ["进行中", "已完成"]}}``

    Returns:
        (DataTable, 新行 id 列表, 最终采用的列信息 —— 含 overrides 结果)

    建表与导入包在同一 try/except 中，若数据导入失败则自动清理已创建的
    DataTable / DataField 元数据及物理表，避免残留空壳。
    """
    rows, _file_cols, actual_fmt = parse_file_to_rows(content, format, filename=filename)
    columns = analyze_json_columns(rows) if actual_fmt in ("json", "xlsx") else _analyze_dict_rows_as_csv(rows)
    if not columns:
        raise ValueError("文件没有有效列")

    # 应用前端字段类型覆盖（如果有）
    columns = _apply_column_overrides(columns, column_overrides)

    dt = DataTable(workspace_id=workspace_id, owner_id=owner_id, name=table_name)
    dt.ensure_db_name()
    db.add(dt)
    db.commit()
    db.refresh(dt)

    for i, col in enumerate(columns):
        cfg: dict[str, Any] = {}
        if col["field_type"] in ("select", "multiselect"):
            cfg["options"] = _options_strings_to_dicts(col.get("options", []))
        else:
            cfg.update(_infer_decimals_config(col["field_type"], col.get("sample_values", [])))
        f = DataField(table_id=dt.id, name=col["name"], field_type=col["field_type"], order=i, config=cfg)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)

    try:
        ddl_create(engine, dt)
        ensure_default_view(db, dt, owner_id=owner_id, commit=True)
        valid = [_parse_link_import_value(dt, r) for r in rows if isinstance(r, dict)]
        _prefill_before_bulk(db, dt, valid)
        ids = rec.bulk_create(engine, dt, valid, db=db)
        _sync_after_bulk(db, dt)
    except Exception:
        _cleanup_partial_table(engine, db, dt)
        raise
    return dt, ids, columns
