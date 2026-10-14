"""列级类型提升：低基数→select、类时间戳→timestamp、超长→longtext、列表→multiselect.

``infer_column_type`` / ``promote_inferred_column_type`` 是外部入口。
"""

from __future__ import annotations

import json
import re
from typing import Any

from cndb.plugins.tables.field_types import MULTI_SELECT_SPLIT_RE
from cndb.plugins.tables.services.transfer.normalize.values import (
    _infer_single_value,
    _is_boolean,
    _normalize_numeric,
    _pick_inferred_type,
)


def _is_select_candidate(unique_values: list[str], inferred_type: str, non_empty_count: int) -> bool:
    """判断某列是否应被提升为 select 类型（低基数离散值启发式）.

    规则：
    - 唯一值数 ≥ 2，且不超过样本量感知的上限（避免自由文本列被误判）
    - 推断类型必须是 text（其他类型已各有归属：boolean/number/date/email/url 等）
    - 唯一值数 / 非空样本数 的比例需低于样本量自适应阈值（越大样本允许的比例越低）
    - 所有值都不在 boolean 值集中（避免把 "是/否" 这类被误推为 text 时仍保持 bool）

    样本量感知阈值：
    - 样本 < 100 行：允许 ≤ 20 个唯一值，比例 ≤ 0.50（小样本下保守）
    - 样本 100~1000 行：允许 ≤ 30 个唯一值，比例 ≤ 0.30
    - 样本 > 1000 行：允许 ≤ 50 个唯一值，比例 ≤ 0.20（大样本下严格控比）
    """
    if inferred_type != "text":
        return False
    n = len(unique_values)
    if n < 2:
        return False

    # 样本量自适应阈值：小样本下放宽比例（避免少量分类被丢弃），大样本下严格控比（避免自由文本被误判）
    if non_empty_count < 20:
        # 极小样本（< 20 行）：允许较高比例，因为小数据里的重复值多半是离散分类
        max_unique = 15
        max_ratio = 0.80
    elif non_empty_count < 100:
        max_unique = 25
        max_ratio = 0.60
    elif non_empty_count <= 1000:
        max_unique = 60
        max_ratio = 0.35
    else:
        max_unique = 100
        max_ratio = 0.20

    if n > max_unique:
        return False

    # 唯一值占比检查
    if non_empty_count > 0 and n / non_empty_count > max_ratio:
        return False

    # boolean 优先级更高：如果所有值都是 boolean 值域的字符串，不应转 select
    return not all(_is_boolean(v) for v in unique_values)


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


# ── Unix 时间戳列级表决参数 ──────────────────────────────
# 候选值域与 TimestampFieldType.validate_value 上限对齐（双向锁定）：
# 秒级 [1e9, 4102444800]（2001-09-09 ~ 2100-01-01），毫秒级为秒级 ×1000
_TS_EPOCH_MIN_SEC = 1_000_000_000
_TS_EPOCH_MAX_SEC = 4_102_444_800
_TS_EPOCH_MIN_MS = 1_000_000_000_000
_TS_EPOCH_MAX_MS = 41_024_448_000_000


def _is_epoch_candidate(value: str) -> bool:
    """单个样本是否落在 Unix 时间戳候选值域（秒或毫秒）.

    负数不是候选（validate_value 拒绝负值，双向一致）；
    10 位以内 < 1e9、11/12/14 位的整数落在两值域间隙，均判非候选。
    """
    if not value.isdigit():
        return False
    n = int(value)
    return _TS_EPOCH_MIN_SEC <= n <= _TS_EPOCH_MAX_SEC or _TS_EPOCH_MIN_MS <= n <= _TS_EPOCH_MAX_MS


def _promote_to_timestamp_if_epoch_like(inferred_type: str, samples: list[str]) -> str:
    """列级表决：number 列 ≥80% 样本落入 Unix 秒/毫秒候选值域则提升 timestamp.

    单个 10/13 位整数与普通编号（订单号、用户 ID）无法区分，必须整列表决 ——
    编号列值域散布或带固定前缀，命中率难达阈值；时间戳列几乎全列命中。
    10/13 位混合列按值域并集判定。
    """
    if inferred_type != "number" or not samples:
        return inferred_type
    hit = sum(1 for v in samples if _is_epoch_candidate(v))
    if hit * 5 >= len(samples) * 4:
        return "timestamp"
    return inferred_type


def _promote_to_longtext_if_chunky(inferred_type: str, samples: list[str]) -> str:
    """text 列含换行样本或大比例超长样本时提升为 longtext（多行文本）.

    须在 multiselect/select 提升之前调用 —— 含换行的文本不是合格的 select
    选项；提升后 multiselect/select 因类型守卫（仅 text/json 可提升）自然跳过。
    阈值保守取值（任一换行 或 ≥20% 样本 ≥200 字符），避免普通备注列误提升。
    """
    if inferred_type != "text" or not samples:
        return inferred_type
    if any("\n" in v for v in samples):
        return "longtext"
    long_hits = sum(1 for v in samples if len(v) >= 200)
    if long_hits * 5 >= len(samples):
        return "longtext"
    return inferred_type


# ── multiselect 列表值识别启发式参数 ──────────────────────
_LIST_LIKE_MIN_SEGMENTS = 2  # 单值最少拆出段数（1 段是普通文本）
_LIST_LIKE_MAX_SEGMENTS = 6  # 单值最多拆出段数（过多像自由文本）
_LIST_LIKE_MAX_SEGMENT_LEN = 12  # 单段最大字符数（过长像地址/句子片段）
_LIST_LIKE_MIN_OPTIONS = 3  # 列级提升：拆出选项数下限（过少像"姓名,性别"个人信息串）
_LIST_LIKE_MAX_OPTIONS = 30  # 列级提升：拆出选项数上限
_LIST_SEGMENT_SENTENCE_PUNCT_RE = re.compile(r"[。！？!?]")  # 段内句读 → 像句子片段


def _split_list_like(value: str) -> list[str] | None:
    """若值像"分隔符连接的离散选项列表"则返回拆分结果，否则 None.

    守卫（任一命中即判非列表）：
    - 无分隔符（, ， ; ； 、）或拆出段数超出 2~6；
    - 含空段（如 "a,,b" / 尾随分隔符）—— 结构可疑；
    - 段长超过 12 字符、段内含空白或句读 —— 像地址/英文句子片段；
    - 段可归一为数字 —— 千分位（1,234）或欧式小数（1,5）而非列表。
    """
    v = value.strip()
    if not v or not MULTI_SELECT_SPLIT_RE.search(v):
        return None
    parts = [p.strip() for p in MULTI_SELECT_SPLIT_RE.split(v)]
    if any(not p for p in parts):
        return None
    if not (_LIST_LIKE_MIN_SEGMENTS <= len(parts) <= _LIST_LIKE_MAX_SEGMENTS):
        return None
    for seg in parts:
        if len(seg) > _LIST_LIKE_MAX_SEGMENT_LEN or " " in seg:
            return None
        if _LIST_SEGMENT_SENTENCE_PUNCT_RE.search(seg) or _normalize_numeric(seg) is not None:
            return None
    return parts


def _split_json_array_like(value: str) -> list[str] | None:
    """若样本是"标量 JSON 数组"（如 ``["前端", "后端"]`` 的 dumps 串）则返回元素列表，否则 None.

    与 :func:`_split_list_like` 的字符串歧义守卫不同，数组元素已是离散值，
    仅保留存储安全守卫：
    - 可被 json.loads 解析为 list；
    - 全部元素为标量（str/int/float/bool，嵌套 list/dict 判非）；
    - 元素转字符串后非空且不含分隔符（含分隔符的元素逗号连接存储后有歧义）。
    """
    v = value.strip()
    if not v.startswith("["):
        return None
    try:
        parsed = json.loads(v)
    except ValueError:
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    if len(parsed) > _LIST_LIKE_MAX_OPTIONS:
        return None
    segments: list[str] = []
    for item in parsed:
        if isinstance(item, (dict, list)) or item is None:
            return None
        s = str(item).strip()
        if not s or MULTI_SELECT_SPLIT_RE.search(s):
            return None
        segments.append(s)
    return segments


def _promote_to_multiselect_if_list_like(
    inferred_type: str,
    samples: list[str],
    parser: Any = None,
) -> tuple[str, list[str]]:
    """对推断后的列类型做列表值检查：多数值可拆出高复用选项则提升为 multiselect.

    须在 select 提升之前调用 —— 低基数列表值（如 ["a,b","a,c"]）的唯一原始值
    同样满足 select 低基数条件，会被 select 抢走。

    Args:
        inferred_type: 列推断类型；text 走分隔符串拆分，json 走标量数组解析（parser 传入），
            其余类型已有归属不提升。
        samples: 列样本值字符串列表。
        parser: 单值拆分函数（str → list[str] | None），默认分隔符串拆分。

    守卫：
    - ≥60% 且至少 2 个样本可拆出列表（混合列中以离散选项为主才安全）；
    - 拆出选项总数 3~30；
    - ≥50% 的选项在 ≥2 个值中复用 —— 排除"张三,男,北京"式逐行唯一个人信息串。

    Returns:
        (最终字段类型, 拆分后的选项列表 — 若最终为 multiselect 则作为 options 使用, 否则为空列表)
    """
    split_fn = parser or _split_list_like
    if inferred_type not in ("text", "json"):
        return inferred_type, []
    parsed = [split_fn(v) for v in samples]
    hit = [segs for segs in parsed if segs is not None]
    if len(hit) < 2 or len(hit) * 10 < len(samples) * 6:
        return inferred_type, []
    option_counts: dict[str, int] = {}
    for segs in hit:
        for s in set(segs):
            option_counts[s] = option_counts.get(s, 0) + 1
    if not (_LIST_LIKE_MIN_OPTIONS <= len(option_counts) <= _LIST_LIKE_MAX_OPTIONS):
        return inferred_type, []
    reused = sum(1 for c in option_counts.values() if c >= 2)
    if reused < len(option_counts) * 0.5:
        return inferred_type, []
    options: list[str] = []
    for segs in hit:
        for s in segs:
            if s not in options:
                options.append(s)
    return "multiselect", options


def promote_inferred_column_type(inferred: str, samples: list[str]) -> tuple[str, list[str]]:
    """对已推断的列类型运行完整提升链 —— 列级类型推断的单一收口.

    链序固定为 timestamp → longtext → multiselect → select（后两者顺序
    不可交换：低基数列表值同样满足 select 低基数条件，先到先得）。
    analyze_csv_columns / column_profiler / diff_reporter 三处入口统一
    经本函数做二次提升，保证同一列在预览、画像、落库三侧类型一致。

    Args:
        inferred: 已由单值推断 + 众数投票得到的列类型.
        samples: 列非空样本字符串列表（非 str 值由调用方 str() 归一）.

    Returns:
        (最终字段类型, options 列表 —— multiselect/select 提升命中时非空)
    """
    inferred = _promote_to_timestamp_if_epoch_like(inferred, samples)
    inferred = _promote_to_longtext_if_chunky(inferred, samples)
    inferred, options = _promote_to_multiselect_if_list_like(inferred, samples)
    if not options:
        inferred, options = _promote_to_select_if_low_cardinality(inferred, samples)
    return inferred, options


def infer_column_type(samples: list[str]) -> tuple[str, list[str]]:
    """从非空字符串样本推断列类型（单值推断 → 众数 → 完整提升链）.

    供 analyze_csv_columns / diff_reporter 等以字符串样本为输入的入口复用；
    column_profiler 因需处理非 str 原始值分类，计数自持、仅复用提升链.

    Returns:
        (最终字段类型, options 列表 —— 提升命中时非空)
    """
    type_counts: dict[str, int] = {}
    for v in samples:
        t = _infer_single_value(v)
        if t != "empty":
            type_counts[t] = type_counts.get(t, 0) + 1
    inferred = _pick_inferred_type(type_counts) if type_counts else "text"
    return promote_inferred_column_type(inferred, samples)
