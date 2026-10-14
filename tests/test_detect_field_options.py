"""字段改为单选/多选时的「识别选项」测试.

覆盖场景：
1. select 识别：物理列（旧类型 text 数据）整值唯一值收集，strip / 去空 / 保序去重
2. multiselect 识别：默认逗号分隔符拆分；用户自定义分隔符（含多字符）拆分
3. 非法入参：target_type 不是 select/multiselect、multiselect 分隔符为空 → ValueError
4. 物理表缺列 → RuntimeError
5. REST API：POST /fields/{id}/detect-options 只读返回、404、400
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.models.base import Base
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import Base as TablesBase
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.fields.field_ops import detect_options_from_field_data
from cndb.plugins.tables.services.transfer import import_rows_from_json
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole

# ── 服务层 fixtures ──────────────────────────────────


@pytest.fixture
def test_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'detect.db'}", connect_args={"check_same_thread": False})
    TablesBase.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield engine, session
    finally:
        session.close()


def _make_table(session: Session, name: str = "识别测试表") -> DataTable:
    dt = DataTable(workspace_id=1, name=name)
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
    config: dict | None = None,
    order: int = 0,
) -> DataField:
    f = DataField(
        table_id=table.id,
        name=name,
        field_type=field_type,
        config=config or {},
        order=order,
    )
    f.ensure_db_name()
    session.add(f)
    session.flush()
    return f


# ── 服务层：detect_options_from_field_data ──────────


class TestDetectOptionsFromFieldData:
    def test_select_detects_distinct_values(self, test_session):
        """select：旧类型 text 列整值识别，去重保序、跳过空值."""
        engine, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "状态", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)

        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"状态": "进行中"},
                    {"状态": "已完成"},
                    {"状态": "进行中"},
                    {"状态": None},
                    {"状态": "  已完成  "},
                ]
            ),
            db=session,
        )

        options = detect_options_from_field_data(session, table, f, target_type="select")
        assert options == ["进行中", "已完成"]

    def test_multiselect_default_comma_delimiter(self, test_session):
        """multiselect：默认逗号分隔符拆分单元格值."""
        engine, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "标签", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)

        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"标签": "urgent,backend"},
                    {"标签": "backend, devops"},
                    {"标签": "urgent"},
                ]
            ),
            db=session,
        )

        options = detect_options_from_field_data(session, table, f, target_type="multiselect")
        assert options == ["urgent", "backend", "devops"]

    def test_multiselect_custom_delimiter(self, test_session):
        """multiselect：用户自定义分隔符（含多字符）按首现顺序识别."""
        engine, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "技能", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)

        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"技能": "Python | Java"},
                    {"技能": "Go|Python"},
                ]
            ),
            db=session,
        )

        options = detect_options_from_field_data(session, table, f, target_type="multiselect", delimiter="|")
        assert options == ["Python", "Java", "Go"]

    def test_multiselect_multi_char_delimiter(self, test_session):
        """multiselect：多字符分隔符整体拆分，不逐字符切断."""
        engine, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "路径", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)

        import_rows_from_json(
            engine,
            table,
            json.dumps(
                [
                    {"路径": "a::b::c"},
                ]
            ),
            db=session,
        )

        options = detect_options_from_field_data(session, table, f, target_type="multiselect", delimiter="::")
        assert options == ["a", "b", "c"]

    def test_invalid_target_type_raises(self, test_session):
        """target_type 不是 select/multiselect → ValueError."""
        engine, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "x", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)

        with pytest.raises(ValueError, match="不是单选/多选"):
            detect_options_from_field_data(session, table, f, target_type="text")

    def test_empty_delimiter_raises(self, test_session):
        """multiselect 分隔符为空 → ValueError."""
        engine, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "x", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)

        with pytest.raises(ValueError, match="分隔符不能为空"):
            detect_options_from_field_data(session, table, f, target_type="multiselect", delimiter="")

    def test_missing_physical_column_raises(self, test_session):
        """物理表缺少字段物理列 → RuntimeError."""
        engine, session = test_session
        table = _make_table(session)
        f = _add_field(session, table, "幽灵", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)
        session.delete(f)
        session.commit()

        f_orphan = DataField(table_id=table.id, name="幽灵", field_type="text", db_column_name="field_ghost", order=0)
        with pytest.raises(RuntimeError, match="无法识别选项"):
            detect_options_from_field_data(session, table, f_orphan, target_type="select")


# ── REST API ─────────────────────────────────────────


@pytest.fixture
def api_engine(tmp_path: Path):
    settings.AUTH_ENABLED = True
    engine = create_engine(f"sqlite:///{tmp_path / 'detect_api.db'}", connect_args={"check_same_thread": False})
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
def api_db(api_engine):
    SessionLocal = sessionmaker(bind=api_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def api_client(api_db):
    from cndb.app import app

    def _override_get_db():
        yield api_db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def api_user(api_db):
    u = User(username="detect_owner", nickname="Detect Owner")
    u.set_password("passw0rd")
    api_db.add(u)
    api_db.commit()
    api_db.refresh(u)
    return u


@pytest.fixture
def api_auth(api_client, api_user):
    r = api_client.post(
        "/api/v1/accounts/auth/login",
        json={"login": api_user.username, "password": "passw0rd"},
    )
    assert r.status_code == 200, f"登录失败: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def api_workspace(api_db, api_user):
    ws = Workspace(name="识别工作区", created_by_id=api_user.id)
    api_db.add(ws)
    api_db.flush()
    from cndb.plugins.workspaces.models import WorkspaceMember

    api_db.add(WorkspaceMember(workspace_id=ws.id, user_id=api_user.id, role=WorkspaceRole.OWNER))
    api_db.commit()
    api_db.refresh(ws)
    return ws


class TestDetectOptionsApi:
    def test_detect_select_options_api(self, api_client, api_db, api_workspace, api_auth):
        """text 字段存量数据 + target_type=select → 返回唯一值列表（不持久化）."""
        ws = api_workspace
        r = api_client.post(f"/api/v1/workspaces/{ws.id}/tables", headers=api_auth, json={"name": "员工表"})
        assert r.status_code == 201
        tid = r.json()["id"]
        r = api_client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{tid}/fields",
            headers=api_auth,
            json={"name": "部门", "field_type": "text", "config": {}, "order": 0},
        )
        assert r.status_code == 201
        fid = r.json()["id"]
        r = api_client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{tid}/records/bulk-create",
            headers=api_auth,
            json={"rows": [{"values": {"部门": "研发"}}, {"values": {"部门": "销售"}}, {"values": {"部门": "研发"}}]},
        )
        assert r.status_code == 201, r.text

        r = api_client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{tid}/fields/{fid}/detect-options",
            headers=api_auth,
            json={"target_type": "select"},
        )
        assert r.status_code == 200
        assert r.json()["options"] == ["研发", "销售"]

        # 只读：字段 config 不被改动（text 归一化后带默认键，但绝无 options）
        r = api_client.get(f"/api/v1/workspaces/{ws.id}/tables/{tid}/fields", headers=api_auth)
        field = next(f for f in r.json() if f["id"] == fid)
        assert "options" not in field["config"]

    def test_detect_multiselect_with_custom_delimiter_api(self, api_client, api_db, api_workspace, api_auth):
        """target_type=multiselect + 自定义分隔符 → 拆分识别."""
        ws = api_workspace
        r = api_client.post(f"/api/v1/workspaces/{ws.id}/tables", headers=api_auth, json={"name": "任务表"})
        tid = r.json()["id"]
        r = api_client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{tid}/fields",
            headers=api_auth,
            json={"name": "标签", "field_type": "text", "config": {}, "order": 0},
        )
        fid = r.json()["id"]
        api_client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{tid}/records/bulk-create",
            headers=api_auth,
            json={"rows": [{"values": {"标签": "前端 | 紧急"}}, {"values": {"标签": "后端"}}]},
        )

        r = api_client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{tid}/fields/{fid}/detect-options",
            headers=api_auth,
            json={"target_type": "multiselect", "delimiter": "|"},
        )
        assert r.status_code == 200
        assert r.json()["options"] == ["前端", "紧急", "后端"]

    def test_detect_invalid_target_type_api(self, api_client, api_db, api_workspace, api_auth):
        """target_type 非法 → 400."""
        ws = api_workspace
        r = api_client.post(f"/api/v1/workspaces/{ws.id}/tables", headers=api_auth, json={"name": "参数表"})
        tid = r.json()["id"]
        r = api_client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{tid}/fields",
            headers=api_auth,
            json={"name": "普通", "field_type": "text", "config": {}, "order": 0},
        )
        fid = r.json()["id"]

        r = api_client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{tid}/fields/{fid}/detect-options",
            headers=api_auth,
            json={"target_type": "number"},
        )
        assert r.status_code == 400
        assert "不是单选/多选" in r.json()["detail"]

    def test_detect_field_not_found_api(self, api_client, api_db, api_workspace, api_auth):
        """字段不存在 → 404."""
        ws = api_workspace
        r = api_client.post(f"/api/v1/workspaces/{ws.id}/tables", headers=api_auth, json={"name": "空表"})
        tid = r.json()["id"]

        r = api_client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{tid}/fields/99999/detect-options",
            headers=api_auth,
            json={"target_type": "select"},
        )
        assert r.status_code == 404
