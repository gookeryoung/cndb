"""文档知识图谱聚合（需求 0168）测试.

覆盖：节点/边结构、断链虚拟节点、自环过滤与边去重、歧义标记、
H33 可见性过滤、C6 节点上限与 30s 缓存（含 reset）、
需求 0182 C1 写路径缓存失效与 C2 截断丢边计数。
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
        # 同参再调：命中缓存（无写入时同样是同一个对象）
        assert build_link_graph(db, wid, owner, max_nodes=2) is first
        # 需求 0182 C1：写路径会失效缓存，不再靠 TTL 等自然过期
        _create(client, wid, auth_headers, "新增文档", "正文")
        second = build_link_graph(db, wid, owner, max_nodes=2)
        assert second is not first
        assert second["total"] == 4
        # 不同 max_nodes 是不同的缓存槽：不能被截断版结果串味
        assert build_link_graph(db, wid, owner)["truncated"] is False

    def test_cache_invalidated_by_writes(self, client, auth_headers, db):
        """需求 0182 C1：写路径必须让图谱缓存失效，不能靠 30s TTL 等自然过期."""
        from cndb.plugins.accounts.models import User
        from cndb.plugins.documents.services.content import build_link_graph

        wid = _ws(client, auth_headers, "图谱缓存失效")
        target = _create(client, wid, auth_headers, "目标文档", "正文")
        owner = db.query(User).filter(User.username == "testuser").first()
        assert owner is not None
        _reset_cache()

        before = build_link_graph(db, wid, owner)
        assert all(edge["target"] != target["id"] for edge in before["edges"])

        # 新建文档引用目标：缓存必须失效，否则仍是旧图
        source = _create(client, wid, auth_headers, "引用方", "[[目标文档]]")
        after_create = build_link_graph(db, wid, owner)
        assert (source["id"], target["id"]) in {(e["source"], e["target"]) for e in after_create["edges"]}

        # 改正文（PUT content）：边消失后同样要立刻反映
        r = client.put(
            API.format(wid=wid) + f"/{source['id']}/content",
            json={"content": "正文不再引用"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        after_update = build_link_graph(db, wid, owner)
        assert all(edge["source"] != source["id"] for edge in after_update["edges"])

    def test_cache_invalidated_by_rename_and_delete(self, client, auth_headers, db):
        """需求 0182 C1：改标题 / 删除也会改变边，同样要失效."""
        from cndb.plugins.accounts.models import User
        from cndb.plugins.documents.services.content import build_link_graph

        wid = _ws(client, auth_headers, "图谱改标题")
        target = _create(client, wid, auth_headers, "旧标题", "正文")
        source = _create(client, wid, auth_headers, "引用方", "[[旧标题]]")
        owner = db.query(User).filter(User.username == "testuser").first()
        assert owner is not None
        _reset_cache()
        assert any(e["target"] == target["id"] for e in build_link_graph(db, wid, owner)["edges"])

        r = client.patch(API.format(wid=wid) + f"/{target['id']}", json={"title": "新标题"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        renamed = build_link_graph(db, wid, owner)
        assert any(e["target"] == target["id"] for e in renamed["edges"]) is False
        assert any(e["broken"] and e["raw"] == "[[旧标题]]" for e in renamed["edges"])

        # 删除被引用方：节点消失，指向它的边变断链
        r = client.delete(API.format(wid=wid) + f"/{target['id']}", headers=auth_headers)
        assert r.status_code == 200, r.text
        deleted = build_link_graph(db, wid, owner)
        ids = {n["id"] for n in deleted["nodes"]}
        assert target["id"] not in ids
        assert source["id"] in ids

    def test_edges_out_of_view_counted_when_truncated(self, client, auth_headers, db):
        """需求 0182 C2：被截断丢弃的边要单独计数，不能混进断链."""
        from cndb.plugins.accounts.models import User
        from cndb.plugins.documents.services.content import build_link_graph

        wid = _ws(client, auth_headers, "图谱窗口外")
        # 三个文档：引用方 → 目标文档；目标先建（updated_at 更早），max_nodes=2 时被截掉
        target = _create(client, wid, auth_headers, "窗口外目标", "正文")
        _create(client, wid, auth_headers, "中间文档", "正文")
        source = _create(client, wid, auth_headers, "引用方", "[[窗口外目标]]")
        owner = db.query(User).filter(User.username == "testuser").first()
        assert owner is not None
        _reset_cache()

        payload = build_link_graph(db, wid, owner, max_nodes=2)
        assert payload["truncated"] is True
        assert payload["edges_out_of_view"] == 1
        # 不能同时生成断链节点：目标其实存在，只是不在窗口里
        assert not [n for n in payload["nodes"] if n["broken"]]
        assert not [e for e in payload["edges"] if e["source"] == source["id"] and e["broken"]]

        full = build_link_graph(db, wid, owner)
        assert full["truncated"] is False
        assert full["edges_out_of_view"] == 0
        assert any(e["target"] == target["id"] for e in full["edges"])

    def test_edges_out_of_view_ignores_invisible_documents(self, client, auth_headers, db):
        """H33：窗口外计数不能泄漏「存在但不可见」的草稿（需求 0182 C2）."""
        from cndb.plugins.accounts.models import User
        from cndb.plugins.documents.services.content import build_link_graph

        wid = _ws(client, auth_headers, "图谱窗口外可见性")
        _create(client, wid, auth_headers, "他人草稿", "草稿正文")
        _create(client, wid, auth_headers, "已发布", "公开正文 [[他人草稿]]", status="published")

        viewer = User(username="graph_viewer2", nickname="graph_viewer2")
        viewer.set_password("passw0rd")
        db.add(viewer)
        db.flush()
        from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole

        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        _reset_cache()

        payload = build_link_graph(db, wid, viewer, max_nodes=1)
        assert payload["edges_out_of_view"] == 0
        assert {n["title"] for n in payload["nodes"]} == {"已发布"}

    def test_node_payload_carries_updated_at_and_first_tag(self, client, auth_headers, db):
        """需求 0191 C3/C4：节点带 updated_at 与首个标签名，tooltip / 色组数据源."""
        from cndb.plugins.documents.models import Tag

        wid = _ws(client, auth_headers, "图谱载荷")
        a = _create(client, wid, auth_headers, "带标签甲", "正文 [[乙]]")
        tag1 = Tag(workspace_id=wid, name="主标签")
        tag2 = Tag(workspace_id=wid, name="次要标签")
        db.add_all([tag1, tag2])
        db.commit()
        r = client.patch(
            f"{API.format(wid=wid)}/{a['id']}",
            json={"tag_ids": [tag2.id, tag1.id]},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        _reset_cache()

        payload = client.get(API.format(wid=wid) + "/links/graph", headers=auth_headers).json()
        node_a = next(n for n in payload["nodes"] if n["id"] == a["id"])
        # 首个标签按 tag_id 最小者（主标签语义），不是传入顺序
        assert node_a["tag"] == "主标签"
        assert node_a["updated_at"]
        # 断链虚拟节点无时间与标签
        broken = next(n for n in payload["nodes"] if n["broken"])
        assert broken["updated_at"] is None
        assert broken["tag"] is None

    def test_set_tags_invalidates_graph_cache(self, client, auth_headers, db):
        """需求 0191 C4：改标签后图谱写后即见（0182 C1 教训，不靠 30s TTL）."""
        from cndb.plugins.documents.models import Tag

        wid = _ws(client, auth_headers, "图谱标签失效")
        a = _create(client, wid, auth_headers, "标签失效甲", "正文")
        tag = Tag(workspace_id=wid, name="失效标签")
        db.add(tag)
        db.commit()
        _reset_cache()

        first = client.get(API.format(wid=wid) + "/links/graph", headers=auth_headers).json()
        assert next(n for n in first["nodes"] if n["id"] == a["id"])["tag"] is None

        client.post(
            f"{API.format(wid=wid)}/{a['id']}/tags",
            json={"tag_ids": [tag.id]},
            headers=auth_headers,
        )
        second = client.get(API.format(wid=wid) + "/links/graph", headers=auth_headers).json()
        assert next(n for n in second["nodes"] if n["id"] == a["id"])["tag"] == "失效标签"

    def test_folder_node_marked(self, client, auth_headers):
        """文件夹也是节点（链接目标可为文件夹），前端据此跳目录列表而非编辑器."""
        wid = _ws(client, auth_headers, "图谱文件夹")
        _create(client, wid, auth_headers, "资料夹", is_folder=True)
        _create(client, wid, auth_headers, "正文文档", "[[资料夹]]")
        _reset_cache()
        payload = client.get(API.format(wid=wid) + "/links/graph", headers=auth_headers).json()
        folder = next(node for node in payload["nodes"] if node["title"] == "资料夹")
        assert folder["is_folder"] is True
        assert folder["content_type"] == "folder"
