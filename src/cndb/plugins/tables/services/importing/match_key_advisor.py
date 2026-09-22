"""参考列智能推荐 —— 导入 analyze 阶段的 match_keys 候选评估.

职责：结合文件侧列画像（:mod:`column_profiler` 产出）与目标表现有数据统计，
为每个候选字段评估"适合作为参考列（match_keys / upsert 匹配键）"的程度：

- ``score``: 0~1 综合分（唯一率 0.6 + 非空率 0.4，取文件/表两侧较小值）
- ``recommended``: 综合分与两侧唯一率达标 → 前端展示 ★ 推荐
- ``disabled`` + ``reason``: 字段类型不支持（link/attachment/multiselect/json）、
  全空列（文件或表侧空值率 ≥ 1）→ 禁用并提示原因

输出全为标量结构，天然 JSON 可序列化，直接进 DiffReporter 报告供前端消费。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import distinct, func, select

from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import records as rec

logger = logging.getLogger(__name__)

# 不允许作为参考列的字段类型（值本身无业务匹配语义或结构不适合等值比较）
_DISABLED_TYPES = {"link", "attachment", "multiselect", "json"}
# 推荐阈值：综合分 / 唯一率
_RECOMMEND_SCORE = 0.9
_RECOMMEND_UNIQUE = 0.99
# 单次聚合查询的候选列上限（超宽表防止生成超大 SQL；超出部分仅按文件侧评估）
_MAX_AGG_COLUMNS = 50


def _ratio(numerator: int, denominator: int) -> float:
    """安全计算比率，分母为 0 时返回 0.0."""
    return round(numerator / denominator, 4) if denominator > 0 else 0.0


def _file_side_stats(
    source_col: str,
    rows: list[dict[str, Any]],
    profile: dict[str, Any] | None,
) -> tuple[float, float]:
    """取文件侧 (唯一率, 非空率)；画像缺失时从行数据直接估算."""
    if profile is not None:
        non_null = max(len(rows) - int(profile.get("null_count", 0)), 0)
        unique = _ratio(int(profile.get("unique_count", 0)), non_null)
        nonnull_ratio = round(1.0 - float(profile.get("null_ratio", 0.0)), 4)
        return unique, nonnull_ratio

    # 兜底：直接扫行（画像缺失的罕见场景）
    seen: set[Any] = set()
    non_null = 0
    for row in rows:
        v = row.get(source_col)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        non_null += 1
        seen.add(v if not isinstance(v, (list, dict)) else str(v))
    return _ratio(len(seen), non_null), _ratio(non_null, len(rows))


def _table_side_stats(
    engine: Any,
    table: DataTable,
    candidates: list[DataField],
) -> dict[str, dict[str, int]]:
    """一次聚合查询取表侧统计.

    Returns:
        {字段名: {"table_rows": 总行数, "non_null": 非空数, "distinct": 去重数}}；
        查询失败或物理表不存在时返回空 dict（调用方按"仅文件侧评估"降级）.
    """
    sa_table = rec._get_sa_table(engine, table)
    usable = [(f.name, f.db_column_name) for f in candidates if f.db_column_name in sa_table.c]
    if not usable:
        return {}

    parts: list[Any] = [func.count().label("total")]
    for i, (_name, dbc) in enumerate(usable):
        col = sa_table.c[dbc]
        parts.append(func.count(col).label(f"nn{i}"))
        parts.append(func.count(distinct(col)).label(f"uq{i}"))

    stmt = select(*parts).where(sa_table.c._trashed.is_(False))
    with engine.connect() as conn:
        row = conn.execute(stmt).mappings().one()

    result: dict[str, dict[str, int]] = {}
    total = int(row["total"])
    for i, (name, _dbc) in enumerate(usable):
        result[name] = {
            "table_rows": total,
            "non_null": int(row[f"nn{i}"]),
            "distinct": int(row[f"uq{i}"]),
        }
    return result


def recommend_match_keys(
    engine: Any,
    table: DataTable,
    rows: list[dict[str, Any]],
    file_columns: list[str],
    column_profiles: list[dict[str, Any]],
    *,
    field_mapping: dict[str, str | None] | None = None,
) -> list[dict[str, Any]]:
    """为每个候选字段评估是否适合作为导入参考列（match_keys）.

    Args:
        engine: SQLAlchemy engine（查目标表现有数据统计）.
        table: 目标数据表.
        rows: 解析后的文件行（画像缺失时兜底估算用）.
        file_columns: 文件原始列名.
        column_profiles: ``profile_columns`` 产出的列画像.
        field_mapping: 可选的源列 → 目标字段映射（None 时文件列名 == 字段名）.

    Returns:
        按推荐优先排序的列表，每项::

            {"field": str, "field_type": str, "score": float,
             "recommended": bool, "disabled": bool, "reason": str, "stats": {...}}
    """
    fields = table.active_fields()
    profile_by_col = {p.get("name"): p for p in column_profiles}
    # 目标字段名 → 文件源列名（field_mapping 为 None 时同名对齐）
    src_col_of: dict[str, str] = {}
    if field_mapping:
        for src, dst in field_mapping.items():
            if dst and src in file_columns:
                src_col_of[dst] = src
    for col in file_columns:
        src_col_of.setdefault(col, col)

    # 类型不支持 → 直接禁用，不参与聚合查询
    eligible: list[DataField] = []
    for f in fields:
        if f.field_type in _DISABLED_TYPES:
            continue
        eligible.append(f)

    table_stats: dict[str, dict[str, int]] = {}
    if eligible:
        try:
            table_stats = _table_side_stats(engine, table, eligible[:_MAX_AGG_COLUMNS])
        except Exception as exc:  # 物理表缺失/方言差异时降级为仅文件侧评估
            logger.warning("参考列表侧统计查询失败，降级为仅文件侧评估: %s", exc)
            table_stats = {}

    entries: list[dict[str, Any]] = []
    for f in fields:
        field_type = f.field_type
        src_col = src_col_of.get(f.name, f.name)
        file_unique, file_nonnull = _file_side_stats(src_col, rows, profile_by_col.get(src_col))

        entry: dict[str, Any] = {
            "field": f.name,
            "field_type": field_type,
            "score": 0.0,
            "recommended": False,
            "disabled": False,
            "reason": "",
            "stats": {
                "file_unique_ratio": file_unique,
                "file_null_ratio": round(1.0 - file_nonnull, 4),
                "table_unique_ratio": None,
                "table_null_ratio": None,
                "table_rows": None,
            },
        }

        if field_type in _DISABLED_TYPES:
            entry["disabled"] = True
            entry["reason"] = f"该字段类型（{field_type}）不适合做参考列"
            entries.append(entry)
            continue

        stat = table_stats.get(f.name)
        if stat and stat["table_rows"] > 0:
            table_unique = _ratio(stat["distinct"], stat["non_null"])
            table_nonnull = _ratio(stat["non_null"], stat["table_rows"])
            entry["stats"]["table_unique_ratio"] = table_unique
            entry["stats"]["table_null_ratio"] = round(1.0 - table_nonnull, 4)
            entry["stats"]["table_rows"] = stat["table_rows"]
            score = 0.6 * min(file_unique, table_unique) + 0.4 * min(file_nonnull, table_nonnull)
        else:
            # 表空或统计降级：仅按文件侧评估
            score = 0.6 * file_unique + 0.4 * file_nonnull
            entry["reason"] = "表内暂无数据，仅按文件侧评估"
        entry["score"] = round(score, 3)

        # ── 禁用判定：仅"明确不可用"的两类 ──
        if file_nonnull <= 0.0:
            entry["disabled"] = True
            entry["reason"] = "文件中该列全为空，无法用于匹配"
            entries.append(entry)
            continue
        if stat and stat["table_rows"] > 0 and stat["non_null"] == 0:
            entry["disabled"] = True
            entry["reason"] = "表中该列全为空，无法用于匹配"
            entries.append(entry)
            continue

        # ── 推荐判定 / 非禁用项提示原因 ──
        table_unique_val = entry["stats"]["table_unique_ratio"]
        weakest_unique = file_unique if table_unique_val is None else min(file_unique, table_unique_val)
        if score >= _RECOMMEND_SCORE and weakest_unique >= _RECOMMEND_UNIQUE:
            entry["recommended"] = True
            if entry["reason"] == "":
                entry["reason"] = "文件与表内取值唯一，适合做参考列"
        elif weakest_unique < _RECOMMEND_UNIQUE:
            weak_side = "文件中" if table_unique_val is None or file_unique <= table_unique_val else "表中"
            entry["reason"] = f"{weak_side}该列有重复值（唯一率 {round(weakest_unique * 100)}%），可能匹配多行"
        elif entry["reason"] == "":
            entry["reason"] = "唯一性或非空率不足，慎用"

        entries.append(entry)

    # 推荐项排前，同级按 score 降序
    def _sort_key(e: dict[str, Any]) -> tuple[bool, float]:
        return (not e["recommended"], -e["score"])

    entries.sort(key=_sort_key)
    return entries


__all__ = ["recommend_match_keys"]
