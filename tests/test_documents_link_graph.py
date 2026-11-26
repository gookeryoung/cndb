"""文档知识图谱聚合（需求 0168）测试.

覆盖：节点/边结构、断链虚拟节点、自环过滤与边去重、歧义标记、
H33 可见性过滤、C6 节点上限与 30s 缓存（含 reset）。
"""

from __future__ import annotations

API = "/api/v1/workspaces/{wid}/documents"


def _ws(client, auth_headers, name: str) -> int:
    r = client.post("/api/v1/workspaces", json={"name": name}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create(client, wid: int, auth, title: str, content: str = "", **overrides) -> dict:
    r = client.post(API.format(wid=wid), json={"title": title, "content": content, **overrides}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def _reset_cache():
    from cndb.plugins.documents.services.content import reset_link_graph_cache

    reset_link_graph_cache()


class TestLinkGraph:
    def test_nodes_edges_and_broken_links(self, client, auth_headers):
        wid = _ws(client, auth_headers, "图谱结构")
        a = _create(client, wid, auth_headers, "甲", "正文 [[乙]] 与 [[不存在的文档#锚|别名]]")
        b = _create(client, wid, auth_headers, "乙", "反向 [[甲]]")
        _reset_cache()

        r = client.get(API.format(wid=wid) + "/links/graph", headers=auth_headers)
        assert r.status_code == 200, r.text
        payload = r.json()
        ids = {n["id"] for n in payload["nodes"]}
        assert {a["id"], b["id"]} <= ids
        assert payload["total"] >= 2
        assert payload["truncated"] is False
        # 前端据此区分「进编辑器」与「进文件夹列表」
        assert all("is_folder" in node for node in payload["nodes"])
        assert all(node["is_folder"] is False for node in payload["nodes"] if not node["broken"])

        edges = {(e["source"], e["target"]): e for e in payload["edges"]}
        assert edges[(a["id"], b["id"])]["broken"] is False
        assert edges[(b["id"], a["id"])]["broken"] is False
        broken = [e for e in payload["edges"] if e["broken"]]
        assert len(broken) == 1
        assert broken[0]["raw"] == "[[不存在的文档#锚|别名]]"
        broken_node = next(n for n in payload["nodes"] if n["id"] == broken[0]["target"])
        assert broken_node["title"] == "不存在的文档"
        assert broken_node["broken"] is True

    def test_self_link_and_duplicate_edges_filtered(self, client, auth_headers):
        wid = _ws(client, auth_headers, "图谱自环")
        a = _create(client, wid, auth_headers, "甲", "[[甲]] [[甲#章节]] [[甲|别名]]")
        _reset_cache()
        payload = client.get(API.format(wid=wid) + "/links/graph", headers=auth_headers).json()
        assert not [e for e in payload["edges"] if e["source"] == a["id"]]

    def test_ambiguous_title_marked(self, client, auth_headers):
        wid = _ws(client, auth_headers, "图谱歧义")
        _create(client, wid, auth_headers, "甲", "[[重名]]")
        _create(client, wid, auth_headers, "重名", "正文")
        _create(client, wid, auth_headers, "重名", "另一个")
        _reset_cache()
        payload = client.get(API.format(wid=wid) + "/links/graph", headers=auth_headers).json()
        ambiguous = [e for e in payload["edges"] if e["ambiguous"]]
        assert len(ambiguous) == 1

    def test_viewer_cannot_see_others_draft(self, client, auth_headers, db):
        from cndb.plugins.accounts.models import User
        from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole

        wid = _ws(client, auth_headers, "图谱可见性")
        _create(client, wid, auth_headers, "他人草稿", "草稿正文不泄漏")
        # 已发布文档正文引用草稿；草稿对 viewer 不可见 → 节点和边都不出现
        _create(client, wid, auth_headers, "已发布", "公开正文 [[他人草稿]]", status="published")

        viewer = User(username="graph_viewer", nickname="graph_viewer")
        viewer.set_password("passw0rd")
        db.add(viewer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        _reset_cache()

        from cndb.plugins.documents.services.content import build_link_graph

        payload = build_link_graph(db, wid, viewer)
        titles = {n["title"] for n in payload["nodes"]}
        assert "他人草稿" not in titles
        assert "已发布" in titles
        assert not [
            e
            for e in payload["edges"]
            if any(n["id"] == e["target"] and n["title"] == "他人草稿" for n in payload["nodes"])
        ]

    def test_truncation_and_cache(self, client, auth_headers, db):
        from cndb.plugins.accounts.models import User
        from cndb.plugins.documents.services.content import build_link_graph

        wid = _ws(client, auth_headers, "图谱规模")
        for i in range(3):
            _create(client, wid, auth_headers, f"文档{i}", f"[[文档{i}]]")
        owner = db.query(User).filter(User.username == "testuser").first()
        assert owner is not None
        _reset_cache()

        first = build_link_graph(db, wid, owner, max_nodes=2)
        assert first["truncated"] is True
        assert len([n for n in first["nodes"] if not n["broken"]]) == 2
        # 同 key 再调：命中缓存（改动数据库也不影响）
        _create(client, wid, auth_headers, "新增文档", "正文")
        second = build_link_graph(db, wid, owner, max_nodes=2)
        assert second is first
        _reset_cache()
        third = build_link_graph(db, wid, owner, max_nodes=2)
        assert third is not first
        assert third["total"] == 4
