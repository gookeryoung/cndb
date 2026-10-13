"""写模式判定（resolve_write_mode）+ 使用工况一致性测试.

覆盖：
- 写模式矩阵：owner/editor×allow_edit/viewer × 表级阈值（direct/change_request/denied）；
- 列表端点 write_mode 响应与当前用户写路径分派一致；
- 典型工况：直编用户编辑直接落库不生成申请、申请轨道用户编辑自动生成申请；
- 表成员授权边界：工作区 viewer + TableMember write 仍走申请轨道（当前行为登记）。

背景：修改申请列表页提示曾无条件引导"表格编辑自动生成申请"，
对直编用户（owner/editor+allow_edit）与实际行为矛盾 —— 本测试锁定分派与标注同源。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.change_requests import services as cr_services
from cndb.plugins.tables.models import DataField, DataTable, TableMember, TablePermission
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

CR = "/api/v1/workspaces/{ws}/tables/{tb}/change-requests"
REC = "/api/v1/workspaces/{ws}/tables/{tb}/records"


def make_table(db: Session, ws: Workspace, name: str = "WriteModeTable") -> DataTable:
    """建一张带两个字段的物理表."""
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name=name)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for fname, ftype in [("名称", "text"), ("数量", "number")]:
        f = DataField(table_id=dt.id, name=fname, field_type=ftype)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    return dt


def _make_user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _add_member(db: Session, ws: Workspace, user: User, role: WorkspaceRole) -> None:
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=role))
    db.commit()


@pytest.fixture
def owner(db):
    return _make_user(db, "wm_owner")


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="WriteModeWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    """带 2 行数据的表，返回 (DataTable, row_ids)."""
    dt = make_table(db, ws)
    engine = db.get_bind()
    ids = rec.bulk_create(engine, dt, [{"名称": "甲", "数量": 1}, {"名称": "乙", "数量": 2}], db=db)
    return dt, ids


@pytest.fixture
def editor(db, ws):
    u = _make_user(db, "wm_editor")
    _add_member(db, ws, u, WorkspaceRole.EDITOR)
    return u


@pytest.fixture
def viewer(db, ws):
    u = _make_user(db, "wm_viewer")
    _add_member(db, ws, u, WorkspaceRole.VIEWER)
    return u


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth_owner(client, owner):
    return _login(client, owner.username)


@pytest.fixture
def auth_editor(client, editor):
    return _login(client, editor.username)


@pytest.fixture
def auth_viewer(client, viewer):
    return _login(client, viewer.username)


def _row(db: Session, dt: DataTable, row_id: int) -> dict | None:
    return rec.get_row(db.get_bind(), dt, row_id, db=db)


class TestResolveWriteMode:
    """写模式三态判定矩阵（单元级，直连 services.resolve_write_mode）."""

    def test_owner_direct(self, db, ws, table, owner) -> None:
        dt, _ = table
        assert cr_services.resolve_write_mode(db, dt, owner) == "direct"

    def test_editor_allow_edit_on_direct(self, db, ws, table, editor) -> None:
        dt, _ = table
        assert ws.allow_edit is True  # 工作区默认开启直编
        assert cr_services.resolve_write_mode(db, dt, editor) == "direct"

    def test_editor_allow_edit_off_change_request(self, db, ws, table, editor) -> None:
        dt, _ = table
        ws.allow_edit = False
        db.commit()
        assert cr_services.resolve_write_mode(db, dt, editor) == "change_request"

    def test_viewer_change_request(self, db, ws, table, viewer) -> None:
        dt, _ = table
        assert cr_services.resolve_write_mode(db, dt, viewer) == "change_request"

    def test_table_threshold_denies_editor(self, db, ws, table, editor) -> None:
        """表级 edit_records_role=owner：编辑者有直编资格但被表级阈值拦下 → denied."""
        dt, _ = table
        db.add(TablePermission(table_id=dt.id, edit_records_role="owner"))
        db.commit()
        assert cr_services.resolve_write_mode(db, dt, editor) == "denied"

    def test_table_threshold_does_not_affect_viewer(self, db, ws, table, viewer) -> None:
        """viewer 无直编资格，与表级阈值无关 → change_request."""
        dt, _ = table
        db.add(TablePermission(table_id=dt.id, edit_records_role="owner"))
        db.commit()
        assert cr_services.resolve_write_mode(db, dt, viewer) == "change_request"


class TestWriteModeEndpoint:
    """列表端点 write_mode 响应：与当前用户写路径分派同源."""

    def test_owner_gets_direct(self, client, ws, table, auth_owner) -> None:
        dt, _ = table
        r = client.get(CR.format(ws=ws.id, tb=dt.id), headers=auth_owner)
        assert r.status_code == 200
        assert r.json()["write_mode"] == "direct"

    def test_editor_gets_direct(self, client, ws, table, auth_editor) -> None:
        dt, _ = table
        r = client.get(CR.format(ws=ws.id, tb=dt.id), headers=auth_editor)
        assert r.json()["write_mode"] == "direct"

    def test_viewer_gets_change_request(self, client, ws, table, auth_viewer) -> None:
        dt, _ = table
        r = client.get(CR.format(ws=ws.id, tb=dt.id), headers=auth_viewer)
        assert r.json()["write_mode"] == "change_request"

    def test_editor_denied_by_table_threshold(self, client, ws, table, db, auth_editor) -> None:
        dt, _ = table
        db.add(TablePermission(table_id=dt.id, edit_records_role="owner"))
        db.commit()
        r = client.get(CR.format(ws=ws.id, tb=dt.id), headers=auth_editor)
        assert r.json()["write_mode"] == "denied"


class TestUsageScenarios:
    """使用工况一致性：write_mode 与实际写路径行为互证."""

    def test_direct_user_writes_without_request(self, client, ws, table, db, auth_editor) -> None:
        """直编用户（editor+allow_edit）：编辑直接落库，不生成修改申请."""
        dt, ids = table
        r = client.patch(
            f"{REC.format(ws=ws.id, tb=dt.id)}/{ids[0]}", json={"values": {"数量": 99}}, headers=auth_editor
        )
        assert r.status_code == 200
        assert r.json()["数量"] == 99
        # 落库且未生成申请
        assert _row(db, dt, ids[0])["数量"] == 99
        assert client.get(CR.format(ws=ws.id, tb=dt.id) + "?scope=all", headers=auth_editor).json()["total"] == 0

    def test_change_request_user_generates_request(self, client, ws, table, db, auth_viewer) -> None:
        """申请轨道用户（viewer）：编辑不落库，自动生成申请."""
        dt, ids = table
        r = client.patch(
            f"{REC.format(ws=ws.id, tb=dt.id)}/{ids[0]}", json={"values": {"数量": 88}}, headers=auth_viewer
        )
        assert r.status_code == 202
        assert "change_request" in r.json()
        assert _row(db, dt, ids[0])["数量"] == 1  # 数据未变

    def test_allow_edit_flip_switches_track(self, client, ws, table, db, auth_editor) -> None:
        """同一编辑者：工作区关闭直编后写路径从直存切换为申请轨道."""
        dt, ids = table
        r = client.patch(
            f"{REC.format(ws=ws.id, tb=dt.id)}/{ids[0]}", json={"values": {"数量": 10}}, headers=auth_editor
        )
        assert r.status_code == 200  # allow_edit=True → 直存

        ws.allow_edit = False
        db.commit()
        r = client.patch(
            f"{REC.format(ws=ws.id, tb=dt.id)}/{ids[0]}", json={"values": {"数量": 11}}, headers=auth_editor
        )
        assert r.status_code == 202  # allow_edit=False → 申请轨道
        assert _row(db, dt, ids[0])["数量"] == 10  # 未落库

    def test_denied_user_gets_403(self, client, ws, table, db, auth_editor) -> None:
        """denied 工况（表级阈值拦截编辑者）：写操作 403，不生成申请."""
        dt, ids = table
        db.add(TablePermission(table_id=dt.id, edit_records_role="owner"))
        db.commit()
        r = client.patch(
            f"{REC.format(ws=ws.id, tb=dt.id)}/{ids[0]}", json={"values": {"数量": 5}}, headers=auth_editor
        )
        assert r.status_code == 403
        assert client.get(CR.format(ws=ws.id, tb=dt.id) + "?scope=all", headers=auth_editor).json()["total"] == 0


class TestTableMemberEdge:
    """表成员授权边界工况：分派只看工作区角色，TableMember write 授权不改变轨道."""

    def test_viewer_with_member_write_still_change_request(self, client, ws, table, db, auth_viewer, viewer) -> None:
        """工作区 viewer + 表成员 write 授权：编辑仍走申请轨道（当前行为登记，
        与表级授权预期不一致 —— 已在 seed 演示问题清单中登记为 open 问题）."""
        dt, ids = table
        db.add(TableMember(table_id=dt.id, user_id=viewer.id, role="write"))
        db.commit()

        r = client.get(CR.format(ws=ws.id, tb=dt.id), headers=auth_viewer)
        assert r.json()["write_mode"] == "change_request"

        r = client.patch(
            f"{REC.format(ws=ws.id, tb=dt.id)}/{ids[0]}", json={"values": {"数量": 66}}, headers=auth_viewer
        )
        assert r.status_code == 202
        assert _row(db, dt, ids[0])["数量"] == 1  # 未落库，转为申请

    def test_owner_member_write_direct(self, client, ws, table, db, auth_owner, owner) -> None:
        """对照组：owner + 表成员 write → 直编不受影响."""
        dt, ids = table
        db.add(TableMember(table_id=dt.id, user_id=owner.id, role="write"))
        db.commit()
        r = client.patch(
            f"{REC.format(ws=ws.id, tb=dt.id)}/{ids[0]}", json={"values": {"数量": 77}}, headers=auth_owner
        )
        assert r.status_code == 200
        assert _row(db, dt, ids[0])["数量"] == 77
