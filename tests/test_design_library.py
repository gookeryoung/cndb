"""复用模块库 P0：DSL 库引用、快照作用域、发布与权限（ADR 0118）."""

from __future__ import annotations

import hashlib
import json

import pytest

from cndb.plugins.design.models import DesignLibraryModule, DesignLibraryVersion
from cndb.plugins.design.services.dsl.compile import compile_design
from cndb.plugins.design.services.dsl.nodes import FileSource, LibrarySource
from cndb.plugins.design.services.dsl.parse import DslSyntaxError, parse_program
from cndb.plugins.workspaces.models import WorkspaceRole
from tests.pipeline_helpers import add_member, login, make_user, make_workspace

BASE = "/api/v1/workspaces/{ws}/designs"
LIB_BASE = "/api/v1/workspaces/{ws}/design-library"

PART = "param d = 10\ncyl(d = d, h = 5)\n"


def _source(
    key: str = "轮毂",
    *,
    module_id: int = 1,
    version_id: int = 1,
    version: int = 1,
    content: str = PART,
    files: tuple[FileSource, ...] = (),
) -> LibrarySource:
    return LibrarySource(
        module_id=module_id,
        module_version_id=version_id,
        module_key=key,
        version_number=version,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        bundle_hash="bundle",
        files=files,
    )


def _ok(content: str, **kwargs):
    result = compile_design(content, **kwargs)
    assert result.ok, result.diagnostics
    return result


class TestLibraryDsl:
    def test_library_use_compiles_and_snapshots(self):
        result = _ok(
            'use "lib:轮毂@1"(d = 20) as w',
            library_resolver=lambda key, version: _source(key, version=version),
        )
        ir = result.ir
        assert ir is not None
        (assembly,) = ir["outline"]["children"]
        assert assembly["kind"] == "assembly"
        assert assembly["name"] == "w"
        assert "file_id" not in assembly
        assert assembly["ref"] == {
            "source": "library",
            "module_key": "轮毂",
            "module_version_id": 1,
            "version_number": 1,
            "file_key": "轮毂",
            "kind": "part",
        }
        (dep,) = result.dependencies
        assert dep.source == "library"
        assert dep.file_key == "轮毂"
        assert dep.version_number == 1
        assert dep.bundle_hash == "bundle"
        assert json.dumps(ir["nodes"]).find("20") >= 0

    def test_vendor_snapshots_keep_distinct_identity(self):
        """vendor 快照 module_version_id 为 0：多个模块不得共享缓存 / 依赖槽位."""
        alpha = _source("alpha", module_id=0, version_id=0, content="cyl(d = 11, h = 1)\n")
        beta = _source("beta", module_id=0, version_id=0, content="cyl(d = 77, h = 2)\n")
        result = _ok(
            'use "lib:alpha@1" as a\nuse "lib:beta@1" as b\n',
            library_resolver=lambda key, version: {"alpha": alpha, "beta": beta}.get(key),
        )
        assert [node["d"] for node in result.ir["nodes"]] == [11.0, 77.0]
        assert [item.file_key for item in result.dependencies] == ["alpha", "beta"]

    def test_snapshot_wins_over_consumer_file_key(self):
        """I3：库快照内部同名 key 优先，消费方本地文件不得改变模块几何."""
        wheel = "cyl(d = 99, h = 1)\n"
        bundle = (
            FileSource(
                file_id=0,
                file_key="wheel",
                kind="part",
                content=wheel,
                version_number=1,
                content_hash=hashlib.sha256(wheel.encode()).hexdigest(),
                source="library",
                module_id=1,
                module_version_id=1,
                module_key="轮毂",
            ),
        )
        result = _ok(
            'use "lib:轮毂@1"',
            resolver=lambda key: FileSource(
                file_id=11,
                file_key=key,
                kind="part",
                content="cyl(d = 1, h = 1)\n",
                version_number=1,
                content_hash="x",
            ),
            library_resolver=lambda key, version: _source(key, content='use "wheel"\n', files=bundle),
        )
        assert result.ir is not None
        (node,) = result.ir["nodes"]
        assert node["d"] == 99.0
        assert [item.source for item in result.dependencies] == ["library"]

    def test_missing_library_reports_diagnostic(self):
        result = compile_design('use "lib:不存在@1"', library_resolver=lambda key, version: None)
        assert not result.ok
        assert "未找到引用的复用模块 '不存在@v1'" in result.diagnostics[0].message

    def test_nested_library_rejected(self):
        result = compile_design(
            'use "lib:a@1"',
            library_resolver=lambda key, version: _source(key, content='use "lib:b@1"\n', version=version),
        )
        assert not result.ok
        assert "快照内不允许再引用复用模块" in result.diagnostics[0].message

    @pytest.mark.parametrize("raw", ['use "lib:轮毂"', 'use "lib:轮毂@0"', 'use "lib:轮毂@x"'])
    def test_bad_library_syntax(self, raw: str):
        with pytest.raises(DslSyntaxError) as exc:
            parse_program(raw)
        assert "库引用格式" in exc.value.message

    def test_deterministic(self):
        kwargs = {"library_resolver": lambda key, version: _source(key, version=version)}
        first = _ok('use "lib:轮毂@1"(d = 20)', **kwargs)
        second = _ok('use "lib:轮毂@1"(d = 20)', **kwargs)
        assert first.ir == second.ir
        assert first.dependencies == second.dependencies


def _url(ws, suffix: str = "") -> str:
    return f"{BASE.format(ws=ws.id)}{suffix}"


@pytest.fixture
def owner(db):
    return make_user(db, "library_owner")


@pytest.fixture
def ws_a(db, owner):
    return make_workspace(db, owner, "LibraryA")


@pytest.fixture
def ws_b(db, owner):
    return make_workspace(db, owner, "LibraryB")


@pytest.fixture
def auth(client, owner):
    return login(client, owner)


def _create_part(client, ws, headers, title: str = "轮毂", content: str = PART):
    return client.post(
        _url(ws),
        json={"title": title, "content": content, "kind": "part"},
        headers=headers,
    )


def _publish(client, ws, design_id, headers, **body):
    payload = {"visibility": "public", "name": "标准轮毂", **body}
    return client.post(_url(ws, f"/{design_id}/publish"), json=payload, headers=headers)


class TestPublish:
    def test_publish_and_republish_increments_version(self, client, db, ws_a, auth):
        design_id = _create_part(client, ws_a, auth).json()["id"]
        first = _publish(client, ws_a, design_id, auth)
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["module_key"] == "标准轮毂"
        assert body["version_number"] == 1
        assert body["visibility"] == "public"

        second = _publish(client, ws_a, design_id, auth, comment="v2")
        assert second.status_code == 200
        assert second.json()["module_key"] == body["module_key"]
        assert second.json()["version_number"] == 2

        module = db.query(DesignLibraryModule).filter_by(module_key="标准轮毂").one()
        versions = (
            db.query(DesignLibraryVersion)
            .filter_by(module_id=module.id)
            .order_by(DesignLibraryVersion.version_number)
            .all()
        )
        assert [item.version_number for item in versions] == [1, 2]
        assert versions[0].content == PART
        assert versions[0].params == [{"name": "d", "default": 10}]

    def test_assembly_cannot_publish(self, client, ws_a, auth):
        design_id = client.post(
            _url(ws_a), json={"title": "组件", "content": "box(size = [1, 1, 1])"}, headers=auth
        ).json()["id"]
        assert _publish(client, ws_a, design_id, auth).status_code == 400

    def test_viewer_cannot_publish(self, client, db, ws_a):
        viewer = make_user(db, "library_viewer")
        add_member(db, ws_a, viewer, WorkspaceRole.VIEWER)
        headers = login(client, viewer)
        resp = client.post(_url(ws_a), json={"title": "只读件", "content": PART, "kind": "part"}, headers=headers)
        assert resp.status_code == 403

    def test_nested_library_publish_rejected(self, client, ws_a, auth):
        first_id = _create_part(client, ws_a, auth, title="内层件").json()["id"]
        assert _publish(client, ws_a, first_id, auth).status_code == 200
        key = _publish(client, ws_a, first_id, auth).json()["module_key"]
        outer = _create_part(client, ws_a, auth, title="外层件", content=f'use "lib:{key}@1"').json()["id"]
        resp = _publish(client, ws_a, outer, auth)
        assert resp.status_code == 400
        assert "模块内部不允许再引用复用模块" in resp.text

    def test_module_key_globally_unique(self, client, db, ws_a, ws_b, auth):
        a = _create_part(client, ws_a, auth, title="同名件").json()["id"]
        b = _create_part(client, ws_b, auth, title="同名件").json()["id"]
        key_a = _publish(client, ws_a, a, auth).json()["module_key"]
        key_b = _publish(client, ws_b, b, auth).json()["module_key"]
        assert key_a != key_b


def _lib_url(ws, suffix: str = "") -> str:
    return f"{LIB_BASE.format(ws=ws.id)}{suffix}"


class TestLibraryBrowser:
    def test_list_visibility_and_filters(self, client, ws_a, ws_b, auth):
        public_id = _create_part(client, ws_a, auth, title="公开件").json()["id"]
        _publish(client, ws_a, public_id, auth, name="公开模块")
        private_id = _create_part(client, ws_a, auth, title="私有件").json()["id"]
        _publish(client, ws_a, private_id, auth, name="私有模块", visibility="workspace")

        items = client.get(_lib_url(ws_b, "/modules"), headers=auth).json()
        assert [item["name"] for item in items] == ["公开模块"]
        assert items[0]["latest_version"] == 1
        assert items[0]["version_count"] == 1

        own = client.get(_lib_url(ws_a, "/modules"), headers=auth).json()
        assert {item["name"] for item in own} == {"公开模块", "私有模块"}
        assert {
            item["name"] for item in client.get(_lib_url(ws_a, "/modules?owned_only=true"), headers=auth).json()
        } == {"公开模块", "私有模块"}
        assert [item["name"] for item in client.get(_lib_url(ws_a, "/modules?q=公开"), headers=auth).json()] == [
            "公开模块"
        ]

    def test_archived_hidden_by_default_and_owner_can_include(self, client, ws_a, auth):
        design_id = _create_part(client, ws_a, auth, title="待归档").json()["id"]
        module_id = _publish(client, ws_a, design_id, auth, name="归档件").json()["module_id"]
        assert (
            client.patch(_lib_url(ws_a, f"/modules/{module_id}"), json={"is_archived": True}, headers=auth).status_code
            == 200
        )
        assert client.get(_lib_url(ws_a, "/modules"), headers=auth).json() == []
        archived = client.get(_lib_url(ws_a, "/modules?include_archived=true"), headers=auth).json()
        assert [item["name"] for item in archived] == ["归档件"]

    def test_detail_version_and_preview(self, client, ws_a, auth):
        design_id = _create_part(client, ws_a, auth).json()["id"]
        published = _publish(client, ws_a, design_id, auth, comment="首版").json()
        module_id = published["module_id"]

        detail = client.get(_lib_url(ws_a, f"/modules/{module_id}"), headers=auth)
        assert detail.status_code == 200
        body = detail.json()
        assert body["can_manage"] is True
        assert [item["version_number"] for item in body["versions"]] == [1]
        assert body["params"] == [{"name": "d", "default": 10}]

        version = client.get(_lib_url(ws_a, f"/modules/{module_id}/versions/1"), headers=auth).json()
        assert version["content"] == PART
        assert version["comment"] == "首版"
        assert version["files"] == []

        preview = client.post(
            _lib_url(ws_a, f"/modules/{module_id}/versions/1/preview"),
            json={"overrides": {"d": 22}},
            headers=auth,
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["ok"] is True
        assert preview.json()["ir"]["nodes"][0]["d"] == 22.0

        assert client.get(_lib_url(ws_a, f"/modules/{module_id}/versions/9"), headers=auth).status_code == 404

    def test_editor_cannot_patch_module(self, client, db, ws_a, auth):
        design_id = _create_part(client, ws_a, auth).json()["id"]
        module_id = _publish(client, ws_a, design_id, auth, visibility="workspace").json()["module_id"]
        editor = make_user(db, "library_editor")
        add_member(db, ws_a, editor, WorkspaceRole.EDITOR)
        resp = client.patch(
            _lib_url(ws_a, f"/modules/{module_id}"),
            json={"name": "改名"},
            headers=login(client, editor),
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == "design_library_forbidden"

    def test_patch_visibility_and_archive_keeps_existing_reference(self, client, ws_a, ws_b, auth):
        design_id = _create_part(client, ws_a, auth).json()["id"]
        published = _publish(client, ws_a, design_id, auth).json()
        key, module_id = published["module_key"], published["module_id"]

        consumer = client.post(
            _url(ws_b),
            json={"title": "既有装配", "content": f'use "lib:{key}@1"'},
            headers=auth,
        )
        assert consumer.status_code == 201, consumer.text

        patched = client.patch(
            _lib_url(ws_a, f"/modules/{module_id}"),
            json={"visibility": "workspace", "is_archived": True},
            headers=auth,
        )
        assert patched.status_code == 200
        assert patched.json()["visibility"] == "workspace"
        assert patched.json()["is_archived"] is True

        # 既有引用授权：带 design_id 可查看 / 预览，消费设计继续可用
        granted = client.get(_lib_url(ws_b, f"/modules/{module_id}?design_id={consumer.json()['id']}"), headers=auth)
        assert granted.status_code == 200
        assert client.get(_lib_url(ws_b, f"/modules/{module_id}"), headers=auth).status_code == 404
        assert client.get(_url(ws_b, f"/{consumer.json()['id']}/ir"), headers=auth).status_code == 200

    def test_dependencies_reports_library_items_and_updates(self, client, ws_a, ws_b, auth):
        design_id = _create_part(client, ws_a, auth).json()["id"]
        key = _publish(client, ws_a, design_id, auth).json()["module_key"]
        consumer = client.post(
            _url(ws_b),
            json={"title": "依赖装配", "content": f'use "lib:{key}@1"'},
            headers=auth,
        )
        consumer_id = consumer.json()["id"]

        deps = client.get(_url(ws_b, f"/{consumer_id}/dependencies"), headers=auth).json()
        assert deps["items"] == []
        (item,) = deps["library_items"]
        assert item["module_key"] == key
        assert item["version_number"] == 1
        assert item["latest_version"] == 1
        assert item["has_update"] is False

        _publish(client, ws_a, design_id, auth, comment="v2")
        deps = client.get(_url(ws_b, f"/{consumer_id}/dependencies"), headers=auth).json()
        assert deps["library_items"][0]["latest_version"] == 2
        assert deps["library_items"][0]["has_update"] is True

    def test_restore_missing_library_dependency_400(self, client, db, ws_a, ws_b, auth):
        """历史快照引用的库版本已删除：restore 给专用 400，而不是普通编译失败（ADR 0118 §7）."""
        from cndb.plugins.design.models import (
            DesignLibraryModule,
            DesignLibraryref,
            DesignLibraryVersion,
        )

        design_id = _create_part(client, ws_a, auth).json()["id"]
        key = _publish(client, ws_a, design_id, auth).json()["module_key"]
        consumer_id = client.post(
            _url(ws_b),
            json={"title": "依赖装配", "content": f'use "lib:{key}@1"'},
            headers=auth,
        ).json()["id"]

        module_id = db.query(DesignLibraryModule).filter_by(module_key=key).one().id
        db.query(DesignLibraryref).filter_by(module_id=module_id).delete()
        db.query(DesignLibraryVersion).filter_by(module_id=module_id).delete()
        db.commit()

        resp = client.post(_url(ws_b, f"/{consumer_id}/versions/1/restore"), headers=auth)
        assert resp.status_code == 400
        assert resp.json()["code"] == "design_library_dependency_missing"


class TestCrossWorkspaceReference:
    def test_public_module_usable_from_other_workspace(self, client, ws_a, ws_b, auth):
        design_id = _create_part(client, ws_a, auth).json()["id"]
        key = _publish(client, ws_a, design_id, auth).json()["module_key"]
        resp = client.post(
            _url(ws_b),
            json={
                "title": "跨区装配",
                "content": f'use "lib:{key}@1"(d = 32) as w',
            },
            headers=auth,
        )
        assert resp.status_code == 201, resp.text

    def test_private_module_rejected_cross_workspace(self, client, ws_a, ws_b, auth):
        design_id = _create_part(client, ws_a, auth).json()["id"]
        key = _publish(client, ws_a, design_id, auth, visibility="workspace").json()["module_key"]
        resp = client.post(
            _url(ws_b),
            json={"title": "越权装配", "content": f'use "lib:{key}@1"'},
            headers=auth,
        )
        assert resp.status_code == 400
        assert "未找到引用的复用模块" in resp.text

    def test_archived_module_blocks_new_but_keeps_existing(self, client, db, ws_a, ws_b, auth):
        design_id = _create_part(client, ws_a, auth).json()["id"]
        key = _publish(client, ws_a, design_id, auth).json()["module_key"]
        consumer = client.post(
            _url(ws_b),
            json={"title": "既有装配", "content": f'use "lib:{key}@1"'},
            headers=auth,
        )
        assert consumer.status_code == 201, consumer.text
        consumer_id = consumer.json()["id"]

        module = db.query(DesignLibraryModule).filter_by(module_key=key).one()
        module.is_archived = True
        db.commit()

        denied = client.post(
            _url(ws_b),
            json={"title": "新装配", "content": f'use "lib:{key}@1"'},
            headers=auth,
        )
        assert denied.status_code == 400
        assert client.get(_url(ws_b, f"/{consumer_id}/ir"), headers=auth).status_code == 200
