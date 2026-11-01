"""design REST API 测试：CRUD / 即时编译 / 版本 / 权限（ADR 0079 D3 / D6 / D7）."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cndb.plugins.design.models import DesignDesign, DesignDesignVersion
from cndb.plugins.workspaces.models import WorkspaceRole
from tests.pipeline_helpers import add_member, login, make_user, make_workspace

BASE = "/api/v1/workspaces/{ws}/designs"

GOOD_CONTENT = """
param width = 80

module plate(w, h, t) {
  difference {
    box(size = [w, h, t])
    translate([w / 2, h / 2, -1]) {
      cyl(d = 8, h = t + 2)
    }
  }
}

plate(width, 40, 12)
"""

BAD_CONTENT = "box(size = [1, 2, -3])"


@pytest.fixture
def owner(db):
    return make_user(db, "design_api_owner")


@pytest.fixture
def ws(db, owner):
    return make_workspace(db, owner, "DesignApiWS")


@pytest.fixture
def auth_owner(client, owner):
    return login(client, owner)


@pytest.fixture
def auth_editor(client, db, ws):
    user = make_user(db, "design_api_editor")
    add_member(db, ws, user, WorkspaceRole.EDITOR)
    return login(client, user)


@pytest.fixture
def auth_viewer(client, db, ws):
    user = make_user(db, "design_api_viewer")
    add_member(db, ws, user, WorkspaceRole.VIEWER)
    return login(client, user)


@pytest.fixture
def auth_outsider(client, db):
    return login(client, make_user(db, "design_api_outsider"))


def _url(ws, suffix: str = "") -> str:
    return f"{BASE.format(ws=ws.id)}{suffix}"


def _create(client, ws, headers, title: str = "法兰板", content: str = GOOD_CONTENT):
    return client.post(_url(ws), json={"title": title, "content": content}, headers=headers)


class TestCreate:
    def test_create_ok_compiles_and_versions(self, client, db, ws, auth_owner):
        resp = _create(client, ws, auth_owner)
        assert resp.status_code == 201
        body = resp.json()
        assert body["title"] == "法兰板"
        assert body["version_number"] == 1
        assert body["compiled"]["version"] == 2
        assert body["compiled"]["units"] == {"length": "mm", "angle": "deg"}
        assert body["compiled"]["nodes"], "顶层实例应产出几何"
        # 创建即落 v1
        design_id = body["id"]
        versions = db.scalars(select(DesignDesignVersion).where(DesignDesignVersion.design_id == design_id)).all()
        assert [v.version_number for v in versions] == [1]
        assert versions[0].content == GOOD_CONTENT
        assert versions[0].compiled == body["compiled"]

    def test_create_empty_content_ok(self, client, ws, auth_owner):
        """空程序合法（边界 #3：顶层无实例编译通过、nodes 为空）."""
        resp = _create(client, ws, auth_owner, title="空白设计", content="")
        assert resp.status_code == 201
        assert resp.json()["compiled"]["nodes"] == []

    def test_create_compile_fail_400(self, client, db, ws, auth_owner):
        resp = _create(client, ws, auth_owner, content=BAD_CONTENT)
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "design_compile_failed"
        assert "第1行" in body["detail"]
        # 库内零残留
        assert db.scalars(select(DesignDesign.id)).all() == []
        assert db.scalars(select(DesignDesignVersion.id)).all() == []

    def test_create_duplicate_title_409(self, client, ws, auth_owner):
        assert _create(client, ws, auth_owner).status_code == 201
        resp = _create(client, ws, auth_owner)
        assert resp.status_code == 409
        assert resp.json()["code"] == "design_title_conflict"

    def test_create_viewer_403(self, client, ws, auth_viewer):
        resp = _create(client, ws, auth_viewer)
        assert resp.status_code == 403
        # ADR 0047：403 文案带角色与拥有者指引
        assert "角色为【查看者】" in resp.json()["detail"]
        assert "请联系工作区拥有者" in resp.json()["detail"]

    def test_create_outsider_403(self, client, ws, auth_outsider):
        resp = _create(client, ws, auth_outsider)
        assert resp.status_code == 403
        assert "你不是该工作区成员" in resp.json()["detail"]

    def test_create_missing_title_422(self, client, ws, auth_owner):
        resp = client.post(_url(ws), json={"content": GOOD_CONTENT}, headers=auth_owner)
        assert resp.status_code == 422


class TestListAndGet:
    def test_list_and_detail(self, client, ws, auth_owner, auth_viewer):
        created = _create(client, ws, auth_owner).json()
        resp = client.get(_url(ws), headers=auth_viewer)
        assert resp.status_code == 200
        items = resp.json()
        assert [item["id"] for item in items] == [created["id"]]
        assert "content" not in items[0], "列表项不含原文"
        assert items[0]["version_count"] == 1

        detail = client.get(_url(ws, f"/{created['id']}"), headers=auth_viewer).json()
        assert detail["content"] == GOOD_CONTENT
        assert detail["compiled"] == created["compiled"]

    def test_list_filters_deleted_and_title(self, client, ws, auth_owner):
        a = _create(client, ws, auth_owner, title="支座").json()
        _create(client, ws, auth_owner, title="法兰板")
        client.delete(_url(ws, f"/{a['id']}"), headers=auth_owner)
        items = client.get(_url(ws), headers=auth_owner).json()
        assert [i["title"] for i in items] == ["法兰板"]
        hit = client.get(_url(ws), params={"q_title": "法兰"}, headers=auth_owner).json()
        assert [i["title"] for i in hit] == ["法兰板"]

    def test_get_missing_404(self, client, ws, auth_owner):
        resp = client.get(_url(ws, "/9999"), headers=auth_owner)
        assert resp.status_code == 404
        assert resp.json()["code"] == "design_not_found"

    def test_get_deleted_404(self, client, ws, auth_owner):
        created = _create(client, ws, auth_owner).json()
        client.delete(_url(ws, f"/{created['id']}"), headers=auth_owner)
        assert client.get(_url(ws, f"/{created['id']}"), headers=auth_owner).status_code == 404

    def test_member_read_outsider_denied(self, client, ws, auth_viewer, auth_outsider):
        assert client.get(_url(ws), headers=auth_viewer).status_code == 200
        resp = client.get(_url(ws), headers=auth_outsider)
        assert resp.status_code == 403


class TestUpdate:
    def test_rename_and_description(self, client, ws, auth_editor):
        created = _create(client, ws, auth_editor).json()
        resp = client.put(
            _url(ws, f"/{created['id']}"),
            json={"title": "支座", "description": "试验夹具"},
            headers=auth_editor,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "支座"
        assert body["description"] == "试验夹具"
        assert body["content"] == GOOD_CONTENT, "改名不触发重编译与内容变更"

    def test_rename_conflict_409(self, client, ws, auth_owner):
        _create(client, ws, auth_owner, title="支座")
        other = _create(client, ws, auth_owner, title="法兰板").json()
        resp = client.put(_url(ws, f"/{other['id']}"), json={"title": "支座"}, headers=auth_owner)
        assert resp.status_code == 409

    def test_update_viewer_403(self, client, ws, auth_owner, auth_viewer):
        created = _create(client, ws, auth_owner).json()
        resp = client.put(_url(ws, f"/{created['id']}"), json={"title": "x"}, headers=auth_viewer)
        assert resp.status_code == 403
        assert "角色为【查看者】" in resp.json()["detail"]


class TestSaveContent:
    def test_save_ok_appends_version(self, client, db, ws, auth_owner):
        created = _create(client, ws, auth_owner).json()
        new_content = "box(size = [10, 10, 10])"
        resp = client.put(
            _url(ws, f"/{created['id']}/content"),
            json={"content": new_content, "comment": "简化"},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["version_number"] == 2
        assert body["content"] == new_content
        assert body["compiled"]["nodes"] == [{"op": "box", "size": [10, 10, 10]}]
        versions = db.scalars(
            select(DesignDesignVersion)
            .where(DesignDesignVersion.design_id == created["id"])
            .order_by(DesignDesignVersion.version_number)
        ).all()
        assert [v.version_number for v in versions] == [1, 2]
        assert versions[1].comment == "简化"
        assert versions[1].content == new_content

    def test_save_compile_fail_keeps_old_ir(self, client, db, ws, auth_owner):
        """边界 #2：保存被拒时库内旧 compiled 不动、内容不丢."""
        created = _create(client, ws, auth_owner).json()
        old_compiled = created["compiled"]
        resp = client.put(
            _url(ws, f"/{created['id']}/content"),
            json={"content": BAD_CONTENT},
            headers=auth_owner,
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "design_compile_failed"
        design = db.get(DesignDesign, created["id"])
        assert design.content == GOOD_CONTENT
        assert design.compiled == old_compiled
        # 版本不增加
        count = len(
            db.scalars(select(DesignDesignVersion.id).where(DesignDesignVersion.design_id == created["id"])).all()
        )
        assert count == 1

    def test_save_viewer_403(self, client, ws, auth_owner, auth_viewer):
        created = _create(client, ws, auth_owner).json()
        resp = client.put(
            _url(ws, f"/{created['id']}/content"),
            json={"content": GOOD_CONTENT},
            headers=auth_viewer,
        )
        assert resp.status_code == 403


class TestDelete:
    def test_soft_delete(self, client, db, ws, auth_editor):
        created = _create(client, ws, auth_editor).json()
        resp = client.delete(_url(ws, f"/{created['id']}"), headers=auth_editor)
        assert resp.status_code == 204
        design = db.get(DesignDesign, created["id"])
        assert design is not None and design.is_deleted is True, "软删不清行"
        # 删除后同名可新建（唯一约束查全量，含软删项 → 同名仍 409）
        dup = _create(client, ws, auth_editor, title="法兰板")
        assert dup.status_code == 409

    def test_delete_viewer_403(self, client, ws, auth_owner, auth_viewer):
        created = _create(client, ws, auth_owner).json()
        resp = client.delete(_url(ws, f"/{created['id']}"), headers=auth_viewer)
        assert resp.status_code == 403


class TestPreview:
    def test_preview_ok_no_side_effect(self, client, db, ws, auth_viewer):
        """preview 无写副作用（viewer 可用：编辑器只读态也要渲染）."""
        resp = client.post(
            _url(ws, "/preview"),
            json={"content": GOOD_CONTENT},
            headers=auth_viewer,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["diagnostics"] == []
        assert body["ir"]["nodes"]
        # 库内无新行
        assert db.scalars(select(DesignDesign.id)).all() == []
        assert db.scalars(select(DesignDesignVersion.id)).all() == []

    def test_preview_diagnostics_structured(self, client, ws, auth_owner):
        resp = client.post(
            _url(ws, "/preview"),
            json={"content": BAD_CONTENT},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["ir"] is None
        assert body["diagnostics"][0]["line"] == 1
        assert body["diagnostics"][0]["severity"] == "error"
        assert "正数" in body["diagnostics"][0]["message"]

    def test_preview_overrides_recompile(self, client, ws, auth_owner):
        content = "param w = 10\nbox(size = [w, 2, 3])"
        resp = client.post(
            _url(ws, "/preview"),
            json={"content": content, "overrides": {"w": 50}},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["ir"]["nodes"] == [{"op": "box", "size": [50, 2, 3]}]
        assert body["ir"]["params"] == [{"name": "w", "value": 50}]

    def test_preview_unknown_override(self, client, ws, auth_owner):
        resp = client.post(
            _url(ws, "/preview"),
            json={"content": "box(size = [1, 1, 1])", "overrides": {"nope": 1}},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "nope" in body["diagnostics"][0]["message"]

    def test_preview_route_not_shadowed(self, client, ws, auth_owner):
        """``/preview`` 声明在动态 ``/{design_id}`` 之前（pipeline /checks 同型守卫）."""
        resp = client.post(_url(ws, "/preview"), json={"content": ""}, headers=auth_owner)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_preview_outsider_403(self, client, ws, auth_outsider):
        resp = client.post(_url(ws, "/preview"), json={"content": ""}, headers=auth_outsider)
        assert resp.status_code == 403


class TestVersions:
    def test_version_list_desc(self, client, ws, auth_owner, auth_viewer):
        created = _create(client, ws, auth_owner).json()
        client.put(
            _url(ws, f"/{created['id']}/content"),
            json={"content": "box(size = [1, 1, 1])", "comment": "v2"},
            headers=auth_owner,
        )
        resp = client.get(_url(ws, f"/{created['id']}/versions"), headers=auth_viewer)
        assert resp.status_code == 200
        items = resp.json()
        assert [i["version_number"] for i in items] == [2, 1]
        assert items[0]["comment"] == "v2"
        assert "content" not in items[0], "版本列表不含原文（回看端点属 P2）"

    def test_versions_of_missing_404(self, client, ws, auth_owner):
        assert client.get(_url(ws, "/9999/versions"), headers=auth_owner).status_code == 404

    @staticmethod
    def _make_two_versions(client, ws, headers) -> dict:
        """建一个两版本的设计（v1 = GOOD_CONTENT，v2 = 简化单盒），返回 v1 详情."""
        created = _create(client, ws, headers).json()
        client.put(
            _url(ws, f"/{created['id']}/content"),
            json={"content": "box(size = [1, 1, 1])", "comment": "简化"},
            headers=headers,
        )
        return created

    def test_get_version_detail(self, client, ws, auth_owner, auth_viewer):
        """回看（P2）：单版本端点返回该版原文与 IR 快照，成员可读."""
        created = self._make_two_versions(client, ws, auth_owner)
        resp = client.get(_url(ws, f"/{created['id']}/versions/1"), headers=auth_viewer)
        assert resp.status_code == 200
        body = resp.json()
        assert body["version_number"] == 1
        assert body["content"] == GOOD_CONTENT
        assert body["compiled"]["nodes"], "v1 的 IR 快照随版本保留"

    def test_get_version_missing_404(self, client, ws, auth_owner):
        created = _create(client, ws, auth_owner).json()
        resp = client.get(_url(ws, f"/{created['id']}/versions/99"), headers=auth_owner)
        assert resp.status_code == 404
        assert resp.json()["code"] == "design_version_not_found"

    def test_restore_version_recompiles_as_new(self, client, db, ws, auth_editor):
        """恢复（P2）：以 v1 原文重编译落 v3，历史版本不受影响."""
        created = self._make_two_versions(client, ws, auth_editor)
        resp = client.post(_url(ws, f"/{created['id']}/versions/1/restore"), headers=auth_editor)
        assert resp.status_code == 200
        body = resp.json()
        assert body["version_number"] == 3
        assert body["content"] == GOOD_CONTENT
        assert body["compiled"] == created["compiled"], "同原文重编译应产出同 IR（I3）"
        design = db.get(DesignDesign, created["id"])
        assert design.content == GOOD_CONTENT
        versions = db.scalars(
            select(DesignDesignVersion)
            .where(DesignDesignVersion.design_id == created["id"])
            .order_by(DesignDesignVersion.version_number)
        ).all()
        assert [v.version_number for v in versions] == [1, 2, 3]
        assert versions[2].comment == "恢复自 v1"
        assert versions[1].content == "box(size = [1, 1, 1])", "历史 v2 不受恢复影响"

    def test_restore_viewer_403(self, client, ws, auth_owner, auth_viewer):
        created = self._make_two_versions(client, ws, auth_owner)
        resp = client.post(_url(ws, f"/{created['id']}/versions/1/restore"), headers=auth_viewer)
        assert resp.status_code == 403
        assert "角色为【查看者】" in resp.json()["detail"]

    def test_restore_missing_version_404(self, client, ws, auth_owner):
        created = _create(client, ws, auth_owner).json()
        resp = client.post(_url(ws, f"/{created['id']}/versions/99/restore"), headers=auth_owner)
        assert resp.status_code == 404
        assert resp.json()["code"] == "design_version_not_found"


class TestOutline:
    """装配大纲端点（ADR 0083 D4 / D5）：快照优先 + 历史快照只读派生."""

    @staticmethod
    def _outline_url(ws, design_id: int) -> str:
        return _url(ws, f"/{design_id}/outline")

    def test_outline_from_compiled_snapshot(self, client, ws, auth_owner):
        created = _create(client, ws, auth_owner).json()
        resp = client.get(self._outline_url(ws, created["id"]), headers=auth_owner)
        assert resp.status_code == 200
        body = resp.json()
        assert body["design_id"] == created["id"]
        assert body["version_number"] == 1
        assert body["source"] == "compiled"
        (assembly,) = body["outline"]["children"]
        assert assembly["kind"] == "assembly"
        assert assembly["name"] == "plate"
        (group,) = assembly["children"]
        assert group["kind"] == "group"
        assert group["op"] == "difference"
        assert [part["primitive"] for part in group["children"]] == ["box", "cyl"]
        assert all(part["line"] >= 1 and part["col"] >= 1 for part in group["children"])

    def test_outline_viewer_readable(self, client, ws, auth_owner, auth_viewer):
        created = _create(client, ws, auth_owner).json()
        resp = client.get(self._outline_url(ws, created["id"]), headers=auth_viewer)
        assert resp.status_code == 200

    def test_outline_outsider_403(self, client, ws, auth_owner, auth_outsider):
        created = _create(client, ws, auth_owner).json()
        resp = client.get(self._outline_url(ws, created["id"]), headers=auth_outsider)
        assert resp.status_code == 403

    def test_outline_missing_404(self, client, ws, auth_owner):
        resp = client.get(self._outline_url(ws, 999), headers=auth_owner)
        assert resp.status_code == 404
        assert resp.json()["code"] == "design_not_found"

    def test_outline_legacy_snapshot_derived_without_writing(self, client, db, ws, auth_owner):
        """IR v1 快照无 outline：按原文即时编译派生（source=content），库内快照不动（D5）."""
        created = _create(client, ws, auth_owner).json()
        design = db.scalar(select(DesignDesign).where(DesignDesign.id == created["id"]))
        design.compiled = {"version": 1, "units": {"length": "mm", "angle": "deg"}, "params": [], "nodes": []}
        db.commit()

        resp = client.get(self._outline_url(ws, created["id"]), headers=auth_owner)
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "content"
        assert body["outline"]["children"][0]["kind"] == "assembly"

        db.refresh(design)
        assert "outline" not in design.compiled, "只读派生不落库"

    def test_outline_empty_design(self, client, ws, auth_owner):
        created = _create(client, ws, auth_owner, title="空白设计", content="").json()
        body = client.get(self._outline_url(ws, created["id"]), headers=auth_owner).json()
        assert body["outline"] == {"children": []}
