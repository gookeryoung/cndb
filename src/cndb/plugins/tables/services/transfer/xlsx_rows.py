"""有界、流式的 XLSX 行读取器 —— 专治 WPS 导出的"虚假范围"文件.

**问题**（线上实测）：WPS 保存的 XLSX 常把"仅样式"的整行/整列写进文件，于是
``ws.max_row`` / 声明维度可能被撑到 1048576 行（实际只有几十行数据）。旧实现

    wb = load_workbook(buf); rows = list(ws.iter_rows(values_only=True))

有两个后果，且都不会报错：
1. 非只读模式会把百万空行实例化成单元格对象 → 内存暴涨，容器可能被 OOM 杀掉，
   任务行永远停在"运行中 5%"（现象：进度卡 5%、无报错）；
2. 列数多时是「百万行 × 列数」次遍历，等同于卡死。

**本模块的做法**：
- ``read_only=True``：流式读取，不构建样式/图形对象（WPS 单元格图片由 ``wps_images``
  直接解析 zip 读取，不依赖 openpyxl 的图形对象，因此不受影响）；
- ``data_only`` 默认 **False**：必须保留公式串（WPS 单元格图片用
  ``=_xlfn.DISPIMG("ID_...",1)`` 形式引用，且通常没有缓存值，开了 data_only 就变 None，
  图片会解析不出来 —— 这一点有测试守着）；
- ``ws.reset_dimensions = True``：**忽略文件声明的维度**，避免按虚假范围遍历；
- 双上限：非空数据行上限 + 扫描行上限（防止畸形文件无限扫描），
  超限抛 :class:`XlsxTooLargeError`（提示拆分文件），而不是静默卡死。
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any

# 非空数据行上限（超过则明确报错，提示拆分文件）
MAX_DATA_ROWS = 200_000
# 扫描行上限：WPS 的虚假范围会带来大量空行，允许扫描但不允许无限（约 200 万行 XML 行）
MAX_SCAN_ROWS = 2_000_000
# 列数上限（防止 XFD 级宽表把每行元组撑爆内存）
MAX_COLUMNS = 2_048


class XlsxTooLargeError(ValueError):
    """XLSX 规模超出导入上限（可读错误，而不是卡死/崩溃）."""


def read_xlsx_rows(
    raw: bytes | str,
    *,
    max_data_rows: int = MAX_DATA_ROWS,
    max_scan_rows: int = MAX_SCAN_ROWS,
    max_columns: int = MAX_COLUMNS,
    data_only: bool = False,
) -> Iterator[tuple[int, tuple[Any, ...]]]:
    """流式产出 ``(工作表行号, 行值元组)``，**跳过全空行**.

    Args:
        raw: XLSX 字节（或等价字符串）
        max_data_rows: 非空数据行上限，超出抛 :class:`XlsxTooLargeError`
        max_scan_rows: 扫描（含空行）行数上限，超出抛 :class:`XlsxTooLargeError`
        max_columns: 列数上限，超出抛 :class:`XlsxTooLargeError`
        data_only: 是否只取公式的计算值（默认 False —— 导入链路依赖公式串识别 WPS 单元格图片）

    Yields:
        ``(sheet_row, values)``：``sheet_row`` 为真实工作表行号（1 基，用于错误提示）
    """
    from openpyxl import load_workbook

    data = raw if isinstance(raw, bytes) else raw.encode()
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=data_only, keep_links=False)
    try:
        ws = wb.active
        if ws is None:  # pragma: no cover - 文件必有活动工作表
            return
        # 关键：忽略文件声明的维度（WPS 的虚假范围全靠这一步化解）。
        # openpyxl 各版本形态不同：3.1.x 是方法，早期版本可赋值 —— 两种都兼容。
        reset_dimensions = getattr(ws, "reset_dimensions", None)
        if callable(reset_dimensions):
            reset_dimensions()
        else:  # pragma: no cover - 早期 openpyxl 版本该属性可直接赋值
            setattr(ws, "reset_dimensions", True)  # noqa: B010 - 兼容旧版属性赋值形态

        column_limit = max_columns if max_columns > 0 else None
        scanned = 0
        emitted = 0
        for sheet_row, row in enumerate(ws.iter_rows(values_only=True), start=1):
            scanned += 1
            if max_scan_rows > 0 and scanned > max_scan_rows:
                raise XlsxTooLargeError(
                    f"文件行数异常：已扫描 {scanned} 行仍未结束（上限 {max_scan_rows}），"
                    "常见于 WPS/Excel 写入的整列样式造成的虚假范围，请另存为「仅数据」副本后重试"
                )
            if not any(cell is not None for cell in row):
                continue
            if column_limit is not None and len(row) > column_limit:
                raise XlsxTooLargeError(f"文件列数过多（{len(row)} 列，上限 {column_limit}），请删除多余空列后重试")
            emitted += 1
            if max_data_rows > 0 and emitted > max_data_rows:
                raise XlsxTooLargeError(f"文件数据行数超过上限（{max_data_rows} 行），请拆分文件后分批导入")
            yield sheet_row, row
    finally:
        wb.close()


def xlsx_max_row_hint(raw: bytes | str) -> int | None:
    """仅读取工作表声明的最大行号（用于诊断/提示，不加载单元格）."""
    try:
        from openpyxl import load_workbook

        data = raw if isinstance(raw, bytes) else raw.encode()
        wb = load_workbook(io.BytesIO(data), read_only=True, keep_links=False)
        try:
            ws = wb.active
            return int(getattr(ws, "max_row", 0) or 0)
        finally:
            wb.close()
    except Exception:
        return None


__all__ = [
    "MAX_COLUMNS",
    "MAX_DATA_ROWS",
    "MAX_SCAN_ROWS",
    "XlsxTooLargeError",
    "read_xlsx_rows",
    "xlsx_max_row_hint",
]
