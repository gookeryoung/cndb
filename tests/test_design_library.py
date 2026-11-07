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
