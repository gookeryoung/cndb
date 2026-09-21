"""数据管理健壮性测试 — 语义等价 diff / 预览截断 / 导出特殊字符 / 损坏文件 / 端到端 roundtrip.

聚焦错误场景与边界锁定：
- upsert diff 语义等价（"1.0" vs 1、True vs "true"、文本空白不误报）
- preview 200 行截断（计数不截断、预览截断）
- 导出特殊字符往返一致（逗号/引号/换行/emoji/公式串/参差行）
- 损坏文件解析（垃圾字节 xlsx、仅表头 CSV、重复表头）
- 导入→导出→再导入 roundtrip 一致性
"""

from __future__ import annotations

import csv
import io
import zipfile

import pytest
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from cndb.plugins.tables import ddl
from cndb.plugins.tables.diff_reporter import _json_safe
from cndb.plugins.tables.import_tasks import create_import_task, execute_import_task
from cndb.plugins.tables.importer import Importer
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.transfer import export_rows_to_csv, export_rows_to_xlsx
from tests.helpers import wait_import_settled

# ── 公共 Fixture 与造数工具 ─────────────────────────


@pytest.fixture
def test_session(db_engine, db):
    """复用 conftest 内存 DB，yield (engine, session)."""
    yield db_engine, db


def _make_table(session: Session, engine, *, workspace_id: int = 1) -> DataTable:
    """创建一个 DataTable（不含字段）."""
    dt = DataTable(workspace_id=workspace_id, name="健壮性测试表")
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
    """为表添加一个字段（flush 不 commit，由调用方统一提交）."""
    f = DataField(
        table_id=table.id, name=name, field_type=field_type, required=required, config=config or {}, order=order
    )
    f.ensure_db_name()
    session.add(f)
    session.flush()
    return f


def _make_table_with_fields(session: Session, engine, fields: list[tuple[str, str]]) -> DataTable:
    """建表 + 逐个添加字段 + 建物理表，fields 为 (name, field_type) 列表."""
    table = _make_table(session, engine)
    for i, (name, ftype) in enumerate(fields):
        _add_field(session, table, name, ftype, order=i)
    session.commit()
    ddl.create_table(engine, table)
    return table


# ── A: upsert 语义等价 diff ─────────────────────────


class TestUpsertSemanticEquivalence:
    """命中行的语义等价值不应被误报为字段变化."""

    def test_upsert_numeric_string_no_false_diff(self, test_session):
        """number 库内 1 vs 文件 "1.0" —— 数值语义等价，无变化."""
        engine, session = test_session
        from cndb.plugins.tables import records as rec

        table = _make_table_with_fields(session, engine, [("code", "text"), ("qty", "number")])
        rec.bulk_create(engine, table, [{"code": "A1", "qty": 1}], db=session)

        imp = Importer(engine, session, table)
        rpt = imp.analyze("code,qty\nA1,1.0\n", "csv", match_keys=["code"]).report

        assert rpt["update_count"] == 1
        assert rpt["update_changed_count"] == 0
        assert rpt["update_no_change_count"] == 1
        assert rpt["update_preview"][0]["field_diffs"] == {}

    def test_upsert_boolean_string_no_false_diff(self, test_session):
        """boolean 库内 True vs 文件 "true" —— 布尔语义等价，无变化."""
        engine, session = test_session
        from cndb.plugins.tables import records as rec

        table = _make_table_with_fields(session, engine, [("code", "text"), ("active", "boolean")])
        rec.bulk_create(engine, table, [{"code": "A1", "active": True}], db=session)

        imp = Importer(engine, session, table)
        rpt = imp.analyze("code,active\nA1,true\n", "csv", match_keys=["code"]).report

        assert rpt["update_no_change_count"] == 1
        assert rpt["update_changed_count"] == 0
        assert rpt["update_preview"][0]["field_diffs"] == {}

    def test_upsert_whitespace_no_false_diff(self, test_session):
        """text "abc" vs " abc " —— 字符串去空白比较，无变化."""
        engine, session = test_session
        from cndb.plugins.tables import records as rec

        table = _make_table_with_fields(session, engine, [("code", "text"), ("name", "text")])
        rec.bulk_create(engine, table, [{"code": "A1", "name": "abc"}], db=session)

        imp = Importer(engine, session, table)
        rpt = imp.analyze("code,name\nA1, abc \n", "csv", match_keys=["code"]).report

        assert rpt["update_no_change_count"] == 1
        assert rpt["update_changed_count"] == 0
        assert rpt["update_preview"][0]["field_diffs"] == {}


# ── A: 预览截断 ─────────────────────────────────────


class TestPreviewLimit:
    """preview 按 PREVIEW_LIMIT=200 截断，计数保持全量."""

    def test_update_preview_truncated_at_200(self, test_session):
        """205 行全命中已有 key → update_count==205 但 update_preview 仅 200 条."""
        engine, session = test_session
        from cndb.plugins.tables import records as rec

        table = _make_table_with_fields(session, engine, [("code", "text"), ("name", "text")])
        rec.bulk_create(engine, table, [{"code": f"K{i:04d}", "name": f"旧{i}"} for i in range(205)], db=session)

        csv_content = "code,name\n" + "".join(f"K{i:04d},新{i}\n" for i in range(205))
        imp = Importer(engine, session, table)
        rpt = imp.analyze(csv_content, "csv", match_keys=["code"]).report

        assert rpt["update_count"] == 205
        assert len(rpt["update_preview"]) == 200
        assert rpt["update_changed_count"] == 205

    def test_new_preview_truncated_at_200(self, test_session):
        """205 行全新 key → new_count==205 但 new_preview 仅 200 条."""
        engine, session = test_session
        table = _make_table_with_fields(session, engine, [("code", "text")])

        csv_content = "code\n" + "".join(f"K{i:04d}\n" for i in range(205))
        imp = Importer(engine, session, table)
        rpt = imp.analyze(csv_content, "csv", match_keys=["code"]).report

        assert rpt["new_count"] == 205
        assert len(rpt["new_preview"]) == 200


# ── B: 导出特殊字符往返 ─────────────────────────────


class TestExportSpecialChars:
    """导出函数对特殊字符的转义与参差行的行为锁定."""

    _SPECIAL_ROWS = [
        {"name": "值,带逗号", "note": '含"引号"', "bio": "第一行\n第二行", "cmd": "=cmd()"},
        {"name": "emoji🚀", "note": "中文标点；", "bio": "tab\t制表", "cmd": "+1+1"},
    ]

    def test_csv_roundtrip_special_chars(self):
        """CSV 导出含逗号/引号/换行/emoji/公式串 → DictReader 解析回逐值相等."""
        out = export_rows_to_csv(self._SPECIAL_ROWS)
        reader = csv.DictReader(io.StringIO(out))
        parsed = list(reader)
        assert len(parsed) == 2
        for original, row in zip(self._SPECIAL_ROWS, parsed, strict=True):
            for key, expected in original.items():
                assert row[key] == expected, f"列 {key} 往返不一致: {row[key]!r} != {expected!r}"
        # 公式样串原样保留（当前实现不做注入转义，锁定现状）
        assert parsed[0]["cmd"] == "=cmd()"

    def test_xlsx_roundtrip_special_chars(self):
        """XLSX 导出同值域 → load_workbook 读回逐值相等."""
        xlsx_bytes = export_rows_to_xlsx(self._SPECIAL_ROWS)
        wb = load_workbook(io.BytesIO(xlsx_bytes))
        ws = wb.active
        assert ws is not None
        rows = list(ws.iter_rows(values_only=True))
        header = list(rows[0])
        assert header == list(self._SPECIAL_ROWS[0].keys())
        for original, row in zip(self._SPECIAL_ROWS, rows[1:], strict=True):
            for key, expected in original.items():
                assert row[header.index(key)] == expected, f"列 {key} 往返不一致: {row!r} != {expected!r}"

    def test_csv_ragged_extra_column_raises(self):
        """第二行含 fieldnames 之外的键 → DictWriter 默认 extrasaction=raise 抛 ValueError."""
        rows = [{"a": "1"}, {"a": "2", "b": "3"}]
        with pytest.raises(ValueError, match="fields not in fieldnames"):
            export_rows_to_csv(rows)

    def test_csv_ragged_missing_column_blank(self):
        """第二行缺键 → CSV 写空串；XLSX 该格为 None."""
        rows = [{"a": "1", "b": "x"}, {"a": "2"}]

        out = export_rows_to_csv(rows)
        parsed = list(csv.DictReader(io.StringIO(out)))
        assert parsed[1]["a"] == "2"
        assert parsed[1]["b"] == ""

        xlsx_bytes = export_rows_to_xlsx(rows)
        wb = load_workbook(io.BytesIO(xlsx_bytes))
        ws = wb.active
        assert ws is not None
        data_rows = list(ws.iter_rows(min_row=2, values_only=True))
        assert data_rows[1] == ("2", None)


# ── C: 损坏文件解析 ─────────────────────────────────


class TestCorruptFileParsing:
    """损坏/退化输入的解析错误路径."""

    def test_analyze_garbage_xlsx_raises(self, test_session):
        """垃圾字节标 fmt=xlsx → openpyxl 抛 zipfile.BadZipFile（不被包装吞掉）."""
        engine, session = test_session
        table = _make_table_with_fields(session, engine, [("name", "text")])

        imp = Importer(engine, session, table)
        with pytest.raises(zipfile.BadZipFile, match="not a zip file"):
            imp.analyze(b"garbage-bytes-not-a-zip", "xlsx")

    def test_task_garbage_xlsx_fails_with_message(self, test_session, db):
        """任务层垃圾 xlsx → 状态 failed 且 error_message 非空（兜底不崩溃）."""
        engine, session = test_session
        table = _make_table_with_fields(session, engine, [("name", "text")])

        task = create_import_task(
            session, table_id=table.id, user_id=1, filename="bad.xlsx", fmt="xlsx", content=b"garbage-bytes"
        )
        execute_import_task(session, task.id)
        db.refresh(task)

        assert task.status == "failed"
        assert task.error_message, "失败任务必须携带 error_message"

    def test_analyze_csv_header_only(self, test_session):
        """仅表头无数据行 → total==0，正常返回不异常."""
        engine, session = test_session
        table = _make_table_with_fields(session, engine, [("name", "text"), ("email", "email")])

        imp = Importer(engine, session, table)
        rpt = imp.analyze("name,email\n", "csv").report

        assert rpt["total"] == 0
        assert rpt["valid_count"] == 0
        assert rpt["error_count"] == 0

    def test_parse_csv_duplicate_headers(self):
        """重复表头列名 → file_columns 保留两个 name，行值后列覆盖."""
        rows, file_columns = Importer._parse_csv("name,name\na,b\n")
        assert file_columns == ["name", "name"]
        assert len(rows) == 1
        assert rows[0]["name"] == "b"


# ── F: 端到端 roundtrip ─────────────────────────────


class TestImportExportRoundtripE2E:
    """导入 → 导出 → 再导入的一致性验证（走真实 API 路由）."""

    def _create_ws_table_fields(self, client, auth_headers, *, ws_name, tbl_name, fields):
        """创建 workspace + table + fields（全部走 API，确保物理建列），返回 (wid, tid)."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": ws_name})
        assert ws.status_code in (200, 201), f"创建 workspace 失败: {ws.status_code} {ws.text[:100]}"
        wid = ws.json()["id"]

        tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": tbl_name})
        assert tbl.status_code in (200, 201), f"创建 table 失败: {tbl.status_code} {tbl.text[:100]}"
        tid = tbl.json()["id"]

        # 字段必须走 fields API —— 直接 db.add(DataField) 不会触发物理建列
        for f_def in fields:
            r = client.post(f"/api/v1/workspaces/{wid}/tables/{tid}/fields", headers=auth_headers, json=f_def)
            assert r.status_code in (200, 201), f"创建字段 {f_def['name']} 失败: {r.status_code} {r.text[:200]}"
        return wid, tid

    def _import_via_two_phase(self, client, auth_headers, wid, tid, csv_content):
        """两阶段导入：analyze → 等 pending_confirm → confirm → 等 done."""
        resp = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/analyze",
            headers=auth_headers,
            files={"file": ("data.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
        )
        assert resp.status_code == 200, f"analyze 失败: {resp.status_code} {resp.text[:200]}"
        task_id = resp.json()["task_id"]

        async_url = f"/api/v1/workspaces/{wid}/tables/{tid}/import/async/{task_id}"
        settled = wait_import_settled(client, async_url, auth_headers)
        assert settled["status"] == "pending_confirm", f"analyze 后应处于 pending_confirm: {settled['status']}"

        confirm = client.post(f"/api/v1/workspaces/{wid}/tables/{tid}/import/{task_id}/confirm", headers=auth_headers)
        assert confirm.status_code == 200, f"confirm 失败: {confirm.status_code} {confirm.text[:200]}"

        final = wait_import_settled(client, async_url, auth_headers)
        assert final["status"] == "done", f"导入未完成: {final.get('status')} err={final.get('error_message')}"

    def _export_rows(self, client, auth_headers, wid, tid, fmt):
        """导出并返回解析结果（csv → 字符串；json → list[dict]）."""
        resp = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/export?format={fmt}",
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"导出失败: {resp.status_code} {resp.text[:200]}"
        return resp.text if fmt == "csv" else resp.json()

    def test_roundtrip_import_export_reimport(self, client, auth_headers):
        """导入(2好1坏) → 导出 → 再导入新表 → 行数与值一致."""
        fields = [
            {"name": "name", "field_type": "text", "required": True, "order": 0},
            {"name": "email", "field_type": "email", "order": 1},
        ]
        wid, tid = self._create_ws_table_fields(
            client, auth_headers, ws_name="roundtrip_ws", tbl_name="RoundtripA", fields=fields
        )

        csv_content = "name,email\n张三,zhang@x.com\n李四,li@x.com\n王五,bad-email\n"
        self._import_via_two_phase(client, auth_headers, wid, tid, csv_content)

        # 导出表 A 的 JSON 行数据
        rows_a = self._export_rows(client, auth_headers, wid, tid, "json")
        assert len(rows_a) == 2
        values_a = sorted((r["name"], r["email"]) for r in rows_a)

        # 再导入到结构相同的表 B（独立工作区，走同步 bulk 导入端点）
        wid2, tid2 = self._create_ws_table_fields(
            client, auth_headers, ws_name="roundtrip_ws_b", tbl_name="RoundtripB", fields=fields
        )
        csv_export = self._export_rows(client, auth_headers, wid, tid, "csv")
        re_import = client.post(
            f"/api/v1/workspaces/{wid2}/tables/{tid2}/import",
            headers=auth_headers,
            files={"file": ("export.csv", io.BytesIO(csv_export.encode("utf-8")), "text/csv")},
        )
        assert re_import.status_code == 200, f"再导入失败: {re_import.status_code} {re_import.text[:200]}"
        assert re_import.json()["imported"] == 2

        rows_b = self._export_rows(client, auth_headers, wid2, tid2, "json")
        assert len(rows_b) == 2
        assert sorted((r["name"], r["email"]) for r in rows_b) == values_a

    def test_roundtrip_preserves_quoted_values(self, client, auth_headers):
        """含逗号/双引号的值经 导入→导出 往返不变形."""
        wid, tid = self._create_ws_table_fields(
            client,
            auth_headers,
            ws_name="quoted_ws",
            tbl_name="QuotedValues",
            fields=[{"name": "name", "field_type": "text", "order": 0}],
        )

        # CSV 引号转义：第一行含逗号，第二行含双引号
        csv_content = 'name\n"张三, Jr."\n"含""引号"""'
        self._import_via_two_phase(client, auth_headers, wid, tid, csv_content)

        csv_export = self._export_rows(client, auth_headers, wid, tid, "csv")
        parsed = list(csv.DictReader(io.StringIO(csv_export)))
        values = sorted(r["name"] for r in parsed)
        assert values == sorted(["张三, Jr.", '含"引号"'])


# ── 附带: _json_safe bytes 有损解码 ─────────────────


def test_json_safe_lossy_bytes():
    """非 UTF-8 bytes → 替换符 U+FFFD 有损解码，不抛异常."""
    assert _json_safe(b"\xff") == "\ufffd"
