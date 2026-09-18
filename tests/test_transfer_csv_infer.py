"""CSV 列类型推断 + 自动建表测试 —— 纯函数 + 集成."""

from __future__ import annotations

import pytest

from cndb.plugins.tables import transfer


class TestAnalyzeCsvColumns:
    """analyze_csv_columns 纯函数测试."""

    def test_basic_types(self):
        csv = "name,age,email,score,join_date,is_active\nZhang,25,a@b.com,85.5,2024-01-15,true\n"
        cols, n = transfer.analyze_csv_columns(csv)
        assert n == 1
        types = {c["name"]: c["field_type"] for c in cols}
        assert types["name"] == "text"
        assert types["age"] == "number"
        assert types["email"] == "email"
        assert types["score"] == "float"
        assert types["join_date"] == "date"
        assert types["is_active"] == "boolean"

    def test_datetime_inference(self):
        csv = "created_at\n2024-01-15T10:30:00\n2023-06-20 08:45:00\n"
        cols, _n = transfer.analyze_csv_columns(csv)
        assert cols[0]["field_type"] == "datetime"

    def test_url_inference(self):
        csv = "website\nhttps://example.com\nhttp://test.org/path\n"
        cols, _n = transfer.analyze_csv_columns(csv)
        assert cols[0]["field_type"] == "url"

    def test_percentage_inference(self):
        csv = "rate\n85.5%\n92%\n50%\n"
        cols, _n = transfer.analyze_csv_columns(csv)
        assert cols[0]["field_type"] == "percentage"

    def test_phone_with_separators(self):
        csv = "phone\n+86-138-0013-8000\n138-0013-8001\n"
        cols, _n = transfer.analyze_csv_columns(csv)
        assert cols[0]["field_type"] == "phone"

    def test_boolean_chinese(self):
        csv = "active\n是\n否\n是\n"
        cols, _n = transfer.analyze_csv_columns(csv)
        assert cols[0]["field_type"] == "boolean"

    def test_long_number_with_leading_zero(self):
        """长数字串前导零应保持 text."""
        csv = "code\n00123456789\n"
        cols, _n = transfer.analyze_csv_columns(csv)
        assert cols[0]["field_type"] == "text"

    def test_empty_csv(self):
        cols, n = transfer.analyze_csv_columns("name,age\n")
        assert n == 0
        assert all(c["field_type"] == "text" for c in cols)

    def test_null_ratio(self):
        csv = "name,age\nA,\nB,25\nC,\n"
        cols, _n = transfer.analyze_csv_columns(csv)
        age_col = next(c for c in cols if c["name"] == "age")
        assert age_col["null_ratio"] == 0.6667

    def test_sample_values_limit(self):
        rows = "".join(f"name\nX{i}\n" for i in range(20))
        cols, _ = transfer.analyze_csv_columns(rows, sample_rows=100)
        assert len(cols[0]["sample_values"]) <= 5


@pytest.fixture
def csv_workspace(db, db_engine):
    """复用 conftest 内存 DB，种子 csv_user + CSVWS workspace."""
    from cndb.plugins.accounts.models import User
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

    u = User(username="csv_user")
    u.set_password("pass")
    db.add(u)
    db.flush()
    ws = Workspace(name="CSVWS", created_by_id=u.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
    db.commit()
    yield db_engine, db, ws


class TestCreateTableFromCsv:
    """create_table_from_csv 集成测试."""

    def test_basic_create(self, csv_workspace):
        engine, db, ws = csv_workspace
        csv = "name,age,score\nAlice,30,95.5\nBob,25,87\n"
        dt, ids = transfer.create_table_from_csv(engine, db, ws.id, "自动表", csv)
        assert dt.name == "自动表"
        assert len(ids) == 2
        assert len(dt.fields) == 3
        field_map = {f.name: f.field_type for f in dt.fields}
        assert field_map["name"] == "text"
        assert field_map["age"] == "number"
        assert field_map["score"] == "float"

        # 自动建表同时生成默认视图「全部」
        from cndb.plugins.tables.models import DataView

        views = db.query(DataView).filter(DataView.table_id == dt.id).all()
        assert len(views) == 1
        v = views[0]
        assert v.name == "全部"
        assert v.view_type == "grid"
        assert v.is_default is True
        assert v.order == 0

    def test_empty_csv_error(self, csv_workspace):
        engine, db, ws = csv_workspace
        with pytest.raises(ValueError, match="没有有效列"):
            transfer.create_table_from_csv(engine, db, ws.id, "空表", "")

    def test_single_column_csv(self, csv_workspace):
        engine, db, ws = csv_workspace
        csv = "id\n1\n2\n3\n"
        dt, ids = transfer.create_table_from_csv(engine, db, ws.id, "单列", csv)
        assert len(ids) == 3
        assert dt.fields[0].field_type == "number"

    def test_select_field_config_preserved_as_dicts(self, csv_workspace):
        """CSV 含低基数离散列 → 推断为 select,config.options 存为 dict 格式."""
        engine, db, ws = csv_workspace
        csv = "name,status\nAlice,active\nBob,done\nCarol,active\nDan,done\nEve,pending\nFrank,done\nGrace,active\nHelen,pending\n"
        dt, ids = transfer.create_table_from_csv(engine, db, ws.id, "状态表", csv)
        assert len(ids) == 8
        status_field = next(f for f in dt.fields if f.name == "status")
        assert status_field.field_type == "select"
        cfg = status_field.config
        assert "options" in cfg
        opts = cfg["options"]
        assert len(opts) == 3, f"expected 3 options, got {opts}"
        # 每个 option 是 dict 格式 {label, value}
        for opt in opts:
            assert isinstance(opt, dict), f"expected dict option, got {type(opt)}: {opt}"
            assert "label" in opt and "value" in opt
        labels = [o["label"] for o in opts]
        assert set(labels) == {"active", "done", "pending"}


class TestImportFailureCleanup:
    """导入流程中途失败时，DataTable/DataField/物理表 应被回滚清理，不留空壳."""

    def test_create_table_from_csv_bulk_failure_cleans_up(self, csv_workspace, monkeypatch):
        """bulk_create 抛异常 → DataTable / DataField / 物理表 全部被清理."""
        engine, db, ws = csv_workspace

        # 先确认当前没有表
        from cndb.plugins.tables.models import DataTable

        before_count = db.query(DataTable).filter(DataTable.workspace_id == ws.id).count()

        # mock bulk_create 让它在数据导入阶段失败
        from cndb.plugins.tables import transfer as transfer_mod

        def _boom_bulk_create(*args, **kwargs):
            raise RuntimeError("模拟导入失败：字段类型不匹配")

        monkeypatch.setattr(transfer_mod.rec, "bulk_create", _boom_bulk_create)

        csv = "name,age\nAlice,30\n"
        with pytest.raises(RuntimeError, match="模拟导入失败"):
            transfer.create_table_from_csv(engine, db, ws.id, "清理测试表", csv)

        # 断言：DataTable 元数据应不存在
        after_count = db.query(DataTable).filter(DataTable.workspace_id == ws.id).count()
        assert after_count == before_count, f"期望表被清理: 之前 {before_count} 现在 {after_count}"

        # 断言：物理表应不存在
        from cndb.plugins.tables import ddl

        insp = ddl.inspect(engine)
        existing_tables = insp.get_table_names()
        # 没有表残留（DDL 建的物理表会以 data_* 开头）
        assert not any(t.startswith("data_") for t in existing_tables), f"物理表残留: {existing_tables}"

    def test_create_table_from_file_bulk_failure_cleans_up(self, csv_workspace, monkeypatch):
        """create_table_from_file 走的也是同一条清理路径."""
        engine, db, ws = csv_workspace

        from cndb.plugins.tables import transfer as transfer_mod
        from cndb.plugins.tables.models import DataTable

        before_count = db.query(DataTable).filter(DataTable.workspace_id == ws.id).count()

        def _boom_bulk_create(*args, **kwargs):
            raise ValueError("模拟文件导入失败")

        monkeypatch.setattr(transfer_mod.rec, "bulk_create", _boom_bulk_create)

        csv_bytes = b"name,age\nAlice,30\n"
        with pytest.raises(ValueError, match="模拟文件导入失败"):
            transfer.create_table_from_file(
                engine,
                db,
                ws.id,
                "文件清理测试表",
                csv_bytes,
                filename="test.csv",
            )

        after_count = db.query(DataTable).filter(DataTable.workspace_id == ws.id).count()
        assert after_count == before_count

    def test_create_table_from_json_data_bulk_failure_cleans_up(self, csv_workspace, monkeypatch):
        """create_table_from_json_data 同样应清理."""
        engine, db, ws = csv_workspace

        from cndb.plugins.tables import transfer as transfer_mod
        from cndb.plugins.tables.models import DataTable

        before_count = db.query(DataTable).filter(DataTable.workspace_id == ws.id).count()

        def _boom_bulk_create(*args, **kwargs):
            raise RuntimeError("模拟 JSON 导入失败")

        monkeypatch.setattr(transfer_mod.rec, "bulk_create", _boom_bulk_create)

        rows = [{"name": "Alice", "age": 30}]
        with pytest.raises(RuntimeError, match="模拟 JSON 导入失败"):
            transfer.create_table_from_json_data(engine, db, ws.id, "JSON清理表", rows)

        after_count = db.query(DataTable).filter(DataTable.workspace_id == ws.id).count()
        assert after_count == before_count

    def test_successful_import_leaves_table(self, csv_workspace):
        """正常导入不应误清理 —— 基线验证."""
        engine, db, ws = csv_workspace
        csv = "name,age\nAlice,30\n"
        dt, ids = transfer.create_table_from_csv(engine, db, ws.id, "正常表", csv)
        assert dt.id is not None
        assert len(ids) == 1

        from cndb.plugins.tables.models import DataTable

        assert db.get(DataTable, dt.id) is not None


class TestDecodeBytesAuto:
    """多编码自动检测 + 解码 —— 纯函数测试."""

    def test_utf8_no_bom(self):
        text, enc, _conf = transfer.decode_bytes_auto("姓名,年龄\n张三,25".encode())
        assert enc in ("utf-8", "utf-8-sig")
        assert "张三" in text

    def test_utf8_with_bom(self):
        text, enc, _conf = transfer.decode_bytes_auto("姓名,年龄\n张三,25".encode("utf-8-sig"))
        assert enc == "utf-8-sig"
        assert text.startswith("姓名")  # BOM 已被去除

    def test_gbk(self):
        text, enc, _conf = transfer.decode_bytes_auto("姓名,年龄\n张三,25".encode("gbk"))
        assert enc in ("gbk", "gb18030")
        assert "张三" in text

    def test_gb18030(self):
        text, enc, _conf = transfer.decode_bytes_auto("姓名,年龄\n张三,25".encode("gb18030"))
        assert enc in ("gb18030", "gbk")
        assert "张三" in text

    def test_big5(self):
        text, enc, _conf = transfer.decode_bytes_auto("姓名,年齡\n張三,25".encode("big5"))
        assert enc == "big5"
        assert "張三" in text

    def test_pure_ascii(self):
        text, enc, _conf = transfer.decode_bytes_auto("name,age\nAlice,30\n".encode("ascii"))
        # ASCII 是 UTF-8 的子集，会先命中 utf-8
        assert enc in ("utf-8", "utf-8-sig", "gb18030")
        assert "Alice" in text

    def test_non_bytes_passthrough(self):
        result, enc, _conf = transfer.decode_bytes_auto("already-text")  # type: ignore[arg-type]
        assert result == "already-text"
        assert enc == "utf-8"

    def test_latin1_fallback(self):
        # 构造一段所有文本编码都不适合的字节，应兜底到 latin-1
        bad_bytes = bytes(range(0x80, 0xC0)) + bytes(range(0xF5, 0xFF))
        text, enc, _conf = transfer.decode_bytes_auto(bad_bytes)
        assert enc == "latin-1"
        assert len(text) == len(bad_bytes)


class TestGuessFormatEncoding:
    """Importer.guess_format_from_content 在编码修复后的行为."""

    def test_utf8_csv_bytes(self):
        from cndb.plugins.tables.importer import guess_format_from_content

        data = b"name,age\nAlice,30\n"
        assert guess_format_from_content(data) == "csv"

    def test_gbk_csv_bytes(self):
        from cndb.plugins.tables.importer import guess_format_from_content

        data = "姓名,年龄\n张三,25\n".encode("gbk")
        assert guess_format_from_content(data) == "csv"

    def test_binary_bytes_returns_xlsx(self):
        from cndb.plugins.tables.importer import guess_format_from_content

        bad_bytes = bytes(range(0x80, 0xC0)) + bytes(range(0xF5, 0xFF))
        assert guess_format_from_content(bad_bytes) == "xlsx"

    def test_json_bytes(self):
        from cndb.plugins.tables.importer import guess_format_from_content

        data = '[{"name": "张三"}]'.encode()
        assert guess_format_from_content(data) == "json"


class TestGuessFormatFromFilename:
    """guess_format_from_filename 单元测试."""

    def test_xlsx(self):
        assert transfer.guess_format_from_filename("report.xlsx") == "xlsx"
        assert transfer.guess_format_from_filename("REPORT.XLSX") == "xlsx"

    def test_csv(self):
        assert transfer.guess_format_from_filename("data.csv") == "csv"

    def test_json(self):
        assert transfer.guess_format_from_filename("config.json") == "json"

    def test_xls_raises_friendly_error(self):
        with pytest.raises(ValueError, match="xls"):
            transfer.guess_format_from_filename("old-report.xls")

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            transfer.guess_format_from_filename("data.txt")


__all__ = []
