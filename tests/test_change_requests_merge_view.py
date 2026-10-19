"""同行合并视图 + 批量审批 + 冲突检测测试.

覆盖：列表 group_by=row 分组与时间倒序 / 冲突字段与基准漂移检测 /
行组批量合并（无冲突自动、冲突显式裁决、保留当前值、delete 互斥）/ 权限与原子性 / stale 传染。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

CR = "/api/v1/workspaces/{ws}/tables/{tb}/change-requests"
REC = "/api/v1/workspaces/{ws}/tables/{tb}/records"


def make_table(db: Session, ws: Workspace, name: str = "MergeViewTable") -> DataTable:
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


@pytest.fixture
def owner(db):
    u = User(username="mv_owner", nickname="MvOwner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="MergeViewWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


def _add_member(db: Session, ws: Workspace, username: str, role: WorkspaceRole) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=role))
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def editor(db, ws):
    return _add_member(db, ws, "mv_editor", WorkspaceRole.EDITOR)


@pytest.fixture
def viewer(db, ws):
    return _add_member(db, ws, "mv_viewer", WorkspaceRole.VIEWER)


@pytest.fixture
def table(db, ws):
    dt = make_table(db, ws)
    engine = db.get_bind()
    ids = rec.bulk_create(
        engine,
        dt,
        [{"名称": "甲", "数量": 1}, {"名称": "乙", "数量": 2}, {"名称": "丙", "数量": 3}],
        db=db,
    )
    return dt, ids


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


def _create(client, ws, dt, items, auth) -> dict:
    r = client.post(CR.format(ws=ws.id, tb=dt.id), json={"items": items}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


class TestGroupedList:
    def test_group_by_row_and_time_desc(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        r1 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 5}}], auth_editor)
        r2 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"名称": "新甲"}}], auth_owner)
        _create(client, ws, dt, [{"op": "update", "row_id": ids[1], "values": {"数量": 6}}], auth_editor)
        # 纯新增（无 row_id）→ ungrouped
        _create(client, ws, dt, [{"op": "create", "values": {"名称": "丁", "数量": 4}}], auth_editor)

        data = client.get(
            CR.format(ws=ws.id, tb=dt.id), params={"scope": "open", "group_by": "row"}, headers=auth_owner
        ).json()
        groups = data["groups"]
        assert data["total"] == 4
        by_row = {g["row_id"]: g for g in groups}
        assert set(by_row) == {ids[0], ids[1]}
        assert len(by_row[ids[0]]["requests"]) == 2
        # 组内时间倒序：后提交的 r2 在前
        assert [q["id"] for q in by_row[ids[0]]["requests"]] == [r2["id"], r1["id"]]
        # 组间按最新提交倒序：ids[1]（r3）晚于 ids[0]
        assert [g["row_id"] for g in groups] == [ids[1], ids[0]]
        assert len(data["ungrouped"]) == 1

    def test_conflict_fields_detected(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 5}}], auth_editor)
        _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 6}}], auth_owner)
        data = client.get(
            CR.format(ws=ws.id, tb=dt.id), params={"scope": "open", "group_by": "row"}, headers=auth_owner
        ).json()
        g = data["groups"][0]
        assert g["conflict_fields"] == ["数量"]
        assert g["has_conflict"] is True

    def test_same_value_not_conflict(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 5}}], auth_editor)
        _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 5}}], auth_owner)
        data = client.get(
            CR.format(ws=ws.id, tb=dt.id), params={"scope": "open", "group_by": "row"}, headers=auth_owner
        ).json()
        assert data["groups"][0]["conflict_fields"] == []
        assert data["groups"][0]["has_conflict"] is False

    def test_drift_fields_detected(self, client, ws, table, db, auth_owner, auth_editor, auth_viewer) -> None:
        dt, ids = table
        _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 17}}], auth_viewer)
        # 编辑者直编改掉 数量 → 基准漂移
        client.patch(REC.format(ws=ws.id, tb=dt.id) + f"/{ids[0]}", json={"values": {"数量": 4}}, headers=auth_editor)
        data = client.get(
            CR.format(ws=ws.id, tb=dt.id), params={"scope": "open", "group_by": "row"}, headers=auth_owner
        ).json()
        assert data["groups"][0]["drift_fields"] == ["数量"]
        assert data["groups"][0]["has_drift"] is True

    def test_flat_list_still_returns_items(self, client, ws, table, auth_editor) -> None:
        dt, ids = table
        _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 5}}], auth_editor)
        data = client.get(CR.format(ws=ws.id, tb=dt.id), params={"scope": "open"}, headers=auth_editor).json()
        assert "items" in data
        assert data["items"][0]["row_ids"] == [ids[0]]
        assert data["items"][0]["fields"] == ["数量"]


class TestRowMerge:
    def test_no_conflict_applies_multiple_requests(self, client, ws, table, db, auth_owner, auth_editor) -> None:
        dt, ids = table
        r1 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 10}}], auth_editor)
        r2 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"名称": "新甲"}}], auth_editor)
        url = CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[0]}/merge"
        r = client.post(url, json={"request_ids": [r1["id"], r2["id"]]}, headers=auth_owner)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body["merged_request_ids"]) == {r1["id"], r2["id"]}
        row = _row(db, dt, ids[0])
        assert row["数量"] == 10
        assert row["名称"] == "新甲"
        # 两个申请均置 merged
        for rid in (r1["id"], r2["id"]):
            detail = client.get(f"{CR.format(ws=ws.id, tb=dt.id)}/{rid}", headers=auth_owner).json()
            assert detail["status"] == "merged"

    def test_conflict_requires_resolution(self, client, ws, table, db, auth_owner, auth_editor) -> None:
        dt, ids = table
        r1 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 10}}], auth_editor)
        r2 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 20}}], auth_editor)
        url = CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[0]}/merge"
        # 未裁决 → 409，保持 open
        r = client.post(url, json={"request_ids": [r1["id"], r2["id"]]}, headers=auth_owner)
        assert r.status_code == 409
        assert _row(db, dt, ids[0])["数量"] == 1
        # 显式采用 r2 的值
        item_id = r2["items"][0]["id"]
        r = client.post(
            url,
            json={
                "request_ids": [r1["id"], r2["id"]],
                "resolutions": {"数量": {"strategy": "item", "item_id": item_id}},
            },
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        assert _row(db, dt, ids[0])["数量"] == 20

    def test_resolution_keep_current_skips_field(self, client, ws, table, db, auth_owner, auth_editor) -> None:
        dt, ids = table
        r1 = _create(
            client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 10, "名称": "新甲"}}], auth_editor
        )
        r2 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 20}}], auth_editor)
        url = CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[0]}/merge"
        r = client.post(
            url,
            json={"request_ids": [r1["id"], r2["id"]], "resolutions": {"数量": {"strategy": "current"}}},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        row = _row(db, dt, ids[0])
        assert row["数量"] == 1  # 保留当前值
        assert row["名称"] == "新甲"  # 非冲突字段照常应用

    def test_reject_create_or_other_row(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        cr_create = _create(client, ws, dt, [{"op": "create", "values": {"名称": "丁", "数量": 4}}], auth_editor)
        url = CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[0]}/merge"
        r = client.post(url, json={"request_ids": [cr_create["id"]]}, headers=auth_owner)
        assert r.status_code == 400

        cr_multi = _create(
            client,
            ws,
            dt,
            [
                {"op": "update", "row_id": ids[0], "values": {"数量": 9}},
                {"op": "update", "row_id": ids[1], "values": {"数量": 8}},
            ],
            auth_editor,
        )
        r = client.post(url, json={"request_ids": [cr_multi["id"]]}, headers=auth_owner)
        assert r.status_code == 400

    def test_delete_conflict_requires_row_action(self, client, ws, table, db, auth_owner, auth_editor) -> None:
        dt, ids = table
        cr_del = _create(client, ws, dt, [{"op": "delete", "row_id": ids[0]}], auth_editor)
        cr_upd = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 10}}], auth_editor)
        url = CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[0]}/merge"
        r = client.post(url, json={"request_ids": [cr_del["id"], cr_upd["id"]]}, headers=auth_owner)
        assert r.status_code == 409
        # keep → 保留行并应用修改
        r = client.post(
            url, json={"request_ids": [cr_del["id"], cr_upd["id"]], "row_action": "keep"}, headers=auth_owner
        )
        assert r.status_code == 200, r.text
        row = _row(db, dt, ids[0])
        assert row is not None
        assert row["数量"] == 10

    def test_delete_conflict_apply_delete(self, client, ws, table, db, auth_owner, auth_editor) -> None:
        dt, ids = table
        cr_del = _create(client, ws, dt, [{"op": "delete", "row_id": ids[1]}], auth_editor)
        cr_upd = _create(client, ws, dt, [{"op": "update", "row_id": ids[1], "values": {"数量": 10}}], auth_editor)
        url = CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[1]}/merge"
        r = client.post(
            url, json={"request_ids": [cr_del["id"], cr_upd["id"]], "row_action": "delete"}, headers=auth_owner
        )
        assert r.status_code == 200, r.text
        assert _row(db, dt, ids[1]) is None

    def test_viewer_403(self, client, ws, table, auth_owner, auth_viewer) -> None:
        dt, ids = table
        cr = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 10}}], auth_viewer)
        url = CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[0]}/merge"
        r = client.post(url, json={"request_ids": [cr["id"]]}, headers=auth_viewer)
        assert r.status_code == 403

    def test_atomicity_invalid_value_keeps_all_open(self, client, ws, table, db, auth_owner, auth_editor) -> None:
        dt, ids = table
        r1 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 10}}], auth_editor)
        r2 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"名称": "新甲"}}], auth_editor)
        # 直接篡改 r2 的 values 为非法 number 文本
        from cndb.plugins.change_requests.models import ChangeItem

        item = db.query(ChangeItem).filter(ChangeItem.request_id == r2["id"]).first()
        item.values = {"名称": "新甲", "数量": "非数字"}
        db.commit()

        url = CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[0]}/merge"
        r = client.post(url, json={"request_ids": [r1["id"], r2["id"]]}, headers=auth_owner)
        assert r.status_code == 409
        assert _row(db, dt, ids[0])["数量"] == 1
        for rid in (r1["id"], r2["id"]):
            detail = client.get(f"{CR.format(ws=ws.id, tb=dt.id)}/{rid}", headers=auth_owner).json()
            assert detail["status"] == "open"

    def test_marks_other_open_requests_stale(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        r1 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 10}}], auth_editor)
        r2 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"名称": "新甲"}}], auth_editor)
        r3 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 99}}], auth_editor)
        url = CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[0]}/merge"
        r = client.post(url, json={"request_ids": [r1["id"], r2["id"]]}, headers=auth_owner)
        assert r.status_code == 200, r.text
        detail = client.get(f"{CR.format(ws=ws.id, tb=dt.id)}/{r3['id']}", headers=auth_owner).json()
        assert detail["stale"] is True
