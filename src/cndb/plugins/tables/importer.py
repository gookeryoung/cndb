"""导入流水线编排器 —— Parser → RowValidator → DiffReporter → bulk_create.

Importer 是"文件导入追加到已有表"的统一入口。它串联：
1. 解析：把 CSV / JSON / XLSX 原始内容转为 ``list[dict[str, Any]]``
2. 校验：RowValidator 逐行校验，不中断
3. 报告：DiffReporter 汇总 valid/warning/error
4. 落库：过滤出 valid（可选加 warning）行 → 调 ``records.bulk_create``

与 :mod:`transfer` 的关系：Importer 是上层编排，transfer 做底层解析；
transfer 的三个 ``import_rows_from_*`` 保留作为旧流程直连接口，不被 Importer 替代。

支持字段映射与缺口填充：
- field_mapping: ``{源列名: 目标字段名}`` —— 把文件/API 的列对齐到目标表字段
- gap_filling:   目标侧缺失字段的填充策略 — "empty" / "default" / "value" / "error"
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.tables import records as rec
from cndb.plugins.tables.diff_reporter import DiffReporter
from cndb.plugins.tables.field_mapping import GapFilling
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.row_validator import RowValidator, ValidationResult

_Format = str


# ── 结果数据结构 ───────────────────────────────────


@dataclass
class ImportAnalysisResult:
    """analyze() 阶段返回."""

    report: dict[str, Any]
    results: list[ValidationResult]
    file_columns: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report": self.report,
            "total": len(self.results),
            "file_columns": self.file_columns,
        }


@dataclass
class ImportExecuteResult:
    """execute() 阶段返回."""

    imported_ids: list[int]
    report: dict[str, Any]
    failed_results: list[ValidationResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "imported_ids": self.imported_ids,
            "imported_rows": len(self.imported_ids),
            "report": self.report,
            "failed_count": len(self.failed_results),
        }


# ── Importer ──────────────────────────────────────


class Importer:
    """统一导入流水线.

    Args:
        engine: SQLAlchemy Engine（bulk_create 用）.
        db: SQLAlchemy Session（link 字段写入关联表时需要传）.
        table: 目标数据表.
        field_mapping: 可选的源列 → 目标字段映射 — 透传给 RowValidator.
        gap_filling: 目标侧缺失字段填充策略 — 透传给 RowValidator.
        fill_values: gap_filling="value" 时的固定值 — 透传给 RowValidator.
    """

    def __init__(
        self,
        engine: Any,
        db: Session,
        table: DataTable,
        *,
        field_mapping: dict[str, str | None] | None = None,
        gap_filling: GapFilling = "empty",
        fill_values: dict[str, Any] | None = None,
    ) -> None:
        self.engine = engine
        self.db = db
        self.table = table
        self.field_mapping = field_mapping
        self.gap_filling = gap_filling
        self.fill_values = fill_values

    # ── 公共 API ────────────────────────────────

    def analyze(
        self,
        content: bytes | str,
        format: _Format | None = None,
        *,
        rows: list[dict[str, Any]] | None = None,
    ) -> ImportAnalysisResult:
        """仅做解析 + 校验 + 报告，不写库.

        传入已解析的 ``rows`` 可跳过解析阶段（比如前端直接传 JSON 对象数组）.
        """
        if rows is None:
            assert format is not None, "必须提供 format 或 rows"
            rows, file_columns = self._parse(content, format)
        else:
            file_columns = self._collect_columns(rows)

        rv = RowValidator(
            self.table,
            field_mapping=self.field_mapping,
            gap_filling=self.gap_filling,
            fill_values=self.fill_values,
        )
        results = rv.validate_all(rows)
        report = DiffReporter.build(results, self.table.active_fields(), file_columns)
        return ImportAnalysisResult(report=report, results=results, file_columns=file_columns)

    def execute(
        self,
        content: bytes | str | None = None,
        format: _Format | None = None,
        *,
        analysis: ImportAnalysisResult | None = None,
        rows: list[dict[str, Any]] | None = None,
        skip_errors: bool = True,
        import_warnings: bool = True,
    ) -> ImportExecuteResult:
        """完整流水线：解析 → 校验 → 报告 → 落库.

        三种入口优先级：analysis > content+format > rows.
        skip_errors=True 默认跳过 error 行（只落库 valid + warning）.
        import_warnings=True 默认 warning 行也落库.
        """
        if analysis is not None:
            # 已有 analyze 结果，跳过解析
            results = analysis.results
            report = analysis.report
        else:
            analysis = self.analyze(content or "", format, rows=rows)
            results = analysis.results
            report = analysis.report

        # 过滤要落库的行
        to_import: list[dict[str, Any]] = []
        failed: list[ValidationResult] = []
        for r in results:
            if r.status == "error":
                if skip_errors:
                    failed.append(r)
                    continue
                to_import.append(r.values)
            elif r.status == "warning":
                if import_warnings:
                    to_import.append(r.values)
                else:
                    failed.append(r)
            else:  # valid
                to_import.append(r.values)

        if not to_import:
            return ImportExecuteResult(imported_ids=[], report=report, failed_results=failed)

        ids = rec.bulk_create(self.engine, self.table, to_import, db=self.db)

        # 更新 report：补充实际导入行数
        report = dict(report)
        report["actually_imported"] = len(ids)

        return ImportExecuteResult(imported_ids=ids, report=report, failed_results=failed)

    # ── 内部：解析 ──────────────────────────────

    def _parse(self, content: bytes | str, format: _Format) -> tuple[list[dict[str, Any]], list[str]]:
        """把文件内容转为 (行列表, 文件列名)."""
        if format == "csv":
            return self._parse_csv(content)
        if format == "json":
            return self._parse_json(content)
        if format == "xlsx":
            return self._parse_xlsx(content)
        raise ValueError(f"不支持的格式: {format}")

    @staticmethod
    def _parse_csv(content: bytes | str) -> tuple[list[dict[str, Any]], list[str]]:
        text = content if isinstance(content, str) else content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        file_columns = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
        return rows, file_columns

    @staticmethod
    def _parse_json(content: bytes | str) -> tuple[list[dict[str, Any]], list[str]]:
        text = content if isinstance(content, str) else content.decode("utf-8")
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

    @staticmethod
    def _parse_xlsx(content: bytes | str) -> tuple[list[dict[str, Any]], list[str]]:
        from openpyxl import load_workbook

        raw = content if isinstance(content, bytes) else content.encode()
        wb = load_workbook(io.BytesIO(raw))
        ws = wb.active
        assert ws is not None
        all_rows = list(ws.iter_rows(values_only=True))
        if not all_rows:
            return [], []
        file_columns = [str(c) if c is not None else f"col_{i}" for i, c in enumerate(all_rows[0])]
        rows = [dict(zip(file_columns, r, strict=False)) for r in all_rows[1:] if any(c is not None for c in r)]
        return rows, file_columns

    @staticmethod
    def _collect_columns(rows: list[dict[str, Any]]) -> list[str]:
        seen: list[str] = []
        for r in rows:
            for k in r:
                if k not in seen:
                    seen.append(k)
        return seen


def guess_format_from_content(content: bytes | str) -> _Format:
    """从内容推断格式（按内容特征而非文件名）."""
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8-sig")
        except Exception:
            return "xlsx"  # 无法解码为文本 → xlsx
    text = content.strip()
    if text.startswith("{") or text.startswith("["):
        try:
            json.loads(text[:2048])
            return "json"
        except Exception:
            pass
    # 快速 CSV 检查：第一行有逗号或制表符分隔的多列
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if "," in first_line or "\t" in first_line:
        return "csv"
    return "csv"  # 默认兜底


__all__ = [
    "ImportAnalysisResult",
    "ImportExecuteResult",
    "Importer",
    "guess_format_from_content",
]
