"""单值级类型推断：正则、布尔、数值归一与各类日期/JSON/手机号识别.

不含列级提升逻辑（见 promote.py）与 Excel 精度保护（见 coerce.py）。
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

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
