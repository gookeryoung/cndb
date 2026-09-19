"""导入导出 — CSV/XLSX 导入 + JSON/XLSX 导出.

link 字段约定：
- 导出：行响应中 link 值为 [{"id", "value"}] 摘要列表，序列化为分号分隔的目标行 id 串；
- 导入：CSV/XLSX 中 link 列的分号分隔 id 串（或单个 id）解析回列表写入关联表.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import date
from typing import Any

from cndb.plugins.tables import records as rec
from cndb.plugins.tables.ddl import create_table as ddl_create
from cndb.plugins.tables.ddl import drop_table as ddl_drop
from cndb.plugins.tables.field_types import MULTI_SELECT_SPLIT_RE
from cndb.plugins.tables.links import is_link_field
from cndb.plugins.tables.models import DataField, DataTable, ensure_default_view

logger = logging.getLogger(__name__)


# ── 编码自动检测 ──────────────────────────────────────

# 优先级编码列表：先去 BOM，再按常见度逐一尝试
_ENCODING_CANDIDATES: list[str] = [
    "utf-8-sig",  # 带/不带 BOM 的 UTF-8
    "utf-8",
    "gb18030",  # 覆盖 GBK + GB2312 全部字符集（中国 Windows 默认 ANSI 代码页 CP936 等价）
    "gbk",
    "big5",  # 繁体中文
    "utf-16",  # BOM 自动判别 LE/BE
    "latin-1",  # 兜底（永远不会失败）
]


def decode_bytes_auto(data: bytes) -> tuple[str, str, float]:
    """对原始字节做编码自动检测并解码为文本.

    依次尝试 ``_ENCODING_CANDIDATES`` 中的编码，第一个成功解码且
    不可打印字符占比低于 5% 的即为最终结果；全部失败时再走 chardet.detect()，
    仍不行则 fallback 到 latin-1.

    Returns:
        (解码后的文本, 实际使用的编码, 置信度 0-1)
    """
    if not isinstance(data, bytes):
        return data, "utf-8", 1.0

    for enc in _ENCODING_CANDIDATES:
        try:
            text = data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        # 质量检查：如果出现过多不可打印字符，跳过
        if text:
            bad = sum(1 for c in text if not c.isprintable() and c not in "\r\n\t")
            if bad / len(text) >= 0.05:
                continue
        return text, enc, 1.0

    # chardet 兜底（只接受 confidence ≥ 0.5 的结果，低置信度视为盲猜）
    try:
        import chardet

        detection = chardet.detect(data)
        chardet_enc = detection.get("encoding")
        chardet_conf = float(detection.get("confidence") or 0.0)
        if chardet_enc and chardet_enc.lower() != "ascii" and chardet_conf >= 0.5:
            # chardet 可能返回 "EUC-JP" 之类 Python 也能解，尝试
            try:
                text = data.decode(chardet_enc)
                if text:
                    bad = sum(1 for c in text if not c.isprintable() and c not in "\r\n\t")
                    if bad / len(text) < 0.10:
                        return text, chardet_enc, chardet_conf
            except (UnicodeDecodeError, LookupError):
                pass
    except Exception:  # chardet 自身也可能失败
        logger.debug("chardet 检测失败，继续 latin-1 兜底", exc_info=True)

    # 兜底（理论上 latin-1 永远会命中，不会走到这里）
    logger.warning("所有候选编码均未通过质量检查，使用 latin-1 兜底")
    return data.decode("latin-1"), "latin-1", 0.5


def sniff_csv_delimiter(text: str) -> str:
    """从文本中嗅探 CSV 分隔符 —— 优先 csv.Sniffer，失败按候选分隔符计数.

    Returns:
        单字符分隔符：',' / ';' / '\\t' / '|'
    """
    if not text.strip():
        return ","
    # 先尝试 csv.Sniffer
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
        if dialect.delimiter in (",", ";", "\t", "|"):
            return dialect.delimiter
    except (csv.Error, Exception):
        pass
    # 退化：按候选分隔符统计头 10 行出现频率，选第一行里计数最高的
    candidates = [",", ";", "\t", "|"]
    first_lines = text.splitlines()[:10]
    best_delim = ","
    best_score = -1
    for d in candidates:
        # 好分隔符应该在每行里出现次数相近且 >= 1
        scores = [line.count(d) for line in first_lines if d in line]
        if not scores:
            continue
        # 稳定出现 + 次数多加分
        avg = sum(scores) / len(scores)
        variance = sum((s - avg) ** 2 for s in scores) / len(scores)
        score = avg - variance  # 方差小且均值大 → 好分隔符
        if score > best_score:
            best_score = score
            best_delim = d
    return best_delim


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


# ── CSV 列类型推断辅助 ──────────────────────────────────


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


def _options_strings_to_dicts(options: list[str]) -> list[dict[str, Any]]:
    """把 list[str] 格式的 select options 转为 [{label, value}] 字典格式.

    供 transfer / importer 在持久化 DataField.config 前调用，保证与
    SelectFieldConfig._normalize_options 及前端消费方约定一致。
    """
    return [{"label": o, "value": o} for o in options]


def _infer_decimals_config(field_type: str, sample_values: list[Any]) -> dict[str, Any]:
    """按样本推断 float/number 字段的 decimals 配置.

    根因：NumberFieldConfig.decimals 默认 0，float 字段不设置时
    ``round(5.5, 0) == 6``，导入的小数会被静默取整丢失精度.
    """
    if field_type not in ("float", "number"):
        return {}
    max_dec = 0
    for s in sample_values[:50]:
        text = str(s)
        if "." not in text:
            continue
        try:
            dec = len(text.split(".", 1)[1])
        except (TypeError, ValueError):
            continue
        max_dec = max(max_dec, dec)
    return {"decimals": min(max_dec, 10) if max_dec > 0 else 2}


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
        # multiselect 提升须在 select 之前：低基数列表值同样满足 select 低基数条件会被抢走
        inferred, promote_options = _promote_to_multiselect_if_list_like(inferred, samples)
        if not promote_options:
            inferred, promote_options = _promote_to_select_if_low_cardinality(inferred, samples)

        col_info: dict[str, Any] = {
            "name": name,
            "field_type": inferred,
            "sample_values": samples[:5],
            "null_ratio": round(null_ratio, 4),
        }
        if promote_options:
            col_info["options"] = promote_options
        columns.append(col_info)

    return columns, total_rows


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


def _prefill_before_bulk(db: Any, table: DataTable, rows: list[dict[str, Any]]) -> None:
    """bulk_create 前：从待导入行预填充 select/multiselect options，让后续值校验通过.

    db 可为 None（纯 engine 场景），此时跳过不报错.
    """
    if not db or not rows:
        return
    try:
        from cndb.plugins.tables.field_ops import prefill_select_options_from_rows

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
        from cndb.plugins.tables.field_ops import sync_select_options_from_table

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
    import json

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
    # 把 CSV 空单元格（空字符串或仅空白）归一为 None — 否则 number/date 等类型校验会因 '' 抛 ValueError
    rows = []
    for r in reader:
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
    header = [str(c) for c in rows[0]]
    # 长数字保护：对每个单元格值做精度保护转换
    data = [
        _parse_link_import_value(
            table,
            {k: _coerce_long_numeric_to_text(v) for k, v in zip(header, row, strict=False)},
        )
        for row in rows[1:]
        if any(c is not None for c in row)
    ]
    _prefill_before_bulk(db, table, data)
    ids = rec.bulk_create(engine, table, data, db=db)
    _sync_after_bulk(db, table)
    return ids


def guess_format_from_filename(filename: str) -> str:
    """根据文件名推断格式（json/csv/tsv/xlsx）.

    不支持旧版 ``.xls``（BIFF 格式），openpyxl 无法解析；
    用户需另存为 ``.xlsx`` 再导入。
    """
    lower = filename.lower()
    if lower.endswith(".xlsx"):
        return "xlsx"
    if lower.endswith(".tsv"):
        return "tsv"
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith(".json"):
        return "json"
    if lower.endswith(".xls"):
        raise ValueError("不支持旧版 .xls 格式，请在 Excel 中另存为 .xlsx 后再导入")
    raise ValueError(f"无法从文件名推断格式: {filename}")


# ── JSON 数组类型推断 ──────────────────────────────────


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


def _python_type_to_field_type(value: Any) -> str:
    """把 Python 对象直接映射到字段类型（JSON 推断的第一捷径）."""
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
    return "text"


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
        # multiselect 提升须在 select 之前；含 dict 编码样本的列不做列表提升
        # （dict 行落 multiselect 会把 "{'a': 1, 'b': 2}" 拆出垃圾选项）
        col_samples = samples[key]
        promote_options: list[str] = []
        if not any(s.lstrip().startswith("{") for s in col_samples):
            parser = _split_json_array_like if inferred == "json" else None
            inferred, promote_options = _promote_to_multiselect_if_list_like(inferred, col_samples, parser)
        if not promote_options:
            inferred, promote_options = _promote_to_select_if_low_cardinality(inferred, col_samples)

        col_info: dict[str, Any] = {
            "name": key,
            "field_type": inferred,
            "sample_values": col_samples[:5],
            "null_ratio": round(null_ratio, 4),
        }
        if promote_options:
            col_info["options"] = promote_options
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


# ── 通用文件解析 / 分析 / 建表 ───────────────────────────


def parse_file_to_rows(
    content: bytes | str,
    format: str | None = None,
    *,
    filename: str | None = None,
) -> tuple[list[dict[str, Any]], list[str], str]:
    """把任意支持的文件内容转为 (行列表, 文件列名, 实际使用的 format).

    支持：csv / tsv / delimited / json / xlsx / xls（拒绝）.
    format 未指定时：优先用 filename 推断，退化到内容特征推断.

    Returns:
        (rows, file_columns, actual_format)
    """
    from cndb.plugins.tables.importer import guess_format_from_content

    # 1) 确定 format
    actual_fmt = format
    if actual_fmt is None and filename is not None:
        try:
            actual_fmt = guess_format_from_filename(filename)
        except ValueError:
            actual_fmt = None
    if actual_fmt is None:
        actual_fmt = guess_format_from_content(content)

    # 2) 统一转 bytes 解码（文本类）或直接 bytes（二进制类）
    if actual_fmt == "xlsx":
        # openpyxl 只吃 bytes
        raw = content if isinstance(content, bytes) else content.encode("utf-8")
        rows, cols = _parse_xlsx_bytes(raw)
        return rows, cols, "xlsx"

    if actual_fmt == "json":
        if isinstance(content, bytes):
            text, _enc, _conf = decode_bytes_auto(content)
        else:
            text = content
        rows, cols = _parse_json_text(text)
        return rows, cols, "json"

    # csv / tsv / delimited — 统一走分隔符文本解析
    if isinstance(content, bytes):
        text, _enc, _conf = decode_bytes_auto(content)
    else:
        text = content
    delim = "\t" if actual_fmt == "tsv" else None
    rows, cols = _parse_delimited_text(text, delimiter=delim)
    return rows, cols, actual_fmt


def _parse_delimited_text(
    text: str,
    *,
    delimiter: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """解析分隔符文本（逗号/分号/pipe/tab 自动 sniff）."""
    delim = delimiter or sniff_csv_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    file_columns = list(reader.fieldnames or [])
    rows: list[dict[str, Any]] = []
    for r in reader:
        cleaned = {}
        for k, v in r.items():
            if isinstance(v, str):
                stripped = v.strip()
                cleaned[k] = None if stripped == "" else stripped
            else:
                cleaned[k] = v
        rows.append(cleaned)
    return rows, file_columns


def _parse_json_text(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """解析 JSON 对象数组文本."""
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("JSON 必须是对象数组")
    file_columns: list[str] = []
    seen: set[str] = set()
    for item in data:
        if isinstance(item, dict):
            for k in item:
                if k not in seen:
                    seen.add(k)
                    file_columns.append(k)
    return [r for r in data if isinstance(r, dict)], file_columns


def _parse_xlsx_bytes(xlsx_bytes: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """解析 XLSX 字节串."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(xlsx_bytes))
    ws = wb.active
    assert ws is not None
    all_rows = list(ws.iter_rows(values_only=True))
    if not all_rows:
        return [], []
    file_columns = [str(c) if c is not None else f"col_{i}" for i, c in enumerate(all_rows[0])]
    rows: list[dict[str, Any]] = []
    for r in all_rows[1:]:
        if not any(c is not None for c in r):
            continue
        row_dict: dict[str, Any] = {}
        for i, key in enumerate(file_columns):
            v = r[i] if i < len(r) else None
            if isinstance(v, str):
                stripped = v.strip()
                row_dict[key] = None if stripped == "" else stripped
            else:
                # 长数字保护：避免 Excel 数值精度经 JSON/JS 链路进一步丢失
                row_dict[key] = _coerce_long_numeric_to_text(v)
        rows.append(row_dict)
    return rows, file_columns


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
    "analyze_file_columns",
    "analyze_json_columns",
    "create_table_from_csv",
    "create_table_from_file",
    "create_table_from_json_data",
    "decode_bytes_auto",
    "export_rows_to_csv",
    "export_rows_to_json",
    "export_rows_to_xlsx",
    "guess_format_from_filename",
    "import_rows_from_csv",
    "import_rows_from_json",
    "import_rows_from_xlsx",
    "ingest_from_api",
    "parse_file_to_rows",
    "sniff_csv_delimiter",
]
