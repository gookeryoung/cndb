"""回归：记录写后读一致性 —— create 的审计/事件 detail 含 date 等类型时不得静默失败（缓存失效丢失导致读到旧 total）."""

from __future__ import annotations


def test_create_then_list_total_fresh(client, auth_headers, db):
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_seq"})
    wid = ws.json()["id"]
    t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_seq"})
    tid = t.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "n", "field_type": "text", "order": 0},
    )
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "d", "field_type": "date", "order": 1},
    )
    url = f"/api/v1/workspaces/{wid}/tables/{tid}/records"

    def total(limit=1):
        r = client.get(url, params={"limit": limit}, headers=auth_headers)
        return r.json()["total"]

    client.post(url, headers=auth_headers, json={"values": {"n": "a", "d": "2024-01-01"}})
    assert total() == 1, "first create visible"

    # delete → list（模拟 111 的清理尾部读，填充缓存）
    r = client.get(url, params={"limit": 500}, headers=auth_headers)
    for row in r.json()["items"]:
        client.delete(f"{url}/{row['id']}", headers=auth_headers)
    assert total() == 0

    # create → list（模拟 137）：detail 含 date 也不得吞掉缓存失效
    client.post(url, headers=auth_headers, json={"values": {"n": "b", "d": "2024-06-01"}})
    t1 = total()
    t2 = total(limit=500)
    assert t1 == 1, f"limit=1 total stale: {t1}"
    assert t2 == 1, f"limit=500 total stale: {t2}"
