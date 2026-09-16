"""导入流水线编排器 —— Parser → RowValidator → DiffReporter → bulk_create.

Importer 是"文件导入追加到已有表"的统一入口。它串联：
1. 解析：把 CSV / JSON / XLSX 原始内容转为 ``list[dict[str, Any]]``
2. 校验：RowValidator 逐行校验，不中断
3. 报告：DiffReporter 汇总 valid/warning/error
4. 落库：过滤出 valid（可选加 warning）行 → 调 ``records.bulk_create``

与 :mod:`transfer` 的关系：Importer 是上层编排，transfer 做底层解析；
transfer 的三个 ``import_rows_from_*`` 保留作为旧流程直连接口，不被 Importer 替代。
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.tables import records as rec
from cndb.plugins.tables.diff_reporter import DiffReporter
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
    upsert_result: dict[str, Any] | None = None
    planned_columns: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report": self.report,
            "total": len(self.results),
            "file_columns": self.file_columns,
            "upsert_result": self.upsert_result,
            "planned_columns": self.planned_columns,
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
    """

    def __init__(self, engine: Any, db: Session, table: DataTable) -> None:
        self.engine = engine
        self.db = db
        self.table = table

    # ── 公共 API ────────────────────────────────

    def analyze(
        self,
        content: bytes | str,
        format: _Format | None = None,
        *,
        rows: list[dict[str, Any]] | None = None,
        match_keys: list[str] | None = None,
        unknown_cols_strategy: str = "drop",
    ) -> ImportAnalysisResult:
        """仅做解析 + 校验 + 报告，不写库.

        传入已解析的 ``rows`` 可跳过解析阶段（比如前端直接传 JSON 对象数组）.
        V2: 当 match_keys 非空时进行 upsert 匹配；当 unknown_cols_strategy == "add_text_field"
        时产出 planned_columns 供 execute 阶段自动建字段.
        """
        if rows is None:
            assert format is not None, "必须提供 format 或 rows"
            rows, file_columns = self._parse(content, format)
        else:
            file_columns = self._collect_columns(rows)

        rv = RowValidator(self.table)
        results = rv.validate_all(rows)
        report = DiffReporter.build(results, self.table.active_fields(), file_columns)

        # V2: upsert 匹配
        upsert_result: dict[str, Any] | None = None
        if match_keys:
            valid_rows = [r for r in results if r.status in ("valid", "warning")]
            valid_values = [r.values for r in valid_rows]
            exact_map, conflict_map = rec.find_rows_by_key(self.engine, self.table, match_keys, valid_values)
            new_list: list[dict[str, Any]] = []
            update_list: list[dict[str, Any]] = []
            for vr in valid_rows:
                key_tup = tuple(vr.values.get(c) for c in match_keys)
                if key_tup in exact_map:
                    update_list.append(
                        {
                            "row_number": vr.row_number,
                            "values": vr.values,
                            "match_key_values": {c: vr.values.get(c) for c in match_keys},
                            "existing_row_id": exact_map[key_tup],
                        }
                    )
                else:
                    new_list.append(
                        {
                            "row_number": vr.row_number,
                            "values": vr.values,
                            "match_key_values": {c: vr.values.get(c) for c in match_keys},
                        }
                    )
            multi_key_conflicts = sum(1 for c in conflict_map.values() if c > 1)
            upsert_result = {
                "update_rows": update_list,
                "new_rows": new_list,
                "exact_map": {str(k): v for k, v in exact_map.items()},
                "conflict_map": {str(k): v for k, v in conflict_map.items()},
                "multi_key_conflicts": multi_key_conflicts,
                "new_count": len(new_list),
                "update_count": len(update_list),
                "new_preview": self._sample_preview(new_list, match_keys, "new"),
                "update_preview": self._sample_preview(update_list, match_keys, "update"),
            }

        # V2: 未知列策略 → 字段规划
        planned_columns: list[dict[str, Any]] = []
        if unknown_cols_strategy == "add_text_field":
            existing_names = {f.name for f in self.table.fields if not f.trashed}
            unknown = [c for c in report.get("skipped_columns", []) if c not in existing_names]
            # 收集每个 unknown 列的样本
            sample_map: dict[str, list[str]] = {}
            for col in unknown:
                samples: list[str] = []
                for v in results:
                    val = v.values.get(col) if v.values else None
                    if val is not None:
                        s = str(val).strip()
                        if s and len(samples) < 50:
                            samples.append(s)
                sample_map[col] = samples
            for col in unknown:
                ft, options = DiffReporter.infer_new_column_type(sample_map[col])
                entry: dict[str, Any] = {
                    "name": col,
                    "field_type": ft,
                    "sample_values": sample_map[col][:5],
                }
                if options:
                    entry["options"] = options
                planned_columns.append(entry)

        # 最终报告（带 upsert + planned_columns）
        final_report = DiffReporter.build(
            results,
            self.table.active_fields(),
            file_columns,
            upsert_result=upsert_result,
            planned_columns=planned_columns,
        )
        return ImportAnalysisResult(
            report=final_report,
            results=results,
            file_columns=file_columns,
            upsert_result=upsert_result,
            planned_columns=planned_columns,
        )

    def execute(
        self,
        content: bytes | str | None = None,
        format: _Format | None = None,
        *,
        analysis: ImportAnalysisResult | None = None,
        rows: list[dict[str, Any]] | None = None,
        skip_errors: bool = True,
        import_warnings: bool = True,
        match_keys: list[str] | None = None,
        unknown_cols_strategy: str = "drop",
    ) -> ImportExecuteResult:
        """完整流水线：解析 → 校验 → 报告 → 落库.

        三种入口优先级：analysis > content+format > rows.
        skip_errors=True 默认跳过 error 行（只落库 valid + warning）.
        import_warnings=True 默认 warning 行也落库.
        V2: 支持 upsert 分流（match_keys 非空时按 key 更新已存在行）和自动建字段.
        """
        # 如果调用方没提供 analysis，或提供了但没有 V2 字段，先确保有完整分析
        if analysis is None or (match_keys and not analysis.upsert_result):
            analysis = self.analyze(
                content or "",
                format,
                rows=rows,
                match_keys=match_keys,
                unknown_cols_strategy=unknown_cols_strategy,
            )
        results = analysis.results
        report = analysis.report
        upsert_result = analysis.upsert_result
        planned_columns = analysis.planned_columns

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

        # V2: 先处理未知列自动新增（在 upsert 分流之前）
        if planned_columns:
            self._auto_add_fields(planned_columns)

        # V2: upsert 分流
        if upsert_result is not None:
            update_rows = upsert_result.get("update_rows") or []
            new_rows_meta = upsert_result.get("new_rows") or []
            # 构建待更新 / 待创建的 values list
            to_import_ids = {id(v) for v in to_import}
            update_values = [r["values"] for r in update_rows if id(r["values"]) in to_import_ids]
            update_list = [
                {"row_id": r["existing_row_id"], "values": rv}
                for r, rv in zip(update_rows, update_values, strict=False)
                if id(rv) in to_import_ids
            ]
            new_values = [r["values"] for r in new_rows_meta if id(r["values"]) in to_import_ids]
            updated_count = 0
            if update_list:
                updated_count = rec.bulk_update_rows(self.engine, self.table, update_list, db=self.db)
            # unmatched = 在 to_import 里但不在 upsert 的 new/update 中
            matched_new_ids = {id(rv) for rv in new_values}
            matched_update_ids = {id(rv) for rv in update_values}
            unmatched_vals = [v for v in to_import if id(v) not in matched_new_ids and id(v) not in matched_update_ids]
            all_new = new_values + unmatched_vals
            if all_new:
                ids = rec.bulk_create(self.engine, self.table, all_new, db=self.db)
            else:
                ids: list[int] = []
            report = dict(report)
            report["actually_created"] = len(ids)
            report["actually_updated"] = updated_count
        else:
            ids = rec.bulk_create(self.engine, self.table, to_import, db=self.db)
            # 更新 report：补充实际导入行数
            report = dict(report)
            report["actually_imported"] = len(ids)

        return ImportExecuteResult(imported_ids=ids, report=report, failed_results=failed)

    # ── 内部：upsert / 字段自动新增 ──────────────

    def _sample_preview(
        self,
        rows: list[dict[str, Any]],
        match_keys: list[str],
        kind: str,
    ) -> list[dict[str, Any]]:
        """生成预览数据（限前 200 行，每行前 5 个非 key 字段样本）."""
        preview: list[dict[str, Any]] = []
        for item in rows[:200]:
            entry: dict[str, Any] = {
                "row_number": item["row_number"],
                "match_key_values": item["match_key_values"],
            }
            if kind == "update":
                entry["existing_row_id"] = item["existing_row_id"]
            # 取前 5 个非 match_keys 字段作为样本
            sample_fields: dict[str, Any] = {}
            counter = 0
            for k, v in item["values"].items():
                if k in match_keys:
                    continue
                if v is None:
                    continue
                sample_fields[k] = v
                counter += 1
                if counter >= 5:
                    break
            entry["field_sample"] = sample_fields
            preview.append(entry)
        return preview

    def _auto_add_fields(self, planned_columns: list[dict[str, Any]]) -> None:
        """根据 planned_columns 自动创建 DataField + DDL 物理列（事务安全）.

        事务策略：先 ORM add 不 commit → 跑 DDL（失败就逆向 drop）→ 最后 ORM commit.
        同名已存在字段跳过（幂等）.
        """
        from cndb.plugins.tables import ddl
        from cndb.plugins.tables.models import DataField

        if not planned_columns:
            return

        existing_names = {f.name for f in self.table.fields if not f.trashed}
        fields_to_create: list[DataField] = []

        for plan in planned_columns:
            name = plan["name"]
            if name in existing_names:
                continue
            field_type = plan.get("field_type", "text")
            options = plan.get("options") or []
            cfg: dict[str, Any] = {}
            if field_type == "select" and options:
                cfg["options"] = options
            if field_type in ("float", "number"):
                max_dec = 0
                for s in plan.get("sample_values", [])[:50]:
                    try:
                        text = str(s)
                        if "." in text:
                            dec = len(text.split(".", 1)[1])
                            max_dec = max(max_dec, dec)
                    except (TypeError, ValueError):
                        continue
                cfg["decimals"] = min(max_dec, 10) if max_dec > 0 else 2

            f = DataField(
                table_id=self.table.id,
                name=name,
                field_type=field_type,
                config=cfg,
                order=len(self.table.fields) + len(fields_to_create),
            )
            f.ensure_db_name()
            self.db.add(f)
            fields_to_create.append(f)

        # DDL 阶段：先全部 DDL 成功再 commit ORM
        ddl_ok: list[DataField] = []
        try:
            for f in fields_to_create:
                ddl.add_column(self.engine, self.table, f)
                ddl_ok.append(f)
            self.db.commit()
            # 刷新 table.fields 缓存（Importer 构造时已缓存 table 对象，需要重新绑定新字段）
            self.db.refresh(self.table)
        except Exception:
            # 逆向清理已成功的 DDL 列
            for f in reversed(ddl_ok):
                with contextlib.suppress(Exception):
                    ddl.drop_column(self.engine, self.table, f)
            # ORM rollback（DataField 尚未 commit，这步清理其 pending 状态）
            with contextlib.suppress(Exception):
                self.db.rollback()
            raise

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
