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


__all__ = []
