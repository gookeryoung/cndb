"""links.py 端到端测试 —— 覆盖 8 个公开函数 + 内部辅助函数."""

from __future__ import annotations


def test_link_field_via_api_chain(client, auth_headers, db):
    """创建表 B（目标）、表 A（有 link 字段指向 B），写入数据，完整测试 link 链路."""
    # 建工作区
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_links"})
    wid = ws.json()["id"]

    # 表 B（目标）先建，拿到 tid_b
    tb = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "targets"})
    tid_b = tb.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_b}/fields",
        headers=auth_headers,
        json={"name": "label", "field_type": "text", "order": 0},
    )
    # 建 3 条目标数据
    for name in ["alpha", "beta", "gamma"]:
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_b}/records",
            headers=auth_headers,
            json={"values": {"label": name}},
        )
    list_b = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_b}/records/list",
        headers=auth_headers,
        json={"filters": [], "sorts": [], "limit": 10, "offset": 0},
    )
    b_row_ids = [r["id"] for r in list_b.json()["rows"]]
    assert len(b_row_ids) == 3

    # 表 A（源）建 link 字段指向 B
    ta = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "sources"})
    tid_a = ta.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_a}/fields",
        headers=auth_headers,
        json={"name": "title", "field_type": "text", "order": 0},
    )
    # link 字段：target_table_id = tid_b
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_a}/fields",
        headers=auth_headers,
        json={
            "name": "links_to_b",
            "field_type": "link",
            "order": 1,
            "config": {"target_table_id": tid_b, "multiple": True},
        },
    )

    # 表 A 写一行，带 link 值 [b_row_ids[0], b_row_ids[1]]
    ra = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_a}/records",
        headers=auth_headers,
        json={"values": {"title": "hello", "links_to_b": [b_row_ids[0], b_row_ids[1]]}},
    )
    assert ra.status_code == 201, ra.text
    a_row_id = ra.json()["id"]

    # 读回 A 行，确认 link 字段有摘要
    ga = client.get(f"/api/v1/workspaces/{wid}/tables/{tid_a}/records/{a_row_id}", headers=auth_headers)
    assert ga.status_code == 200
    row_a = ga.json()
    assert "links_to_b" in row_a
    link_val = row_a["links_to_b"]
    assert isinstance(link_val, list)
    assert len(link_val) == 2
    # 每项应有 id 和 value
    assert all("id" in item for item in link_val)

    # 反查 B 行的 references
    refs = client.get(
        f"/api/v1/workspaces/{wid}/tables/{tid_b}/records/{b_row_ids[0]}/references",
        headers=auth_headers,
    )
    assert refs.status_code == 200
    ref_data = refs.json()
    assert "references" in ref_data
    assert isinstance(ref_data["references"], list)


def test_is_link_field_and_link_fields(client, auth_headers, db):
    """单元测试：is_link_field / link_fields."""
    from cndb.plugins.tables.models import DataField, DataTable
    from cndb.plugins.tables.services.core.links import is_link_field, link_fields

    dt = DataTable(name="t_test", db_table_name="table_test123456")
    f1 = DataField(name="plain", field_type="text", db_column_name="field_plain001")
    f2 = DataField(name="rel", field_type="link", db_column_name="field_rel001")
    dt.fields = [f1, f2]

    assert is_link_field(f1) is False
    assert is_link_field(f2) is True

    links = link_fields(dt)
    assert len(links) == 1
    assert links[0].name == "rel"


def test_clear_row_links_noop_for_missing_table(db_engine, db):
    """clear_row_links 对不存在物理表不应抛错（无关联记录时的安全调用）."""
    from cndb.plugins.tables.models import DataField, DataTable
    from cndb.plugins.tables.services.core.links import clear_row_links

    dt = DataTable(name="t_empty", db_table_name="table_never_exist123456")
    f = DataField(
        name="rel",
        field_type="link",
        db_column_name="field_never_exist",
        config={"target_table_id": 999},
    )
    dt.fields = [f]
    # 物理关联表不存在时，clear_row_links 应该静默跳过
    clear_row_links(db_engine, dt, [1, 2, 3])


def test_link_table_exists(db_engine):
    """link_table_exists 对从未创建的表返回 False."""
    from cndb.plugins.tables.services.core.links import link_table_exists

    assert link_table_exists(db_engine, "link_never_created_abcdef123") is False
