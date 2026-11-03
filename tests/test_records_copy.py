"""复制行（需求 0092）：按源行原值复制，不触发自动编号 / 默认值 / 日期自动填充.

判定层用 ORM + ddl 直接建表；接口层走 ``POST /records/copy`` 校验权限与 404。
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

TABLES = "/api/v1/workspaces/{ws}/tables"
RECORDS = TABLES + "/{tid}/records"
COPY = RECORDS + "/copy"


def _login(client, username: str, password: str = "passw0rd") -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_user(db: Session, username: str) -> User:
    user = User(username=username, nickname=username)
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def owner(db) -> User:
    return _make_user(db, "copy_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    workspace = Workspace(name="复制行库", created_by_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(workspace)
    return workspace


@pytest.fixture
def auth(client, owner) -> dict[str, str]:
    return _login(client, owner.username)


def _make_table(db: Session, db_engine, ws: Workspace) -> DataTable:
    """编号（自动编号）、状态（默认值）、创建日期（on_create 自动填充）、备注（可空）."""
    dt = DataTable(workspace_id=ws.id, name="复制表")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    specs: list[dict] = [
        {
            "name": "编号",
            "field_type": "text",
            "order": 0,
            "config": {"default_mode": "auto_increment", "increment_prefix": "PRJ-", "increment_padding": 3},
        },
        {"name": "状态", "field_type": "text", "order": 1, "default_value": "待办"},
        {"name": "创建日期", "field_type": "date", "order": 2, "config": {"auto_fill": "on_create"}},
        {"name": "备注", "field_type": "text", "order": 3},
        {"name": "数量", "field_type": "number", "order": 4},
    ]
    fields = []
    for spec in specs:
        field = DataField(table_id=dt.id, **spec)
        field.ensure_db_name()
        fields.append(field)
    db.add_all(fields)
    db.commit()
    db.refresh(dt)
    ddl.create_table(db_engine, dt)
    return dt


class TestCopyRowValues:
    """判定层：源行读取与 exact 写入."""

    def test_copy_row_values_reads_source_as_is(self, db, db_engine, ws):
        dt = _make_table(db, db_engine, ws)
        source = rec.create_row(db_engine, dt, {"备注": "原始备注"})
        assert source is not None

        values = rec.copy_row_values(db_engine, dt, int(source["id"]))
        assert values is not None
        # 自动编号 / 默认值 / 自动填充字段都取源行值（不是重新生成）
        assert values["编号"] == source["编号"]
        assert values["状态"] == "待办"
        assert values["创建日期"] == source["创建日期"]
        assert values["备注"] == "原始备注"

    def test_exact_copy_keeps_values_and_empty_fields(self, db, db_engine, ws):
        """exact 复制：值完全一致；源行空值仍为空（不被默认值 / 自动填充补上）."""
        dt = _make_table(db, db_engine, ws)
        source = rec.create_row(db_engine, dt, {"编号": "PRJ-900", "状态": None, "创建日期": None, "备注": None})
        assert source is not None
        assert source["状态"] is None

        values = rec.copy_row_values(db_engine, dt, int(source["id"]))
        assert values is not None
        ids = rec.bulk_create(db_engine, dt, [values], db=db, exact_copy=True)
        copied = rec.get_row(db_engine, dt, ids[0], db=db)

        assert copied is not None
        for field in ("编号", "状态", "创建日期", "备注", "数量"):
            assert copied[field] == source[field], field

    def test_plain_bulk_create_would_fill_defaults(self, db, db_engine, ws):
        """对照：非 exact 路径会给源行空值补默认值 / 自动填充（本次修复的原因）."""
        dt = _make_table(db, db_engine, ws)
        source = rec.create_row(db_engine, dt, {"编号": "PRJ-901", "状态": None, "创建日期": None})
        assert source is not None

        values = rec.copy_row_values(db_engine, dt, int(source["id"]))
        assert values is not None
        ids = rec.bulk_create(db_engine, dt, [values], db=db)
        copied = rec.get_row(db_engine, dt, ids[0], db=db)

        assert copied is not None
        # 普通建行：空日期被 auto_fill 自动填充成今天（复制行必须避免的正是这类覆盖）
        assert copied["创建日期"] == date.today()

    def test_copy_does_not_regenerate_auto_increment(self, db, db_engine, ws):
        """自动编号字段按源行复制，不重新取号（重复号是预期的「与源行一致」）."""
        dt = _make_table(db, db_engine, ws)
        first = rec.create_row(db_engine, dt, {})
        second = rec.create_row(db_engine, dt, {})
        assert first is not None and second is not None
        assert first["编号"] != second["编号"]

        values = rec.copy_row_values(db_engine, dt, int(first["id"]))
        assert values is not None
        ids = rec.bulk_create(db_engine, dt, [values], db=db, exact_copy=True)
        copied = rec.get_row(db_engine, dt, ids[0], db=db)
        assert copied is not None
        assert copied["编号"] == first["编号"]

    def test_copy_row_values_respects_read_scope(self, db, db_engine, ws):
        dt = _make_table(db, db_engine, ws)
        source = rec.create_row(db_engine, dt, {})
        assert source is not None
        # 不存在的行 → None（上层转 404）
        assert rec.copy_row_values(db_engine, dt, 999999) is None


class TestCopyEndpoint:
    def _seed(self, client, ws, auth) -> tuple[int, int]:
        r = client.post(TABLES.format(ws=ws.id), json={"name": "复制表"}, headers=auth)
        assert r.status_code == 201, r.text
        tid = int(r.json()["id"])
        for spec in (
            {
                "name": "编号",
                "field_type": "text",
                "order": 0,
                "config": {"default_mode": "auto_increment", "increment_prefix": "PRJ-", "increment_padding": 3},
            },
            {"name": "状态", "field_type": "text", "order": 1, "default_value": "待办"},
            {"name": "创建日期", "field_type": "date", "order": 2, "config": {"auto_fill": "on_create"}},
            {"name": "备注", "field_type": "text", "order": 3},
        ):
            r = client.post(f"{TABLES.format(ws=ws.id)}/{tid}/fields", json=spec, headers=auth)
            assert r.status_code in (200, 201), r.text
        r = client.post(
            RECORDS.format(ws=ws.id, tid=tid),
            json={"values": {"状态": None, "创建日期": "2020-01-02", "备注": "原样"}},
            headers=auth,
        )
        assert r.status_code == 201, r.text
        return tid, int(r.json()["id"])

    def test_copy_returns_identical_row(self, client, db, db_engine, ws, auth):
        tid, row_id = self._seed(client, ws, auth)
        source = client.get(RECORDS.format(ws=ws.id, tid=tid) + f"/{row_id}", headers=auth).json()

        r = client.post(COPY.format(ws=ws.id, tid=tid), json={"row_ids": [row_id]}, headers=auth)
        assert r.status_code == 201, r.text
        assert r.json()["created"] == 1
        copied_id = int(r.json()["ids"][0])
        copied = client.get(RECORDS.format(ws=ws.id, tid=tid) + f"/{copied_id}", headers=auth).json()

        for field in ("编号", "状态", "创建日期", "备注"):
            assert copied[field] == source[field], field
        # 源行的空状态（不被默认值补上）与历史日期（不被 auto_fill 改成今天）都原样保留
        assert copied["状态"] is None
        assert copied["创建日期"] == "2020-01-02"

    def test_copy_missing_row_404(self, client, ws, auth, db_engine):
        r = client.post(TABLES.format(ws=ws.id), json={"name": "空表"}, headers=auth)
        assert r.status_code == 201, r.text
        tid = int(r.json()["id"])
        r = client.post(COPY.format(ws=ws.id, tid=tid), json={"row_ids": [999999]}, headers=auth)
        assert r.status_code == 404

    def test_copy_requires_edit_permission(self, client, db, ws):
        viewer = _make_user(db, "copy_viewer")
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        owner_auth = _login(client, _owner_username(db, ws))
        tid, row_id = self._seed(client, ws, owner_auth)

        r = client.post(
            COPY.format(ws=ws.id, tid=tid),
            json={"row_ids": [row_id]},
            headers=_login(client, viewer.username),
        )
        assert r.status_code == 403


def _owner_username(db: Session, ws: Workspace) -> str:
    user = db.get(User, ws.created_by_id)
    return user.username
