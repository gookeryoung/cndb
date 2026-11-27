"""数据表关联图聚合（需求 0187 P0）.

覆盖：节点 / 边结构、lookup 不建边、自关联不画自环改为节点徽标、
跨工作区与已删目标聚合为虚拟节点且不泄漏表名、
H64 可读表过滤（不可读的表不建节点也不做边端点）、
截断计数（truncated / edges_out_of_view）、
写路径缓存失效（建 / 删关联字段后立即读到新图）。
"""

from __future__ import annotations

API = "/api/v1/workspaces/{wid}/tables"
FIELDS = "/api/v1/workspaces/{wid}/tables/{tid}/fields"


def _ws(client, auth_headers, name: str) -> int:
    r = client.post("/api/v1/workspaces", json={"name": name}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _table(client, wid: int, auth, name: str) -> dict:
    r = client.post(API.format(wid=wid), json={"name": name}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def _link(client, wid: int, tid: int, auth, name: str, target: int, **extra) -> dict:
    payload = {"name": name, "field_type": "link", "config": {"target_table_id": target, **extra}}
    r = client.post(FIELDS.format(wid=wid, tid=tid), json=payload, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def _graph(client, wid: int, auth, **params) -> dict:
    r = client.get(API.format(wid=wid) + "/link-graph", headers=auth, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _reset_cache():
    from cndb.plugins.tables.services.core.link_graph import reset_link_graph_cache

    reset_link_graph_cache()


class TestLinkGraphStructure:
    def test_nodes_and_edges(self, client, auth_headers):
        wid = _ws(client, auth_headers, "关联图结构")
        project = _table(client, wid, auth_headers, "项目")
        task = _table(client, wid, auth_headers, "任务")
        field = _link(client, wid, task["id"], auth_headers, "所属项目", project["id"], multiple=True)
        _reset_cache()

        payload = _graph(client, wid, auth_headers)
        nodes = {n["id"]: n for n in payload["nodes"]}
        assert project["id"] in nodes and task["id"] in nodes
        assert nodes[project["id"]]["name"] == "项目"
        assert nodes[project["id"]]["in_degree"] == 1
        assert nodes[task["id"]]["out_degree"] == 1
        assert nodes[task["id"]]["self_loop"] is False
        assert payload["truncated"] is False
        assert payload["edges_out_of_view"] == 0

        edge = next(e for e in payload["edges"] if e["id"] == field["id"])
        assert edge["source"] == task["id"]
        assert edge["target"] == project["id"]
        assert edge["field_name"] == "所属项目"
        assert edge["multiple"] is True
        assert edge["target_state"] == "ok"
        # 真实表 id 恒为正，虚拟节点用负数
        assert all(n["id"] > 0 for n in payload["nodes"])

    def test_lookup_does_not_create_edge_but_counts_references(self, client, auth_headers):
        wid = _ws(client, auth_headers, "关联图lookup")
        project = _table(client, wid, auth_headers, "项目")
        task = _table(client, wid, auth_headers, "任务")
        link = _link(client, wid, task["id"], auth_headers, "所属项目", project["id"], reference_fields=[])

        # 在目标表上一个可被引用的普通字段
        r = client.post(
            FIELDS.format(wid=wid, tid=project["id"]),
            json={"name": "项目名", "field_type": "text"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        source_field = r.json()

        # 用 reference_fields 让 link 字段带出 1 个 lookup 引用字段
        r = client.patch(
            FIELDS.format(wid=wid, tid=task["id"]) + f"/{link['id']}",
            json={
                "config": {
                    "target_table_id": project["id"],
                    "multiple": True,
                    "reference_fields": [source_field["id"]],
                }
            },
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        _reset_cache()

        payload = _graph(client, wid, auth_headers)
        link_edges = [e for e in payload["edges"] if e["field_name"] == "所属项目"]
        # lookup 是同一关系的投影列：只产生一条边，不会因为引用字段多画几条
        assert len(link_edges) == 1
        assert link_edges[0]["reference_field_count"] == 1
        assert all(e["source"] != e["target"] for e in payload["edges"])

    def test_self_link_marked_not_drawn(self, client, auth_headers):
        wid = _ws(client, auth_headers, "关联图自关联")
        task = _table(client, wid, auth_headers, "任务")
        _link(client, wid, task["id"], auth_headers, "父任务", task["id"])
        _reset_cache()

        payload = _graph(client, wid, auth_headers)
        node = next(n for n in payload["nodes"] if n["id"] == task["id"])
        assert node["self_loop"] is True
        # 自环不进 edges（画自环没有信息量）
        assert payload["edges"] == []


class TestLinkGraphVisibility:
    def test_cross_workspace_target_aggregated_without_name(self, client, auth_headers):
        wid = _ws(client, auth_headers, "关联图主区")
        other_wid = _ws(client, auth_headers, "关联图他区")
        external_table = _table(client, other_wid, auth_headers, "他区机密表")
        local = _table(client, wid, auth_headers, "本区表")
        _link(client, wid, local["id"], auth_headers, "外部来源", external_table["id"])
        _reset_cache()

        payload = _graph(client, wid, auth_headers)
        # 响应体不得出现他区表名（H17 / H53）
        assert "他区机密表" not in str(payload)
        virtual = [n for n in payload["nodes"] if n["virtual"]]
        assert len(virtual) == 1
        assert virtual[0]["id"] < 0
        edge = payload["edges"][0]
        assert edge["target"] == virtual[0]["id"]
        assert edge["target_state"] == "other_workspace"

    def test_trashed_target_aggregated(self, client, auth_headers):
        wid = _ws(client, auth_headers, "关联图已删目标")
        target = _table(client, wid, auth_headers, "将被删除的表")
        local = _table(client, wid, auth_headers, "源表")
        _link(client, wid, local["id"], auth_headers, "指向已删", target["id"])
        r = client.delete(API.format(wid=wid) + f"/{target['id']}", headers=auth_headers)
        assert r.status_code == 204, r.text
        _reset_cache()

        payload = _graph(client, wid, auth_headers)
        assert all(n["id"] != target["id"] for n in payload["nodes"])
        edge = payload["edges"][0]
        assert edge["target_state"] == "trashed"
        assert edge["target"] < 0

    def test_table_without_read_permission_is_not_a_node(self, client, auth_headers, db):
        """H64：不可读的表既不建节点，也不作为边端点暴露."""
        from cndb.plugins.accounts.models import User
        from cndb.plugins.tables.models import TablePermission
        from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole

        wid = _ws(client, auth_headers, "关联图权限")

        viewer = User(username="graph_viewer", nickname="graph_viewer")
        viewer.set_password("passw0rd")
        db.add(viewer)
        db.commit()
        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()

        visible = _table(client, wid, auth_headers, "公开表")
        secret = _table(client, wid, auth_headers, "私有表")
        # 私有表把读门槛提到 OWNER：viewer 读不到
        db.query(TablePermission).filter(TablePermission.table_id == secret["id"]).delete()
        db.add(TablePermission(table_id=secret["id"], read_role=WorkspaceRole.OWNER.value))
        db.commit()
        _link(client, wid, visible["id"], auth_headers, "指向私有表", secret["id"])

        r = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": viewer.username, "password": "passw0rd"},
        )
        assert r.status_code == 200, r.text
        viewer_auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
        _reset_cache()

        payload = _graph(client, wid, viewer_auth)
        ids = {n["id"] for n in payload["nodes"]}
        assert visible["id"] in ids
        assert secret["id"] not in ids
        assert secret["id"] not in {e["target"] for e in payload["edges"]}
        # 目标不可读 → 归入「已删除 / 不可访问」虚拟节点
        assert payload["edges"][0]["target_state"] == "restricted"
        # 虚拟节点不带任何表名（源表上的字段名是用户起的，属于可见信息，不算泄漏）
        virtual = next(n for n in payload["nodes"] if n["virtual"])
        assert virtual["name"] != secret["name"]

        # owner 视角可见真实节点与真实边
        _reset_cache()
        owner_payload = _graph(client, wid, auth_headers)
        assert secret["id"] in {n["id"] for n in owner_payload["nodes"]}
        assert secret["id"] in {e["target"] for e in owner_payload["edges"]}


class TestLinkGraphLimits:
    def test_truncation_and_edges_out_of_view(self, client, auth_headers):
        wid = _ws(client, auth_headers, "关联图截断")
        hub = _table(client, wid, auth_headers, "中心")
        leaf = _table(client, wid, auth_headers, "叶子")
        _link(client, wid, hub["id"], auth_headers, "指向叶子", leaf["id"])
        _reset_cache()

        payload = _graph(client, wid, auth_headers, max_nodes=1)
        assert payload["truncated"] is True
        assert payload["total"] == 2
        assert len(payload["nodes"]) == 1
        # 叶子落在窗口外：边不画，但要计数（否则中心表看着像孤岛）
        assert payload["edges_out_of_view"] == 1
        assert payload["edges"] == []


class TestLinkGraphCacheInvalidation:
    def test_new_link_field_visible_immediately(self, client, auth_headers):
        wid = _ws(client, auth_headers, "关联图失效")
        a = _table(client, wid, auth_headers, "甲")
        b = _table(client, wid, auth_headers, "乙")
        _reset_cache()

        # 先读一次把空图写进缓存
        assert _graph(client, wid, auth_headers)["edges"] == []

        field = _link(client, wid, a["id"], auth_headers, "指向乙", b["id"])
        # 不调用 reset：写路径必须自己失效，否则用户会以为「刚建的关联没生效」
        payload = _graph(client, wid, auth_headers)
        assert [e["id"] for e in payload["edges"]] == [field["id"]]

    def test_deleted_link_field_disappears_immediately(self, client, auth_headers):
        wid = _ws(client, auth_headers, "关联图删除失效")
        a = _table(client, wid, auth_headers, "甲")
        b = _table(client, wid, auth_headers, "乙")
        field = _link(client, wid, a["id"], auth_headers, "指向乙", b["id"])
        _reset_cache()
        assert len(_graph(client, wid, auth_headers)["edges"]) == 1

        r = client.delete(FIELDS.format(wid=wid, tid=a["id"]) + f"/{field['id']}", headers=auth_headers)
        assert r.status_code == 204, r.text
        assert _graph(client, wid, auth_headers)["edges"] == []

    def test_cache_is_scoped_per_workspace(self, client, auth_headers):
        wid_one = _ws(client, auth_headers, "关联图缓存一")
        wid_two = _ws(client, auth_headers, "关联图缓存二")
        _reset_cache()

        a = _table(client, wid_two, auth_headers, "甲")
        b = _table(client, wid_two, auth_headers, "乙")
        _graph(client, wid_two, auth_headers)

        # 在另一个工作区建关联不应污染本工作区的缓存条目
        c = _table(client, wid_one, auth_headers, "丙")
        d = _table(client, wid_one, auth_headers, "丁")
        _link(client, wid_one, c["id"], auth_headers, "指向丁", d["id"])
        _reset_cache()

        assert _graph(client, wid_one, auth_headers)["edges"] != []
        _link(client, wid_two, a["id"], auth_headers, "指向乙", b["id"])
        assert _graph(client, wid_two, auth_headers)["edges"] != []


class TestCanEditFlag:
    """P1 E5 / D8：编辑入口的能力位由后端算，前端只按位显隐."""

    def test_owner_sees_can_edit_true(self, client, auth_headers):
        wid = _ws(client, auth_headers, "关联图能力位 owner")
        a = _table(client, wid, auth_headers, "甲")
        b = _table(client, wid, auth_headers, "乙")
        _link(client, wid, a["id"], auth_headers, "指向乙", b["id"])
        _reset_cache()

        payload = _graph(client, wid, auth_headers)
        nodes = {n["id"]: n for n in payload["nodes"]}
        assert nodes[a["id"]]["can_edit"] is True
        assert nodes[b["id"]]["can_edit"] is True
        assert payload["edges"][0]["can_edit"] is True

    def test_viewer_cannot_edit(self, client, auth_headers, db):
        """viewer 有 READ 但无 EDIT_SCHEMA：节点仍是节点，但编辑入口必须关闭."""
        from cndb.plugins.accounts.models import User
        from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole

        wid = _ws(client, auth_headers, "关联图能力位 viewer")

        viewer = User(username="graph_edit_viewer", nickname="graph_edit_viewer")
        viewer.set_password("passw0rd")
        db.add(viewer)
        db.commit()
        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()

        a = _table(client, wid, auth_headers, "甲")
        b = _table(client, wid, auth_headers, "乙")
        _link(client, wid, a["id"], auth_headers, "指向乙", b["id"])

        r = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": viewer.username, "password": "passw0rd"},
        )
        assert r.status_code == 200, r.text
        viewer_auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
        _reset_cache()

        payload = _graph(client, wid, viewer_auth)
        assert payload["nodes"], "viewer 应能看到可读表节点"
        assert all(n["can_edit"] is False for n in payload["nodes"])
        assert all(e["can_edit"] is False for e in payload["edges"])

    def test_virtual_node_is_never_editable(self, client, auth_headers, db):
        """虚拟聚合节点没有对应的真实表，恒不可编辑."""
        from cndb.plugins.tables.models import DataTable

        wid = _ws(client, auth_headers, "关联图能力位虚拟")
        a = _table(client, wid, auth_headers, "甲")
        b = _table(client, wid, auth_headers, "乙")
        _link(client, wid, a["id"], auth_headers, "指向乙", b["id"])

        # 把目标表送进回收站 → 该边改连「已删除 / 不可访问」虚拟节点
        target = db.get(DataTable, b["id"])
        target.trashed = True
        db.commit()
        _reset_cache()

        payload = _graph(client, wid, auth_headers)
        virtual = next(n for n in payload["nodes"] if n["virtual"])
        assert virtual["can_edit"] is False
        assert payload["edges"][0]["target_state"] == "trashed"


class TestChangeTargetTableGuard:
    """P1 E2′ / D7：改关联目标表时，失效关联必须先给影响面并要求 force.

    实测背景（2026-11-28）：改目标表只更新 metadata，关联物理表的 target_row_id
    原样保留，读取侧静默回退为 `#1`——用户看不出数据已失效。
    """

    def _seed(self, client, auth_headers):
        wid = _ws(client, auth_headers, "改目标表拦截")
        a = _table(client, wid, auth_headers, "源表")
        b = _table(client, wid, auth_headers, "旧目标")
        c = _table(client, wid, auth_headers, "新目标")
        field = _link(client, wid, a["id"], auth_headers, "关联", b["id"])

        # 旧目标建 1 行，源表建 1 行并关联它
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{b['id']}/records",
            json={"values": {}},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        target_row = r.json()["id"]
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{a['id']}/records",
            json={"values": {"关联": [target_row]}},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        return wid, a, b, c, field

    def test_change_target_without_force_is_rejected(self, client, auth_headers):
        wid, a, _b, c, field = self._seed(client, auth_headers)

        r = client.patch(
            FIELDS.format(wid=wid, tid=a["id"]) + f"/{field['id']}",
            json={"config": {"target_table_id": c["id"], "multiple": True}},
            headers=auth_headers,
        )
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "失效" in detail
        assert "force" in detail

        # 被拒绝后配置不得变更
        fields = client.get(FIELDS.format(wid=wid, tid=a["id"]), headers=auth_headers).json()
        current = next(f for f in fields if f["id"] == field["id"])
        assert current["config"]["target_table_id"] == _b["id"]

    def test_change_target_with_force_clears_dangling(self, client, auth_headers):
        wid, a, _b, c, field = self._seed(client, auth_headers)

        r = client.patch(
            FIELDS.format(wid=wid, tid=a["id"]) + f"/{field['id']}",
            params={"force": True},
            json={"config": {"target_table_id": c["id"], "multiple": True}},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["config"]["target_table_id"] == c["id"]

        # 失效关联被清理：源表行仍在，但该字段取值变空
        rows = client.get(f"/api/v1/workspaces/{wid}/tables/{a['id']}/records", headers=auth_headers).json()["rows"]
        assert len(rows) == 1, "源表主行不得被删除，只清理失效关联"
        assert not rows[0].get("关联"), f"失效关联应被清除，实际: {rows[0].get('关联')}"

    def test_change_target_without_dangling_needs_no_force(self, client, auth_headers):
        """没有任何关联数据时改目标表是安全操作，不该无谓拦截."""
        wid = _ws(client, auth_headers, "改目标表无数据")
        a = _table(client, wid, auth_headers, "源表")
        b = _table(client, wid, auth_headers, "旧目标")
        c = _table(client, wid, auth_headers, "新目标")
        field = _link(client, wid, a["id"], auth_headers, "关联", b["id"])

        r = client.patch(
            FIELDS.format(wid=wid, tid=a["id"]) + f"/{field['id']}",
            json={"config": {"target_table_id": c["id"], "multiple": True}},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["config"]["target_table_id"] == c["id"]
