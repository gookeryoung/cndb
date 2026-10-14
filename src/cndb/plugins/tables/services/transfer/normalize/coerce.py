"""跨层共用的小工具：Excel 长数字精度保护、日期分类、图片元数据识别与 Python 类型映射."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from cndb.plugins.tables.field_types import is_image_meta
from cndb.plugins.tables.services.transfer.normalize.values import _infer_single_value

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


def _looks_like_image_metadata_list(value: Any) -> bool:
    """判断值是否为图片元数据列表（WPS 单元格图片解析产物 / 附件同构值）.

    非空 ``list[dict]`` 且每项均为图片元数据（mime_type 以 image/ 开头
    或 filename 为图片扩展名）→ True。普通 JSON 数组 / 标量列表不受影响。
    """
    if not isinstance(value, list) or not value:
        return False
    return all(isinstance(item, dict) and is_image_meta(item) for item in value)


def _python_type_to_field_type(value: Any) -> str:
    """把 Python 对象直接映射到字段类型（JSON 推断的第一捷径）.

    日期类对象（xlsx 单元格经 openpyxl 读出的 datetime/date）映射到
    date/datetime 字段类型，见 _classify_date_like；
    图片元数据列表（WPS 单元格图片解析产物）映射到 image。
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
    if _looks_like_image_metadata_list(value):
        return "image"
    if isinstance(value, (list, dict)):
        return "json"
    date_like = _classify_date_like(value)
    if date_like is not None:
        return date_like
    return "text"
