"""CSV 列类型推断 + 自动建表测试 —— 纯函数 + 集成."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.models.base import Base
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
def csv_workspace(tmp_path):
    db_path = tmp_path / "test_csv.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    from cndb.plugins.accounts.models import User
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

    u = User(username="csv_user")
    u.set_password("pass")
    session.add(u)
    session.flush()
    ws = Workspace(name="CSVWS", created_by_id=u.id)
    session.add(ws)
    session.flush()
    session.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
    session.commit()

    try:
        yield engine, session, ws
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


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


class TestDecodeBytesAuto:
    """多编码自动检测 + 解码 —— 纯函数测试."""

    def test_utf8_no_bom(self):
        text, enc = transfer.decode_bytes_auto("姓名,年龄\n张三,25".encode())
        assert enc in ("utf-8", "utf-8-sig")
        assert "张三" in text

    def test_utf8_with_bom(self):
        text, enc = transfer.decode_bytes_auto("姓名,年龄\n张三,25".encode("utf-8-sig"))
        assert enc == "utf-8-sig"
        assert text.startswith("姓名")  # BOM 已被去除

    def test_gbk(self):
        text, enc = transfer.decode_bytes_auto("姓名,年龄\n张三,25".encode("gbk"))
        assert enc in ("gbk", "gb18030")
        assert "张三" in text

    def test_gb18030(self):
        text, enc = transfer.decode_bytes_auto("姓名,年龄\n张三,25".encode("gb18030"))
        assert enc in ("gb18030", "gbk")
        assert "张三" in text

    def test_big5(self):
        text, enc = transfer.decode_bytes_auto("姓名,年齡\n張三,25".encode("big5"))
        assert enc == "big5"
        assert "張三" in text

    def test_pure_ascii(self):
        text, enc = transfer.decode_bytes_auto("name,age\nAlice,30\n".encode("ascii"))
        # ASCII 是 UTF-8 的子集，会先命中 utf-8
        assert enc in ("utf-8", "utf-8-sig", "gb18030")
        assert "Alice" in text

    def test_non_bytes_passthrough(self):
        result, enc = transfer.decode_bytes_auto("already-text")  # type: ignore[arg-type]
        assert result == "already-text"
        assert enc == "utf-8"

    def test_latin1_fallback(self):
        # 构造一段所有文本编码都不适合的字节，应兜底到 latin-1
        bad_bytes = bytes(range(0x80, 0xC0)) + bytes(range(0xF5, 0xFF))
        text, enc = transfer.decode_bytes_auto(bad_bytes)
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
