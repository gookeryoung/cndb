"""文件解析与格式识别 — 编码检测、分隔符嗅探、CSV/XLSX/JSON 解析与结构守卫."""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Sequence
from typing import Any

from cndb.plugins.tables.services.transfer.header_detect import (
    HEADER_SCAN_ROWS,
    HeaderDetection,
    detect_header_row,
)
from cndb.plugins.tables.services.transfer.normalize import _coerce_long_numeric_to_text

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
                logger.debug("候选编码 %s 解码失败，尝试下一个", chardet_enc, exc_info=True)
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
        logger.debug("csv.Sniffer 分隔符嗅探失败，退化为计数统计", exc_info=True)
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


def _validate_csv_structure(fieldnames: Sequence[str]) -> None:
    """CSV 表头结构守卫：空列名 / 重复列名明确报错，避免静默丢数据.

    DictReader 对重复列名取后列值（前列数据静默丢失），空表头列数据无法
    按名寻址 —— 均属结构性缺陷，报错优于静默变形（与参差行导出
    extrasaction=raise 哲学一致）。少列短行不在此守卫（尾逗号截断属常态）；
    多列溢出（restkey）在行循环内检查。
    """
    seen: set[str] = set()
    dup: list[str] = []
    for name in fieldnames:
        # DictReader 对异常短的表头行会产出 None 列名，一并拦截
        if not name or not name.strip():
            raise ValueError("CSV 表头存在空列名，请检查表头行")
        if name in seen and name not in dup:
            dup.append(name)
        seen.add(name)
    if dup:
        raise ValueError(f"CSV 表头存在重复列名: {', '.join(dup)}")


def _check_csv_row_overflow(row: dict[Any, Any], line_num: int, header_len: int) -> None:
    """检查单行值数是否超出表头列数（DictReader restkey 行为），超出即报错.

    多余值通常来自字段内未转义的逗号/换行 —— 静默丢弃会丢数据，报错提示修复。
    """
    extra = row.get(None)
    if extra:
        raise ValueError(
            f"CSV 第 {line_num} 行有 {header_len + len(extra)} 个值，"
            f"超出表头列数 {header_len}，请检查值中未转义的逗号或换行"
        )


def _validate_xlsx_header(headers: list[str]) -> None:
    """XLSX 表头结构守卫：空列名 / 重复列名明确报错，语义与 CSV 守卫对齐.

    重复列名按名构建行 dict 时后列覆盖前列（前列数据静默丢失），空列名
    数据无法按名寻址 —— 均属结构性缺陷，报错优于静默变形（与 CSV 守卫
    同款决策）。取代旧的 col_{i} 静默兜底。
    """
    seen: set[str] = set()
    dup: list[str] = []
    for name in headers:
        if not name or not name.strip():
            raise ValueError("XLSX 表头存在空列名，请检查表头行")
        if name in seen and name not in dup:
            dup.append(name)
        seen.add(name)
    if dup:
        raise ValueError(f"XLSX 表头存在重复列名: {', '.join(dup)}")


def _check_xlsx_row_overflow(row_cells: Sequence[Any], sheet_row: int, header_len: int) -> None:
    """检查 XLSX 单行值数是否超出表头列数，超出即报错.

    zip 对超长行会静默截断丢数据；短行保持既有补 None 空值语义不报错
    （对齐 CSV"尾逗号截断属常态"）。sheet_row 为 1-based 的 Excel 行号。
    """
    if len(row_cells) > header_len:
        raise ValueError(
            f"XLSX 第 {sheet_row} 行有 {len(row_cells)} 个值，超出表头列数 {header_len}，请检查是否列错位或表头缺失"
        )


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


def parse_file_to_rows(
    content: bytes | str,
    format: str | None = None,
    *,
    filename: str | None = None,
    image_saver: Any = None,
    header_row: int | None = None,
) -> tuple[list[dict[str, Any]], list[str], str]:
    """把任意支持的文件内容转为 (行列表, 文件列名, 实际使用的 format).

    支持：csv / tsv / delimited / json / xlsx / xls（拒绝）.
    format 未指定时：优先用 filename 推断，退化到内容特征推断。

    Args:
        image_saver: WPS 单元格图片解析器（img → 元数据 dict | None）；
            None 时用 ephemeral（不落盘，仅保证类型推断与样本可用）。
        header_row: 可选，1 基表头行号（按文件中的非空行序号）。为空时自动识别
            （兼容表格顶部有标题行 / 合并行的情况）；传入时按用户选择切分。

    Returns:
        (rows, file_columns, actual_format)
    """
    rows, cols, actual_fmt, _detection = parse_file_to_rows_with_detection(
        content,
        format,
        filename=filename,
        image_saver=image_saver,
        header_row=header_row,
    )
    return rows, cols, actual_fmt


def parse_file_to_rows_with_detection(
    content: bytes | str,
    format: str | None = None,
    *,
    filename: str | None = None,
    image_saver: Any = None,
    header_row: int | None = None,
) -> tuple[list[dict[str, Any]], list[str], str, HeaderDetection | None]:
    """:func:`parse_file_to_rows` 的增强版：额外返回表头行识别结果.

    仅表格类格式（csv / tsv / delimited / xlsx）有 ``HeaderDetection``；
    JSON 对象数组没有表头概念，第四项恒为 ``None``。
    """
    from cndb.plugins.tables.services.importing.importer import guess_format_from_content

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
        rows, cols, detection = _parse_xlsx_detailed(raw, image_saver=image_saver, header_row=header_row)
        return rows, cols, "xlsx", detection

    if actual_fmt == "json":
        if isinstance(content, bytes):
            text, _enc, _conf = decode_bytes_auto(content)
        else:
            text = content
        rows, cols = _parse_json_text(text)
        return rows, cols, "json", None

    # csv / tsv / delimited — 统一走分隔符文本解析
    if isinstance(content, bytes):
        text, _enc, _conf = decode_bytes_auto(content)
    else:
        text = content
    delim = "\t" if actual_fmt == "tsv" else None
    rows, cols, detection = _parse_delimited_detailed(text, delimiter=delim, header_row=header_row)
    return rows, cols, actual_fmt, detection


def _resolve_header_detection(
    raw_rows: list[list[Any]],
    header_row: int | None,
) -> tuple[int, HeaderDetection | None]:
    """运行表头识别 / 校验用户指定行，返回 (表头下标, 识别结果).

    用户指定行优先；自动识别只在前 ``HEADER_SCAN_ROWS`` 个非空行内进行。
    """
    if not raw_rows:
        return 0, None
    preferred: int | None = None
    if header_row is not None:
        if not isinstance(header_row, int) or isinstance(header_row, bool) or header_row < 1:
            raise ValueError("表头行号必须是从 1 开始的整数")
        preferred = header_row - 1
        if preferred >= HEADER_SCAN_ROWS:
            raise ValueError(f"表头行只在前 {HEADER_SCAN_ROWS} 个非空行内识别或指定（收到第 {header_row} 行）")
        if preferred >= len(raw_rows):
            raise ValueError(f"指定的表头行 {header_row} 超出文件非空行数 {len(raw_rows)}")
    detection = detect_header_row(raw_rows, preferred_index=preferred)
    return (detection.index if detection is not None else 0), detection


def _parse_delimited_detailed(
    text: str,
    *,
    delimiter: str | None = None,
    header_row: int | None = None,
) -> tuple[list[dict[str, Any]], list[str], HeaderDetection | None]:
    """解析分隔符文本：先识别表头行，再按表头切出数据行（单次流式读取）."""
    delim = delimiter or sniff_csv_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    buffered: list[tuple[list[str], int]] = []
    for record in reader:
        if not any((field or "").strip() for field in record):
            continue
        buffered.append((record, reader.line_num))
        if len(buffered) >= HEADER_SCAN_ROWS:
            break
    if not buffered:
        return [], [], None

    index, detection = _resolve_header_detection([record for record, _ln in buffered], header_row)
    header = [(field or "").strip() for field in buffered[index][0]]
    _validate_csv_structure(header)

    rows: list[dict[str, Any]] = []

    def _append(record: list[str], line_num: int) -> None:
        if len(record) > len(header):
            raise ValueError(
                f"CSV 第 {line_num} 行有 {len(record)} 个值，超出表头列数 {len(header)}，请检查值中未转义的逗号或换行"
            )
        cleaned: dict[str, Any] = {}
        for i, key in enumerate(header):
            raw_value = record[i] if i < len(record) else None
            if isinstance(raw_value, str):
                stripped = raw_value.strip()
                cleaned[key] = None if stripped == "" else stripped
            else:
                cleaned[key] = raw_value
        rows.append(cleaned)

    for record, line_num in buffered[index + 1 :]:
        _append(record, line_num)
    for record in reader:
        if not any((field or "").strip() for field in record):
            continue
        _append(record, reader.line_num)
    return rows, header, detection


def _parse_delimited_text(
    text: str,
    *,
    delimiter: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """解析分隔符文本（逗号/分号/pipe/tab 自动 sniff）."""
    rows, cols, _detection = _parse_delimited_detailed(text, delimiter=delimiter)
    return rows, cols


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


def _parse_xlsx_detailed(
    xlsx_bytes: bytes,
    *,
    image_saver: Any = None,
    header_row: int | None = None,
) -> tuple[list[dict[str, Any]], list[str], HeaderDetection | None]:
    """解析 XLSX 字节串：识别表头行后切出数据行（表头空列名/重复列名/行溢出明确报错）.

    WPS 单元格图片：单元格值为 ``=DISPLIMG("ID_xxx",1)`` 公式时，按
    ``xl/cellimages.xml`` 映射取出图片，经 image_saver（默认 ephemeral，
    不落盘）解析为 ``[图片元数据 dict]``；解析失败置 None。
    """
    from cndb.plugins.tables.services.transfer.wps_images import make_displimg_resolver, match_displimg_formula
    from cndb.plugins.tables.services.transfer.xlsx_rows import read_xlsx_rows

    resolve_image = make_displimg_resolver(xlsx_bytes, image_saver)

    # 有界流式读取：WPS 导出文件常声明到 1048576 行（仅样式），全量物化会卡死（历史线上问题）。
    # 先缓冲前 HEADER_SCAN_ROWS 个非空行做表头识别，再继续流式消费剩余行。
    stream = read_xlsx_rows(xlsx_bytes)
    buffered: list[tuple[int, tuple[Any, ...]]] = []
    for item in stream:
        buffered.append(item)
        if len(buffered) >= HEADER_SCAN_ROWS:
            break
    if not buffered:
        return [], [], None

    raw_rows = [list(values) for _sheet_row, values in buffered]
    index, detection = _resolve_header_detection(raw_rows, header_row)
    header = [str(c) if c is not None else "" for c in raw_rows[index]]
    _validate_xlsx_header(header)

    rows: list[dict[str, Any]] = []

    def _append(sheet_row: int, values: Sequence[Any]) -> None:
        nonlocal header
        # 与旧实现（openpyxl 补齐到最大列宽）一致：更宽的行 → 表头出现空列名并报错
        if len(values) > len(header):
            header = [*header, *([""] * (len(values) - len(header)))]
            _validate_xlsx_header(header)
        _check_xlsx_row_overflow(values, sheet_row, len(header))
        row_dict: dict[str, Any] = {}
        for i, key in enumerate(header):
            value = values[i] if i < len(values) else None
            if isinstance(value, str):
                displimg_id = match_displimg_formula(value)
                if displimg_id is not None:
                    row_dict[key] = resolve_image(displimg_id)
                    continue
                stripped = value.strip()
                row_dict[key] = None if stripped == "" else stripped
            else:
                # 长数字保护：避免 Excel 数值精度经 JSON/JS 链路进一步丢失
                row_dict[key] = _coerce_long_numeric_to_text(value)
        rows.append(row_dict)

    for sheet_row, values in buffered[index + 1 :]:
        _append(sheet_row, values)
    for sheet_row, values in stream:
        _append(sheet_row, values)
    return rows, header, detection


def _parse_xlsx_bytes(
    xlsx_bytes: bytes,
    *,
    image_saver: Any = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """解析 XLSX 字节串（表头空列名/重复列名/行溢出明确报错）."""
    rows, cols, _detection = _parse_xlsx_detailed(xlsx_bytes, image_saver=image_saver)
    return rows, cols
