"""change_requests 插件补充覆盖率测试：服务层边界分支 / merge 二次失败 / 行组批量合并 /
问题清单空列表分支.

仅覆盖既有实现中未被 tests/test_change_requests*.py、tests/test_issues_api.py 触达的分支，不改变行为。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.change_requests import services
from cndb.plugins.change_requests.models import ChangeRequest
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

CR = "/api/v1/workspaces/{ws}/tables/{tb}/change-requests"
REC = "/api/v1/workspaces/{ws}/tables/{tb}/records"
ISSUES = "/api/v1/workspaces/{ws}/tables/{tb}/issues"


def make_table(db: Session, ws: Workspace, name: str = "CRExtraTable") -> DataTable:
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
def owner(db) -> User:
    u = User(username="cre_owner", nickname="CreOwner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner) -> Workspace:
    w = Workspace(name="CreExtraWS", created_by_id=owner.id)
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
def editor(db, ws) -> User:
    return _add_member(db, ws, "cre_editor", WorkspaceRole.EDITOR)


@pytest.fixture
def viewer(db, ws) -> User:
    return _add_member(db, ws, "cre_viewer", WorkspaceRole.VIEWER)


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
def auth_owner(client, owner) -> dict[str, str]:
    return _login(client, owner.username)


@pytest.fixture
def auth_editor(client, editor) -> dict[str, str]:
    return _login(client, editor.username)


@pytest.fixture
def auth_viewer(client, viewer) -> dict[str, str]:
    return _login(client, viewer.username)


def _row(db: Session, dt: DataTable, row_id: int) -> dict | None:
    return rec.get_row(db.get_bind(), dt, row_id, db=db)


def _create(client: TestClient, ws: Workspace, dt: DataTable, items: list[dict], auth: dict[str, str]) -> dict:
    r = client.post(CR.format(ws=ws.id, tb=dt.id), json={"items": items}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


# ── 服务层直接调用边界 ────────────────────────────────


class TestServiceDirectUnits:
    def test_can_write_directly_non_member_false(self, db, ws, table, owner) -> None:
        dt, _ids = table
        outsider = User(username="cre_outsider", nickname="CreOutsider")
        outsider.set_password("passw0rd")
        db.add(outsider)
        db.commit()
        db.refresh(outsider)
        assert services.can_write_directly(db, dt, outsider) is False

    def test_create_dispatch_request_requires_row_id(self, db, table, owner) -> None:
        dt, _ids = table
        with pytest.raises(HTTPException) as exc:
            services.create_dispatch_request(db, dt, owner, "update", None, {"数量": 1})
        assert exc.value.status_code == 400

    def test_create_dispatch_request_missing_row_404(self, db, table, owner) -> None:
        dt, _ids = table
        with pytest.raises(HTTPException) as exc:
            services.create_dispatch_request(db, dt, owner, "update", 999999, {"数量": 1})
        assert exc.value.status_code == 404

    def test_create_dispatch_request_invalid_op_400(self, db, table, owner) -> None:
        dt, _ids = table
        with pytest.raises(HTTPException) as exc:
            services.create_dispatch_request(db, dt, owner, "bogus", None, {})
        assert exc.value.status_code == 400

    def test_create_request_invalid_op_400(self, db, table, owner) -> None:
        dt, _ids = table
        with pytest.raises(HTTPException) as exc:
            services.create_request(db, dt, owner, title=None, description="", items=[{"op": "bogus"}])
        assert exc.value.status_code == 400

    def test_create_request_create_with_row_id_400(self, db, table, owner) -> None:
        dt, _ids = table
        with pytest.raises(HTTPException) as exc:
            services.create_request(
                db, dt, owner, title=None, description="", items=[{"op": "create", "row_id": 7, "values": {}}]
            )
        assert exc.value.status_code == 400

    def test_get_request_or_404_missing(self, db, table) -> None:
        dt, _ids = table
        with pytest.raises(HTTPException) as exc:
            services.get_request_or_404(db, dt, 999999)
        assert exc.value.status_code == 404

    def test_mark_others_stale_without_exclude(self, client, db, ws, table, auth_editor) -> None:
        dt, ids = table
        cr = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 5}}], auth_editor)
        services._mark_others_stale(db, dt.id, exclude_ids=set(), row_ids={ids[0]})
        db.commit()
        assert db.query(ChangeRequest).filter(ChangeRequest.id == cr["id"]).first().stale is True


# ── merge（逐项）边界 ────────────────────────────────


class TestMergeEdges:
    def test_merge_update_missing_row_auto_skip(self, client, db, ws, table, auth_owner, auth_viewer) -> None:
        dt, ids = table
        cr = _create(client, ws, dt, [{"op": "update", "row_id": ids[1], "values": {"数量": 99}}], auth_viewer)
        rec.trash_row(db.get_bind(), dt, ids[1], db=db)
        r = client.post(
            f"{CR.format(ws=ws.id, tb=dt.id)}/{cr['id']}/merge",
            json={"items": [{"item_id": cr["items"][0]["id"], "action": "apply"}]},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        assert r.json()["skipped"] == 1

    def test_merge_second_phase_value_error_409(
        self, client, db, ws, table, auth_owner, auth_editor, monkeypatch
    ) -> None:
        dt, ids = table
        cr = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 10}}], auth_editor)

        def _boom(*_args, **_kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(rec, "update_row", _boom)
        r = client.post(
            f"{CR.format(ws=ws.id, tb=dt.id)}/{cr['id']}/merge",
            json={"items": [{"item_id": cr["items"][0]["id"], "action": "apply"}]},
            headers=auth_owner,
        )
        assert r.status_code == 409
        assert "申请保持打开" in r.json()["detail"]

    def test_close_merged_request_409(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        cr = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 12}}], auth_editor)
        url = CR.format(ws=ws.id, tb=dt.id)
        client.post(
            f"{url}/{cr['id']}/merge",
            json={"items": [{"item_id": cr["items"][0]["id"], "action": "apply"}]},
            headers=auth_owner,
        )
        r = client.post(f"{url}/{cr['id']}/close", headers=auth_owner)
        assert r.status_code == 409

    def test_update_base_after_merge_409(self, client, ws, table, auth_owner, auth_viewer) -> None:
        dt, ids = table
        base = CR.format(ws=ws.id, tb=dt.id)
        cr = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 13}}], auth_viewer)
        client.post(
            f"{base}/{cr['id']}/merge",
            json={"items": [{"item_id": cr["items"][0]["id"], "action": "apply"}]},
            headers=auth_owner,
        )
        r = client.post(f"{base}/{cr['id']}/update-base", headers=auth_viewer)
        assert r.status_code == 409

    def test_update_base_skips_create_item(self, client, ws, table, auth_viewer) -> None:
        dt, ids = table
        base = CR.format(ws=ws.id, tb=dt.id)
        cr = _create(
            client,
            ws,
            dt,
            [
                {"op": "create", "values": {"名称": "丁", "数量": 4}},
                {"op": "update", "row_id": ids[0], "values": {"数量": 21}},
            ],
            auth_viewer,
        )
        r = client.post(f"{base}/{cr['id']}/update-base", headers=auth_viewer)
        assert r.status_code == 200, r.text
        items = {i["op"]: i for i in r.json()["items"]}
        assert items["update"]["base_values"]["数量"] == 1

    def test_update_base_row_missing_409(self, client, db, ws, table, auth_viewer) -> None:
        dt, ids = table
        base = CR.format(ws=ws.id, tb=dt.id)
        cr = _create(client, ws, dt, [{"op": "update", "row_id": ids[1], "values": {"数量": 22}}], auth_viewer)
        rec.trash_row(db.get_bind(), dt, ids[1], db=db)
        r = client.post(f"{base}/{cr['id']}/update-base", headers=auth_viewer)
        assert r.status_code == 409

    def test_update_base_no_refreshable_items_400(self, client, ws, table, auth_viewer) -> None:
        dt, _ids = table
        base = CR.format(ws=ws.id, tb=dt.id)
        cr = _create(client, ws, dt, [{"op": "create", "values": {"名称": "戊", "数量": 5}}], auth_viewer)
        r = client.post(f"{base}/{cr['id']}/update-base", headers=auth_viewer)
        assert r.status_code == 400


# ── 行组聚合 / 行组批量合并边界 ───────────────────────


class TestGroupedAndRowMergeEdges:
    def test_flat_list_meta_with_delete_item(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        _create(client, ws, dt, [{"op": "delete", "row_id": ids[0]}], auth_editor)
        data = client.get(CR.format(ws=ws.id, tb=dt.id), params={"scope": "open"}, headers=auth_owner).json()
        item = data["items"][0]
        assert item["row_ids"] == [ids[0]]
        assert item["fields"] == []  # delete 项不贡献字段

    def test_group_by_row_marks_row_missing(self, client, db, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 5}}], auth_editor)
        rec.trash_row(db.get_bind(), dt, ids[0], db=db)
        data = client.get(
            CR.format(ws=ws.id, tb=dt.id), params={"scope": "open", "group_by": "row"}, headers=auth_owner
        ).json()
        assert data["groups"][0]["row_missing"] is True

    def test_row_merge_not_open_409(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        cr = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 10}}], auth_editor)
        client.post(f"{CR.format(ws=ws.id, tb=dt.id)}/{cr['id']}/close", headers=auth_owner)
        r = client.post(
            CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[0]}/merge",
            json={"request_ids": [cr["id"]]},
            headers=auth_owner,
        )
        assert r.status_code == 409

    def test_row_merge_invalid_resolution_item_id_400(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        r1 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 10}}], auth_editor)
        r2 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 20}}], auth_editor)
        r = client.post(
            CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[0]}/merge",
            json={
                "request_ids": [r1["id"], r2["id"]],
                "resolutions": {"数量": {"strategy": "item", "item_id": 999999}},
            },
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "item_id 非法" in r.json()["detail"]

    def test_row_merge_delete_missing_row_applies(self, client, db, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        cr = _create(client, ws, dt, [{"op": "delete", "row_id": ids[1]}], auth_editor)
        rec.trash_row(db.get_bind(), dt, ids[1], db=db)
        r = client.post(
            CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[1]}/merge",
            json={"request_ids": [cr["id"]], "row_action": "delete"},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        assert r.json()["applied"] == 1

    def test_row_merge_keep_current_leaves_no_effective(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        r1 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 10}}], auth_editor)
        r2 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 20}}], auth_editor)
        r = client.post(
            CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[0]}/merge",
            json={"request_ids": [r1["id"], r2["id"]], "resolutions": {"数量": {"strategy": "current"}}},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        assert r.json()["applied"] == 0

    def test_row_merge_update_row_missing(self, client, db, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        r1 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 10}}], auth_editor)
        r2 = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"名称": "新甲"}}], auth_editor)
        rec.trash_row(db.get_bind(), dt, ids[0], db=db)
        r = client.post(
            CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[0]}/merge",
            json={"request_ids": [r1["id"], r2["id"]]},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        assert r.json()["applied"] == 2

    def test_row_merge_value_error_409(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        cr = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": "非数字"}}], auth_editor)
        r = client.post(
            CR.format(ws=ws.id, tb=dt.id) + f"/rows/{ids[0]}/merge",
            json={"request_ids": [cr["id"]]},
            headers=auth_owner,
        )
        assert r.status_code == 409
        assert "申请保持打开" in r.json()["detail"]


# ── 路由层：viewer 重开 403 ───────────────────────────


class TestReopenPermission:
    def test_viewer_reopen_own_closed_403(self, client, ws, table, auth_viewer) -> None:
        dt, ids = table
        base = CR.format(ws=ws.id, tb=dt.id)
        cr = _create(client, ws, dt, [{"op": "update", "row_id": ids[0], "values": {"数量": 14}}], auth_viewer)
        assert client.post(f"{base}/{cr['id']}/close", headers=auth_viewer).status_code == 200
        r = client.post(f"{base}/{cr['id']}/reopen", headers=auth_viewer)
        assert r.status_code == 403


# ── issues：空列表分支 ───────────────────────────────


class TestIssuesEmptyList:
    def test_list_issues_empty_table(self, client, ws, table, auth_owner) -> None:
        dt, _ids = table
        r = client.get(ISSUES.format(ws=ws.id, tb=dt.id), headers=auth_owner)
        assert r.status_code == 200
        assert r.json() == {"items": [], "total": 0}

    def test_get_issue_or_404_missing(self, client, ws, table, auth_owner) -> None:
        dt, _ids = table
        r = client.get(ISSUES.format(ws=ws.id, tb=dt.id) + "/999999", headers=auth_owner)
        assert r.status_code == 404
