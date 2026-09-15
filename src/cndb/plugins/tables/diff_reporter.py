"""差异/统计报告生成器 —— 导入流水线的"汇总"阶段.

职责：接收 RowValidator 产出的 ValidationResult 列表，结合 DataTable 字段定义
和原始文件列名，产出一份 JSON 可序列化的导入报告，直接给前端预览面板消费，
也可以存入 ImportTask.validation_report 字段供后续追溯。
"""

from __future__ import annotations

from typing import Any

from cndb.plugins.tables.models import DataField

from .row_validator import ValidationResult


class DiffReporter:
    """生成导入差异报告.

    输出结构：
    {
        "total": int,
        "valid_count": int,
        "warning_count": int,
        "error_count": int,
        "skipped_columns": [str],
        "missing_required": [str],
        "warnings": [{"row_number": int, "field": str, "message": str}, ...],
        "errors":   [{"row_number": int, "field": str, "message": str}, ...],
    }

    所有字段均为原生 Python dict/list/int/str，可直接 ``json.dumps``.
    """

    @staticmethod
    def build(
        results: list[ValidationResult],
        table_fields: list[DataField],
        file_columns: list[str],
    ) -> dict[str, Any]:
        """根据校验结果 + 表字段 + 文件列名生成报告."""
        field_names = {f.name for f in table_fields if not f.trashed}
        required_names = {f.name for f in table_fields if f.required and not f.trashed}
        file_name_set = set(file_columns)

        # ── 计数 ───────────────────────────────────
        total = len(results)
        valid_count = sum(1 for r in results if r.status == "valid")
        warning_count = sum(1 for r in results if r.status == "warning")
        error_count = sum(1 for r in results if r.status == "error")

        # ── 列差异 ─────────────────────────────────
        skipped_columns = sorted(file_name_set - field_names)
        missing_required = sorted(required_names - file_name_set)

        # ── 错误/警告明细 ──────────────────────────
        warnings: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for r in results:
            for issue in r.issues:
                entry: dict[str, Any] = {
                    "row_number": r.row_number,
                    "field": issue.field,
                    "message": issue.message,
                }
                if issue.level == "warning":
                    warnings.append(entry)
                else:
                    errors.append(entry)

        return {
            "total": total,
            "valid_count": valid_count,
            "warning_count": warning_count,
            "error_count": error_count,
            "skipped_columns": skipped_columns,
            "missing_required": missing_required,
            "warnings": warnings,
            "errors": errors,
        }


__all__ = ["DiffReporter"]
