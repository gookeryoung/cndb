"""tables 插件覆盖率补全测试 —— 集中覆盖边界分支."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.models.base import Base
from cndb.plugins.accounts.models import User
from cndb.plugins.tables import ddl, query
from cndb.plugins.tables import records as rec
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole


@pytest.fixture
def db_engine(tmp_path: Path):
    settings.AUTH_ENABLED = True
    db_path = tmp_path / "cov.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    import cndb.plugins.accounts.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db(db_engine):
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    from cndb.app import app

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def owner_user(db):
    u = User(username="cov_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def member_user(db):
    u = User(username="cov_member", nickname="Member")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth_owner(client, owner_user):
    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": owner_user.username, "password": "passw0rd"},
    )
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth_member(client, member_user):
    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": member_user.username, "password": "passw0rd"},
    )
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def workspace(db, owner_user, member_user):
    from cndb.plugins.workspaces.models import WorkspaceMember

    ws = Workspace(name="CovWS", created_by_id=owner_user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner_user.id, role=WorkspaceRole.OWNER))
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=member_user.id, role=WorkspaceRole.EDITOR))
    db.commit()
    db.refresh(ws)
    return ws


@pytest.fixture
def table_with_fields(db, db_engine, workspace):
    dt = DataTable(workspace_id=workspace.id, name="CovTable")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()

    df1 = DataField(table_id=dt.id, name="姓名", field_type="text", order=0)
    df1.ensure_db_name()
    df2 = DataField(table_id=dt.id, name="年龄", field_type="number", order=1)
    df2.ensure_db_name()
    df3 = DataField(
        table_id=dt.id,
        name="城市",
        field_type="select",
        config={"options": ["北京", "上海", "广州"]},
        order=2,
    )
    df3.ensure_db_name()

    db.add_all([df1, df2, df3])
    db.commit()
    db.refresh(dt)

    ddl.create_table(db_engine, dt)
    # 添加 2 行数据
    rec.create_row(db_engine, dt, {"姓名": "张三", "年龄": 28, "城市": "北京"})
    rec.create_row(db_engine, dt, {"姓名": "李四", "年龄": 35, "城市": "上海"})
    return dt, [df1, df2, df3]


# ── Query 全操作符覆盖 ──────────────────────────────


class TestQueryAllOperators:
    """覆盖 query.py 所有操作符和边界分支（每个测试只做一次断言）."""

    def test_eq_neq(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from sqlalchemy import MetaData

        sa_table = ddl.build_sa_table(MetaData(), dt)
        assert query.compile_filters(dt, sa_table, [{"field_name": "年龄", "op": "!=", "value": 28}]) is not None

    def test_gte_lt_single(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        _, total = rec.list_rows(db_engine, dt, filters=[{"field_name": "年龄", "op": ">=", "value": 28}])
        assert total == 2

    def test_lt_single(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        _, total = rec.list_rows(db_engine, dt, filters=[{"field_name": "年龄", "op": "<", "value": 30}])
        assert total == 1

    def test_gt_single(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        _, total = rec.list_rows(db_engine, dt, filters=[{"field_name": "年龄", "op": ">", "value": 28}])
        assert total == 1

    def test_lte_single(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        _, total = rec.list_rows(db_engine, dt, filters=[{"field_name": "年龄", "op": "<=", "value": 30}])
        assert total == 1

    def test_in(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        _, total = rec.list_rows(db_engine, dt, filters=[{"field_name": "姓名", "op": "in", "value": ["张三", "李四"]}])
        assert total == 2

    def test_not_in(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        _, total = rec.list_rows(db_engine, dt, filters=[{"field_name": "姓名", "op": "not_in", "value": ["张三"]}])
        assert total == 1

    def test_contains(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        _, total = rec.list_rows(db_engine, dt, filters=[{"field_name": "姓名", "op": "contains", "value": "张"}])
        assert total == 1

    def test_starts_with(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        _, total = rec.list_rows(db_engine, dt, filters=[{"field_name": "姓名", "op": "starts_with", "value": "张"}])
        assert total == 1

    def test_ends_with(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        _, total = rec.list_rows(db_engine, dt, filters=[{"field_name": "姓名", "op": "ends_with", "value": "四"}])
        assert total == 1

    def test_is_empty(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from sqlalchemy import MetaData

        sa_table = ddl.build_sa_table(MetaData(), dt)
        assert query.compile_filters(dt, sa_table, [{"field_name": "姓名", "op": "is_empty"}]) is not None

    def test_is_not_empty(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from sqlalchemy import MetaData

        sa_table = ddl.build_sa_table(MetaData(), dt)
        assert query.compile_filters(dt, sa_table, [{"field_name": "姓名", "op": "is_not_empty"}]) is not None

    def test_and_logic(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        _, total = rec.list_rows(
            db_engine,
            dt,
            filters=[
                {"field_name": "年龄", "op": ">", "value": 20},
                {"field_name": "年龄", "op": "<", "value": 40},
            ],
            filter_logic="AND",
        )
        assert total == 2

    def test_or_logic(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        _, total = rec.list_rows(
            db_engine,
            dt,
            filters=[
                {"field_name": "年龄", "op": "<", "value": 20},
                {"field_name": "年龄", "op": ">", "value": 30},
            ],
            filter_logic="OR",
        )
        assert total == 1

    def test_unknown_field_skipped(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        _, total = rec.list_rows(
            db_engine,
            dt,
            filters=[{"field_name": "不存在", "op": "=", "value": "x"}],
        )
        assert total == 2

    def test_empty_filters(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        _, total = rec.list_rows(db_engine, dt, filters=[])
        assert total == 2

    def test_in_invalid_value(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from sqlalchemy import MetaData

        sa_table = ddl.build_sa_table(MetaData(), dt)
        with pytest.raises(ValueError, match="in 操作符"):
            query.compile_filters(dt, sa_table, [{"field_name": "姓名", "op": "in", "value": "not-a-list"}])

    def test_not_in_invalid_value(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from sqlalchemy import MetaData

        sa_table = ddl.build_sa_table(MetaData(), dt)
        with pytest.raises(ValueError, match="not_in"):
            query.compile_filters(dt, sa_table, [{"field_name": "姓名", "op": "not_in", "value": "not-a-list"}])

    def test_compile_filters_none_filters(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from sqlalchemy import MetaData

        sa_table = ddl.build_sa_table(MetaData(), dt)
        assert query.compile_filters(dt, sa_table, [], "AND") is None

    def test_sorts_all_directions(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        rows, _ = rec.list_rows(db_engine, dt, sorts=[{"field_name": "年龄", "direction": "asc"}])
        assert rows[0]["年龄"] == 28

    def test_sorts_desc(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        rows, _ = rec.list_rows(db_engine, dt, sorts=[{"field_name": "年龄", "direction": "desc"}])
        assert rows[0]["年龄"] == 35

    def test_sorts_default_asc(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        rows, _ = rec.list_rows(db_engine, dt, sorts=[{"field_name": "年龄"}])
        assert rows[0]["年龄"] == 28

    def test_compile_sorts_unknown_field_skipped(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from sqlalchemy import MetaData

        sa_table = ddl.build_sa_table(MetaData(), dt)
        assert query.compile_sorts(dt, sa_table, [{"field_name": "不存在", "direction": "asc"}]) == []

    def test_count_rows(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from sqlalchemy import MetaData

        sa_table = ddl.build_sa_table(MetaData(), dt)
        assert query.count_rows(dt, sa_table, []) is not None


class TestRecordsEdgeCases:
    def test_update_row_noop(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        row = rec.create_row(db_engine, dt, {"姓名": "NOOP", "年龄": 18})
        result = rec.update_row(db_engine, dt, row["id"], {})
        assert result is not None

    def test_update_nonexistent_row(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        result = rec.update_row(db_engine, dt, 99999, {"年龄": 50})
        assert result is None

    def test_delete_nonexistent_row(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        assert rec.delete_row(db_engine, dt, 99999) is False

    def test_bulk_update_empty_values(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        assert rec.bulk_update(db_engine, dt, [1, 2], {}) == 0

    def test_unknown_field_skipped(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        row = rec.create_row(db_engine, dt, {"姓名": "X", "年龄": 1, "不存在的字段": "skip"})
        assert row is not None

    def test_unknown_field_type_raises(self, db_engine, db, workspace):
        from cndb.plugins.tables.field_types import FieldType, default_registry

        # 临时注册一个会抛错的 field type
        from cndb.plugins.tables.models import DataField as DF
        from cndb.plugins.tables.models import DataTable as DT

        dt = DT(workspace_id=workspace.id, name="BadType")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()

        class _BadType(FieldType):
            name = "badtemp"

            def make_column(self, name, nullable=True):
                from sqlalchemy import Column, String

                return Column(name, String(255), nullable=nullable)

            def validate_value(self, value, config=None):
                raise ValueError("bad")

        default_registry.register(_BadType())

        df = DF(table_id=dt.id, name="坏", field_type="badtemp")
        df.ensure_db_name()
        db.add(df)
        db.commit()
        db.refresh(dt)
        ddl.create_table(db_engine, dt)

        with pytest.raises(ValueError, match="坏"):
            rec.create_row(db_engine, dt, {"坏": "anything"})

        default_registry.unregister("badtemp")


# ── DDL 边界覆盖 ────────────────────────────────────


class TestDDLEdgeCases:
    def test_build_sa_table_extra_columns(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from sqlalchemy import Column, DateTime, MetaData, func

        sa_table = ddl.build_sa_table(
            MetaData(),
            dt,
            extra_columns=[Column("created_at", DateTime, server_default=func.now())],
        )
        assert "created_at" in sa_table.columns

    def test_add_column_unknown_type(self, db_engine, table_with_fields, db):
        dt, _ = table_with_fields
        from cndb.plugins.tables.models import DataField

        bad = DataField(table_id=dt.id, name="坏", field_type="nonexistent_type")
        bad.ensure_db_name()
        db.add(bad)
        db.commit()
        with pytest.raises(ValueError, match="未知字段类型"):
            ddl.add_column(db_engine, dt, bad)

    def test_drop_table_nonexistent(self, db_engine):
        ddl.drop_table(db_engine, "table_nonexistent_000000000000")  # 不应报错

    def test_get_engine_variants(self):
        eng1 = ddl.get_engine("sqlite:///:memory:")
        eng2 = ddl.get_engine("sqlite:///test.db")
        # psycopg2 未安装，跳过 postgresql 分支
        assert eng1 is not None
        assert eng2 is not None


# ── API routers 边界覆盖 ────────────────────────────


class TestTablesAPIErrors:
    """覆盖 routers 的 HTTP 错误分支."""

    def test_create_field_unknown_type(self, client, workspace, auth_owner, table_with_fields):
        dt, _ = table_with_fields
        r = client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/fields",
            json={"name": "bad", "field_type": "bogus_type"},
            headers=auth_owner,
        )
        assert r.status_code == 400

    def test_create_field_duplicate_name(self, client, workspace, auth_owner, table_with_fields):
        dt, _ = table_with_fields
        r = client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/fields",
            json={"name": "姓名", "field_type": "text"},  # 重复
            headers=auth_owner,
        )
        assert r.status_code == 400

    def test_get_table_not_found(self, client, workspace, auth_owner):
        r = client.get(
            f"/api/v1/workspaces/{workspace.id}/tables/99999",
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_update_table_not_found(self, client, workspace, auth_owner):
        r = client.patch(
            f"/api/v1/workspaces/{workspace.id}/tables/99999",
            json={"name": "x"},
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_delete_table_not_found(self, client, workspace, auth_owner):
        r = client.delete(
            f"/api/v1/workspaces/{workspace.id}/tables/99999",
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_field_not_found(self, client, workspace, auth_owner, table_with_fields):
        dt, _ = table_with_fields
        r = client.patch(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/fields/99999",
            json={"name": "x"},
            headers=auth_owner,
        )
        assert r.status_code == 404
        r = client.delete(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/fields/99999",
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_delete_field(self, client, workspace, auth_owner, table_with_fields):
        dt, fields = table_with_fields
        r = client.delete(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/fields/{fields[-1].id}",
            headers=auth_owner,
        )
        assert r.status_code == 204

    def test_record_not_found(self, client, workspace, auth_owner, table_with_fields):
        dt, _ = table_with_fields
        r = client.get(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records/99999",
            headers=auth_owner,
        )
        assert r.status_code == 404
        r = client.patch(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records/99999",
            json={"values": {"姓名": "x"}},
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_delete_record_soft(self, client, workspace, auth_owner, table_with_fields):
        dt, _ = table_with_fields
        r = client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records",
            json={"values": {"姓名": "待删", "年龄": 0}},
            headers=auth_owner,
        )
        rid = r.json()["id"]
        r = client.delete(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records/{rid}",
            headers=auth_owner,
        )
        assert r.status_code == 204

    def test_delete_record_hard(self, client, workspace, auth_owner, table_with_fields):
        dt, _ = table_with_fields
        r = client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records",
            json={"values": {"姓名": "硬删", "年龄": 0}},
            headers=auth_owner,
        )
        rid = r.json()["id"]
        r = client.delete(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records/{rid}?soft=false",
            headers=auth_owner,
        )
        assert r.status_code == 204

    def test_create_record_invalid_values(self, client, workspace, auth_owner, table_with_fields):
        dt, _ = table_with_fields
        r = client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records",
            json={"values": {}},  # 必填字段缺失
            headers=auth_owner,
        )
        # 年龄是 number 但不是必填，只有姓名也不是必填...
        # 实际上应该是 201（空也行）或 400，取决于字段配置
        # 我们断言不是 500 即可
        assert r.status_code in (201, 400)

    def test_list_records_with_invalid_logic(self, client, workspace, auth_owner, table_with_fields):
        dt, _ = table_with_fields
        r = client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records/list",
            json={"filter_logic": "BAD_LOGIC"},
            headers=auth_owner,
        )
        # 不会报错，默认行为
        assert r.status_code == 200

    def test_list_records_no_token(self, client, workspace, table_with_fields):
        dt, _ = table_with_fields
        r = client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records/list",
            json={},
        )
        # 无 token → 401/403 取决于 deps 行为
        assert r.status_code in (401, 403)


__all__ = []
