"""修改申请 API + 双轨写入分派测试（设计 3.3/3.4 节）.

覆盖：创建（多 item/服务端快照）/ 列表冲突计数 / 详情字段级 diff /
merge 逐项决策与整体 409 / stale 标记 / update-base / 权限边界 /
editor 直编、viewer 生成申请、allow_edit 关闭、批删多 item。
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


def make_table(db: Session, ws: Workspace, name: str = "CRTable") -> DataTable:
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


@pytest.fixture
def owner(db):
    u = User(username="cr_api_owner", nickname="CrApiOwner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="CrApiWS", created_by_id=owner.id)
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
    return _add_member(db, ws, "cr_api_editor", WorkspaceRole.EDITOR)


@pytest.fixture
def viewer(db, ws):
    return _add_member(db, ws, "cr_api_viewer", WorkspaceRole.VIEWER)


@pytest.fixture
def table(db, ws):
    """带 3 行数据的表，返回 (DataTable, row_ids)."""
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


class TestCreateRequest:
    def test_create_multi_items_snapshot_base(self, client, ws, table, auth_owner) -> None:
        dt, ids = table
        url = CR.format(ws=ws.id, tb=dt.id)
        r = client.post(
            url,
            json={
                "title": "批量调整",
                "items": [
                    {"op": "update", "row_id": ids[0], "values": {"数量": 10}},
                    {"op": "delete", "row_id": ids[1]},
                ],
            },
            headers=auth_owner,
        )
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "open"
        assert len(body["items"]) == 2
        upd = next(i for i in body["items"] if i["op"] == "update")
        assert upd["base_values"] == {"数量": 1}
        dele = next(i for i in body["items"] if i["op"] == "delete")
        assert dele["base_values"]["名称"] == "乙"
        assert dele["values"] == {}

    def test_create_auto_title(self, client, ws, table, auth_editor) -> None:
        dt, ids = table
        url = CR.format(ws=ws.id, tb=dt.id)
        r = client.post(
            url,
            json={"items": [{"op": "update", "row_id": ids[0], "values": {"名称": "新甲"}}]},
            headers=auth_editor,
        )
        assert r.status_code == 201
        assert r.json()["title"] == f"修改行 #{ids[0]}"

    def test_create_update_missing_row_400(self, client, ws, table, auth_owner) -> None:
        dt, _ids = table
        r = client.post(
            CR.format(ws=ws.id, tb=dt.id),
            json={"items": [{"op": "update", "row_id": 99999, "values": {"数量": 1}}]},
            headers=auth_owner,
        )
        assert r.status_code == 400

    def test_create_update_item_row_must_exist(self, client, ws, table, auth_owner) -> None:
        dt, _ids = table
        r = client.post(
            CR.format(ws=ws.id, tb=dt.id),
            json={"items": [{"op": "delete"}]},
            headers=auth_owner,
        )
        assert r.status_code == 400  # delete 缺 row_id → 服务端校验拦截

    def test_non_member_403(self, client, db, ws, table) -> None:
        dt, _ids = table
        u = User(username="cr_api_stranger", nickname="CrApiStranger")
        u.set_password("passw0rd")
        db.add(u)
        db.commit()
        auth = _login(client, u.username)
        r = client.get(CR.format(ws=ws.id, tb=dt.id), headers=auth)
        assert r.status_code == 403


class TestListAndDetail:
    def test_list_scope_and_conflicts_count(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        url = CR.format(ws=ws.id, tb=dt.id)
        # 两个 open 申请都引用 ids[0]，另有一个引用 ids[1] 的申请随后关闭
        r1 = client.post(
            url, json={"items": [{"op": "update", "row_id": ids[0], "values": {"数量": 5}}]}, headers=auth_owner
        ).json()
        r2 = client.post(
            url, json={"items": [{"op": "update", "row_id": ids[0], "values": {"数量": 6}}]}, headers=auth_editor
        ).json()
        r3 = client.post(
            url, json={"items": [{"op": "update", "row_id": ids[1], "values": {"数量": 7}}]}, headers=auth_editor
        ).json()
        client.post(f"{url}/{r3['id']}/close", headers=auth_editor)

        open_list = client.get(url, headers=auth_owner).json()
        assert open_list["total"] == 2
        by_id = {i["id"]: i for i in open_list["items"]}
        assert by_id[r1["id"]]["conflicts_count"] == 1  # 与另一个 open 申请共享 1 行

        all_list = client.get(url, params={"scope": "all"}, headers=auth_owner).json()
        all_by_id = {i["id"]: i for i in all_list["items"]}
        assert all_list["total"] == 3
        assert all_by_id[r3["id"]]["conflicts_count"] == 0  # 已关闭，不参与冲突计数

        mine = client.get(url, params={"scope": "mine"}, headers=auth_editor).json()
        assert {i["id"] for i in mine["items"]} == {r2["id"], r3["id"]}  # 编辑者提交的申请

    def test_list_scope_merged(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        url = CR.format(ws=ws.id, tb=dt.id)
        r1 = client.post(
            url, json={"items": [{"op": "update", "row_id": ids[0], "values": {"数量": 5}}]}, headers=auth_editor
        ).json()
        client.post(
            url, json={"items": [{"op": "update", "row_id": ids[1], "values": {"数量": 6}}]}, headers=auth_editor
        )
        client.post(
            f"{url}/{r1['id']}/merge",
            json={"items": [{"item_id": r1["items"][0]["id"], "action": "apply"}]},
            headers=auth_owner,
        )

        merged = client.get(url, params={"scope": "merged"}, headers=auth_owner).json()
        assert {i["id"] for i in merged["items"]} == {r1["id"]}
        assert merged["items"][0]["status"] == "merged"

    def test_detail_field_conflicts_after_drift(self, client, ws, table, auth_owner, auth_editor, auth_viewer) -> None:
        dt, ids = table
        url = CR.format(ws=ws.id, tb=dt.id)
        cr = client.post(
            url,
            json={"items": [{"op": "update", "row_id": ids[0], "values": {"名称": "新甲", "数量": 9}}]},
            headers=auth_viewer,
        ).json()
        # 提交后编辑者直编改掉 数量 → 基准漂移
        client.patch(REC.format(ws=ws.id, tb=dt.id) + f"/{ids[0]}", json={"values": {"数量": 4}}, headers=auth_editor)
        detail = client.get(f"{url}/{cr['id']}", headers=auth_owner).json()
        item = detail["items"][0]
        assert item["field_conflicts"] == ["数量"]
        assert item["current_values"]["数量"] == 4


class TestMerge:
    def _create(
        self,
        client: TestClient,
        ws: Workspace,
        table: tuple[DataTable, list[int]],
        items: list[dict],
        auth: dict[str, str],
    ) -> dict:
        dt, _ids = table
        return client.post(CR.format(ws=ws.id, tb=dt.id), json={"items": items}, headers=auth).json()

    def test_merge_apply_update(self, client, ws, table, db, auth_owner, auth_editor) -> None:
        dt, ids = table
        cr = self._create(client, ws, table, [{"op": "update", "row_id": ids[0], "values": {"数量": 10}}], auth_editor)
        r = client.post(
            f"{CR.format(ws=ws.id, tb=dt.id)}/{cr['id']}/merge",
            json={"items": [{"item_id": cr["items"][0]["id"], "action": "apply"}], "comment": "同意"},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["applied"] == 1
        assert r.json()["request"]["status"] == "merged"
        # 合并响应须为完整详情（含 items/actions）：前端以响应覆盖详情缓存，
        # 缺 items 会致详情页 undefined.length 崩溃
        assert r.json()["request"]["items"][0]["values"] == {"数量": 10}
        assert [a["action"] for a in r.json()["request"]["actions"]] == ["merge"]
        assert _row(db, dt, ids[0])["数量"] == 10

    def test_merge_skip_leaves_row(self, client, ws, table, db, auth_owner, auth_editor) -> None:
        dt, ids = table
        cr = self._create(client, ws, table, [{"op": "update", "row_id": ids[0], "values": {"数量": 11}}], auth_editor)
        r = client.post(
            f"{CR.format(ws=ws.id, tb=dt.id)}/{cr['id']}/merge",
            json={"items": [{"item_id": cr["items"][0]["id"], "action": "skip"}]},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["skipped"] == 1
        assert _row(db, dt, ids[0])["数量"] == 1
        assert r.json()["request"]["status"] == "merged"

    def test_merge_delete_missing_row_auto_skip(self, client, ws, table, db, auth_owner, auth_editor) -> None:
        dt, ids = table
        # 申请删除 ids[2]，但 merge 前该行已被直接删除
        cr = self._create(client, ws, table, [{"op": "delete", "row_id": ids[2]}], auth_editor)
        rec.trash_row(db.get_bind(), dt, ids[2], db=db)
        r = client.post(
            f"{CR.format(ws=ws.id, tb=dt.id)}/{cr['id']}/merge",
            json={"items": [{"item_id": cr["items"][0]["id"], "action": "apply"}]},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["skipped"] == 1

    def test_merge_delete_applies_soft_delete(self, client, ws, table, db, auth_owner, auth_editor) -> None:
        dt, ids = table
        cr = self._create(client, ws, table, [{"op": "delete", "row_id": ids[0]}], auth_editor)
        r = client.post(
            f"{CR.format(ws=ws.id, tb=dt.id)}/{cr['id']}/merge",
            json={"items": [{"item_id": cr["items"][0]["id"], "action": "apply"}]},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert _row(db, dt, ids[0]) is None  # 软删后常规读取不可见

    def test_merge_value_error_409_keeps_open(self, client, ws, table, db, auth_owner, auth_editor) -> None:
        dt, ids = table
        # number 字段写入非法文本 → 预校验失败整体 409
        cr = self._create(
            client,
            ws,
            table,
            [
                {"op": "update", "row_id": ids[0], "values": {"数量": 20}},
                {"op": "update", "row_id": ids[1], "values": {"数量": "不是数字"}},
            ],
            auth_editor,
        )
        decisions = [{"item_id": i["id"], "action": "apply"} for i in cr["items"]]
        r = client.post(
            f"{CR.format(ws=ws.id, tb=dt.id)}/{cr['id']}/merge",
            json={"items": decisions},
            headers=auth_owner,
        )
        assert r.status_code == 409
        assert r.json()["detail"].startswith("变更项")
        # 申请保持 open 且数据未落库
        detail = client.get(f"{CR.format(ws=ws.id, tb=dt.id)}/{cr['id']}", headers=auth_owner).json()
        assert detail["status"] == "open"
        assert _row(db, dt, ids[0])["数量"] == 1

    def test_merge_marks_sharing_requests_stale(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        url = CR.format(ws=ws.id, tb=dt.id)
        cr1 = self._create(client, ws, table, [{"op": "update", "row_id": ids[0], "values": {"数量": 30}}], auth_editor)
        cr2 = self._create(client, ws, table, [{"op": "update", "row_id": ids[0], "values": {"数量": 31}}], auth_editor)
        client.post(
            f"{url}/{cr1['id']}/merge",
            json={"items": [{"item_id": cr1["items"][0]["id"], "action": "apply"}]},
            headers=auth_owner,
        )
        detail = client.get(f"{url}/{cr2['id']}", headers=auth_owner).json()
        assert detail["stale"] is True

    def test_merge_twice_409(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        cr = self._create(client, ws, table, [{"op": "update", "row_id": ids[0], "values": {"数量": 12}}], auth_editor)
        url = f"{CR.format(ws=ws.id, tb=dt.id)}/{cr['id']}/merge"
        payload = {"items": [{"item_id": cr["items"][0]["id"], "action": "apply"}]}
        client.post(url, json=payload, headers=auth_owner)
        r = client.post(url, json=payload, headers=auth_owner)
        assert r.status_code == 409

    def test_viewer_merge_403(self, client, ws, table, auth_owner, auth_viewer) -> None:
        dt, ids = table
        cr = self._create(client, ws, table, [{"op": "update", "row_id": ids[0], "values": {"数量": 13}}], auth_viewer)
        r = client.post(
            f"{CR.format(ws=ws.id, tb=dt.id)}/{cr['id']}/merge",
            json={"items": [{"item_id": cr["items"][0]["id"], "action": "apply"}]},
            headers=auth_viewer,
        )
        assert r.status_code == 403

    def test_merge_create_item(self, client, ws, table, db, auth_owner, auth_editor) -> None:
        dt, _ids = table
        cr = self._create(client, ws, table, [{"op": "create", "values": {"名称": "丁", "数量": 4}}], auth_editor)
        r = client.post(
            f"{CR.format(ws=ws.id, tb=dt.id)}/{cr['id']}/merge",
            json={"items": [{"item_id": cr["items"][0]["id"], "action": "apply"}]},
            headers=auth_owner,
        )
        assert r.status_code == 200
        rows, total = rec.list_rows(db.get_bind(), dt, limit=None, db=db)
        assert total == 4
        assert any(row["名称"] == "丁" for row in rows)


class TestCloseReopen:
    def test_submitter_close_and_editor_reopen(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        url = CR.format(ws=ws.id, tb=dt.id)
        cr = client.post(
            url,
            json={"items": [{"op": "update", "row_id": ids[0], "values": {"数量": 14}}]},
            headers=auth_editor,
        ).json()
        r = client.post(f"{url}/{cr['id']}/close", headers=auth_editor)  # 提交人可关闭自己的
        assert r.status_code == 200
        assert r.json()["status"] == "closed"
        r = client.post(f"{url}/{cr['id']}/reopen", headers=auth_owner)
        assert r.status_code == 200
        assert r.json()["status"] == "open"

    def test_viewer_cannot_close_others(self, client, ws, table, auth_owner, auth_viewer) -> None:
        dt, ids = table
        url = CR.format(ws=ws.id, tb=dt.id)
        cr = client.post(
            url,
            json={"items": [{"op": "update", "row_id": ids[0], "values": {"数量": 15}}]},
            headers=auth_owner,
        ).json()
        r = client.post(f"{url}/{cr['id']}/close", headers=auth_viewer)
        assert r.status_code == 403

    def test_merged_cannot_reopen(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        url = CR.format(ws=ws.id, tb=dt.id)
        cr = client.post(
            url,
            json={"items": [{"op": "update", "row_id": ids[0], "values": {"数量": 16}}]},
            headers=auth_editor,
        ).json()
        client.post(
            f"{url}/{cr['id']}/merge",
            json={"items": [{"item_id": cr["items"][0]["id"], "action": "apply"}]},
            headers=auth_owner,
        )
        r = client.post(f"{url}/{cr['id']}/reopen", headers=auth_owner)
        assert r.status_code == 409


class TestUpdateBase:
    def test_update_base_refreshes_and_resets_stale(
        self, client, ws, table, db, auth_owner, auth_editor, auth_viewer
    ) -> None:
        dt, ids = table
        url = CR.format(ws=ws.id, tb=dt.id)
        cr = client.post(
            url,
            json={"items": [{"op": "update", "row_id": ids[0], "values": {"数量": 17}}]},
            headers=auth_viewer,
        ).json()
        # 编辑者直编造成漂移 → owner 合并另一申请使其 stale 的替代路径：
        # 直接由编辑者更新行后，详情标记冲突；update-base 刷新基准
        client.patch(REC.format(ws=ws.id, tb=dt.id) + f"/{ids[0]}", json={"values": {"数量": 5}}, headers=auth_editor)
        r = client.post(f"{url}/{cr['id']}/update-base", headers=auth_viewer)  # 仅提交人
        assert r.status_code == 200
        detail = client.get(f"{url}/{cr['id']}", headers=auth_owner).json()
        assert detail["items"][0]["base_values"]["数量"] == 5
        assert detail["items"][0]["field_conflicts"] == []
        assert detail["stale"] is False
        # values 保留
        assert detail["items"][0]["values"] == {"数量": 17}

    def test_non_submitter_403(self, client, ws, table, auth_owner, auth_editor) -> None:
        dt, ids = table
        url = CR.format(ws=ws.id, tb=dt.id)
        cr = client.post(
            url,
            json={"items": [{"op": "update", "row_id": ids[0], "values": {"数量": 18}}]},
            headers=auth_editor,
        ).json()
        r = client.post(f"{url}/{cr['id']}/update-base", headers=auth_owner)
        assert r.status_code == 403


class TestComments:
    def test_all_members_can_comment(self, client, ws, table, auth_owner, auth_viewer) -> None:
        dt, ids = table
        url = CR.format(ws=ws.id, tb=dt.id)
        cr = client.post(
            url,
            json={"items": [{"op": "update", "row_id": ids[0], "values": {"数量": 19}}]},
            headers=auth_owner,
        ).json()
        r = client.post(f"{url}/{cr['id']}/comments", json={"content": "请审核"}, headers=auth_viewer)
        assert r.status_code == 201
        detail = client.get(f"{url}/{cr['id']}", headers=auth_viewer).json()
        assert [a["action"] for a in detail["actions"]] == ["comment"]
        assert detail["actions"][0]["comment"] == "请审核"


# ── 双轨写入分派（records / bulk-delete） ──────────────


class TestDualTrackDispatch:
    def test_editor_direct_write(self, client, ws, table, db, auth_editor) -> None:
        dt, ids = table
        url = REC.format(ws=ws.id, tb=dt.id)
        r = client.patch(f"{url}/{ids[0]}", json={"values": {"数量": 50}}, headers=auth_editor)
        assert r.status_code == 200
        assert r.json()["数量"] == 50
        assert _row(db, dt, ids[0])["数量"] == 50

    def test_viewer_update_generates_request(self, client, ws, table, db, auth_viewer) -> None:
        dt, ids = table
        r = client.patch(
            f"{REC.format(ws=ws.id, tb=dt.id)}/{ids[0]}",
            json={"values": {"数量": 51}},
            headers=auth_viewer,
        )
        assert r.status_code == 202
        body = r.json()
        assert body["change_request"]["title"] == f"修改行 #{ids[0]}"
        cr_id = body["change_request"]["id"]
        detail = client.get(f"{CR.format(ws=ws.id, tb=dt.id)}/{cr_id}", headers=auth_viewer).json()
        assert detail["items"][0]["base_values"] == {"数量": 1}
        assert _row(db, dt, ids[0])["数量"] == 1  # 数据未变

    def test_viewer_create_and_delete(self, client, ws, table, db, auth_viewer) -> None:
        dt, ids = table
        url = REC.format(ws=ws.id, tb=dt.id)
        r = client.post(url, json={"values": {"名称": "戊", "数量": 5}}, headers=auth_viewer)
        assert r.status_code == 202
        assert r.json()["change_request"]["title"] == "新增行"

        r = client.delete(f"{url}/{ids[1]}", headers=auth_viewer)
        assert r.status_code == 202
        assert r.json()["change_request"]["title"] == f"删除行 #{ids[1]}"
        assert _row(db, dt, ids[1]) is not None  # 未真正删除

    def test_allow_edit_off_editor_uses_request_owner_direct(
        self, client, ws, table, db, auth_editor, auth_owner
    ) -> None:
        dt, ids = table
        ws_obj = db.get(Workspace, ws.id)
        ws_obj.allow_edit = False
        db.commit()
        url = REC.format(ws=ws.id, tb=dt.id)
        # 编辑者被切到申请轨道
        r = client.patch(f"{url}/{ids[0]}", json={"values": {"数量": 52}}, headers=auth_editor)
        assert r.status_code == 202
        assert "change_request" in r.json()
        # owner 恒直编
        r = client.patch(f"{url}/{ids[0]}", json={"values": {"数量": 53}}, headers=auth_owner)
        assert r.status_code == 200
        assert r.json()["数量"] == 53

    def test_viewer_bulk_delete_multi_items(self, client, ws, table, db, auth_viewer, auth_owner) -> None:
        dt, ids = table
        bulk_url = REC.format(ws=ws.id, tb=dt.id) + "/bulk-delete"
        r = client.post(bulk_url, json={"row_ids": [ids[0], ids[1]]}, headers=auth_viewer)
        assert r.status_code == 202
        body = r.json()
        assert body["created_items"] == 2
        cr_id = body["change_request"]["id"]
        assert body["change_request"]["title"] == "删除 2 行"
        # owner 合并 → 两行软删
        cr = client.get(f"{CR.format(ws=ws.id, tb=dt.id)}/{cr_id}", headers=auth_owner).json()
        decisions = [{"item_id": i["id"], "action": "apply"} for i in cr["items"]]
        r = client.post(
            f"{CR.format(ws=ws.id, tb=dt.id)}/{cr_id}/merge",
            json={"items": decisions},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert _row(db, dt, ids[0]) is None
        assert _row(db, dt, ids[1]) is None

    def test_owner_bulk_delete_direct(self, client, ws, table, db, auth_owner) -> None:
        dt, ids = table
        r = client.post(
            REC.format(ws=ws.id, tb=dt.id) + "/bulk-delete",
            json={"row_ids": [ids[0]]},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json() == {"deleted": 1}
