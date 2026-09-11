"""表复制/移动/reorder + 行 restore 测试."""

from __future__ import annotations


def test_copy_table(client, auth_headers, db):
    """复制表结构应生成新表."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_copy"})
    wid = ws.json()["id"]
    tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "src_table"})
    tid = tbl.json()["id"]

    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "f1", "field_type": "text", "order": 0},
    )

    resp = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/copy",
        headers=auth_headers,
    )
    assert resp.status_code == 201
    copied = resp.json()
    assert copied["id"] != tid
    assert copied["name"].startswith("src_table")


def test_copy_table_with_data(client, auth_headers, db):
    """include_data=True 应复制数据."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_copy2"})
    wid = ws.json()["id"]
    tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "src2"})
    tid = tbl.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "name", "field_type": "text", "order": 0},
    )
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records",
        headers=auth_headers,
        json={"values": {"name": "hello"}},
    )
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records",
        headers=auth_headers,
        json={"values": {"name": "world"}},
    )
    resp = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/copy?include_data=true",
        headers=auth_headers,
    )
    assert resp.status_code == 201
    dst_id = resp.json()["id"]
    list_resp = client.post(
        f"/api/v1/workspaces/{wid}/tables/{dst_id}/records/list",
        headers=auth_headers,
        json={"filters": [], "sorts": [], "limit": 100, "offset": 0},
    )
    assert list_resp.json()["total"] == 2


def test_move_table(client, auth_headers, db):
    """移动表到另一个工作区."""
    ws1 = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_move1"})
    ws2 = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_move2"})
    wid1 = ws1.json()["id"]
    wid2 = ws2.json()["id"]
    tbl = client.post(f"/api/v1/workspaces/{wid1}/tables", headers=auth_headers, json={"name": "movable"})
    tid = tbl.json()["id"]

    resp = client.post(
        f"/api/v1/workspaces/{wid1}/tables/{tid}/move?target_workspace_id={wid2}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["workspace_id"] == wid2


def test_reorder_tables(client, auth_headers, db):
    """批量调整表顺序."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_reorder"})
    wid = ws.json()["id"]
    ids = []
    for i in range(3):
        tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": f"t{i}"})
        ids.append(tbl.json()["id"])
    resp = client.post(
        f"/api/v1/workspaces/{wid}/tables/reorder",
        headers=auth_headers,
        json=list(reversed(ids)),
    )
    assert resp.status_code == 200
    reordered = resp.json()
    assert reordered[0]["id"] == ids[2]


def test_get_tables_graph(client, auth_headers, db):
    """表关系图端点应返回 nodes + edges."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_graph"})
    wid = ws.json()["id"]
    client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "g_table"})
    resp = client.get(
        f"/api/v1/workspaces/{wid}/tables/graph",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data


def test_record_soft_delete_and_restore(client, auth_headers, db):
    """软删除 + 恢复完整链路."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_restore"})
    wid = ws.json()["id"]
    tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_res"})
    tid = tbl.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "name", "field_type": "text", "order": 0},
    )
    row = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records",
        headers=auth_headers,
        json={"values": {"name": "delme"}},
    )
    rid = row.json()["id"]
    # 软删除
    resp = client.delete(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/{rid}",
        headers=auth_headers,
    )
    assert resp.status_code == 204
    # 默认列表无
    list_resp = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/list",
        headers=auth_headers,
        json={"filters": [], "sorts": [], "limit": 100, "offset": 0},
    )
    assert list_resp.json()["total"] == 0
    # 恢复
    restore_resp = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/{rid}/restore",
        headers=auth_headers,
    )
    assert restore_resp.status_code == 200
    # 恢复后有
    list_resp3 = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/list",
        headers=auth_headers,
        json={"filters": [], "sorts": [], "limit": 100, "offset": 0},
    )
    assert list_resp3.json()["total"] == 1


def test_restore_nonexistent(client, auth_headers, db):
    """恢复不存在的行应 404."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_restore2"})
    wid = ws.json()["id"]
    tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_nf"})
    tid = tbl.json()["id"]
    resp = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/99999/restore",
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_link_field_type(client, auth_headers, db):
    """link 字段类型应可注册."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_link"})
    wid = ws.json()["id"]
    target = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "target"})
    ttid = target.json()["id"]
    src = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "src"})
    sid = src.json()["id"]
    resp = client.post(
        f"/api/v1/workspaces/{wid}/tables/{sid}/fields",
        headers=auth_headers,
        json={
            "name": "ref",
            "field_type": "link",
            "config": {"target_table_id": ttid},
            "order": 0,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["field_type"] == "link"


class TestTableCopy:
    """copy_table 基础路径测试."""

    def test_copy_table_structure(self, client, auth_headers, db):
        """不带数据复制结构应成功."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_copy"})
        wid = ws.json()["id"]
        tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "源表"})
        tid = tbl.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "姓名", "field_type": "text"},
        )
        resp = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/copy",
            headers=auth_headers,
            json={"include_data": False},
        )
        assert resp.status_code == 201
        dst_tid = resp.json()["id"]
        assert dst_tid != tid


def test_record_references_empty(client, auth_headers):
    """没有 link 字段引用时应返回空列表."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_ref"})
    wid = ws.json()["id"]
    tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_ref"})
    tid = tbl.json()["id"]
    resp = client.get(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/999/references",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"references": []}
