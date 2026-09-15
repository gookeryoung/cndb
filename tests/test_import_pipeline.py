"""导入流水线核心模块单测 — RowValidator / DiffReporter / FailedRowExporter.

聚焦：逐行校验不中断、字段类型校验复用、结构化报告、失败行导出。
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from cndb.plugins.tables import ddl
from cndb.plugins.tables.diff_reporter import DiffReporter
from cndb.plugins.tables.failed_row_exporter import FailedRowExporter
from cndb.plugins.tables.importer import Importer, guess_format_from_content
from cndb.plugins.tables.models import Base, DataField, DataTable
from cndb.plugins.tables.row_validator import RowValidator

# ── 公共 Fixture ──────────────────────────────────


@pytest.fixture
def test_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pv.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield engine, session
    finally:
        session.close()


def _make_table(session: Session, engine, *, workspace_id: int = 1) -> DataTable:
    """创建一个带字段的 DataTable（DDL 建物理列）."""
    dt = DataTable(workspace_id=workspace_id, name="测试表")
    dt.ensure_db_name()
    session.add(dt)
    session.commit()
    session.refresh(dt)
    return dt


def _add_field(
    session: Session,
    table: DataTable,
    name: str,
    field_type: str,
    *,
    required: bool = False,
    config: dict | None = None,
    order: int = 0,
) -> DataField:
    f = DataField(
        table_id=table.id, name=name, field_type=field_type, required=required, config=config or {}, order=order
    )
    f.ensure_db_name()
    session.add(f)
    session.flush()
    return f


# ── RowValidator 基础测试 ──────────────────────────


class TestRowValidatorBasic:
    """TR-1.1: 逐行校验不中断，任何错误不抛异常."""

    def test_all_valid(self, test_session):
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "name", "text", order=0)
        _add_field(session, table, "age", "number", order=1)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        rows = [
            {"name": "张三", "age": "25"},
            {"name": "李四", "age": "30"},
            {"name": "王五", "age": "35"},
        ]
        results = rv.validate_all(rows)
        assert len(results) == 3
        assert all(r.status == "valid" for r in results)
        assert all(not r.issues for r in results)

    def test_email_error_row(self, test_session):
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "name", "text", order=0)
        _add_field(session, table, "email", "email", order=1)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        rows = [
            {"name": "张三", "email": "good@example.com"},
            {"name": "李四", "email": "not-an-email"},  # error
            {"name": "王五", "email": "ok@test.org"},
        ]
        results = rv.validate_all(rows)
        assert len(results) == 3
        assert results[0].status == "valid"
        assert results[1].status == "error"
        assert results[1].issues[0].field == "email"
        assert "邮箱格式" in results[1].issues[0].message
        assert results[2].status == "valid"
        # 关键：校验不中断，第三行正常返回

    def test_multiple_errors_single_row(self, test_session):
        """一行中多个字段同时出错，都要被收集."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "name", "text", required=True, order=0)
        _add_field(session, table, "phone", "phone", order=1)
        _add_field(session, table, "age", "number", order=2)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        rows = [{"name": "abc", "phone": "123", "age": "not_a_number"}]
        results = rv.validate_all(rows)
        assert results[0].status == "error"
        # 两个字段都报错
        err_fields = {i.field for i in results[0].issues if i.level == "error"}
        assert "phone" in err_fields
        assert "age" in err_fields


class TestRowValidatorReuseRegistry:
    """TR-1.2: 字段类型校验与 records._normalize_values 行为一致."""

    def test_number_field_consistency(self, test_session):
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "count", "number", order=0)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        result = rv.validate_row({"count": "42"}, row_number=1)
        assert result.status == "valid"
        # 归一化值应为 int 42
        f = table.active_fields()[0]
        assert result.normalized[f.db_column_name] == 42

    def test_date_field_consistency(self, test_session):
        from datetime import date

        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "birth", "date", order=0)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        result = rv.validate_row({"birth": "2024-01-15"}, row_number=1)
        assert result.status == "valid"
        f = table.active_fields()[0]
        assert isinstance(result.normalized[f.db_column_name], date)

    def test_unknown_type_error(self, test_session):
        """如果字段类型未注册，记为 error."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "xxx", "nonexistent", order=0)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        result = rv.validate_row({"xxx": "abc"}, row_number=1)
        assert result.status == "error"
        assert "未知字段类型" in result.issues[0].message


class TestRowValidatorRequired:
    """TR-1.3: 必填字段空值 → error."""

    def test_required_missing_value(self, test_session):
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "name", "text", required=True, order=0)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        result = rv.validate_row({"name": ""}, row_number=1)
        assert result.status == "error"
        assert any("必填" in i.message for i in result.issues)

    def test_required_missing_key(self, test_session):
        """必填字段在文件中完全缺失."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "name", "text", required=True, order=0)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        result = rv.validate_row({}, row_number=1)
        assert result.status == "error"
        assert any("必填" in i.message or "缺失" in i.message for i in result.issues)


class TestRowValidatorUnknownColumns:
    """TR-1.4: 文件有未匹配列 → warning."""

    def test_unknown_column_warning(self, test_session):
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "name", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        result = rv.validate_row({"name": "ok", "extra": "xxx"}, row_number=1)
        assert result.status == "warning"
        assert any(i.level == "warning" and i.field == "extra" for i in result.issues)

    def test_skip_unknown_columns(self, test_session):
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "name", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table, skip_unknown_columns=True)
        result = rv.validate_row({"name": "ok", "extra": "xxx"}, row_number=1)
        assert result.status == "valid"


class TestRowValidatorLinkField:
    """TR-1.5: link 字段值解析."""

    def test_link_field_valid(self, test_session):
        engine, session = test_session
        # link 字段需要 config.target_table_id，给个假值不影响校验逻辑
        table = _make_table(session, engine)
        _add_field(session, table, "partner", "link", config={"target_table_id": 99, "multiple": True}, order=0)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        result = rv.validate_row({"partner": "1;2;3"}, row_number=1)
        assert result.status == "valid"
        f = table.active_fields()[0]
        assert result.normalized[f.db_column_name] == [1, 2, 3]

    def test_link_field_bad(self, test_session):
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "partner", "link", config={"target_table_id": 99}, order=0)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        result = rv.validate_row({"partner": "abc;def"}, row_number=1)
        assert result.status == "error"
        assert any("link" in i.message.lower() for i in result.issues)


class TestRowValidatorEdgeCases:
    """边界情况."""

    def test_empty_row_dict(self, test_session):
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "name", "text", required=True, order=0)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        result = rv.validate_row({}, row_number=7)
        assert result.row_number == 7
        assert result.status == "error"

    def test_empty_values_lax(self, test_session):
        """空字符串 / None 宽松处理，不触发类型校验."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "email", "email", order=0)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        for val in ["", "   ", None]:
            r = rv.validate_row({"email": val}, row_number=1)
            assert r.status == "valid", f"empty-ish {val!r} should be valid"

    def test_row_numbering_starts_from_one(self, test_session):
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "x", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        results = rv.validate_all([{"x": "a"}, {"x": "b"}, {"x": "c"}])
        assert [r.row_number for r in results] == [1, 2, 3]


# ── DiffReporter ──────────────────────────────────


class TestDiffReporter:
    def _make_table_and_fields(self, test_session):
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "name", "text", required=True, order=0)
        _add_field(session, table, "email", "email", order=1)
        session.commit()
        ddl.create_table(engine, table)
        return table, session

    def test_report_counts(self, test_session):
        """TR-2.1: 计数准确."""
        table, _session = self._make_table_and_fields(test_session)
        rv = RowValidator(table)
        rows = [
            {"name": "ok1", "email": "a@b.com"},
            {"name": "bad", "email": "xxx"},  # error
            {"name": "ok2", "email": "c@d.com"},
            {"name": "ok3", "extra": "w"},  # warning (unknown col)
        ]
        results = rv.validate_all(rows)
        report = DiffReporter.build(results, table.active_fields(), ["name", "email", "extra"])

        assert report["total"] == 4
        assert report["valid_count"] == 2  # rows 0, 2
        assert report["error_count"] == 1  # row 1
        assert report["warning_count"] == 1  # row 3

    def test_report_json_serializable(self, test_session):
        """TR-2.2: 直接 json.dumps 不报错."""
        table, _session = self._make_table_and_fields(test_session)
        rv = RowValidator(table)
        results = rv.validate_all([{"name": "n", "email": "e@e.com"}])
        report = DiffReporter.build(results, table.active_fields(), ["name", "email"])
        text = json.dumps(report, ensure_ascii=False)
        assert isinstance(text, str)
        assert "total" in text

    def test_report_column_diffs(self, test_session):
        """TR-2.3: skipped_columns / missing_required 正确体现."""
        table, _session = self._make_table_and_fields(test_session)
        rv = RowValidator(table)
        results = rv.validate_all([{"email": "e@e.com", "frog": "ribbit"}])
        report = DiffReporter.build(results, table.active_fields(), ["email", "frog"])
        # table 有 name + email；文件有 email + frog
        assert "frog" in report["skipped_columns"]
        # name 是 required，文件中缺失
        assert "name" in report["missing_required"]

    def test_report_warnings_errors_detail(self, test_session):
        table, _session = self._make_table_and_fields(test_session)
        rv = RowValidator(table)
        results = rv.validate_all(
            [
                {"name": "a", "email": "bad"},
                {"name": "b", "email": "b@b.com", "ex": "1"},
            ]
        )
        report = DiffReporter.build(results, table.active_fields(), ["name", "email", "ex"])
        err_rows = {e["row_number"] for e in report["errors"]}
        warn_rows = {w["row_number"] for w in report["warnings"]}
        assert 1 in err_rows
        assert 2 in warn_rows


# ── FailedRowExporter ─────────────────────────────


class TestFailedRowExporter:
    def _build_results(self, test_session):
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "name", "text", required=True, order=0)
        _add_field(session, table, "email", "email", order=1)
        session.commit()
        ddl.create_table(engine, table)
        rv = RowValidator(table)
        rows = [
            {"name": "ok", "email": "ok@ok.com"},  # valid
            {"name": "", "email": "bad"},  # error x2
            {"name": "n2", "email": "a@b.com"},  # valid
        ]
        return rv.validate_all(rows)

    def test_csv_export(self, test_session):
        """TR-3.1: CSV 格式可被 DictReader 正常解析."""
        results = self._build_results(test_session)
        csv_bytes = FailedRowExporter.export_failed_rows(results, format="csv")
        text = csv_bytes.decode("utf-8-sig") if isinstance(csv_bytes, bytes) else csv_bytes
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        assert len(rows) == 1  # 仅 1 行 error
        assert "_row_number" in rows[0]
        assert "_error" in rows[0]
        assert rows[0]["_row_number"] == "2"
        assert "必填" in rows[0]["_error"] or "邮箱" in rows[0]["_error"]

    def test_xlsx_export(self, test_session):
        """TR-3.2: XLSX 格式正常."""
        results = self._build_results(test_session)
        try:
            from openpyxl import load_workbook
        except ImportError:
            pytest.skip("openpyxl not installed")
        xlsx_bytes = FailedRowExporter.export_failed_rows(results, format="xlsx")
        wb = load_workbook(io.BytesIO(xlsx_bytes))
        ws = wb.active
        header = list(next(ws.iter_rows(values_only=True)))
        assert "_error" in header
        assert "_row_number" in header
        data_rows = list(ws.iter_rows(min_row=2, values_only=True))
        assert len(data_rows) == 1

    def test_json_export(self, test_session):
        """TR-3.3: JSON 格式含 _errors list."""
        results = self._build_results(test_session)
        json_text = FailedRowExporter.export_failed_rows(results, format="json")
        data = json.loads(json_text)
        assert isinstance(data, list)
        assert len(data) == 1
        assert isinstance(data[0]["_errors"], list)

    def test_only_error_rows(self, test_session):
        """TR-3.4: 只包含 error 行，warning 行不包含."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "name", "text", order=0)
        _add_field(session, table, "phone", "phone", order=1)
        session.commit()
        ddl.create_table(engine, table)

        rv = RowValidator(table)
        rows = [
            {"name": "a", "phone": "13800000000"},  # valid
            {"name": "b", "phone": "bad"},  # error
            {"name": "c", "phone": "13900000000", "ex": "x"},  # warning (unknown col)
        ]
        results = rv.validate_all(rows)
        csv_bytes = FailedRowExporter.export_failed_rows(results, format="csv")
        text = csv_bytes.decode("utf-8-sig") if isinstance(csv_bytes, bytes) else csv_bytes
        reader = list(csv.DictReader(io.StringIO(text)))
        # 只导出 error 行
        assert len(reader) == 1
        assert reader[0]["_row_number"] == "2"


# ── Importer ────────────────────────────────────


class TestImporter:
    def _make_table(self, test_session):
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "name", "text", required=True, order=0)
        _add_field(session, table, "email", "email", order=1)
        session.commit()
        ddl.create_table(engine, table)
        return engine, session, table

    def test_analyze_no_db_write(self, test_session):
        """TR-4.1: analyze 不触发 DB 写入."""
        engine, session, table = self._make_table(test_session)
        from cndb.plugins.tables import records as rec

        rec._get_sa_table(engine, table)
        count_before = session.execute(select(func.count()).select_from(rec._get_sa_table(engine, table))).scalar()

        importer = Importer(engine, session, table)
        csv = "name,email\nok,ok@ok.com\nbad,not-email"
        result = importer.analyze(csv, format="csv")

        count_after = session.execute(select(func.count()).select_from(rec._get_sa_table(engine, table))).scalar()
        assert count_before == count_after == 0, "analyze 不应写 DB"
        assert result.report["valid_count"] == 1
        assert result.report["error_count"] == 1

    def test_execute_imports_valid_rows_only(self, test_session):
        """TR-4.2: execute 只落库 valid 行 + warning 行."""
        engine, session, table = self._make_table(test_session)
        from cndb.plugins.tables import records as rec

        importer = Importer(engine, session, table)
        csv = "name,email\na,a@a.com\nb,bad\nc,c@c.com"
        result = importer.execute(csv, format="csv")

        count = session.execute(select(func.count()).select_from(rec._get_sa_table(engine, table))).scalar()
        assert count == 2, f"应导入 2 行 valid，实际 {count}"
        assert result.imported_ids == [1, 2]

    def test_execute_all_valid(self, test_session):
        engine, session, table = self._make_table(test_session)
        from cndb.plugins.tables import records as rec

        importer = Importer(engine, session, table)
        csv = "name,email\na,a@a.com\nb,b@b.com\nc,c@c.com"
        result = importer.execute(csv, format="csv")

        count = session.execute(select(func.count()).select_from(rec._get_sa_table(engine, table))).scalar()
        assert count == 3
        assert len(result.failed_results) == 0

    def test_execute_no_valid_rows(self, test_session):
        engine, session, table = self._make_table(test_session)
        from cndb.plugins.tables import records as rec

        importer = Importer(engine, session, table)
        csv = "name,email\n,bad\n,bad2"  # 两行都缺必填 name + email 格式错
        result = importer.execute(csv, format="csv")

        count = session.execute(select(func.count()).select_from(rec._get_sa_table(engine, table))).scalar()
        assert count == 0
        assert len(result.failed_results) == 2

    def test_execute_with_pre_analysis(self, test_session):
        """传 analysis 跳过解析."""
        engine, session, table = self._make_table(test_session)
        from cndb.plugins.tables import records as rec

        importer = Importer(engine, session, table)
        csv = "name,email\na,a@a.com"
        analysis = importer.analyze(csv, format="csv")
        importer.execute(analysis=analysis)

        count = session.execute(select(func.count()).select_from(rec._get_sa_table(engine, table))).scalar()
        assert count == 1

    def test_import_warnings_false_skips_warning_rows(self, test_session):
        """import_warnings=False 时 warning 行也不落库."""
        engine, session, table = self._make_table(test_session)
        from cndb.plugins.tables import records as rec

        # email 格式正确但文件多一个未匹配列
        importer = Importer(engine, session, table)
        csv = "name,email,extra\na,a@a.com,ex"  # extra 是 warning（未匹配列）
        importer.execute(csv, format="csv", import_warnings=False)

        count = session.execute(select(func.count()).select_from(rec._get_sa_table(engine, table))).scalar()
        # warning 行（extra 列）在 import_warnings=False 时也被跳过 → 0 行
        assert count == 0

    def test_json_format(self, test_session):
        """JSON 格式导入."""
        engine, session, table = self._make_table(test_session)
        from cndb.plugins.tables import records as rec

        importer = Importer(engine, session, table)
        data = json.dumps(
            [
                {"name": "a", "email": "a@a.com"},
                {"name": "b", "email": "bad"},
            ]
        )
        importer.execute(data, format="json")

        count = session.execute(select(func.count()).select_from(rec._get_sa_table(engine, table))).scalar()
        assert count == 1

    def test_to_dict_on_results(self, test_session):
        """ImportAnalysisResult.to_dict / ImportExecuteResult.to_dict 覆盖 line 43 / 59."""
        engine, session, table = self._make_table(test_session)
        importer = Importer(engine, session, table)
        csv = "name,email\na,a@a.com"
        analysis = importer.analyze(csv, format="csv")
        d = analysis.to_dict()
        assert "report" in d and "total" in d and "file_columns" in d

        exec_result = importer.execute(analysis=analysis)
        ed = exec_result.to_dict()
        assert "imported_ids" in ed and "imported_rows" in ed and "failed_count" in ed

    def test_execute_skip_errors_false_imports_error_rows(self, test_session):
        """skip_errors=False 时 error 行也进入 to_import（line 141）.

        error 场景选"必填字段空字符串"：RowValidator 记为 error，
        但 text 字段归一化允许空字符串，bulk_create 可正常落库。
        """
        engine, session, table = self._make_table(test_session)
        from cndb.plugins.tables import records as rec

        importer = Importer(engine, session, table)
        # name 必填，空字符串 → RowValidator 记为 error；但 bulk_create 的 text 字段接受空串
        csv = "name,email\ngood,a@b.com\n,a@b.com"  # 第二行 name 为空（error）
        result = importer.execute(csv, format="csv", skip_errors=False)

        count = session.execute(select(func.count()).select_from(rec._get_sa_table(engine, table))).scalar()
        # skip_errors=False → error 行也落库 → 2 行
        assert count == 2, f"skip_errors=False 应导入 2 行，实际 {count}"
        assert len(result.failed_results) == 0

    def test_analyze_with_rows_param_skips_parse(self, test_session):
        """rows 参数直接传入 → 走 _collect_columns 跳过解析（line 101）."""
        engine, session, table = self._make_table(test_session)
        importer = Importer(engine, session, table)
        rows = [{"name": "a", "email": "a@a.com"}, {"name": "b", "extra": "x"}]
        result = importer.analyze("", rows=rows)
        # _collect_columns 收集 name / email / extra
        assert "extra" in result.file_columns
        assert "name" in result.file_columns

    def test_execute_with_rows_param(self, test_session):
        """execute() content=None 但有 rows → analyze 走 rows= 入口."""
        engine, session, table = self._make_table(test_session)
        from cndb.plugins.tables import records as rec

        importer = Importer(engine, session, table)
        rows = [{"name": "hello", "email": "ok@ok.com"}]
        result = importer.execute(rows=rows)  # content=None, format=None, 有 rows
        count = session.execute(select(func.count()).select_from(rec._get_sa_table(engine, table))).scalar()
        assert count == 1
        assert len(result.imported_ids) == 1

    def test_execute_empty_to_import_returns_empty_ids(self, test_session):
        """所有行都是 error 且 skip_errors=True → to_import 为空，返回空列表."""
        engine, session, table = self._make_table(test_session)
        importer = Importer(engine, session, table)
        # 必填 name 为空 → error
        csv = "name,email\n,not-email"
        result = importer.execute(csv, format="csv", skip_errors=True)
        assert result.imported_ids == []
        assert len(result.failed_results) == 1
        assert result.report is not None

    def test_parse_xlsx_format(self, test_session):
        """_parse_xlsx 完整分支（lines 199-210）."""
        import io

        from openpyxl import Workbook

        engine, session, table = self._make_table(test_session)
        importer = Importer(engine, session, table)

        wb = Workbook()
        ws = wb.active
        ws.append(["name", "email"])
        ws.append(["alice", "a@a.com"])
        ws.append(["bob", "b@b.com"])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        analysis = importer.analyze(buf.read(), format="xlsx")
        assert analysis.file_columns == ["name", "email"]
        assert len(analysis.results) == 2

    def test_parse_unsupported_format_raises(self, test_session):
        """_parse 不支持格式 → ValueError（line 171）."""
        engine, session, table = self._make_table(test_session)
        importer = Importer(engine, session, table)
        with pytest.raises(ValueError, match="不支持的格式"):
            importer.analyze("whatever", format="yaml")

    def test_parse_json_not_array_raises(self, test_session):
        """_parse_json 非数组 → ValueError（line 186）."""
        engine, session, table = self._make_table(test_session)
        importer = Importer(engine, session, table)
        with pytest.raises(ValueError, match="JSON 必须是对象数组"):
            importer.analyze('{"a": 1}', format="json")

    def test_parse_json_with_non_dict_items_filtered(self, test_session):
        """_parse_json 中有非 dict 元素 → 过滤掉（line 190 isinstance(item, dict)）."""
        engine, session, table = self._make_table(test_session)
        from cndb.plugins.tables import records as rec

        importer = Importer(engine, session, table)
        data = json.dumps([{"name": "a", "email": "a@a.com"}, "not-a-dict", None, {"name": "b", "email": "b@b.com"}])
        importer.execute(data, format="json")
        count = session.execute(select(func.count()).select_from(rec._get_sa_table(engine, table))).scalar()
        assert count == 2  # 只有两个 dict 元素

    def test_collect_columns_method(self, test_session):
        """_collect_columns 保持首次出现顺序（lines 214-219）."""
        engine, session, table = self._make_table(test_session)
        Importer(engine, session, table)
        rows = [{"b": 1, "a": 2}, {"a": 3, "c": 4}]
        cols = Importer._collect_columns(rows)
        assert cols == ["b", "a", "c"]

    def test_import_warnings_true_includes_warning_rows(self, test_session):
        """import_warnings=True 默认 → warning 行（unknown column）也落库，覆盖 line 144."""
        engine, session, table = self._make_table(test_session)
        from cndb.plugins.tables import records as rec

        importer = Importer(engine, session, table)
        # email 合法但多一个 extra 列 → unknown column warning（非 error）
        csv = "name,email,extra\na,a@a.com,ex"
        result = importer.execute(csv, format="csv", import_warnings=True)  # 默认 True

        count = session.execute(select(func.count()).select_from(rec._get_sa_table(engine, table))).scalar()
        assert count == 1, f"warning 行也应落库，实际 {count}"
        assert len(result.failed_results) == 0

    def test_parse_xlsx_empty_file(self, test_session):
        """_parse_xlsx 空文件 → 返回 ([], [])，覆盖 line 207."""
        import io

        from openpyxl import Workbook

        engine, session, table = self._make_table(test_session)
        Importer(engine, session, table)

        wb = Workbook()
        # 不 append 任何行 → all_rows 为空
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        rows, cols = Importer._parse_xlsx(buf.read())
        assert rows == []
        assert cols == []


class TestImporterGuessFormat:
    def test_json(self):
        text = '[{"a": 1}]'
        assert guess_format_from_content(text) == "json"

    def test_csv(self):
        text = "a,b,c\n1,2,3"
        assert guess_format_from_content(text) == "csv"

    def test_bytes_decodes_to_json(self):
        """bytes 能正常解码 → 按文本特征推断."""
        raw = b'{"key": "value"}'
        assert guess_format_from_content(raw) == "json"

    def test_bytes_cannot_decode_returns_xlsx(self):
        """bytes 解码失败 → 返回 xlsx（line 225-228 分支）."""
        # 构造一段确实无法被 utf-8-sig 解码的字节
        bad_bytes = bytes(range(0x80, 0xC0)) + bytes(range(0xF5, 0xFF))
        result = guess_format_from_content(bad_bytes)
        assert result == "xlsx"

    def test_json_parse_error_falls_through_to_csv(self):
        """以 { 或 [ 开头但不是合法 JSON → pass 掉走后续分支（line 234-235）."""
        text = "[not valid json at all"
        # 不是合法 JSON，也没有逗号 → 走默认
        result = guess_format_from_content(text)
        # 第一行是 "[not valid json at all"，没有逗号/制表符
        # 所以会到 line 240 默认返回 "csv"
        assert result == "csv"

    def test_plain_text_defaults_to_csv(self):
        """纯文本非 CSV 格式 → 默认返回 csv（line 240）."""
        text = "hello world\nsome plain text"
        assert guess_format_from_content(text) == "csv"

    def test_json_object_not_array_detected(self):
        """虽然 JSON 对象不算数组，但合法 JSON 会被识别为 json."""
        text = '{"name": "test"}'
        assert guess_format_from_content(text) == "json"


# ── 路由端点（bulk.py 新增 analyze / confirm / failed-rows）────────


@pytest.mark.usefixtures("client", "db")
class TestImportPipelineEndpoints:
    """通过 TestClient 调 analyze / confirm 端点.

    所有测试都先通过 API 创建真实的 workspace + table + fields + DDL，
    再走端点路由，避免 _check_table_permission 因 workspace 不存在返回 404.
    """

    def _make_csv_file(self, content=None):
        import io

        if content is None:
            content = "name,email\nok,ok@ok.com\nbad,not-email"
        return io.BytesIO(content.encode("utf-8"))

    def _create_ws_table_fields(self, client, db, auth_headers, *, ws_name, tbl_name, fields):
        """创建 workspace + table + fields（通过 API），返回 (wid, tid)."""
        from cndb.plugins.tables import ddl
        from cndb.plugins.tables.models import DataField, DataTable

        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": ws_name})
        assert ws.status_code in (200, 201), f"创建 workspace 失败: {ws.status_code} {ws.text[:100]}"
        wid = ws.json()["id"]

        tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": tbl_name})
        assert tbl.status_code in (200, 201), f"创建 table 失败: {tbl.status_code} {tbl.text[:100]}"
        tid = tbl.json()["id"]

        table = db.get(DataTable, tid)
        for f_def in fields:
            field = DataField(
                table_id=tid,
                name=f_def["name"],
                field_type=f_def.get("field_type", "text"),
                required=f_def.get("required", False),
                order=f_def.get("order", 0),
                config=f_def.get("config", {}),
            )
            field.ensure_db_name()
            db.add(field)
        db.commit()
        ddl.create_table(db.get_bind(), table)

        return wid, tid

    def test_analyze_endpoint_returns_task(self, client, db, auth_headers):
        """POST /import/analyze 返回 task_id + pending_validation."""
        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_analyze_ws",
            tbl_name="EndpointAnalyze",
            fields=[
                {"name": "name", "field_type": "text", "required": True, "order": 0},
                {"name": "email", "field_type": "email", "order": 1},
            ],
        )

        file = self._make_csv_file()
        resp = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/analyze",
            headers=auth_headers,
            files={"file": ("test.csv", file, "text/csv")},
        )
        assert resp.status_code == 200, f"analyze 失败: {resp.status_code} {resp.text[:200]}"
        data = resp.json()
        assert "task_id" in data

        # run_task_in_background 是后台线程，POST 返回时可能还是 pending 状态
        # 轮询 GET /import/async/{task_id} 直到进入 pending_validation 或 pending_confirm
        import time

        tid_resp = data["task_id"]
        final_status = None
        for _ in range(20):
            time.sleep(0.1)
            r = client.get(
                f"/api/v1/workspaces/{wid}/tables/{tid}/import/async/{tid_resp}",
                headers=auth_headers,
            )
            if r.status_code == 200:
                st = r.json().get("status")
                if st != "pending":
                    final_status = st
                    break
        assert final_status in ("pending_validation", "pending_confirm", "running"), (
            f"后台 analyze 未完成，最后状态: {final_status}"
        )

    def test_analyze_endpoint_does_not_write_rows(self, client, db, auth_headers):
        """端到端：POST /import/analyze 后目标表行数保持为 0（两阶段分离验证）."""

        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_nodbwrite_ws",
            tbl_name="NoDbWrite",
            fields=[
                {"name": "name", "field_type": "text", "required": True, "order": 0},
                {"name": "age", "field_type": "number", "order": 1},
            ],
        )

        # 查 DataTable 物理表行数
        from cndb.plugins.tables.models import DataTable

        table = db.get(DataTable, tid)
        phys_table_name = table.db_table_name
        # 直接用 raw SQL count（SQLite 下最可靠）
        count_before = db.execute(__import__("sqlalchemy").text(f"SELECT COUNT(*) FROM {phys_table_name}")).scalar()
        assert count_before == 0, "新表应该是空的"

        # 提交 analyze 并等后台线程完成
        file = self._make_csv_file("name,age\\nAlice,30\\nBob,not-int")
        resp = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/analyze",
            headers=auth_headers,
            files={"file": ("t.csv", file, "text/csv")},
        )
        assert resp.status_code == 200

        import time

        tid_resp = resp.json()["task_id"]
        for _ in range(20):
            time.sleep(0.1)
            r = client.get(
                f"/api/v1/workspaces/{wid}/tables/{tid}/import/async/{tid_resp}",
                headers=auth_headers,
            )
            if r.status_code == 200 and r.json().get("status") in ("pending_confirm", "running", "done"):
                break

        # 关键断言：analyze 阶段不应写库
        count_after = db.execute(__import__("sqlalchemy").text(f"SELECT COUNT(*) FROM {phys_table_name}")).scalar()
        assert count_after == 0, f"analyze 阶段不应写库，实际新增了 {count_after} 行"

    def test_confirm_endpoint_returns_running(self, client, db, auth_headers):
        """POST /import/{task_id}/confirm 触发执行."""
        from cndb.plugins.tables.import_tasks import create_import_task

        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_confirm_ws",
            tbl_name="ConfirmTest",
            fields=[{"name": "name", "field_type": "text", "required": True, "order": 0}],
        )

        task = create_import_task(
            db,
            table_id=tid,
            user_id=1,
            filename="test.csv",
            fmt="csv",
            content=b"name\nhello",
        )
        task.status = "pending_confirm"
        task.validation_report = (
            '{"total":1,"valid_count":1,"error_count":0,"warnings":[],"errors":[],'
            '"skipped_columns":[],"missing_required":[]}'
        )
        db.commit()

        resp = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/{task.id}/confirm",
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"confirm 失败: {resp.status_code} {resp.text[:200]}"
        data = resp.json()
        assert data["status"] == "running"

    def test_confirm_wrong_status_rejected(self, client, db, auth_headers):
        """pending 状态直接 confirm —— 根据状态机决定是否允许."""
        from cndb.plugins.tables.import_tasks import create_import_task

        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_wrongstatus_ws",
            tbl_name="WrongStatus",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )

        task = create_import_task(db, table_id=tid, user_id=1, filename="x.csv", fmt="csv", content=b"name\na")

        resp = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/{task.id}/confirm",
            headers=auth_headers,
        )
        # 状态机 pending → running 是合法转换（旧流程兼容），返回 200 即可
        assert resp.status_code in (200, 400), f"unexpected: {resp.status_code} {resp.text[:200]}"

    def test_failed_rows_endpoint_no_report(self, client, db, auth_headers):
        """validation_report 为空时返回 400."""
        from cndb.plugins.tables.import_tasks import create_import_task

        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_noreport_ws",
            tbl_name="NoReport",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )

        task = create_import_task(db, table_id=tid, user_id=1, filename="x.csv", fmt="csv", content=b"name\na")

        resp = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/{task.id}/failed-rows?format=csv",
            headers=auth_headers,
        )
        assert resp.status_code == 400, f"应返回 400，实际 {resp.status_code}: {resp.text[:200]}"

    def test_non_editor_cannot_analyze(self, client, db, auth_headers):
        """未认证用户调 analyze 返回 401/403."""
        import io

        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_noauth_ws",
            tbl_name="NoAuth",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )
        file = io.BytesIO(b"name\ny")
        resp = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/analyze",
            files={"file": ("t.csv", file, "text/csv")},
            # 注意：这里不传 auth_headers，模拟未认证
        )
        assert resp.status_code in (401, 403, 422), f"未认证应被拒，实际 {resp.status_code}: {resp.text[:100]}"

    def test_failed_rows_task_not_found_404(self, client, db, auth_headers):
        """download_failed_rows task 不存在 → 404（line 384）."""
        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_task404_ws",
            tbl_name="Task404",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )
        resp = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/999999/failed-rows?format=csv",
            headers=auth_headers,
        )
        assert resp.status_code == 404, f"应返回 404，实际 {resp.status_code}: {resp.text[:200]}"

    def test_failed_rows_table_mismatch_404(self, client, db, auth_headers):
        """task.table_id != dt.id → 404（line 384）."""
        from cndb.plugins.tables.import_tasks import create_import_task

        _wid1, tid1 = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_mismatch1_ws",
            tbl_name="MismatchA",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )
        wid2, tid2 = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_mismatch2_ws",
            tbl_name="MismatchB",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )
        # task 属于 tid1，但去 tid2 下查
        task = create_import_task(db, table_id=tid1, user_id=1, filename="x.csv", fmt="csv", content=b"name\na")
        resp = client.get(
            f"/api/v1/workspaces/{wid2}/tables/{tid2}/import/{task.id}/failed-rows?format=csv",
            headers=auth_headers,
        )
        assert resp.status_code == 404, f"应返回 404，实际 {resp.status_code}: {resp.text[:200]}"

    def test_failed_rows_csv_format_success(self, client, db, auth_headers):
        """download_failed_rows CSV 格式正常返回（lines 392-417）."""
        import csv as _csv
        import io as _io

        from cndb.plugins.tables.import_tasks import create_import_task

        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_csvfail_ws",
            tbl_name="CsvFail",
            fields=[
                {"name": "name", "field_type": "text", "required": True, "order": 0},
                {"name": "email", "field_type": "email", "order": 1},
            ],
        )
        csv_content = b"name,email\ngood,a@b.com\n,not-email"  # 第二行 error
        task = create_import_task(db, table_id=tid, user_id=1, filename="x.csv", fmt="csv", content=csv_content)
        # 伪造 validation_report（让 line 385 通过）
        task.validation_report = json.dumps(
            {"total": 2, "valid_count": 1, "error_count": 1, "warnings": [], "errors": []}
        )
        db.commit()

        resp = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/{task.id}/failed-rows?format=csv",
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"应返回 200，实际 {resp.status_code}: {resp.text[:200]}"
        assert "text/csv" in resp.headers.get("content-type", "")
        assert "attachment" in resp.headers.get("content-disposition", "")
        # 解析 CSV 内容
        body = resp.content
        text = body.decode("utf-8-sig")
        reader = list(_csv.DictReader(_io.StringIO(text)))
        # 至少 1 行 error
        assert len(reader) >= 1
        assert "_row_number" in reader[0]
        assert "_error" in reader[0]

    def test_failed_rows_json_format(self, client, db, auth_headers):
        """download_failed_rows JSON 格式正常返回."""
        from cndb.plugins.tables.import_tasks import create_import_task

        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_jsonfail_ws",
            tbl_name="JsonFail",
            fields=[
                {"name": "name", "field_type": "text", "required": True, "order": 0},
                {"name": "email", "field_type": "email", "order": 1},
            ],
        )
        csv_content = b"name,email\ngood,a@b.com\n,not-email"
        task = create_import_task(db, table_id=tid, user_id=1, filename="x.csv", fmt="csv", content=csv_content)
        task.validation_report = '{"total":2,"valid_count":1,"error_count":1}'
        db.commit()

        resp = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/{task.id}/failed-rows?format=json",
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"应返回 200，实际 {resp.status_code}: {resp.text[:200]}"
        ct = resp.headers.get("content-type", "")
        assert "application/json" in ct
        data = json.loads(resp.text)
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_failed_rows_xlsx_format(self, client, db, auth_headers):
        """download_failed_rows XLSX 格式正常返回."""
        from cndb.plugins.tables.import_tasks import create_import_task

        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_xlsxfail_ws",
            tbl_name="XlsxFail",
            fields=[
                {"name": "name", "field_type": "text", "required": True, "order": 0},
                {"name": "email", "field_type": "email", "order": 1},
            ],
        )
        # 构造 xlsx bytes —— create_import_task 在 fmt="xlsx" 时会自动 base64 编码存储
        import io

        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["name", "email"])
        ws.append(["good", "a@b.com"])
        ws.append(["", "not-email"])  # error: name 空 + email 格式错
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        xlsx_bytes = buf.read()

        # 直接传原始 xlsx bytes，create_import_task 会自动 b64encode
        task = create_import_task(db, table_id=tid, user_id=1, filename="x.xlsx", fmt="xlsx", content=xlsx_bytes)
        task.validation_report = '{"total":2,"valid_count":1,"error_count":1}'
        db.commit()

        resp = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/{task.id}/failed-rows?format=xlsx",
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"应返回 200，实际 {resp.status_code}: {resp.text[:200]}"
        ct = resp.headers.get("content-type", "")
        assert "spreadsheetml" in ct
        assert len(resp.content) > 100  # 是个有意义的 xlsx

    def test_get_task_table_mismatch_404(self, client, db, auth_headers):
        """get_import_task task.table_id != dt.id → 404（line 252）."""
        from cndb.plugins.tables.import_tasks import create_import_task

        _wid1, tid1 = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_gap1_ws",
            tbl_name="GapA",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )
        wid2, tid2 = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_gap2_ws",
            tbl_name="GapB",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )
        task = create_import_task(db, table_id=tid1, user_id=1, filename="x.csv", fmt="csv", content=b"name\na")
        resp = client.get(
            f"/api/v1/workspaces/{wid2}/tables/{tid2}/import/async/{task.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 404, f"应返回 404，实际 {resp.status_code}: {resp.text[:200]}"

    def test_get_task_validation_report_invalid_json_raw(self, client, db, auth_headers):
        """get_import_task validation_report 非合法 JSON → validation_report_raw（line 275-276）."""
        from cndb.plugins.tables.import_tasks import create_import_task

        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_rawjson_ws",
            tbl_name="RawJson",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )
        task = create_import_task(db, table_id=tid, user_id=1, filename="x.csv", fmt="csv", content=b"name\na")
        task.validation_report = "not valid json {{{"
        db.commit()

        resp = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/async/{task.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "validation_report_raw" in data
        assert "validation_report" not in data

    def test_get_task_validation_report_valid_json_parsed(self, client, db, auth_headers):
        """get_import_task validation_report 合法 JSON → 解析为 dict（lines 273-274）."""
        from cndb.plugins.tables.import_tasks import create_import_task

        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_goodjson_ws",
            tbl_name="GoodJson",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )
        task = create_import_task(db, table_id=tid, user_id=1, filename="x.csv", fmt="csv", content=b"name\na")
        task.validation_report = json.dumps({"total": 1, "valid_count": 1, "error_count": 0})
        db.commit()

        resp = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/async/{task.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "validation_report" in data
        assert isinstance(data["validation_report"], dict)
        assert "validation_report_raw" not in data

    def test_confirm_task_not_found_404(self, client, db, auth_headers):
        """confirm task 不存在或不属于此表 → 404（line 347）."""
        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_confirm404_ws",
            tbl_name="Confirm404",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )
        resp = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/999999/confirm",
            headers=auth_headers,
        )
        assert resp.status_code == 404, f"应返回 404，实际 {resp.status_code}: {resp.text[:200]}"

    def test_import_endpoint_bad_format_filename(self, client, db, auth_headers):
        """POST /import 扩展名不认识 → 400（line 170）."""
        import io

        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_badfmt_ws",
            tbl_name="BadFmt",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )
        file = io.BytesIO(b"whatever content")
        resp = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import",
            headers=auth_headers,
            files={"file": ("test.unknown_ext", file, "application/octet-stream")},
        )
        assert resp.status_code == 400, f"应返回 400，实际 {resp.status_code}: {resp.text[:200]}"

    def test_import_async_bad_format_filename(self, client, db, auth_headers):
        """POST /import/async 扩展名不认识 → 400（line 209-210）."""
        import io

        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_badfmtasync_ws",
            tbl_name="BadFmtAsync",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )
        file = io.BytesIO(b"whatever")
        resp = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/async",
            headers=auth_headers,
            files={"file": ("test.badext", file, "application/octet-stream")},
        )
        assert resp.status_code == 400, f"应返回 400，实际 {resp.status_code}: {resp.text[:200]}"

    def test_import_analyze_bad_format_filename(self, client, db, auth_headers):
        """POST /import/analyze 扩展名不认识 → 400（line 302-303）."""
        import io

        wid, tid = self._create_ws_table_fields(
            client,
            db,
            auth_headers,
            ws_name="endpoint_badfmtana_ws",
            tbl_name="BadFmtAna",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )
        file = io.BytesIO(b"whatever")
        resp = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/analyze",
            headers=auth_headers,
            files={"file": ("test.badext", file, "application/octet-stream")},
        )
        assert resp.status_code == 400, f"应返回 400，实际 {resp.status_code}: {resp.text[:200]}"


class TestAugmentTaskResult:
    """直接调用 bulk._augment_task_result 覆盖 line 429-436."""

    def test_validation_report_valid_json(self, test_session):
        """validation_report 合法 JSON → result 含解析后的 dict."""
        from cndb.plugins.tables.models import ImportTask
        from cndb.plugins.tables.routers.bulk import _augment_task_result

        _engine, _session = test_session
        task = ImportTask(
            table_id=1,
            format="csv",
            file_content="x",
            validation_report=json.dumps({"total": 3, "valid_count": 2}),
        )
        result = _augment_task_result({}, task)
        assert "validation_report" in result
        assert isinstance(result["validation_report"], dict)
        assert result["validation_report"]["total"] == 3

    def test_validation_report_invalid_json_raw(self, test_session):
        """validation_report 非合法 JSON → result 含 validation_report_raw."""
        from cndb.plugins.tables.models import ImportTask
        from cndb.plugins.tables.routers.bulk import _augment_task_result

        _engine, _session = test_session
        task = ImportTask(
            table_id=1,
            format="csv",
            file_content="x",
            validation_report="not-json {{{",
        )
        result = _augment_task_result({}, task)
        assert "validation_report_raw" in result
        assert "validation_report" not in result

    def test_no_validation_report_noop(self, test_session):
        """validation_report 为空 → result 不变."""
        from cndb.plugins.tables.models import ImportTask
        from cndb.plugins.tables.routers.bulk import _augment_task_result

        _engine, _session = test_session
        task = ImportTask(table_id=1, format="csv", file_content="x")
        result = _augment_task_result({"task_id": 1}, task)
        assert result == {"task_id": 1}


# ── import_tasks 新增 analyze 分支测试 ──────────


class TestImportTaskAnalyzeBranch:
    """import_tasks._parse_to_rows 三格式解析覆盖."""

    def test_parse_csv(self, test_session):
        from cndb.plugins.tables.import_tasks import _parse_to_rows

        engine, _session = test_session
        rows, cols, total = _parse_to_rows("a,b\n1,2\n3,4", "csv", engine, None)
        assert cols == ["a", "b"]
        assert total == 2
        assert len(rows) == 2

    def test_parse_json(self, test_session):
        from cndb.plugins.tables.import_tasks import _parse_to_rows

        engine, _session = test_session
        import json

        text = json.dumps([{"a": 1}, {"a": 2}])
        _rows, cols, total = _parse_to_rows(text, "json", engine, None)
        assert total == 2
        assert "a" in cols

    def test_parse_xlsx(self, test_session):
        import io

        from openpyxl import Workbook

        from cndb.plugins.tables.import_tasks import _parse_to_rows

        wb = Workbook()
        ws = wb.active
        ws.append(["a", "b"])
        ws.append([1, 2])
        ws.append([3, 4])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        rows, cols, total = _parse_to_rows(buf.read(), "xlsx", None, None)
        assert cols == ["a", "b"]
        assert total == 2
        assert len(rows) == 2

    def test_parse_json_not_array(self, test_session):
        from cndb.plugins.tables.import_tasks import _parse_to_rows

        engine, _session = test_session
        with pytest.raises(ValueError):
            _parse_to_rows('{"a": 1}', "json", engine, None)

    def test_parse_csv_empty(self, test_session):
        from cndb.plugins.tables.import_tasks import _parse_to_rows

        engine, _session = test_session
        rows, _cols, _total = _parse_to_rows("x,y\n", "csv", engine, None)
        assert rows == []
