"""失败行导出器 —— 导入流水线的"降级出口"阶段.

职责：从 RowValidator 产出的 ValidationResult 中提取 error 行，
导出为与原始文件相同的格式（CSV / XLSX / JSON），新增 ``_row_number``
和 ``_error`` / ``_errors`` 两列。用户拿到后修正错误、删掉 ``_error``
列即可重导。
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from .row_validator import ValidationResult

_Format = str


class FailedRowExporter:
    """导出校验失败的行.

    Args:
        error_only: 默认 True —— 仅导出 status="error" 的行；设为 False 则同时导出 warning.
    """

    def __init__(self, *, error_only: bool = True) -> None:
        self.error_only = error_only

    # ── 公共入口 ────────────────────────────────

    @staticmethod
    def export_failed_rows(
        results: list[ValidationResult],
        format: _Format = "csv",
        *,
        error_only: bool = True,
    ) -> bytes | str:
        """静态便捷方法，内部实例化后调用 export()."""
        return FailedRowExporter(error_only=error_only).export(results, format)

    def export(self, results: list[ValidationResult], format: _Format) -> bytes | str:
        """按 format 输出失败行文件."""
        failed = [r for r in results if r.status == "error" or (not self.error_only and r.status == "warning")]
        if format == "csv":
            return self._to_csv(failed)
        if format == "xlsx":
            return self._to_xlsx(failed)
        if format == "json":
            return self._to_json(failed)
        raise ValueError(f"不支持的导出格式: {format}")

    # ── 内部实现 ────────────────────────────────

    @staticmethod
    def _collect_all_columns(results: list[ValidationResult]) -> list[str]:
        """收集所有出现过的原始列名（保持首次出现顺序）."""
        seen: list[str] = []
        for r in results:
            for k in r.values:
                if k not in seen:
                    seen.append(k)
        return seen

    @staticmethod
    def _error_text(issues: list[Any]) -> str:
        """把多个 issue.message 用分号拼接."""
        return "; ".join(i.message for i in issues)

    def _to_csv(self, results: list[ValidationResult]) -> bytes:
        cols = self._collect_all_columns(results)
        fieldnames = [*cols, "_row_number", "_error"]
        buf = io.StringIO()
        # 写 BOM，让 Excel 打开时中文不乱码
        buf.write("\ufeff")
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            row = dict(r.values)
            row["_row_number"] = r.row_number
            row["_error"] = self._error_text(r.issues)
            writer.writerow(row)
        return buf.getvalue().encode("utf-8")

    def _to_xlsx(self, results: list[ValidationResult]) -> bytes:
        from openpyxl import Workbook

        cols = self._collect_all_columns(results)
        headers = [*cols, "_row_number", "_error"]

        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "Failed Rows"
        ws.append(headers)
        for r in results:
            row_values = [r.values.get(c) for c in cols]
            ws.append([*row_values, r.row_number, self._error_text(r.issues)])

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def _to_json(self, results: list[ValidationResult]) -> str:
        out: list[dict[str, Any]] = []
        for r in results:
            entry = dict(r.values)
            entry["_row_number"] = r.row_number
            entry["_errors"] = [i.message for i in r.issues]
            out.append(entry)
        return json.dumps(out, ensure_ascii=False, indent=2, default=str)


__all__ = ["FailedRowExporter"]
