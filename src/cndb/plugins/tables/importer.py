"""导入流水线编排器 —— Parser → RowValidator → DiffReporter → bulk_create.

Importer 是"文件导入追加到已有表"的统一入口。它串联：
1. 解析：把 CSV / JSON / XLSX 原始内容转为 ``list[dict[str, Any]]``
2. 校验：RowValidator 逐行校验，不中断
3. 报告：DiffReporter 汇总 valid/warning/error
4. 匹配（V2）：若指定 match_keys，调 records.find_rows_by_key 做 upsert 分类
5. 规划（V2）：若 unknown_cols_strategy="add_text_field"，推断未知列类型
6. 落库：过滤出 valid（可选加 warning）行 → 按分类调 bulk_update_rows + bulk_create

与 :mod:`transfer` 的关系：Importer 是上层编排，transfer 做底层解析；
transfer 的三个 ``import_rows_from_*`` 保留作为旧流程直连接口，不被 Importer 替代。

支持字段映射与缺口填充：
- field_mapping: ``{源列名: 目标字段名}`` —— 把文件/API 的列对齐到目标表字段
- gap_filling:   目标侧缺失字段的填充策略 — "empty" / "default" / "value" / "error"
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy.orm import Session

from cndb.plugins.tables import records as rec
from cndb.plugins.tables.cleaning import apply_cleaning_actions, generate_cleaning_suggestions
from cndb.plugins.tables.column_profiler import profile_columns
from cndb.plugins.tables.ddl import add_column
from cndb.plugins.tables.diff_reporter import DiffReporter
from cndb.plugins.tables.field_mapping import GapFilling
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.row_validator import RowValidator, ValidationResult
from cndb.plugins.tables.transfer import decode_bytes_auto, sniff_csv_delimiter

_Format = str


# ── 结果数据结构 ───────────────────────────────────


@dataclass
class ImportAnalysisResult:
    """analyze() 阶段返回."""

    report: dict[str, Any]
    results: list[ValidationResult]
    file_columns: list[str]
    # V2: upsert 相关
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
    """统一导入流水线（V2 支持 upsert + 未知列自动新增）.

    Args:
        engine: SQLAlchemy Engine（bulk_create / bulk_update_rows 用）.
        db: SQLAlchemy Session（link 字段写入关联表时需要传 + ORM 持久化 DataField）.
        table: 目标数据表.
        field_mapping: 可选的源列 → 目标字段映射 — 透传给 RowValidator.
        gap_filling: 目标侧缺失字段填充策略 — 透传给 RowValidator.
        fill_values: gap_filling="value" 时的固定值 — 透传给 RowValidator.
    """

    # 预览截断上限
    PREVIEW_LIMIT = 200
    SAMPLE_FIELD_LIMIT = 5

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
        match_keys: list[str] | None = None,
        unknown_cols_strategy: str = "drop",
    ) -> ImportAnalysisResult:
        """仅做解析 + 校验 + 报告 + upsert 匹配 + 字段规划，不写库.

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

        # ── V2: upsert 匹配 ─────────────────────
        upsert_result: dict[str, Any] | None = None
        if match_keys:
            upsert_result = self._build_upsert_result(results, match_keys)

        # ── V2: 未知列规划 ───────────────────────
        planned_columns: list[dict[str, Any]] = []
        if unknown_cols_strategy == "add_text_field":
            # 先拿默认 DiffReporter.build 算出 skipped_columns
            default_report = DiffReporter.build(results, self.table.active_fields(), file_columns)
            skipped = default_report.get("skipped_columns", [])
            planned_columns = self._plan_unknown_columns(rows, skipped)

        # ── Task 2: 列级数据质量画像 ────────────────
        column_profiles, data_quality_summary = profile_columns(rows, file_columns)

        # 最终报告（带 upsert + planned_columns + 数据画像）
        report = DiffReporter.build(
            results,
            self.table.active_fields(),
            file_columns,
            upsert_result=upsert_result,
            planned_columns=planned_columns,
            column_profiles=column_profiles,
            data_quality_summary=data_quality_summary,
        )

        # ── Task 4: 清洗建议生成 ─────────────────────
        report["cleaning_suggestions"] = generate_cleaning_suggestions(column_profiles, data_quality_summary)

        return ImportAnalysisResult(
            report=report,
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
        cleaning_actions: list[dict[str, Any]] | None = None,
    ) -> ImportExecuteResult:
        """完整流水线：解析 → （可选）清洗 → 校验 → 报告 → upsert → 落库.

        三种入口优先级：analysis > content+format > rows.
        cleaning_actions 若非空，会在 RowValidator 之前应用到原始 rows 上，
        清洗结果写入 report.cleaning_applied.
        """
        if analysis is not None:
            # 若需清洗，必须回退到原始 rows 重新跑 analyze
            if cleaning_actions:
                orig_rows = self._resolve_original_rows(content, format, rows, analysis)
                cleaned_rows, applied = apply_cleaning_actions(
                    orig_rows, analysis.report.get("column_profiles", []), cleaning_actions
                )
                analysis = self.analyze(
                    content or "",
                    format,
                    rows=cleaned_rows,
                    match_keys=match_keys,
                    unknown_cols_strategy=unknown_cols_strategy,
                )
                analysis.report["cleaning_applied"] = applied
            results = analysis.results
            report = analysis.report
            upsert_result = analysis.upsert_result
            planned_columns = analysis.planned_columns
        else:
            # 先 parse 原始 rows，可能做清洗
            if rows is None:
                assert format is not None, "必须提供 format 或 rows"
                rows, _orig_cols = self._parse(content or "", format)
            if cleaning_actions:
                # 需要列画像来做 IQR / fill_null，先快速跑一次 analyze 拿 profiles
                tmp = self.analyze(content or "", format, rows=rows)
                rows, applied = apply_cleaning_actions(rows, tmp.report.get("column_profiles", []), cleaning_actions)
                analysis = self.analyze(
                    content or "",
                    format,
                    rows=rows,
                    match_keys=match_keys,
                    unknown_cols_strategy=unknown_cols_strategy,
                )
                analysis.report["cleaning_applied"] = applied
            else:
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

        # ── V2: 字段自动新增（在 upsert / create 之前）──
        if planned_columns:
            self._auto_add_fields(planned_columns)

        # ── 过滤要落库的行 ────────────────────────
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

        # ── V2: upsert 分流 ───────────────────────
        new_ids: list[int] = []
        updated_count = 0

        if upsert_result is not None and (
            upsert_result.get("update_rows") or upsert_result.get("multi_key_conflicts", 0) > 0
        ):
            update_list = upsert_result.get("update_rows", [])
            new_list = upsert_result.get("new_rows", [])

            # new_list 里每项直接是 values dict（不带包装），update_list 每项是 {"row_id", "values"}
            # 用 id() 集合做 O(1) 过滤（new_list/update_list 里的 dict 与 to_import 里的是同一对象）
            to_import_ids = {id(v) for v in to_import}
            valid_update: list[dict[str, Any]] = []
            valid_new_vals: list[dict[str, Any]] = []
            if update_list:
                valid_update = [item for item in update_list if id(item["values"]) in to_import_ids]
                updated_count = rec.bulk_update_rows(self.engine, self.table, valid_update, db=self.db)
            if new_list:
                valid_new_vals = [v for v in new_list if id(v) in to_import_ids]
            # skip_errors=False 场景下，error 行也进 to_import 但 upsert 里没匹配到 → 一并创建
            matched_ids = {id(item["values"]) for item in valid_update} | {id(v) for v in valid_new_vals}
            unmatched_vals = [v for v in to_import if id(v) not in matched_ids]
            all_new = valid_new_vals + unmatched_vals
            if all_new:
                new_ids = rec.bulk_create(self.engine, self.table, all_new, db=self.db)
        else:
            # 纯追加路径（兼容旧流程）
            new_ids = rec.bulk_create(self.engine, self.table, to_import, db=self.db)

        # 更新 report：补充实际行数
        report = dict(report)
        report["actually_created"] = len(new_ids)
        report["actually_updated"] = updated_count
        report["actually_imported"] = len(new_ids) + updated_count

        return ImportExecuteResult(
            imported_ids=new_ids,
            report=report,
            failed_results=failed,
        )

    # ── V2: upsert 匹配 ──────────────────────

    def _build_upsert_result(
        self,
        results: list[ValidationResult],
        match_keys: list[str],
    ) -> dict[str, Any]:
        """对 valid + warning 行做 upsert 匹配，产出 new/update 分类 + 预览 + 字段级 diff.

        Returns:
            {
                "new_count": int,
                "update_count": int,
                "multi_key_conflicts": int,
                "new_preview": [...],
                "update_preview": [...],  # 每项含 field_diffs（仅变化的字段）
                "new_rows": [...],
                "update_rows": [...],
            }
        """
        # 收集待匹配行（valid + warning），同时记录原 results 顺序
        to_match: list[tuple[ValidationResult, dict[str, Any]]] = []
        for r in results:
            if r.status in ("valid", "warning"):
                to_match.append((r, r.values))

        values_list = [v for _, v in to_match]
        if not values_list:
            return {
                "new_count": 0,
                "update_count": 0,
                "multi_key_conflicts": 0,
                "new_preview": [],
                "update_preview": [],
                "new_rows": [],
                "update_rows": [],
            }

        exact_map, conflict_map = rec.find_rows_by_key(
            self.engine,
            self.table,
            match_keys,
            values_list,
        )

        # ── 批量查出旧行全部业务字段（供字段级 diff） ──
        existing_row_ids = list({int(rid) for rid in exact_map.values()})
        old_rows_by_id = self._fetch_old_rows_by_ids(existing_row_ids) if existing_row_ids else {}

        # 更新路径：先查库拿到 reference columns 做 preview
        # exact_map 的 key 是 tuple，和文件行里 match_keys 的值一一对应
        new_preview: list[dict[str, Any]] = []
        update_preview: list[dict[str, Any]] = []
        new_rows: list[dict[str, Any]] = []
        update_rows: list[dict[str, Any]] = []
        multi_key_conflicts = len(conflict_map)

        key_cols_set = set(match_keys)

        for r, values in to_match:
            key_tup = tuple(values.get(c) for c in match_keys)
            existing_row_id = exact_map.get(key_tup)
            match_key_values = {c: values.get(c) for c in match_keys}
            field_sample = self._sample_fields(values, key_cols_set)

            if existing_row_id is not None:
                update_rows.append({"row_id": existing_row_id, "values": values})
                if len(update_preview) < self.PREVIEW_LIMIT:
                    old_values = old_rows_by_id.get(int(existing_row_id), cast(dict[str, Any], {}))
                    field_diffs = self._build_field_diffs(old_values, values, key_cols_set)
                    update_preview.append(
                        {
                            "row_number": r.row_number,
                            "match_key_values": match_key_values,
                            "existing_row_id": existing_row_id,
                            "field_sample": field_sample,
                            "field_diffs": field_diffs,
                        }
                    )
            else:
                new_rows.append(values)
                if len(new_preview) < self.PREVIEW_LIMIT:
                    new_preview.append(
                        {
                            "row_number": r.row_number,
                            "match_key_values": match_key_values,
                            "field_sample": field_sample,
                        }
                    )

        return {
            "new_count": len(new_rows),
            "update_count": len(update_rows),
            "multi_key_conflicts": multi_key_conflicts,
            "new_preview": new_preview,
            "update_preview": update_preview,
            "new_rows": new_rows,
            "update_rows": update_rows,
        }

    def _fetch_old_rows_by_ids(self, row_ids: list[int]) -> dict[int, dict[str, Any]]:
        """按 row_id 批量查询旧行全部业务字段值，返回 {row_id: {field_name: value}}."""
        if not row_ids:
            return {}

        from sqlalchemy import select

        sa_table = rec._get_sa_table(self.engine, self.table)
        # 构造 field_name → db_column_name 映射
        col_map: dict[str, str] = {}
        for f in self.table.active_fields():
            if f.db_column_name:
                col_map[f.name] = f.db_column_name

        # 只查 db_column_name 对应的列
        db_cols = [sa_table.c[c] for c in col_map.values() if c in sa_table.c]
        db_col_names = [c.name for c in db_cols]

        with self.engine.connect() as conn:
            stmt = select(sa_table.c.id, *db_cols).where(sa_table.c.id.in_(row_ids))
            rows = conn.execute(stmt).mappings().all()

        result: dict[int, dict[str, Any]] = {}
        # 反转映射：db_column_name → field_name
        db_to_field = {db: fname for fname, db in col_map.items()}
        for row in rows:
            rid = int(row["id"])
            old_vals: dict[str, Any] = {}
            for db_col in db_col_names:
                fname = db_to_field.get(db_col)
                if fname is not None:
                    old_vals[fname] = row[db_col]
            result[rid] = old_vals
        return result

    @staticmethod
    def _build_field_diffs(
        old_values: dict[str, Any],
        new_values: dict[str, Any],
        key_cols: set[str],
    ) -> dict[str, dict[str, Any]]:
        """逐字段比较 old vs new，仅返回有差异的业务字段（不含 match_keys）.

        Returns:
            {field_name: {"old": ..., "new": ..., "changed": bool}}  — 仅包含 changed=True 的字段.
        """
        diffs: dict[str, dict[str, Any]] = {}
        # 遍历 new 里的所有业务字段（文件侧为准），排除 key 列
        for fname, new_val in new_values.items():
            if fname in key_cols:
                continue
            old_val = old_values.get(fname)
            if not Importer._values_equal(old_val, new_val):
                diffs[fname] = {"old": old_val, "new": new_val, "changed": True}
        return diffs

    @staticmethod
    def _values_equal(a: Any, b: Any) -> bool:
        """比较两个值是否相等，处理 None / 空串 / 数字类型差异."""
        # 先处理 None 分支
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        # 字符串 vs 数字：尝试宽松比较
        if isinstance(a, (int, float)) and isinstance(b, str):
            try:
                return a == type(a)(b)  # type: ignore[arg-type]
            except (ValueError, TypeError):
                return str(a).strip() == b.strip()
        if isinstance(b, (int, float)) and isinstance(a, str):
            try:
                return b == type(b)(a)  # type: ignore[arg-type]
            except (ValueError, TypeError):
                return str(b).strip() == a.strip()
        # 字符串去空白比较
        if isinstance(a, str) and isinstance(b, str):
            return a.strip() == b.strip()
        return a == b

    # ── V2: 未知列规划 ───────────────────────

    def _plan_unknown_columns(
        self,
        rows: list[dict[str, Any]],
        skipped_columns: list[str],
    ) -> list[dict[str, Any]]:
        """对 skipped_columns 里每列收集样本值 + 推断类型.

        Returns:
            [{name, field_type, options, sample_values}]
        """
        if not skipped_columns:
            return []
        column_samples: dict[str, list[str]] = {c: [] for c in skipped_columns}
        for row in rows:
            for col in skipped_columns:
                val = row.get(col)
                if val is None:
                    continue
                s = str(val).strip()
                if s and len(column_samples[col]) < 50:
                    column_samples[col].append(s)

        plan: list[dict[str, Any]] = []
        for col in skipped_columns:
            field_type, options = DiffReporter.infer_new_column_type(column_samples[col])
            entry: dict[str, Any] = {
                "name": col,
                "field_type": field_type,
                "sample_values": column_samples[col][:5],
            }
            if options:
                entry["options"] = options
            plan.append(entry)
        return plan

    # ── V2: 字段自动新增（execute 前） ────────

    def _auto_add_fields(self, planned_columns: list[dict[str, Any]]) -> None:
        """根据 planned_columns 自动创建 DataField + DDL 物理列.

        事务策略：先持久化 DataField（拿到 db_column_name），再 DDL 加列.
        DDL 失败 → 回滚已 add 的 DataField；同名已存在则跳过（幂等）.
        """
        if not planned_columns:
            return

        existing_names = {f.name for f in self.table.fields if not f.trashed}
        fields_to_create: list[DataField] = []

        # ── 第一阶段：构造所有 DataField 对象（ORM add 但不 commit） ──
        from cndb.plugins.tables.transfer import _options_strings_to_dicts

        for plan in planned_columns:
            name = plan["name"]
            if name in existing_names:
                continue  # 同名跳过
            field_type = plan.get("field_type", "text")
            options = plan.get("options") or []
            cfg: dict[str, Any] = {}
            if field_type == "select" and options:
                cfg["options"] = _options_strings_to_dicts(options)
            # float 字段自动推断 decimals（NumberFieldConfig 默认 0 会导致 round(5.5, 0)=6）
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
                order=max((f2.order for f2 in self.table.fields if not f2.trashed), default=-1)
                + 1
                + len(fields_to_create),
            )
            f.ensure_db_name()  # 生成 db_column_name（不依赖 ORM commit）
            self.db.add(f)
            fields_to_create.append(f)

        if not fields_to_create:
            return

        # ── 第二阶段：全部 DDL 先成功，再 ORM commit（避免孤儿 DataField） ──
        from cndb.plugins.tables.ddl import drop_column

        ddl_ok: list[DataField] = []  # 记录 DDL 成功的字段，失败时逆向清理
        try:
            for f in fields_to_create:
                add_column(self.engine, self.table, f)
                ddl_ok.append(f)
        except Exception:
            # 逆向清理已成功的 DDL 列
            for f in reversed(ddl_ok):
                with contextlib.suppress(Exception):
                    drop_column(self.engine, self.table, f)
            # ORM rollback（此时 DataField 尚未 commit，rollback 有效）
            with contextlib.suppress(Exception):
                self.db.rollback()
            raise

        # 全部 DDL 成功 → 持久化 DataField 元数据
        self.db.commit()
        self.db.refresh(self.table)

    # ── 工具：预览样本字段 ────────────────────

    def _sample_fields(self, values: dict[str, Any], key_cols: set[str]) -> dict[str, Any]:
        """取前 5 个非 key、非空的字段做预览."""
        sample: dict[str, Any] = {}
        count = 0
        for k, v in values.items():
            if k in key_cols:
                continue
            if v is None or v == "":
                continue
            sample[k] = v if not isinstance(v, str) or len(v) <= 60 else v[:57] + "..."
            count += 1
            if count >= self.SAMPLE_FIELD_LIMIT:
                break
        return sample

    # ── 内部：解析 ──────────────────────────────

    def _parse(self, content: bytes | str, format: _Format) -> tuple[list[dict[str, Any]], list[str]]:
        """把文件内容转为 (行列表, 文件列名)."""
        if format in ("csv", "tsv", "delimited"):
            return self._parse_csv(content, delimiter=None)
        if format == "json":
            return self._parse_json(content)
        if format == "xlsx":
            return self._parse_xlsx(content)
        raise ValueError(f"不支持的格式: {format}")

    @staticmethod
    def _parse_csv(
        content: bytes | str,
        *,
        delimiter: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """解析分隔符文本，自动 sniff 分隔符（逗号/分号/pipe/tab）."""
        if isinstance(content, bytes):
            text, _enc, _conf = decode_bytes_auto(content)
        else:
            text = content
        delim = delimiter or sniff_csv_delimiter(text)
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        file_columns = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
        return rows, file_columns

    @staticmethod
    def _parse_json(content: bytes | str) -> tuple[list[dict[str, Any]], list[str]]:
        if isinstance(content, bytes):
            text, _enc, _conf = decode_bytes_auto(content)
        else:
            text = content
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

    def _resolve_original_rows(
        self,
        content: bytes | str | None,
        fmt: _Format | None,
        rows: list[dict[str, Any]] | None,
        analysis: ImportAnalysisResult,
    ) -> list[dict[str, Any]]:
        """在 execute 清洗分支里拿到"原始未解析前"的 rows.

        优先级：直接传的 rows > content + format 重新解析 > 从 analysis.results 反推.
        最后一个兜底是 analysis.results 里每个 ValidationResult.values，
        这些值经过 RowValidator 可能被类型转换过，但总比空好。
        """
        if rows is not None:
            return rows
        if content is not None and fmt is not None:
            return self._parse(content, fmt)[0]
        # 兜底：从 analysis.results 反推
        return [r.values for r in analysis.results]


def guess_format_from_content(content: bytes | str) -> _Format:
    """从内容推断格式（按内容特征而非文件名）."""
    if isinstance(content, bytes):
        text, enc, _conf = decode_bytes_auto(content)
        # 如果兜底编码是 latin-1，说明原始字节无法被任何文本编码解码，
        # 很可能是二进制（xlsx / 图片等），返回 xlsx 让调用方尝试 openpyxl 解析
        if enc == "latin-1":
            return "xlsx"
    else:
        text = content
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(stripped[:2048])
            return "json"
        except Exception:
            pass
    # 快速检查：是否包含制表符 — 若是优先判为 tsv
    first_line = stripped.splitlines()[0] if stripped.splitlines() else ""
    if "\t" in first_line and "," not in first_line and ";" not in first_line:
        return "tsv"
    if "," in first_line or ";" in first_line or "|" in first_line:
        return "csv"
    return "csv"  # 默认兜底


__all__ = [
    "ImportAnalysisResult",
    "ImportExecuteResult",
    "Importer",
    "guess_format_from_content",
]
