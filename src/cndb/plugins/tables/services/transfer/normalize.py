"""列类型推断与值归一 — 单值推断、众数投票、类型提升链、精度保护.

被 transfer 包内各模块及 importing.cleaning / column_profiler /
diff_reporter / field_types / cli 广泛复用的类型规整基础层。
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from cndb.plugins.tables.field_types import MULTI_SELECT_SPLIT_RE

# ── 列类型推断正则 ──────────────────────────────────────

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")
_URL_RE = re.compile(r"^https?://[\w.-]+(?::\d+)?(?:/[\w./?#=&%+-]*)?$", re.IGNORECASE)
_PHONE_RE = re.compile(r"^[\d+\-() ]{7,20}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:[Z+\-]\d{2}:?\d{2})?$")
# 中文日期：2024年1月1日 / 2024年01月01日 / 2024年1月1（"日"可省略）
_CN_DATE_RE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?$")
# 通用日期：2024/1/1 / 01-01-2024 / 2024.1.1（月日均 1-2 位，分隔符须一致）
_GENERIC_DATE_RE = re.compile(r"^(?:(\d{4})([/\-.])(\d{1,2})\2(\d{1,2})|(\d{1,2})([/\-.])(\d{1,2})\6(\d{4}))$")
# 紧凑日期：20240115（8 位纯数字，年月日合法性另校验）
_COMPACT_DATE_RE = re.compile(r"^\d{8}$")
# 通用日期时间：2024/1/15 10:30 / 2024.1.15 10:30:45（年前置，月日 1-2 位）
_GENERIC_DATETIME_RE = re.compile(r"^(\d{4})([/\-.])(\d{1,2})\2(\d{1,2})[T ]\d{1,2}:\d{2}(?::\d{2})?$")
# 英文月名日期：Jan 15, 2024 / 15 Jan 2024（缩写或全称，逗号可选）
_EN_DATE_PREFIX_RE = re.compile(r"^([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})$")
_EN_DATE_SUFFIX_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3,9}),?\s+(\d{4})$")
# 英文月份名 → 月份数值（缩写 + 全称）
_EN_MONTHS: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
# 科学计数法：1.5e10 / -1.5E-3（点可能属于指数部分，不能当千分位归一）
_SCI_NOTATION_RE = re.compile(r"^[+-]?\d*\.?\d+[eE][+-]?\d+$")
# 全角数字/符号 → 半角（数字、点、负号、加号、百分号、括号、逗号）
_FULLWIDTH_TRANSLATION = str.maketrans("０１２３４５６７８９．－＋％（），", "0123456789.-+%(),")

# 布尔值域（与 field_types.BooleanFieldType 的转换值域保持一致，测试矩阵双向锁定）
_BOOLEAN_TRUE_VALUES = frozenset({"true", "yes", "1", "on", "是", "真", "对", "y", "t", "√"})
_BOOLEAN_FALSE_VALUES = frozenset({"false", "no", "0", "off", "否", "假", "错", "n", "f", "×"})


def _is_boolean(value: str) -> bool:
    """判断值是否属于布尔值域（含中文 真/假、对/错、Y/N、√/× 等）."""
    low = value.strip().lower()
    return low in _BOOLEAN_TRUE_VALUES or low in _BOOLEAN_FALSE_VALUES


def _is_valid_date(y: int, m: int, d: int) -> bool:
    """校验年月日是否为真实存在的日期（如 2024-02-30、2024-13-01 均非法）."""
    try:
        date(y, m, d)
    except ValueError:
        return False
    return True


def _normalize_numeric(value: str) -> str | None:
    """尝试把带千分位/货币符号的数字归一为纯数字字符串.

    支持：
    - 逗号千分位: 1,234 → 1234
    - 逗号小数: 1,5 → 1.5
    - 欧元点千分位 + 逗号小数: 1.234,56 → 1234.56
    - 负数、货币符号 ¥ $ ￥
    - 科学计数法: 1.5e10 → 1.5e10（短路，不走千分位归一，避免点被误删）
    - 会计负数: (1,234) → -1234
    - 全角数字/符号: １２３ → 123
    """
    s = value.strip()
    if not s:
        return None
    # 全角数字/符号归一（０-９ ．－＋％（），）
    s = s.translate(_FULLWIDTH_TRANSLATION)
    # 去掉货币符号
    s = s.replace("¥", "").replace("￥", "").replace("$", "").replace("€", "").strip()
    if not s:
        return None
    # 会计负数：(1,234) → -1234；括号内非法则整体判非数字
    if s.startswith("(") and s.endswith(")") and len(s) > 2:
        inner = _normalize_numeric(s[1:-1].strip())
        if inner is None:
            return None
        return inner[1:] if inner.startswith("-") else "-" + inner
    # 科学计数法短路：点/逗号可能属于指数部分，不能当千分位处理（如 1.5e10 ≠ 15e10）
    if _SCI_NOTATION_RE.match(s):
        try:
            float(s)
        except ValueError:
            return None
        return s
    negative = False
    if s.startswith("-"):
        negative = True
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]
    if not s:
        return None

    # 欧元点格式：只有一个逗号且后面跟 1-2 位数字 → 逗号是小数点，点是千分位
    # 如 "1.234,56" 最后一个逗号在最后 3 位里
    last_comma = s.rfind(",")
    last_dot = s.rfind(".")
    normalized = s
    if last_comma > 0 and last_dot > 0:
        # 同时有逗号和点 —— 看哪个在后面
        if last_comma > last_dot:
            # 逗号在后面 → 欧元点格式
            # 去掉所有点（千分位），把最后一个逗号换成点
            normalized = s.replace(".", "")
            normalized = normalized.rsplit(",", 1)[0] + "." + normalized.rsplit(",", 1)[1]
        else:
            # 点在后面 → 点是小数点，逗号是千分位（国际格式）
            normalized = s.replace(",", "")
    elif last_comma > 0:
        # 只有逗号 —— 判断是小数还是千分位
        after = s[last_comma + 1 :]
        if 1 <= len(after) <= 2 and after.isdigit() and "," not in after:
            # 末尾 1-2 位 → 逗号作小数点（欧洲习惯）
            normalized = s.replace(",", ".", 1)
        else:
            # 千分位逗号
            normalized = s.replace(",", "")
    elif last_dot > 0:
        # 只有点 —— 小数或千分位
        after = s[last_dot + 1 :]
        if len(after) <= 2 and after.isdigit():
            # 末尾 1-2 位 → 点作小数点
            pass  # 已经是标准小数
        else:
            # 点是千分位
            normalized = s.replace(".", "")

    # 归一化后必须是合法数字
    try:
        float(normalized)
    except ValueError:
        return None
    if negative:
        normalized = "-" + normalized
    return normalized


def _is_integer(value: str) -> bool:
    """判断是否为整数（含负数、千分位逗号/点、货币符号）."""
    normalized = _normalize_numeric(value)
    if normalized is None:
        return False
    if normalized.startswith("-"):
        normalized = normalized[1:]
    if "." in normalized or "e" in normalized.lower():
        return False
    if not normalized.isdigit():
        return False
    return not (len(normalized) >= 11 and normalized.startswith("0"))


def _is_float(value: str) -> bool:
    """判断是否为小数（含千分位、欧元点格式）."""
    normalized = _normalize_numeric(value)
    if normalized is None:
        return False
    if "." not in normalized and "e" not in normalized.lower():
        return False
    try:
        float(normalized)
        return True
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
        (_check_json_string, "json"),
        (_check_percentage, "percentage"),
        (lambda x: bool(_ISO_DATETIME_RE.match(x)), "datetime"),
        (_check_generic_datetime, "datetime"),
        (_check_iso_date, "date"),
        (_check_cn_date, "date"),
        (_check_generic_date, "date"),
        (_check_compact_date, "date"),
        (_check_en_date, "date"),
        (_check_phone, "phone"),
        (_check_long_integer, "text"),
        (_is_integer, "number"),
        (_is_float, "float"),
    ]
    for check_fn, result_type in checks:
        if check_fn(v):
            return result_type
    return "text"


def _check_json_string(v: str) -> bool:
    """判断是否为 JSON 对象/数组字符串（{ 或 [ 开头且可被 json.loads 解析）."""
    if not v or v[0] not in "{[":
        return False
    try:
        json.loads(v)
    except ValueError:
        return False
    return True


def _check_percentage(v: str) -> bool:
    """判断是否为百分比字符串（支持全角％）."""
    if v.endswith("％"):
        v = v[:-1] + "%"
    return v.endswith("%") and (_is_float(v[:-1]) or _is_integer(v[:-1]))


def _check_iso_date(v: str) -> bool:
    """ISO 日期 2024-01-15（含年月日合法性校验，2024-02-30 非法）."""
    if _ISO_DATE_RE.match(v) is None:
        return False
    return _is_valid_date(int(v[:4]), int(v[5:7]), int(v[8:10]))


def _check_cn_date(v: str) -> bool:
    """中文日期 2024年1月1日（"日"可省略，含合法性校验）."""
    m = _CN_DATE_RE.match(v)
    if m is None:
        return False
    return _is_valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _check_generic_date(v: str) -> bool:
    """通用日期 2024/1/15、2024.1.15、1/15/2024（含合法性校验）.

    前 4 位为年 → (年, 月, 日)；后 4 位为年 → 美式 (月, 日, 年)，月 >12 判非法回落 text.
    """
    m = _GENERIC_DATE_RE.match(v)
    if m is None:
        return False
    if m.group(1) is not None:
        y, mo, d = int(m.group(1)), int(m.group(3)), int(m.group(4))
    else:
        mo, d, y = int(m.group(5)), int(m.group(7)), int(m.group(8))
    return _is_valid_date(y, mo, d)


def _check_compact_date(v: str) -> bool:
    """紧凑日期 20240115（年份限 1900-2100 且月日合法，否则回落 number/text）."""
    if _COMPACT_DATE_RE.match(v) is None:
        return False
    y, m, d = int(v[:4]), int(v[4:6]), int(v[6:8])
    if not (1900 <= y <= 2100):
        return False
    return _is_valid_date(y, m, d)


def _check_en_date(v: str) -> bool:
    """英文月名日期 Jan 15, 2024 / 15 Jan 2024（缩写或全称，含合法性校验）."""
    m = _EN_DATE_PREFIX_RE.match(v)
    if m is not None:
        mon = _EN_MONTHS.get(m.group(1).lower())
        day, year = int(m.group(2)), int(m.group(3))
    else:
        m2 = _EN_DATE_SUFFIX_RE.match(v)
        if m2 is None:
            return False
        day, year = int(m2.group(1)), int(m2.group(3))
        mon = _EN_MONTHS.get(m2.group(2).lower())
    if mon is None:
        return False
    return _is_valid_date(year, mon, day)


def _check_generic_datetime(v: str) -> bool:
    """斜杠/点分隔日期+时间 2024/1/15 10:30(:45) → datetime（含日期合法性校验）."""
    m = _GENERIC_DATETIME_RE.match(v)
    if m is None:
        return False
    return _is_valid_date(int(m.group(1)), int(m.group(3)), int(m.group(4)))


def _check_long_integer(v: str) -> bool:
    """判断是否应把整数型字符串视为 text.

    规则：
    1. 前导零风格的数字串（如 ``01234567890``）—— 明显是非数值编号（邮政编码、账号等）.
    2. 十进制位数 >= 15 的纯数字串 —— 超过 double 精度边界（2^53 ≈ 9e15），
       作为 number 存库后经 JSON/JS 链路会精度丢失，应判为 text 保真.
    """
    if not _is_integer(v):
        return False
    num_str = v.lstrip("-").replace(",", "")
    if num_str.startswith("0") and len(num_str) >= 11:
        return True
    # 15 位以上的纯整数一律判为 text，避免精度丢失
    return len(num_str) >= 15


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


# ── Excel 长数字精度保护 ──────────────────────────────

# double 能精确表示的最大整数（IEEE 754 52 位尾数）
_DOUBLE_MAX_EXACT_INT = 2**53  # 9007199254740992

# 超过该位数的数字视为"长数字"，需转回字符串避免精度丢失
_LONG_INT_DIGITS_THRESHOLD = 15


def _coerce_long_numeric_to_text(value: Any) -> Any:
    """把 openpyxl 读出的长整数型数值转回字符串.

    根因：Excel 用 IEEE 754 双精度浮点存储数值，有效数字约 15-16 位；
    openpyxl 对 17+ 位长数字直接返回 float，精度已在 Excel 存储层丢失；
    对 16 位数字返回 Python int，但经 JSON 序列化到 JavaScript 后，
    Number 类型同样因 IEEE 754 精度限制再次截断。

    策略：对 int / float 值，若绝对值超过 2^53（或十进制位数 >= 15），
    转成字符串返回，避免精度在任何环节进一步丢失。

    Args:
        value: openpyxl 读出的单元格值（int / float / str / datetime / None）.

    Returns:
        原值或转换后的字符串.
    """
    if value is None:
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) >= _DOUBLE_MAX_EXACT_INT:
            return str(value)
        if len(str(abs(value))) >= _LONG_INT_DIGITS_THRESHOLD:
            return str(value)
        return value
    if isinstance(value, float):
        # 无小数部分的 float 且位数较长 → 转回字符串（openpyxl 对 17+ 位数字返回 float）
        if value.is_integer() and abs(value) >= _DOUBLE_MAX_EXACT_INT:
            # 用 repr 形式可能带科学计数法，需用 int 转回来再 str
            int_val = int(value)
            return str(int_val)
        # 位数 >= 15 的整数型 float → 转回字符串
        if value.is_integer() and len(str(abs(int(value)))) >= _LONG_INT_DIGITS_THRESHOLD:
            return str(int(value))
        return value
    return value


def _classify_date_like(value: Any) -> str | None:
    """date/datetime 对象 → 推断字段类型；非日期对象返回 None.

    Excel 纯日期单元格经 openpyxl 读出为午夜 datetime（不含时间信息），
    归一为 date 类型，使纯日期列推断为 date 而非 datetime；
    带时间信息的 datetime 推断为 datetime。

    注意分支顺序：isinstance(datetime_obj, date) 恒为 True，datetime 须先判。
    """
    if isinstance(value, datetime):
        midnight = (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0)
        return "date" if midnight else "datetime"
    if isinstance(value, date):
        return "date"
    return None


def _format_date_like_sample(value: Any) -> str | None:
    """date/datetime 对象 → ISO 样本字符串；非日期对象返回 None.

    date 与午夜 datetime 输出 "YYYY-MM-DD"（避免 select options / 样本值
    出现 "00:00:00" 尾巴）；带时间 datetime 输出空格分隔 ISO 串
    （与 _ISO_DATETIME_RE 的 ``[T ]`` 分支及落库 strptime 格式清单一致）。
    """
    kind = _classify_date_like(value)
    if kind is None:
        return None
    if kind == "date":
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return value.isoformat(sep=" ")


def _python_type_to_field_type(value: Any) -> str:
    """把 Python 对象直接映射到字段类型（JSON 推断的第一捷径）.

    日期类对象（xlsx 单元格经 openpyxl 读出的 datetime/date）映射到
    date/datetime 字段类型，见 _classify_date_like。
    """
    if value is None:
        return "empty"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        # 长整型（>= 15 位 或 >= 2^53）应当作 text，避免 JSON/JS 精度丢失
        if abs(value) >= _DOUBLE_MAX_EXACT_INT or len(str(abs(value))) >= _LONG_INT_DIGITS_THRESHOLD:
            return "text"
        return "number"
    if isinstance(value, float):
        # 整数型长 float（openpyxl 对 17+ 位数字的返回）→ 当作 text
        if value.is_integer() and (
            abs(value) >= _DOUBLE_MAX_EXACT_INT or len(str(abs(int(value)))) >= _LONG_INT_DIGITS_THRESHOLD
        ):
            return "text"
        return "float"
    if isinstance(value, str):
        if not value.strip():
            return "empty"
        return _infer_single_value(value)
    if isinstance(value, (list, dict)):
        return "json"
    date_like = _classify_date_like(value)
    if date_like is not None:
        return date_like
    return "text"
