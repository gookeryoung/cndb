"""图表实例与渲染 API（ADR 0048）接口测试.

覆盖：两级清单（成员可见 / 非成员 403）、render-preview 不落库（宽松归一 200 /
未知模板 400）、实例 CRUD（editor+ 写、viewer 只读、config 严格校验 400）、
渲染（SVG + ETag 304、模板下线降级）、物理删除后引用降级口径。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.documents.services.charts.registry import CHART_TEMPLATES
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

CHARTS = "/api/v1/workspaces/{ws}/charts"

DUAL = CHART_TEMPLATES["bar-line-dual-axis"].default_config
STACKED = CHART_TEMPLATES["stacked-bar-horizontal"].default_config
GROUPED = CHART_TEMPLATES["grouped-bar-horizontal"].default_config


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def owner(db) -> User:
    return _make_user(db, "ch_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    w = Workspace(name="ChartWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def editor(db, ws) -> User:
    u = _make_user(db, "ch_editor")
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.EDITOR))
    db.commit()
    return u


@pytest.fixture
def viewer(db, ws) -> User:
    u = _make_user(db, "ch_viewer")
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.VIEWER))
    db.commit()
    return u


@pytest.fixture
def outsider(db) -> User:
    return _make_user(db, "ch_outsider")


def _create_chart(client: TestClient, ws_id: int, headers: dict, **overrides) -> dict:
    payload = {"title": "产业营收图", "template_key": "bar-line-dual-axis", "config": DUAL, **overrides}
    r = client.post(CHARTS.format(ws=ws_id), json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


class TestTemplates:
    def test_member_lists_two_levels(self, client, ws, viewer):
        r = client.get(CHARTS.format(ws=ws.id) + "/templates", headers=_login(client, viewer.username))
        assert r.status_code == 200, r.text
        body = r.json()
        cats = {c["key"]: c for c in body["categories"]}
        assert set(cats) == {"comparison"}
        assert {c["key"] for c in cats["comparison"]["children"]} == {"comparison-bar", "comparison-bar-h"}
        assert {t["key"] for t in body["templates"]} == set(CHART_TEMPLATES)
        assert all("default_config" in t for t in body["templates"])

    def test_outsider_and_anonymous_denied(self, client, ws, outsider):
        url = CHARTS.format(ws=ws.id) + "/templates"
        assert client.get(url, headers=_login(client, outsider.username)).status_code == 403
        assert client.get(url).status_code == 401


class TestRenderPreview:
    def test_preview_renders_without_persisting(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        r = client.post(
            CHARTS.format(ws=ws.id) + "/render-preview",
            json={"template_key": "stacked-bar-horizontal", "config": STACKED},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "image/svg+xml"
        assert "水平堆叠" in r.text or "<svg" in r.text

    def test_preview_loose_normalization(self, client, ws, owner):
        """预览走宽松归一：坏值回退默认而非 400（D5，设计器实时反馈）."""
        auth = _login(client, owner.username)
        r = client.post(
            CHARTS.format(ws=ws.id) + "/render-preview",
            json={"template_key": "grouped-bar-horizontal", "config": {"data": {"rows": "bad"}}},
            headers=auth,
        )
        assert r.status_code == 200, r.text

    def test_preview_unknown_template_400(self, client, ws, owner):
        auth = _login(client, owner.username)
        r = client.post(
            CHARTS.format(ws=ws.id) + "/render-preview",
            json={"template_key": "gone", "config": {}},
            headers=auth,
        )
        assert r.status_code == 400

    def test_preview_not_persisted(self, client, ws, owner, db):
        from cndb.plugins.documents.models import DocumentChart

        auth = _login(client, owner.username)
        client.post(
            CHARTS.format(ws=ws.id) + "/render-preview",
            json={"template_key": "stacked-bar-horizontal", "config": STACKED},
            headers=auth,
        )
        assert db.query(DocumentChart).count() == 0


class TestCrud:
    def test_editor_creates_and_reads(self, client, ws, editor):
        auth = _login(client, editor.username)
        chart = _create_chart(client, ws.id, auth)
        assert chart["template_key"] == "bar-line-dual-axis"
        assert chart["category"] == "comparison-bar"
        assert chart["config"]["caption"]["title"] == DUAL["caption"]["title"]

        got = client.get(CHARTS.format(ws=ws.id) + f"/{chart['id']}", headers=auth)
        assert got.status_code == 200
        assert got.json()["id"] == chart["id"]

    def test_create_strips_title_and_validates(self, client, ws, editor):
        auth = _login(client, editor.username)
        # 未知模板 → 400
        r = client.post(
            CHARTS.format(ws=ws.id), json={"title": "x", "template_key": "gone", "config": {}}, headers=auth
        )
        assert r.status_code == 400
        # 结构非法 → 400 + code
        bad = {"title": "x", "template_key": "stacked-bar-horizontal", "config": {"data": {"rows": []}}}
        r = client.post(CHARTS.format(ws=ws.id), json=bad, headers=auth)
        assert r.status_code == 400
        assert r.json()["code"] == "chart_config_invalid"
        # 标题去首尾空白
        ok = client.post(
            CHARTS.format(ws=ws.id),
            json={"title": "  空白标题  ", "template_key": "grouped-bar-horizontal", "config": GROUPED},
            headers=auth,
        )
        assert ok.status_code == 201
        assert ok.json()["title"] == "空白标题"

    def test_viewer_cannot_write_but_can_read(self, client, ws, owner, viewer):
        chart = _create_chart(client, ws.id, _login(client, owner.username))
        auth = _login(client, viewer.username)
        assert client.get(CHARTS.format(ws=ws.id) + f"/{chart['id']}", headers=auth).status_code == 200
        r = client.put(
            CHARTS.format(ws=ws.id) + f"/{chart['id']}",
            json={"title": "改", "template_key": "stacked-bar-horizontal", "config": STACKED},
            headers=auth,
        )
        assert r.status_code == 403
        assert client.delete(CHARTS.format(ws=ws.id) + f"/{chart['id']}", headers=auth).status_code == 403

    def test_update_full_overwrite(self, client, ws, editor):
        auth = _login(client, editor.username)
        chart = _create_chart(client, ws.id, auth)
        r = client.put(
            CHARTS.format(ws=ws.id) + f"/{chart['id']}",
            json={"title": "  结构变化图  ", "template_key": "stacked-bar-horizontal", "config": STACKED},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["title"] == "结构变化图"  # str_strip_whitespace
        assert body["template_key"] == "stacked-bar-horizontal"
        assert body["category"] == "comparison-bar-h"
        assert body["config"] == _normalized(STACKED, "stacked-bar-horizontal")

    def test_list_and_category_filter(self, client, ws, editor):
        auth = _login(client, editor.username)
        _create_chart(client, ws.id, auth)
        _create_chart(client, ws.id, auth, title="结构图", template_key="stacked-bar-horizontal", config=STACKED)
        _create_chart(client, ws.id, auth, title="对比图", template_key="grouped-bar-horizontal", config=GROUPED)

        listing = client.get(CHARTS.format(ws=ws.id), headers=auth).json()
        assert len(listing["items"]) == 3

        comp = client.get(CHARTS.format(ws=ws.id), params={"category": "comparison-bar-h"}, headers=auth).json()
        assert [c["title"] for c in comp["items"]] == ["结构图", "对比图"]

    def test_delete_physical(self, client, ws, editor, db):
        from cndb.plugins.documents.models import DocumentChart

        auth = _login(client, editor.username)
        chart = _create_chart(client, ws.id, auth)
        url = CHARTS.format(ws=ws.id) + f"/{chart['id']}"
        assert client.delete(url, headers=auth).status_code == 200
        assert db.query(DocumentChart).count() == 0
        assert client.get(url, headers=auth).status_code == 404

    def test_non_member_denied_everywhere(self, client, ws, owner, outsider):
        chart = _create_chart(client, ws.id, _login(client, owner.username))
        auth = _login(client, outsider.username)
        base = CHARTS.format(ws=ws.id)
        assert client.get(base, headers=auth).status_code == 403
        assert client.get(base + f"/{chart['id']}", headers=auth).status_code == 403
        assert client.get(base + f"/{chart['id']}/render", headers=auth).status_code == 403
        assert (
            client.post(
                base + "/render-preview",
                json={"template_key": "stacked-bar-horizontal", "config": STACKED},
                headers=auth,
            ).status_code
            == 403
        )


def _normalized(config: dict, key: str) -> dict:
    from cndb.plugins.documents.services.charts.registry import normalize_config

    return normalize_config(key, config)


class TestRenderEndpoint:
    def test_render_svg_with_etag_and_304(self, client, ws, editor):
        auth = _login(client, editor.username)
        chart = _create_chart(client, ws.id, auth)
        url = CHARTS.format(ws=ws.id) + f"/{chart['id']}/render"

        first = client.get(url, headers=auth)
        assert first.status_code == 200
        assert first.headers["content-type"] == "image/svg+xml"
        etag = first.headers["ETag"]
        assert etag.startswith('"')

        cached = client.get(url, headers={**auth, "If-None-Match": etag})
        assert cached.status_code == 304

    def test_etag_changes_after_update(self, client, ws, editor):
        auth = _login(client, editor.username)
        chart = _create_chart(client, ws.id, auth)
        url = CHARTS.format(ws=ws.id) + f"/{chart['id']}"
        etag1 = client.get(url + "/render", headers=auth).headers["ETag"]
        client.put(
            url,
            json={"title": "新图", "template_key": "grouped-bar-horizontal", "config": GROUPED},
            headers=auth,
        )
        etag2 = client.get(url + "/render", headers=auth).headers["ETag"]
        assert etag1 != etag2

    def test_render_degrades_when_template_offline(self, client, ws, editor, monkeypatch):
        """模板下线（注册表移除）→ 占位降级图而非 500（I5）。"""
        from cndb.plugins.documents.services.charts import registry

        auth = _login(client, editor.username)
        chart = _create_chart(client, ws.id, auth)
        monkeypatch.setattr(registry, "CHART_TEMPLATES", {})
        r = client.get(CHARTS.format(ws=ws.id) + f"/{chart['id']}/render", headers=auth)
        assert r.status_code == 200
        assert "图表 #" in r.text
        assert "模板已下线" in r.text

    def test_render_404_cross_workspace(self, client, ws, db, owner):
        other = Workspace(name="其他WS", created_by_id=owner.id)
        db.add(other)
        db.flush()
        # owner 也是另一工作区成员：权限过、但图表不属于该工作区 → 404
        db.add(WorkspaceMember(workspace_id=other.id, user_id=owner.id, role=WorkspaceRole.OWNER))
        db.commit()
        db.refresh(other)
        chart = _create_chart(client, ws.id, _login(client, owner.username))
        r = client.get(CHARTS.format(ws=other.id) + f"/{chart['id']}/render", headers=_login(client, owner.username))
        assert r.status_code == 404
