"""字段映射 —— 跨表字段对齐 / 数据导入列映射 / 缺口分析.

本模块提供字段层的通用对齐能力，供两条链路复用：

1. **Schema 导入**（:mod:`field_ops`）：
   从其他表引入字段定义时，支持源字段名 → 目标字段名的重命名映射，
   并对"跳过某些源字段 / 重命名后与目标表已有字段冲突"等情况给出明确诊断。

2. **数据导入**（:mod:`importer` / :class:`RowValidator`）：
   行数据从文件/API 导入到已有表时，通过 ``field_mapping`` 指定
   "源列 → 目标字段"的对齐关系，并对以下缺口给出处理策略：
   - 源侧多余：源字段在目标表没有对应字段
   - 目标侧缺失：目标字段在源侧没有对应列

核心数据结构：

.. code-block:: python

    field_mapping: dict[str, str | None]
    # key = 源字段名，value = 目标字段名；None 表示该源字段不引入
    # 未显式列出的源字段按源名 == 目标名 自动匹配（若目标表不存在同名，则跳过）

    GapFilling = Literal["empty", "default", "value", "error"]
    # 目标侧缺失时的填充策略：留空 / 用 default_value / 填特定值 / 报错
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from cndb.plugins.tables.models import DataField

logger = logging.getLogger(__name__)

GapFilling = Literal["empty", "default", "value", "error"]


# ── 自动匹配 ─────────────────────────────────────────


def build_default_mapping(
    source_names: list[str],
) -> dict[str, str]:
    """按源名 == 目标名的保守策略构造默认映射."""
    return {name: name for name in source_names}


def apply_user_mapping(
    base: dict[str, str],
    user_mapping: dict[str, str | None],
    source_names: list[str],
) -> dict[str, str]:
    """把用户显式指定的映射合并到 base 默认映射上.

    语义：
    - ``user_mapping[key] = 目标名``  → 覆盖 base[key]
    - ``user_mapping[key] = None``    → 该源字段标记为"不引入"（从 base 中删除）
    - ``user_mapping`` 中 key 不在 source_names  → ValueError
    - source_names 中未被 user_mapping 显式覆盖的项 → 保留 base 默认值

    Returns:
        合并后的映射（仅包含要引入的源字段）.
    """
    src_set = set(source_names)
    for src_name in user_mapping:
        if src_name not in src_set:
            raise ValueError(f"field_mapping 中存在源表没有的字段: {src_name!r}")

    merged: dict[str, str] = dict(base)
    for src_name, dst_name in user_mapping.items():
        if dst_name is None:
            merged.pop(src_name, None)
        else:
            merged[src_name] = dst_name
    return merged


# ── 缺口分析 ─────────────────────────────────────────


def analyze_field_gaps(
    mapping: dict[str, str],
    source_names: list[str],
    target_names: list[str],
) -> dict[str, Any]:
    """分析映射结果的三类缺口.

    Returns:
        dict 含四个键：
        - ``matched``:       list[dict]  —— 成功对齐的 (src, dst) 对
        - ``unmapped_source``: list[str]  —— 源侧未被映射到目标侧（被跳过）
        - ``target_missing``:  list[str]  —— 目标侧有、但源侧没有字段能提供
        - ``conflicts``:       list[dict] —— 映射后目标名与目标表已有字段重名
    """
    # 源侧哪些被映射到了目标侧（映射 value 去重后与源列表比对）
    mapped_src = set(mapping.keys())
    unmapped_source = [n for n in source_names if n not in mapped_src]

    # 目标侧：哪些被覆盖（来自 mapping value 的 set）
    mapped_dst = set(mapping.values())
    target_missing = [n for n in target_names if n not in mapped_dst]

    # 冲突：mapping value 中出现重复（两个源字段想映射到同一个目标字段）
    seen: dict[str, str] = {}
    conflicts: list[dict[str, str]] = []
    for src, dst in mapping.items():
        if dst in seen:
            conflicts.append({"src_a": seen[dst], "src_b": src, "dst": dst})
        else:
            seen[dst] = src

    matched = [{"source": s, "target": d} for s, d in mapping.items()]

    return {
        "matched": matched,
        "unmapped_source": unmapped_source,
        "target_missing": target_missing,
        "conflicts": conflicts,
    }


# ── 对行数据应用映射 ─────────────────────────────────


def remap_row(
    row: dict[str, Any],
    mapping: dict[str, str],
) -> dict[str, Any]:
    """按 mapping 把行 dict 的源侧 key 重命名为目标侧 key.

    - 映射值为目标字段名，输出 dict 的 key 即目标字段名.
    - 源行中存在但 mapping 未覆盖的 key → 丢弃（等价于"该源字段不引入"）.
    - mapping 中的 key 源行不存在 → 目标 key 存在但值为 None（交由后续 GapFilling 处理）.
    """
    out: dict[str, Any] = {}
    for src_name, dst_name in mapping.items():
        out[dst_name] = row.get(src_name)
    return out


# ── 目标侧缺失字段填充 ───────────────────────────────


def apply_gap_filling(
    row: dict[str, Any],
    missing_target_names: list[str],
    target_field_map: dict[str, DataField],
    strategy: GapFilling = "empty",
    *,
    fill_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按 GapFilling 策略为目标侧缺失字段补值.

    Args:
        row: 经 ``remap_row`` 处理后的行 dict（key 为目标字段名）.
        missing_target_names: 目标侧缺失字段名（analyze_field_gaps.target_missing）.
        target_field_map: ``{目标字段名: DataField}`` 用于查询 default_value / required.
        strategy: 填充策略 —— "empty" / "default" / "value" / "error".
        fill_values: strategy="value" 时，按目标字段名指定填充值.

    Returns:
        填充后的行 dict（原地修改并返回）.

    Raises:
        ValueError: strategy="error" 且存在缺失字段.
        ValueError: strategy="value" 但某个缺失字段的 fill_values 未指定.
    """
    if strategy == "empty":
        for name in missing_target_names:
            row[name] = row.get(name)  # 保持 None / 原值
        return row

    if strategy == "default":
        for name in missing_target_names:
            f = target_field_map.get(name)
            row[name] = f.default_value if f is not None else None
        return row

    if strategy == "value":
        fill = fill_values or {}
        for name in missing_target_names:
            row[name] = fill.get(name)  # 未指定 → None，由后续校验处理
        return row

    # strategy == "error"
    if missing_target_names:
        raise ValueError(f"源数据缺少目标必填字段: {missing_target_names}")
    return row


# ── 便捷入口：从两个 DataField 列表自动推断映射 ────────


def auto_match_fields(
    src_fields: list[DataField],
    dst_fields: list[DataField] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """从源表字段列表和目标表已有字段列表构造默认映射 + 缺口分析.

    Returns:
        (mapping, gap_report) — 与 ``build_default_mapping`` + ``analyze_field_gaps`` 结果一致.
    """
    src_names = [f.name for f in src_fields]
    dst_names = [f.name for f in dst_fields] if dst_fields else []
    mapping = build_default_mapping(src_names)
    gap = analyze_field_gaps(mapping, src_names, dst_names)
    return mapping, gap


__all__ = [
    "GapFilling",
    "analyze_field_gaps",
    "apply_gap_filling",
    "apply_user_mapping",
    "auto_match_fields",
    "build_default_mapping",
    "remap_row",
]
