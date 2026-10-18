"""用户批量导入的输入读取层：CSV / XLSX 解析、列头别名归一与行映射."""

from __future__ import annotations

import csv
import secrets
import string
from pathlib import Path
from typing import Any

from cndb.plugins.accounts.services.user_bulk import _PW_FIELD as _pw_field
from cndb.plugins.accounts.services.user_bulk import USER_IMPORT_COLUMN_ALIASES as _USER_IMPORT_COLUMN_ALIASES
from cndb.plugins.tables.services.transfer import _coerce_long_numeric_to_text, decode_bytes_auto

# 列头别名表与服务层共用同一张表（见 cndb.plugins.accounts.services.user_bulk），
# API 导入与 CLI 导入的列识别规则不会漂移。
__all__ = [
    "_USER_IMPORT_COLUMN_ALIASES",
    "_generate_password",
    "_map_header",
    "_map_row",
    "_normalize_header",
    "_open_tabfile",
    "_pw_field",
    "_read_csv",
    "_read_xlsx",
]


def _generate_password(length: int = 12) -> str:
    """生成随机密码（字母 + 数字，不包含易混淆字符 0/O/l/I/1）."""
    alphabet = string.ascii_letters + string.digits
    # 去掉易混淆字符
    alphabet = "".join(c for c in alphabet if c not in "O0lI1")
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _normalize_header(h: str) -> str:
    """列头标准化：去空格 + 小写."""
    return h.strip().lower()


def _map_header(raw: str) -> str | None:
    """把原始列头映射到内部字段名，匹配不到返回 None."""
    normalized = _normalize_header(raw)
    return _USER_IMPORT_COLUMN_ALIASES.get(normalized)


def _open_tabfile(path: Path) -> list[dict[str, Any]]:
    """读 csv 或 xlsx，返回 list[dict[str, Any]]（每行一个 dict，键为内部字段名）.

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 格式不支持
    """
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在: {path}")

    suffix = path.suffix.lower()

    if suffix in (".csv", ".tsv"):
        return _read_csv(path)
    if suffix in (".xlsx", ".xlsm"):
        return _read_xlsx(path)
    raise ValueError(f"不支持的文件格式: {suffix}（支持 .csv / .xlsx）")


def _read_csv(path: Path) -> list[dict[str, Any]]:
    """读 CSV：编码探测复用 transfer.decode_bytes_auto（utf-8/gb18030/big5 + chardet 兜底）.

    原先手写 utf-8 → utf-8-sig → gbk 三级回退，与导入链路的编码探测实现重复，
    且无法处理 big5 / utf-16 等来源；统一到单一实现避免漂移。
    """
    text, _enc, _conf = decode_bytes_auto(path.read_bytes())
    lines = text.splitlines()
    if not lines:
        return []

    reader = csv.DictReader(lines)
    return [_map_row(row) for row in reader if any(v is not None and str(v).strip() for v in row.values())]


def _read_xlsx(path: Path) -> list[dict[str, Any]]:
    """读 xlsx 第一个 sheet."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl 未安装，请执行 `uv sync` 后重试") from exc

    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb.active
    if ws is None:
        return []
    rows_iter = ws.iter_rows(values_only=True)

    try:
        header_raw = next(rows_iter)
    except StopIteration:
        return []

    if header_raw is None:
        return []

    header = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(header_raw)]

    result: list[dict[str, Any]] = []
    for row in rows_iter:
        if row is None or not any(v is not None and str(v).strip() for v in row):
            continue
        raw_row = {
            header[i]: _coerce_long_numeric_to_text(row[i]) if i < len(row) else None for i in range(len(header))
        }
        result.append(_map_row(raw_row))
    return result


def _map_row(raw_row: dict[str, Any]) -> dict[str, Any]:
    """把原始行（原始列头）映射为内部字段字典."""
    mapped: dict[str, Any] = {}
    for raw_col, value in raw_row.items():
        key = _map_header(str(raw_col))
        if key is None:
            continue
        mapped[key] = value if value is not None else ""
    return mapped
