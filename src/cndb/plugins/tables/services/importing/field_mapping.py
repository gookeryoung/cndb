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


# ── 智能建议：跨表字段名匹配 ────────────────────────────


# 常见缩写 → 完整词（双向）
_ABBREV_DICT: dict[str, str] = {
    # 通用
    "amt": "amount",
    "cnt": "count",
    "qty": "quantity",
    "val": "value",
    "id": "identifier",
    "no": "number",
    "num": "number",
    "desc": "description",
    "info": "information",
    "cfg": "config",
    "st": "status",
    "stat": "status",
    "typ": "type",
    "dt": "date",
    "tm": "time",
    "ts": "timestamp",
    "src": "source",
    "dst": "destination",
    "tgt": "target",
    "usr": "user",
    "adm": "admin",
    "pwd": "password",
    "addr": "address",
    "tel": "telephone",
    "phone": "phone",
    "url": "url",
    "img": "image",
    "pic": "picture",
    "msg": "message",
    "err": "error",
    "exc": "exception",
    "tmp": "temp",
    "bak": "backup",
    # 后缀类
    "name_full": "full_name",
    "fullname": "full_name",
    # 中文拼音缩写（低优先级兜底，仅当中文名匹配时生效）
    # 暂不列入 —— 中文场景建议用字符串相似度兜底
}

# 常见前缀/后缀，归一化时剥离
_COMMON_PREFIXES = ("src_", "dst_", "tgt_", "old_", "new_", "prev_", "next_", "cur_", "current_")
_COMMON_SUFFIXES = ("_src", "_dst", "_old", "_new", "_prev", "_cur", "_current")


def _normalize_name(name: str) -> str:
    """把字段名归一化：小写 → 剥离分隔符 → 去常见前后缀."""
    n = name.lower().strip().replace(" ", "_").replace("-", "_").replace(".", "_").replace("/", "_")
    n = "_".join(p for p in n.split("_") if p)  # 去连续 _
    for p in _COMMON_PREFIXES:
        if n.startswith(p):
            n = n[len(p) :]
            break
    for s in _COMMON_SUFFIXES:
        if n.endswith(s):
            n = n[: -len(s)]
            break
    return n


def _expand_abbrev(name: str) -> list[str]:
    """返回字段名的候选扩展形式（含原词 + 每个 token 展开后的版本）."""
    tokens = name.split("_")
    candidates = [name]
    for i, tok in enumerate(tokens):
        expanded = _ABBREV_DICT.get(tok, tok)
        if expanded != tok:
            tokens_copy = list(tokens)
            tokens_copy[i] = expanded
            candidates.append("_".join(tokens_copy))
    return candidates


# 字段类型兼容矩阵（同组内 +0.12 分，跨组但可安全互转 +0.05）
_TYPE_GROUPS: dict[str, str] = {
    "text": "text",
    "longtext": "text",
    "email": "text",
    "url": "text",
    "phone": "text",
    "number": "numeric",
    "float": "numeric",
    "percentage": "numeric",
    "boolean": "boolean",
    "date": "date",
    "datetime": "date",
    "timestamp": "date",
    "select": "select",
    "multiselect": "select",
    "link": "link",
    "attachment": "attachment",
}


def _type_compat(src_type: str | None, dst_type: str | None) -> float:
    """返回 0.0 / 0.05 / 0.15 的类型兼容加分."""
    if not src_type or not dst_type:
        return 0.0
    g_s = _TYPE_GROUPS.get(src_type, src_type)
    g_d = _TYPE_GROUPS.get(dst_type, dst_type)
    if src_type == dst_type:
        return 0.18
    if g_s == g_d:
        return 0.12
    # text ↔ numeric 不加分（可能丢精度），其他跨组给极小分
    return 0.03


def _name_similarity(src_norm: str, dst_norm: str) -> tuple[float, str]:
    """基于归一化名称计算相似度 + 返回匹配理由."""
    import difflib

    # 完全匹配
    if src_norm == dst_norm:
        return 1.0, "同名"

    # 缩写双向匹配
    for s_cand in _expand_abbrev(src_norm):
        for d_cand in _expand_abbrev(dst_norm):
            if s_cand == d_cand and (s_cand != src_norm or d_cand != dst_norm):
                return 0.92, f"缩写扩展: {src_norm} ≡ {dst_norm}"

    # SequenceMatcher
    ratio = difflib.SequenceMatcher(None, src_norm, dst_norm).ratio()

    # 包含关系
    if src_norm in dst_norm or dst_norm in src_norm:
        ratio = max(ratio, 0.85)
        return ratio, f"包含匹配 (相似度 {ratio:.2f})"

    if ratio >= 0.75:
        return ratio, f"名称相似 (相似度 {ratio:.2f})"

    return ratio, f"弱匹配 (相似度 {ratio:.2f})"


def suggest_mapping(
    src_fields: list[DataField],
    dst_fields: list[DataField],
    *,
    min_score: float = 0.6,
) -> list[dict[str, Any]]:
    """为源表每个字段在目标表中推荐一个最佳匹配.

    评分公式：``final = name_score + type_bonus``.

    Args:
        src_fields: 源表字段列表.
        dst_fields: 目标表字段列表（已是候选集，通常是"目标表已有字段"，
            用户也可以只传"目标表中尚未被占用的字段"实现增量建议）.
        min_score: 低于此阈值的推荐会在返回里标记 ``will_map=False``.

    Returns:
        list 每项形如
        ``{"source": src_name, "target": dst_name | None, "score": float,
          "reason": str, "will_map": bool}``
        — ``will_map=False`` 表示得分过低或无候选，前端应提示用户手动选择/跳过.
    """
    src_norm_map = {f.name: _normalize_name(f.name) for f in src_fields}
    dst_norm_map = {f.name: _normalize_name(f.name) for f in dst_fields}

    # 预计算每个 src ↔ dst 的得分 (score, src_name, dst_name, reason)
    scored: list[tuple[float, str, str, str]] = []
    for sf in src_fields:
        for df in dst_fields:
            name_score, reason = _name_similarity(src_norm_map[sf.name], dst_norm_map[df.name])
            type_bonus = _type_compat(sf.field_type, df.field_type)
            final = name_score + type_bonus
            scored.append((final, sf.name, df.name, reason))

    # 贪心分配：按 score 降序，每个 src 先到先得一个 dst
    def _score_tuple_key(r: tuple[float, str, str, str]) -> float:
        return r[0]

    scored_sorted = sorted(scored, key=_score_tuple_key, reverse=True)
    assigned_dst: set[str] = set()
    best_for_src: dict[str, tuple[float, str, str]] = {}  # src → (score, dst, reason)

    for score, src, dst, reason in scored_sorted:
        if src in best_for_src:
            continue  # 该 src 已拿到更高分的候选
        if dst in assigned_dst:
            continue
        assigned_dst.add(dst)
        best_for_src[src] = (score, dst, reason)

    results: list[dict[str, Any]] = []
    for sf in src_fields:
        entry = best_for_src.get(sf.name)
        if entry is None:
            results.append(
                {
                    "source": sf.name,
                    "target": None,
                    "score": 0.0,
                    "reason": "无候选",
                    "will_map": False,
                }
            )
            continue
        score, dst, reason = entry
        will_map = score >= min_score
        if not will_map:
            reason += f"（得分 {score:.2f} < 阈值 {min_score}）"
        results.append(
            {
                "source": sf.name,
                "target": dst,
                "score": round(score, 3),
                "reason": reason,
                "will_map": will_map,
            }
        )

    return results


def suggest_field_mapping(
    src_fields: list[DataField],
    dst_fields: list[DataField],
    *,
    min_score: float = 0.6,
) -> tuple[dict[str, str | None], list[dict[str, Any]]]:
    """suggest_mapping 的便捷封装：返回 ``(mapping_dict, suggestions_list)``.

    mapping_dict 直接可传入 :func:`apply_user_mapping`；
    suggestions_list 供前端渲染"推荐 → 手动覆盖"面板.

    特殊：当目标表（dst_fields）为空时，所有源字段默认 will_map=True 同名导入
    （覆盖 min_score 阈值），符合"目标表还没字段就全量克隆"的直觉.
    """
    # 特殊：目标表暂无字段 → 全部同名导入
    if not dst_fields:
        suggestions: list[dict[str, Any]] = [
            {
                "source": f.name,
                "target": f.name,
                "score": 1.0,
                "reason": "目标表为空，默认同名导入",
                "will_map": True,
            }
            for f in src_fields
        ]
        mapping: dict[str, str | None] = {s["source"]: s["target"] for s in suggestions if s["target"]}
        return mapping, suggestions

    suggestions = suggest_mapping(src_fields, dst_fields, min_score=min_score)
    mapping = {}
    for s in suggestions:
        if s["will_map"] and s["target"]:
            mapping[s["source"]] = s["target"]
        else:
            # will_map=False — 要么无候选要么得分低，先标记为 None（跳过），让用户手动确认
            mapping[s["source"]] = None
    return mapping, suggestions


__all__ = [
    "GapFilling",
    "analyze_field_gaps",
    "apply_gap_filling",
    "apply_user_mapping",
    "auto_match_fields",
    "build_default_mapping",
    "remap_row",
    "suggest_field_mapping",
    "suggest_mapping",
]
