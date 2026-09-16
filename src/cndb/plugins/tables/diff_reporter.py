"""差异/统计报告生成器 —— 导入流水线的"汇总"阶段.

职责：接收 RowValidator 产出的 ValidationResult 列表，结合 DataTable 字段定义
和原始文件列名，产出一份 JSON 可序列化的导入报告，直接给前端预览面板消费，
也可以存入 ImportTask.validation_report 字段供后续追溯。
"""

from __future__ import annotations

from typing import Any

from cndb.plugins.tables.models import DataField

from .row_validator import ValidationResult
from .transfer import _infer_single_value, _pick_inferred_type, _promote_to_select_if_low_cardinality


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
        *,
        upsert_result: dict[str, Any] | None = None,
        planned_columns: list[dict[str, Any]] | None = None,
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

        # ── V2: upsert 统计 + 预览 ──────────────────
        if upsert_result is not None:
            new_count = upsert_result.get("new_count", valid_count)
            update_count = upsert_result.get("update_count", 0)
            multi_key_conflicts = upsert_result.get("multi_key_conflicts", 0)
            new_preview = upsert_result.get("new_preview", [])[:200]
            update_preview = upsert_result.get("update_preview", [])[:200]
        else:
            new_count = valid_count
            update_count = 0
            multi_key_conflicts = 0
            new_preview: list[dict[str, Any]] = []
            update_preview: list[dict[str, Any]] = []

        return {
            "total": total,
            "valid_count": valid_count,
            "warning_count": warning_count,
            "error_count": error_count,
            "skipped_columns": skipped_columns,
            "missing_required": missing_required,
            "warnings": warnings,
            "errors": errors,
            # V2 字段
            "new_count": new_count,
            "update_count": update_count,
            "multi_key_conflicts": multi_key_conflicts,
            "new_preview": new_preview,
            "update_preview": update_preview,
            "planned_columns": planned_columns or [],
        }

    @staticmethod
    def infer_new_column_type(samples: list[str]) -> tuple[str, list[str]]:
        """从样本列表推断字段类型 + select options.

        复用 transfer 的 _infer_single_value + _pick_inferred_type + _promote_to_select_if_low_cardinality.
        返回 (field_type, options) — field_type 可能是 "text" / "number" / "date" / "boolean" / "select".
        空样本 → text + [].
        所有样本都是 "empty" → text + [].
        不支持的类型兜底 → text + [].
        """
        non_empty = [s for s in samples if s is not None and str(s).strip()]
        if not non_empty:
            return "text", []

        type_counts: dict[str, int] = {}
        for v in non_empty:
            t = _infer_single_value(str(v))
            if t != "empty":
                type_counts[t] = type_counts.get(t, 0) + 1

        inferred = _pick_inferred_type(type_counts) if type_counts else "text"
        if inferred == "empty":
            inferred = "text"

        final_type, options = _promote_to_select_if_low_cardinality(inferred, non_empty)

        # 安全兜底：不支持的类型一律转 text
        if final_type not in ("text", "number", "float", "date", "datetime", "boolean", "select"):
            final_type = "text"
            options: list[str] = []
        if final_type != "select":
            options: list[str] = []

        return final_type, options


__all__ = ["DiffReporter"]
