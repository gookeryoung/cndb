"""design REST API 测试：CRUD / 即时编译 / 版本 / 权限（ADR 0079 D3 / D6 / D7）."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cndb.plugins.design.models import DesignDesign, DesignDesignDraft, DesignDesignVersion
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


def _create(client, ws, headers, title: str = "法兰板", content: str = GOOD_CONTENT, **extra):
    return client.post(_url(ws), json={"title": title, "content": content, **extra}, headers=headers)


def _ir(client, ws, design_id: int, headers) -> dict:
    """取 ``GET /{id}/ir`` 快照（详情不再携带 compiled，ADR 0086 D10）."""
    resp = client.get(_url(ws, f"/{design_id}/ir"), headers=headers)
    assert resp.status_code == 200
    return resp.json()


class TestCreate:
    def test_create_ok_compiles_and_versions(self, client, db, ws, auth_owner):
        resp = _create(client, ws, auth_owner)
        assert resp.status_code == 201
        body = resp.json()
        assert body["title"] == "法兰板"
        assert body["version_number"] == 1
        assert body["kind"] == "assembly"
        assert body["file_key"] == "法兰板"
        assert "compiled" not in body, "详情移除 compiled（ADR 0086 D10）"
        ir = _ir(client, ws, body["id"], auth_owner)
        assert ir["ir"]["version"] == 6
        assert ir["ir"]["units"] == {"length": "mm", "angle": "deg"}
        assert ir["ir"]["nodes"], "顶层实例应产出几何"
        assert ir["content_hash"], "详情带 content_hash（与 /ir ETag 同源）"
        # 创建即落 v1
        design_id = body["id"]
        versions = db.scalars(select(DesignDesignVersion).where(DesignDesignVersion.design_id == design_id)).all()
        assert [v.version_number for v in versions] == [1]
        assert versions[0].content == GOOD_CONTENT
        assert versions[0].compiled == ir["ir"]

    def test_create_empty_content_ok(self, client, ws, auth_owner):
        """空程序合法（边界 #3：顶层无实例编译通过、nodes 为空）."""
        resp = _create(client, ws, auth_owner, title="空白设计", content="")
        assert resp.status_code == 201
        assert _ir(client, ws, resp.json()["id"], auth_owner)["ir"]["nodes"] == []

    def test_create_part_kind(self, client, ws, auth_owner):
        """part 文件：kind 落库、file_key 可指定；part 允许无 system 的普通几何."""
        resp = _create(
            client, ws, auth_owner, title="垫圈", content="cyl(d = 10, h = 2)", kind="part", file_key="washer"
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["kind"] == "part"
        assert body["file_key"] == "washer"
        assert body["folder"] == ""

    def test_create_part_system_rejected(self, client, ws, auth_owner):
        """part 文件禁止 system（D3）：400 编译失败."""
        resp = _create(client, ws, auth_owner, title="零件", content="system s {\n  box(w=1,h=1,d=1)\n}\n", kind="part")
        assert resp.status_code == 400
        assert resp.json()["code"] == "design_compile_failed"

    def test_create_folder(self, client, ws, auth_owner):
        resp = _create(client, ws, auth_owner, title="垫圈", content="cyl(d=10, h=2)", folder="parts/底盘")
        assert resp.status_code == 201
        assert resp.json()["folder"] == "parts/底盘"

    @pytest.mark.parametrize("bad", ["/abs", "a/../b", "a\\b", "a//b"])
    def test_create_folder_invalid_400(self, client, ws, auth_owner, bad):
        resp = _create(client, ws, auth_owner, title="目录", content="", folder=bad)
        assert resp.status_code == 400
        assert resp.json()["code"] == "design_folder_invalid"

    def test_create_file_key_conflict_deduped(self, client, ws, auth_owner):
        """file_key 工作区唯一：指定冲突 key 时自动加后缀."""
        first = _create(client, ws, auth_owner, title="垫圈", content="cyl(d=10,h=2)", file_key="washer").json()
        second = _create(client, ws, auth_owner, title="垫圈2", content="cyl(d=12,h=2)", file_key="washer").json()
        assert first["file_key"] == "washer"
        assert second["file_key"] == "washer-2"

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
        assert "compiled" not in detail
        assert detail["file_key"] == created["file_key"]
        assert detail["content_hash"]

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
        assert _ir(client, ws, created["id"], auth_owner)["ir"]["nodes"] == [{"op": "box", "size": [10, 10, 10]}]
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
        old_compiled = _ir(client, ws, created["id"], auth_owner)["ir"]
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

    @staticmethod
    def _versions(db, design_id: int) -> list[DesignDesignVersion]:
        return list(
            db.scalars(
                select(DesignDesignVersion)
                .where(DesignDesignVersion.design_id == design_id)
                .order_by(DesignDesignVersion.version_number)
            ).all()
        )

    def test_save_defaults_manual_change_type(self, client, db, ws, auth_owner):
        """保存缺省 change_type=manual；创建即 v1 也是 manual（C1 / ADR 0113 §2）."""
        created = _create(client, ws, auth_owner).json()
        resp = client.put(
            _url(ws, f"/{created['id']}/content"),
            json={"content": "box(size = [2, 2, 2])"},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        assert [v.change_type for v in self._versions(db, created["id"])] == ["manual", "manual"]

    def test_draft_save_creates_no_version(self, client, db, ws, auth_owner):
        """3s 自动保存等价路径（PUT /draft）不落版本（ADR 0125 C1）."""
        created = _create(client, ws, auth_owner).json()
        resp = client.put(
            _url(ws, f"/{created['id']}/draft"),
            json={"content": "box(size = [3, 3, 3])"},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        assert resp.json()["content"] == "box(size = [3, 3, 3])"
        assert [v.version_number for v in self._versions(db, created["id"])] == [1]

    def test_draft_same_content_no_draft(self, client, db, ws, auth_owner):
        """草稿内容与最新版一致：视为无修改，删除草稿且不落版（ADR 0125 C2）."""
        created = _create(client, ws, auth_owner).json()
        resp = client.put(
            _url(ws, f"/{created['id']}/draft"),
            json={"content": GOOD_CONTENT},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        assert resp.json() is None
        assert [v.version_number for v in self._versions(db, created["id"])] == [1]
        assert db.execute(select(DesignDesignDraft)).scalars().all() == []

    def test_manual_promotes_latest_auto(self, client, db, ws, auth_owner, monkeypatch: pytest.MonkeyPatch):
        """检查点落 auto 后，主动保存同内容：提升为 manual，不新增版本（ADR 0113 D7）."""
        monkeypatch.setattr("cndb.plugins.design.services.drafts.DESIGN_CHECKPOINT_INTERVAL_SECONDS", 0)
        created = _create(client, ws, auth_owner).json()
        auto_content = "box(size = [4, 4, 4])"
        drafted = client.put(
            _url(ws, f"/{created['id']}/draft"),
            json={"content": auto_content},
            headers=auth_owner,
        )
        assert drafted.status_code == 200
        assert drafted.json() is None, "检查点已把草稿落版"
        versions = self._versions(db, created["id"])
        assert [v.version_number for v in versions] == [1, 2]
        assert versions[1].change_type == "auto"

        resp = client.put(
            _url(ws, f"/{created['id']}/content"),
            json={"content": auto_content, "comment": "里程碑"},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        assert resp.json()["version_number"] == 2
        versions = self._versions(db, created["id"])
        assert [v.version_number for v in versions] == [1, 2]
        assert versions[1].change_type == "manual"
        assert versions[1].comment == "里程碑"

    def test_manual_same_content_manual_no_new_version(self, client, db, ws, auth_owner):
        created = _create(client, ws, auth_owner).json()
        resp = client.put(
            _url(ws, f"/{created['id']}/content"),
            json={"content": GOOD_CONTENT},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        assert resp.json()["version_number"] == 1
        assert [v.version_number for v in self._versions(db, created["id"])] == [1]

    def test_change_type_rejected(self, client, ws, auth_owner):
        """保存请求不再接受 change_type：自动保存必须走 /draft（ADR 0125 D4）."""
        created = _create(client, ws, auth_owner).json()
        for value in ("auto", "rollback"):
            resp = client.put(
                _url(ws, f"/{created['id']}/content"),
                json={"content": "box(size = [5, 5, 5])", "change_type": value},
                headers=auth_owner,
            )
            assert resp.status_code == 422


class TestDraft:
    """个人草稿端点（ADR 0125 C1/C2/C5/C6 / D6）."""

    def test_get_empty(self, client, ws, auth_owner):
        created = _create(client, ws, auth_owner).json()
        resp = client.get(_url(ws, f"/{created['id']}/draft"), headers=auth_owner)
        assert resp.status_code == 200
        assert resp.json() is None

    def test_put_get_roundtrip(self, client, ws, auth_owner):
        created = _create(client, ws, auth_owner).json()
        saved = client.put(
            _url(ws, f"/{created['id']}/draft"),
            json={"content": "box(size = [6, 6, 6])", "base_version_number": 1},
            headers=auth_owner,
        )
        assert saved.status_code == 200
        body = saved.json()
        assert body["base_version_number"] == 1
        assert body["current_version_number"] == 1
        assert body["stale"] is False
        got = client.get(_url(ws, f"/{created['id']}/draft"), headers=auth_owner).json()
        assert got["content"] == body["content"]

    def test_viewer_cannot_write(self, client, ws, auth_owner, auth_viewer):
        created = _create(client, ws, auth_owner).json()
        resp = client.put(
            _url(ws, f"/{created['id']}/draft"),
            json={"content": "box(size = [7, 7, 7])"},
            headers=auth_viewer,
        )
        assert resp.status_code == 403
        assert client.get(_url(ws, f"/{created['id']}/draft"), headers=auth_viewer).json() is None

    def test_discard_idempotent(self, client, ws, auth_owner):
        created = _create(client, ws, auth_owner).json()
        client.put(
            _url(ws, f"/{created['id']}/draft"),
            json={"content": "box(size = [8, 8, 8])"},
            headers=auth_owner,
        )
        assert client.delete(_url(ws, f"/{created['id']}/draft"), headers=auth_owner).status_code == 204
        assert client.delete(_url(ws, f"/{created['id']}/draft"), headers=auth_owner).status_code == 204
        assert client.get(_url(ws, f"/{created['id']}/draft"), headers=auth_owner).json() is None

    def test_invalid_base_version(self, client, ws, auth_owner):
        created = _create(client, ws, auth_owner).json()
        resp = client.put(
            _url(ws, f"/{created['id']}/draft"),
            json={"content": "box(size = [8, 8, 8])", "base_version_number": 99},
            headers=auth_owner,
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "design_draft_base_invalid"

    def test_checkpoint_compile_failure_keeps_draft(self, client, db, ws, auth_owner, monkeypatch: pytest.MonkeyPatch):
        """到期检查点编译失败：不落版、不改正式内容、草稿保留（ADR 0125 I5）."""
        monkeypatch.setattr("cndb.plugins.design.services.drafts.DESIGN_CHECKPOINT_INTERVAL_SECONDS", 0)
        created = _create(client, ws, auth_owner).json()
        resp = client.put(
            _url(ws, f"/{created['id']}/draft"),
            json={"content": BAD_CONTENT},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        assert resp.json()["content"] == BAD_CONTENT
        versions = self._versions(db, created["id"])
        assert [v.version_number for v in versions] == [1]
        assert db.get(DesignDesign, created["id"]).content != BAD_CONTENT

    def test_manual_save_deletes_own_draft(self, client, db, ws, auth_owner):
        created = _create(client, ws, auth_owner).json()
        draft_content = "box(size = [2, 6, 6])"
        client.put(
            _url(ws, f"/{created['id']}/draft"),
            json={"content": draft_content},
            headers=auth_owner,
        )
        resp = client.put(
            _url(ws, f"/{created['id']}/content"),
            json={"content": draft_content},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        assert client.get(_url(ws, f"/{created['id']}/draft"), headers=auth_owner).json() is None
        assert [v.version_number for v in self._versions(db, created["id"])] == [1, 2]

    def test_refresh_clears_all_drafts(self, client, db, ws, auth_editor, auth_owner):
        created = _create(client, ws, auth_editor).json()
        for auth in (auth_editor, auth_owner):
            client.put(
                _url(ws, f"/{created['id']}/draft"),
                json={"content": "box(size = [3, 5, 5])"},
                headers=auth,
            )
        assert len(db.execute(select(DesignDesignDraft)).scalars().all()) == 2
        assert client.post(_url(ws, f"/{created['id']}/refresh"), json={}, headers=auth_editor).status_code == 200
        assert db.execute(select(DesignDesignDraft)).scalars().all() == []

    @staticmethod
    def _versions(db, design_id):
        return db.scalars(
            select(DesignDesignVersion)
            .where(DesignDesignVersion.design_id == design_id)
            .order_by(DesignDesignVersion.version_number)
        ).all()


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
        v1_ir = client.get(_url(ws, f"/{created['id']}/versions/1"), headers=auth_editor).json()["compiled"]
        resp = client.post(_url(ws, f"/{created['id']}/versions/1/restore"), headers=auth_editor)
        assert resp.status_code == 200
        body = resp.json()
        assert body["version_number"] == 3
        assert body["content"] == GOOD_CONTENT
        assert _ir(client, ws, created["id"], auth_editor)["ir"] == v1_ir, "同原文重编译应产出同 IR（I3）"
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

    def test_versions_expose_change_type(self, client, ws, auth_owner, auth_viewer, monkeypatch: pytest.MonkeyPatch):
        """列表 / 详情返回 change_type；auto 仅由检查点产生（ADR 0125 D4）."""
        monkeypatch.setattr("cndb.plugins.design.services.drafts.DESIGN_CHECKPOINT_INTERVAL_SECONDS", 0)
        created = self._make_two_versions(client, ws, auth_owner)
        checkpoint = client.put(
            _url(ws, f"/{created['id']}/draft"),
            json={"content": "box(size = [9, 9, 9])"},
            headers=auth_owner,
        )
        assert checkpoint.status_code == 200
        items = client.get(_url(ws, f"/{created['id']}/versions"), headers=auth_viewer).json()
        assert [i["version_number"] for i in items] == [3, 2, 1]
        assert [i["change_type"] for i in items] == ["auto", "manual", "manual"]
        detail = client.get(_url(ws, f"/{created['id']}/versions/3"), headers=auth_viewer).json()
        assert detail["change_type"] == "auto"

    def test_refresh_and_restore_change_types(self, client, db, ws, auth_editor):
        """refresh / rollback 由服务端强制赋值（I4）."""
        created = self._make_two_versions(client, ws, auth_editor)
        refreshed = client.post(_url(ws, f"/{created['id']}/refresh"), json={}, headers=auth_editor)
        assert refreshed.status_code == 200
        assert refreshed.json()["version_number"] == 3
        restored = client.post(_url(ws, f"/{created['id']}/versions/1/restore"), headers=auth_editor)
        assert restored.status_code == 200
        assert restored.json()["version_number"] == 4
        versions = db.scalars(
            select(DesignDesignVersion)
            .where(DesignDesignVersion.design_id == created["id"])
            .order_by(DesignDesignVersion.version_number)
        ).all()
        assert [v.change_type for v in versions] == ["manual", "manual", "refresh", "rollback"]


class TestVersionDiff:
    def test_diff_text_and_structure_summary(self, client, ws, auth_owner, auth_viewer):
        """两版本对比：文本 diff + 参数 / 节点结构摘要，viewer 可读（C5 / C7）."""
        created = _create(client, ws, auth_owner).json()
        client.put(
            _url(ws, f"/{created['id']}/content"),
            json={"content": GOOD_CONTENT.replace("width = 80", "width = 100")},
            headers=auth_owner,
        )
        resp = client.get(
            _url(ws, f"/{created['id']}/diff"),
            params={"base": 1, "head": 2},
            headers=auth_viewer,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["base_version"] == 1 and body["head_version"] == 2
        assert "-param width = 80" in body["diff"]
        assert "+param width = 100" in body["diff"]
        assert body["added"] >= 1 and body["removed"] >= 1
        summary = body["summary"]
        assert summary["available"] is True
        assert summary["params"]["changed"] == [{"name": "width", "base": 80, "head": 100}]
        assert summary["nodes"]["base"] == summary["nodes"]["head"]

    def test_diff_same_version_empty(self, client, ws, auth_owner):
        created = _create(client, ws, auth_owner).json()
        resp = client.get(_url(ws, f"/{created['id']}/diff"), params={"base": 1, "head": 1}, headers=auth_owner)
        assert resp.status_code == 200
        body = resp.json()
        assert body["diff"] == "" and body["added"] == 0 and body["removed"] == 0
        assert body["summary"]["available"] is True

    def test_diff_missing_version_404(self, client, ws, auth_owner):
        created = _create(client, ws, auth_owner).json()
        resp = client.get(_url(ws, f"/{created['id']}/diff"), params={"base": 1, "head": 99}, headers=auth_owner)
        assert resp.status_code == 404
        assert resp.json()["code"] == "design_version_not_found"

    def test_diff_outsider_403(self, client, ws, auth_owner, auth_outsider):
        created = _create(client, ws, auth_owner).json()
        resp = client.get(_url(ws, f"/{created['id']}/diff"), params={"base": 1, "head": 1}, headers=auth_outsider)
        assert resp.status_code == 403


class TestStructureSummary:
    """结构摘要判定层单测（ADR 0113 §2 / D8）."""

    def test_unavailable_when_snapshot_missing(self):
        from cndb.plugins.design.services.diff import structure_summary

        assert structure_summary(None, {"nodes": []})["available"] is False
        assert structure_summary({"nodes": []}, {})["available"] is False

    def test_params_nodes_and_assemblies_diff(self):
        from cndb.plugins.design.services.diff import structure_summary

        base = {
            "nodes": [{}, {}],
            "params": [{"name": "a", "value": 1}, {"name": "gone", "value": 2}],
            "outline": {"children": [{"kind": "system", "name": "旧系统"}, {"kind": "part"}]},
        }
        head = {
            "nodes": [{}],
            "params": [{"name": "a", "value": 5}, {"name": "fresh", "value": 3}],
            "outline": {"children": [{"kind": "assembly", "name": "新装配"}]},
        }
        summary = structure_summary(base, head)
        assert summary["available"] is True
        assert summary["nodes"] == {"base": 2, "head": 1}
        assert summary["params"]["added"] == ["fresh"]
        assert summary["params"]["removed"] == ["gone"]
        assert summary["params"]["changed"] == [{"name": "a", "base": 1, "head": 5}]
        assert summary["assemblies"] == {"added": ["新装配"], "removed": ["旧系统"]}


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
        # IR v5：大纲节点下标落在顶层 nodes 范围内（ADR 0103 D7）
        nodes = client.get(_url(ws, f"/{created['id']}/ir"), headers=auth_owner).json()["ir"]["nodes"]
        assert assembly["node_index"] == 0
        assert group["node_index"] == 0
        assert all(0 <= part["node_index"] < len(nodes) for part in group["children"])

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

    def test_outline_v4_snapshot_without_node_index(self, client, db, ws, auth_owner):
        """IR v4 旧快照无 node_index：大纲端点照常 200，字段缺省（ADR 0103 I2）."""
        created = _create(client, ws, auth_owner).json()
        design = db.scalar(select(DesignDesign).where(DesignDesign.id == created["id"]))
        design.compiled = {
            "version": 4,
            "units": {"length": "mm", "angle": "deg"},
            "params": [],
            "nodes": [{"op": "box", "size": [1, 1, 1]}],
            "outline": {"children": [{"kind": "part", "primitive": "box", "line": 1, "col": 1}]},
        }
        db.commit()

        body = client.get(self._outline_url(ws, created["id"]), headers=auth_owner).json()
        assert body["source"] == "compiled"
        assert "node_index" not in body["outline"]["children"][0]

    def test_outline_empty_design(self, client, ws, auth_owner):
        created = _create(client, ws, auth_owner, title="空白设计", content="").json()
        body = client.get(self._outline_url(ws, created["id"]), headers=auth_owner).json()
        assert body["outline"] == {"children": []}

    def test_outline_system_level_from_snapshot(self, client, ws, auth_owner):
        """ADR 0084：system 声明产出系统级大纲节点（source=compiled 快照）."""
        content = "module wheel() {\n  cyl(d=10, h=4)\n}\nsystem rover {\n  wheel()\n  box(w=1, h=1, d=1)\n}\n"
        created = _create(client, ws, auth_owner, title="小车", content=content).json()
        body = client.get(self._outline_url(ws, created["id"]), headers=auth_owner).json()
        assert body["source"] == "compiled"
        (system,) = body["outline"]["children"]
        assert system["kind"] == "system"
        assert system["name"] == "rover"
        assert [child["kind"] for child in system["children"]] == ["assembly", "part"]

    def test_outline_v2_snapshot_derives_system_from_content(self, client, db, ws, auth_owner):
        """IR v2 快照（无 system 语义）可按原文派生系统级大纲，且不落库（I5 / D7）."""
        content = "system s {\n  box(w=1, h=1, d=1)\n}\n"
        created = _create(client, ws, auth_owner, title="系统快照", content=content).json()
        design = db.scalar(select(DesignDesign).where(DesignDesign.id == created["id"]))
        design.compiled = {
            "version": 2,
            "units": {"length": "mm", "angle": "deg"},
            "params": [],
            "nodes": [],
            "outline": {"children": []},
        }
        db.commit()

        body = client.get(self._outline_url(ws, created["id"]), headers=auth_owner).json()
        assert body["source"] == "compiled", "v2 快照自带 outline，端点仍按快照返回"
        assert body["outline"]["children"] == []

        design.compiled = {"version": 2, "units": {"length": "mm", "angle": "deg"}, "params": [], "nodes": []}
        db.commit()
        derived = client.get(self._outline_url(ws, created["id"]), headers=auth_owner).json()
        assert derived["source"] == "content"
        assert derived["outline"]["children"][0]["kind"] == "system"
        db.refresh(design)
        assert "outline" not in design.compiled, "只读派生不落库"


PART_CONTENT = "param dw = 10\nparam wh = 2\ncyl(d = dw, h = wh)"

ASSEMBLY_CONTENT = 'use "washer"(dw = 12, wh = 3) as w1\ntranslate([50, 0, 0]) use "washer"() as w2\n'


class TestFileLibrary:
    """设计文件库 P1（ADR 0086 §4）：/ir ETag / 引用 / stale / 删除阻断 / refresh / 快照恢复."""

    def _part(self, client, ws, headers, key: str = "washer") -> dict:
        return _create(client, ws, headers, title="垫圈", content=PART_CONTENT, kind="part", file_key=key).json()

    def _assembly(self, client, ws, headers) -> dict:
        return _create(client, ws, headers, title="底盘", content=ASSEMBLY_CONTENT).json()

    def test_ir_etag_and_304(self, client, ws, auth_owner):
        created = _create(client, ws, auth_owner).json()
        first = client.get(_url(ws, f"/{created['id']}/ir"), headers=auth_owner)
        etag = first.headers["ETag"]
        assert etag.strip('"')
        body = first.json()
        assert body["design_id"] == created["id"]
        assert body["version_number"] == 1
        assert body["ir"]["version"] == 6
        again = client.get(_url(ws, f"/{created['id']}/ir"), headers={**auth_owner, "If-None-Match": etag})
        assert again.status_code == 304
        # 保存后 ETag 变化
        client.put(_url(ws, f"/{created['id']}/content"), json={"content": "box(size = [1, 1, 1])"}, headers=auth_owner)
        fresh = client.get(_url(ws, f"/{created['id']}/ir"), headers={**auth_owner, "If-None-Match": etag})
        assert fresh.status_code == 200
        assert fresh.headers["ETag"] != etag

    def test_preview_with_design_id_resolves_use(self, client, ws, auth_owner):
        """preview 带 design_id：use 引用按工作区 resolver 解析（ADR 0086 §4）."""
        self._part(client, ws, auth_owner)
        assembly = self._assembly(client, ws, auth_owner)
        resp = client.post(
            _url(ws, "/preview"),
            json={"content": ASSEMBLY_CONTENT, "design_id": assembly["id"]},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert len(body["ir"]["nodes"]) == 2, "两个 washer 实例独立展开"

    def test_preview_without_design_id_rejects_use(self, client, ws, auth_owner):
        resp = client.post(_url(ws, "/preview"), json={"content": ASSEMBLY_CONTENT}, headers=auth_owner)
        assert resp.status_code == 200
        assert resp.json()["ok"] is False

    def test_save_content_syncs_refs_and_marks_referrers_stale(self, client, db, ws, auth_owner):
        part = self._part(client, ws, auth_owner)
        assembly = self._assembly(client, ws, auth_owner)
        from cndb.plugins.design.models import DesignDesignref

        refs = db.scalars(select(DesignDesignref).where(DesignDesignref.design_id == assembly["id"])).all()
        assert [r.target_design_id for r in refs] == [part["id"]]

        detail = client.get(_url(ws, f"/{assembly['id']}"), headers=auth_owner).json()
        assert detail["dependencies_stale"] is False
        # 零件保存 → 引用方置 stale（D6）
        client.put(
            _url(ws, f"/{part['id']}/content"),
            json={"content": PART_CONTENT.replace("dw = 10", "dw = 14")},
            headers=auth_owner,
        )
        detail = client.get(_url(ws, f"/{assembly['id']}"), headers=auth_owner).json()
        assert detail["dependencies_stale"] is True
        # 装配 refresh：以最新依赖重编译落新版本并清 stale
        resp = client.post(_url(ws, f"/{assembly['id']}/refresh"), json={}, headers=auth_owner)
        assert resp.status_code == 200
        assert resp.json()["version_number"] == 2
        detail = client.get(_url(ws, f"/{assembly['id']}"), headers=auth_owner).json()
        assert detail["dependencies_stale"] is False
        version = db.scalars(
            select(DesignDesignVersion)
            .where(DesignDesignVersion.design_id == assembly["id"])
            .order_by(DesignDesignVersion.version_number.desc())
        ).first()
        assert version is not None and version.comment == "依赖更新"
        assert version.dependencies and version.dependencies[0]["file_key"] == "washer"

    def test_dependencies_endpoint(self, client, ws, auth_owner):
        part = self._part(client, ws, auth_owner)
        assembly = self._assembly(client, ws, auth_owner)
        body = client.get(_url(ws, f"/{assembly['id']}/dependencies"), headers=auth_owner).json()
        assert [item["file_key"] for item in body["items"]] == ["washer"]
        assert body["items"][0]["title"] == "垫圈"
        assert body["referrers"] == []
        reverse = client.get(_url(ws, f"/{part['id']}/dependencies"), headers=auth_owner).json()
        assert [item["file_key"] for item in reverse["referrers"]] == [assembly["file_key"]]

    def test_delete_referenced_409_then_allowed(self, client, ws, auth_owner):
        part = self._part(client, ws, auth_owner)
        assembly = self._assembly(client, ws, auth_owner)
        resp = client.delete(_url(ws, f"/{part['id']}"), headers=auth_owner)
        assert resp.status_code == 409
        assert resp.json()["code"] == "design_file_referenced"
        assert "底盘" in resp.json()["detail"]
        # 引用方软删后可删目标（D3 §5）
        client.delete(_url(ws, f"/{assembly['id']}"), headers=auth_owner)
        assert client.delete(_url(ws, f"/{part['id']}"), headers=auth_owner).status_code == 204

    def test_rename_and_move_do_not_break_refs(self, client, ws, auth_owner):
        """file_key 不可变：改名 / 移动目录后引用不断链（D2）."""
        part = self._part(client, ws, auth_owner)
        assembly = self._assembly(client, ws, auth_owner)
        resp = client.put(
            _url(ws, f"/{part['id']}"),
            json={"title": "新垫圈", "folder": "parts/标准件"},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        assert resp.json()["file_key"] == "washer"
        detail = client.get(_url(ws, f"/{assembly['id']}"), headers=auth_owner).json()
        assert detail["dependencies_stale"] is False
        body = client.get(_url(ws, f"/{assembly['id']}/dependencies"), headers=auth_owner).json()
        assert body["items"][0]["design_id"] == part["id"]

    def test_list_kind_folder_filters(self, client, ws, auth_owner):
        self._part(client, ws, auth_owner)
        _create(client, ws, auth_owner, title="支架", content="box(size=[1,1,1])", folder="parts")
        parts = client.get(_url(ws), params={"kind": "part"}, headers=auth_owner).json()
        assert [item["title"] for item in parts] == ["垫圈"]
        foldered = client.get(_url(ws), params={"folder": "parts"}, headers=auth_owner).json()
        assert [item["title"] for item in foldered] == ["支架"]
        items = client.get(_url(ws), headers=auth_owner).json()
        kinds = {item["title"]: item["kind"] for item in items}
        assert kinds == {"垫圈": "part", "支架": "assembly"}

    def test_version_detail_includes_dependencies(self, client, ws, auth_owner):
        self._part(client, ws, auth_owner)
        assembly = self._assembly(client, ws, auth_owner)
        body = client.get(_url(ws, f"/{assembly['id']}/versions/1"), headers=auth_owner).json()
        assert body["dependencies"] and body["dependencies"][0]["file_key"] == "washer"
        assert body["dependencies"][0]["version_number"] == 1

    def test_restore_recompiles_by_dependency_snapshot(self, client, db, ws, auth_owner):
        """恢复按快照闭包编译（I5）：零件已更新时恢复仍按旧零件版本复现."""
        part = self._part(client, ws, auth_owner)
        assembly = self._assembly(client, ws, auth_owner)
        client.put(
            _url(ws, f"/{part['id']}/content"),
            json={"content": PART_CONTENT.replace("dw = 10", "dw = 20")},
            headers=auth_owner,
        )
        resp = client.post(_url(ws, f"/{assembly['id']}/versions/1/restore"), headers=auth_owner)
        assert resp.status_code == 200
        body = resp.json()
        assert body["version_number"] == 2
        version = db.scalars(
            select(DesignDesignVersion).where(
                DesignDesignVersion.design_id == assembly["id"],
                DesignDesignVersion.version_number == 2,
            )
        ).one()
        assert version.dependencies[0]["version_number"] == 1, "恢复按 v1 快照闭包落库"
        # nodes 数与 v1 相同（两个实例），几何未随零件最新版漂移
        assert len(version.compiled["nodes"]) == 2

    def test_restore_missing_dependency_400(self, client, db, ws, auth_owner):
        """快照闭包中的依赖缺失 → 400 design_dependency_missing（I5 不取最新）."""
        part = self._part(client, ws, auth_owner)
        assembly = self._assembly(client, ws, auth_owner)
        version = db.get(DesignDesignVersion, assembly["id"])
        # 造一个带未知依赖的快照版本（绕过编译写入，仅针对恢复端点的缺失分支）
        version.dependencies = [{"file_id": part["id"], "file_key": "gone", "version_number": 1, "content_hash": "x"}]
        db.commit()
        resp = client.post(_url(ws, f"/{assembly['id']}/versions/1/restore"), headers=auth_owner)
        assert resp.status_code == 400
        assert resp.json()["code"] == "design_dependency_missing"
