"""差异/统计报告生成器 —— 导入流水线的"汇总"阶段.

职责：接收 RowValidator 产出的 ValidationResult 列表，结合 DataTable 字段定义
和原始文件列名，产出一份 JSON 可序列化的导入报告，直接给前端预览面板消费，
也可以存入 ImportTask.validation_report 字段供后续追溯。

V2 扩展（upsert + 字段自动新增）：
- upsert_result 提供 new/update 匹配分类 + 多行冲突标记
- planned_columns 提供未知列自动新增时的字段规划
"""

from __future__ import annotations

from typing import Any

from cndb.plugins.tables.models import DataField
from cndb.plugins.tables.transfer import (
    _infer_single_value,
    _pick_inferred_type,
    _promote_to_select_if_low_cardinality,
)

from .row_validator import ValidationResult

# 预览截断上限
PREVIEW_LIMIT = 200
SAMPLE_FIELD_LIMIT = 5


class DiffReporter:
    """生成导入差异报告.

    输出结构（V2）:
    {
        "total": int,
        "valid_count": int,
        "warning_count": int,
        "error_count": int,
        "new_count": int,          # V2: 待新增行数（未指定 match_keys 时等于 valid_count）
        "update_count": int,       # V2: 待更新行数
        "multi_key_conflicts": int, # V2: 多行同 key 冲突数
        "skipped_columns": [str],
        "missing_required": [str],
        "planned_columns": [       # V2: 未知列自动新增规划
            {"name": str, "field_type": str, "options": [...], "sample_values": [...]},
        ],
        "new_preview": [           # V2: 待新增行预览（前 200 行）
            {"row_number": int, "match_key_values": {...}, "field_sample": {...}},
        ],
        "update_preview": [        # V2: 待更新行预览（前 200 行）
            {"row_number": int, "match_key_values": {...}, "existing_row_id": int, "field_sample": {...}},
        ],
        "warnings": [{"row_number": int, "field": str, "message": str}, ...],
        "errors":   [{"row_number": int, "field": str, "message": str}, ...],
    }

    向后兼容：旧字段全部保留，新增字段有合理默认值；JSON 解析方对缺失
    new_count/update_count/new_preview/update_preview 可回退为 valid_count/0/[]/[]。
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
        """根据校验结果 + 表字段 + 文件列名 + upsert 匹配 + 字段规划生成报告."""
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

        # ── V2: upsert 统计与预览 ──────────────────
        new_count = valid_count
        update_count = 0
        multi_key_conflicts = 0
        new_preview: list[dict[str, Any]] = []
        update_preview: list[dict[str, Any]] = []

        if upsert_result is not None:
            new_count = upsert_result.get("new_count", valid_count)
            update_count = upsert_result.get("update_count", 0)
            multi_key_conflicts = upsert_result.get("multi_key_conflicts", 0)
            new_preview = upsert_result.get("new_preview", [])
            update_preview = upsert_result.get("update_preview", [])

        # ── V2: 字段规划 ───────────────────────────
        planned = planned_columns or []

        return {
            "total": total,
            "valid_count": valid_count,
            "warning_count": warning_count,
            "error_count": error_count,
            "new_count": new_count,
            "update_count": update_count,
            "multi_key_conflicts": multi_key_conflicts,
            "skipped_columns": skipped_columns,
            "missing_required": missing_required,
            "planned_columns": planned,
            "new_preview": new_preview,
            "update_preview": update_preview,
            "warnings": warnings,
            "errors": errors,
        }

    # ── 辅助：未知列类型推断 ──────────────────────────

    @staticmethod
    def infer_new_column_type(samples: list[str]) -> tuple[str, list[str]]:
        """从样本值推断一个新列的字段类型.

        复用 transfer 模块的 _infer_single_value + _promote_to_select_if_low_cardinality.

        Returns:
            (field_type, options) — field_type 不支持时回退为 "text".
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

        # 低基数 select 提升（只对 text 类型做）
        final_type, options = _promote_to_select_if_low_cardinality(inferred, non_empty)

        # 安全兜底：不支持的类型一律转 text
        _ALLOWED = {
            "text",
            "number",
            "float",
            "boolean",
            "email",
            "url",
            "phone",
            "date",
            "datetime",
            "percentage",
            "select",
            "json",
        }
        if final_type not in _ALLOWED:
            final_type = "text"
        return final_type, options


__all__ = ["DiffReporter"]
