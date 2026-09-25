"""lookup 字段类型（引用查找）— B1 行为切片.

覆盖矩阵：
┌──────────────────────────────┬──────────────────────────────────┐
│ 场景                          │ 关键断言                          │
├──────────────────────────────┼──────────────────────────────────┤
│ 注册表含 lookup 类型          │ default_registry.get 返回实例     │
│ 无物理列                      │ has_physical_column is False      │
│ make_column 拒绝             │ RuntimeError                      │
│ 值只读：validate_value 恒 None│ 写入值被丢弃                      │
│ config 结构                  │ source_table_id/source_field_id/  │
│                              │ via_link_field_id 必填            │
└──────────────────────────────┴──────────────────────────────────┘
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cndb.plugins.tables.field_types import default_registry


def test_lookup_field_registered() -> None:
    ft = default_registry.get("lookup")
    assert ft is not None
    assert ft.name == "lookup"
    assert ft.has_physical_column is False


def test_lookup_make_column_rejected() -> None:
    ft = default_registry.get("lookup")
    assert ft is not None
    with pytest.raises(RuntimeError):
        ft.make_column("some_col")


def test_lookup_value_readonly() -> None:
    """lookup 字段只读：任何写入值都应被丢弃为 None."""
    ft = default_registry.get("lookup")
    assert ft is not None
    config = {"source_table_id": 1, "source_field_id": 2, "via_link_field_id": 3}
    assert ft.validate_value(None, config) is None
    assert ft.validate_value(["x", 1], config) is None


def test_lookup_config_required_fields() -> None:
    """config 缺少必填项时应校验失败."""
    from cndb.plugins.tables.field_types.lookup import LookupFieldConfig
    from cndb.plugins.tables.field_types.relation import LinkFieldConfig  # noqa: F401  保证 relation 模块已加载

    cfg = LookupFieldConfig(source_table_id=1, source_field_id=2, via_link_field_id=3)
    assert cfg.source_table_id == 1
    assert cfg.display_field_id is None
    with pytest.raises(ValidationError):
        LookupFieldConfig(source_table_id=1)  # type: ignore[call-arg]


# ── 辅助：建源表/目标表 ───────────────────────────────


def _create_table(client, auth_headers, wid: int, name: str) -> int:
    r = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add_field(
    client, auth_headers, wid: int, tid: int, name: str, field_type: str, config: dict | None = None
) -> dict:
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": name, "field_type": field_type, "config": config or {}},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _get_fields(client, auth_headers, wid: int, tid: int) -> list[dict]:
    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/fields", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def _lookup_env(client, auth_headers, db):
    """源表（1 个 text 字段）+ 目标表（空）."""
    r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WS_LOOKUP"})
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    src_tid = _create_table(client, auth_headers, wid, "SrcLookup")
    dst_tid = _create_table(client, auth_headers, wid, "DstLookup")
    src_field = _add_field(client, auth_headers, wid, src_tid, "src_title", "text")
    return wid, src_tid, dst_tid, src_field


# ── B2: 字段引入 link 模式 ───────────────────────────


class TestFieldImportLinkMode:
    def test_import_link_mode_creates_link_and_lookup(self, client, auth_headers, _lookup_env):
        wid, src_tid, dst_tid, src_field = _lookup_env
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "field_ids": [src_field["id"]], "import_mode": "link"},
        )
        assert r.status_code == 201, r.text
        fields = _get_fields(client, auth_headers, wid, dst_tid)
        types = sorted(f["field_type"] for f in fields)
        assert types == ["link", "lookup"]

        link_f = next(f for f in fields if f["field_type"] == "link")
        lookup_f = next(f for f in fields if f["field_type"] == "lookup")
        assert link_f["config"]["target_table_id"] == src_tid
        assert lookup_f["config"]["source_table_id"] == src_tid
        assert lookup_f["config"]["source_field_id"] == src_field["id"]
        assert lookup_f["config"]["via_link_field_id"] == link_f["id"]

    def test_import_link_mode_reuses_existing_link_field(self, client, auth_headers, _lookup_env):
        """第二次 link 引入应复用已有 link 字段，只新增 lookup 字段."""
        wid, src_tid, dst_tid, src_field = _lookup_env
        _add_field(client, auth_headers, wid, src_tid, "src_price", "number")
        fields_src = _get_fields(client, auth_headers, wid, src_tid)
        first_import = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "field_ids": [src_field["id"]], "import_mode": "link"},
        )
        assert first_import.status_code == 201, first_import.text

        price_field = next(f for f in fields_src if f["name"] == "src_price")
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "field_ids": [price_field["id"]], "import_mode": "link"},
        )
        assert r.status_code == 201, r.text
        fields = _get_fields(client, auth_headers, wid, dst_tid)
        assert sum(1 for f in fields if f["field_type"] == "link") == 1
        assert sum(1 for f in fields if f["field_type"] == "lookup") == 2

    def test_import_link_mode_skips_link_source_fields(self, client, auth_headers, _lookup_env):
        """link/lookup 类型的源字段不支持关联引入，应跳过并说明."""
        wid, src_tid, dst_tid, _src_field = _lookup_env
        link_src = _add_field(
            client, auth_headers, wid, src_tid, "src_link", "link", config={"target_table_id": dst_tid}
        )
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "field_ids": [link_src["id"]], "import_mode": "link"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["created"] == []
        assert any("link" in s or "lookup" in s for s in body["skipped"])

    def test_import_copy_mode_unchanged(self, client, auth_headers, _lookup_env):
        """回归：默认 copy 模式行为与现状一致（只克隆字段本身）."""
        wid, src_tid, dst_tid, src_field = _lookup_env
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "field_ids": [src_field["id"]]},
        )
        assert r.status_code == 201, r.text
        fields = _get_fields(client, auth_headers, wid, dst_tid)
        assert [f["field_type"] for f in fields] == ["text"]


# ── B3: 行读取时 lookup 值解析 ───────────────────────


class TestLookupValueResolution:
    def test_row_read_resolves_lookup_values(self, client, auth_headers, _lookup_env):
        """dst 行 link 到 2 个源行时，lookup 字段返回聚合列表；无关联返回 None."""
        wid, src_tid, dst_tid, src_field = _lookup_env
        # 源表造 2 行
        src_ids = []
        for title in ("alpha", "beta"):
            r = client.post(
                f"/api/v1/workspaces/{wid}/tables/{src_tid}/records",
                headers=auth_headers,
                json={"values": {"src_title": title}},
            )
            assert r.status_code == 201, r.text
            src_ids.append(r.json()["id"])

        # link 模式引入
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "field_ids": [src_field["id"]], "import_mode": "link"},
        )
        assert r.status_code == 201, r.text
        link_name = next(f["name"] for f in r.json()["created"] if f["field_type"] == "link")

        # dst 行 1：关联 2 行 → 聚合列表
        r1 = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records",
            headers=auth_headers,
            json={"values": {link_name: src_ids}},
        )
        assert r1.status_code == 201, r1.text
        row1 = client.get(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/{r1.json()['id']}",
            headers=auth_headers,
        ).json()
        assert row1["src_title"] == ["alpha", "beta"]

        # dst 行 2：无关联 → None
        r2 = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records",
            headers=auth_headers,
            json={"values": {}},
        )
        assert r2.status_code == 201, r2.text
        row2 = client.get(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/{r2.json()['id']}",
            headers=auth_headers,
        ).json()
        assert row2["src_title"] is None

    def test_list_rows_resolves_lookup_values(self, client, auth_headers, _lookup_env):
        """列表查询同样解析 lookup 值."""
        wid, src_tid, dst_tid, src_field = _lookup_env
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/records",
            headers=auth_headers,
            json={"values": {"src_title": "solo"}},
        )
        src_row_id = r.json()["id"]
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "field_ids": [src_field["id"]], "import_mode": "link"},
        )
        link_name = next(f["name"] for f in r.json()["created"] if f["field_type"] == "link")
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records",
            headers=auth_headers,
            json={"values": {link_name: [src_row_id]}},
        )
        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={"filters": [], "sorts": [], "limit": 10, "offset": 0},
        )
        assert listing.status_code == 200, listing.text
        rows = listing.json()["rows"]
        assert rows[0]["src_title"] == ["solo"]


# ── C1: lookup 字段过滤 / 排序 ───────────────────────


def _setup_lookup_rows(client, auth_headers, _lookup_env):
    """引入 lookup 后造 3 条源行 + 3 条 dst 关联行，返回上下文与行值映射.

    dst 行 1 关联 [alpha]，行 2 关联 [beta, alpha]，行 3 无关联。
    """
    wid, src_tid, dst_tid, src_field = _lookup_env
    src_ids: dict[str, int] = {}
    for title in ("alpha", "beta", "gamma"):
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/records",
            headers=auth_headers,
            json={"values": {"src_title": title}},
        )
        assert r.status_code == 201, r.text
        src_ids[title] = r.json()["id"]

    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
        headers=auth_headers,
        json={"source_table_id": src_tid, "field_ids": [src_field["id"]], "import_mode": "link"},
    )
    assert r.status_code == 201, r.text
    created = r.json()["created"]
    link_name = next(f["name"] for f in created if f["field_type"] == "link")
    lookup_name = next(f["name"] for f in created if f["field_type"] == "lookup")

    row_ids: list[int] = []
    for targets in ([src_ids["alpha"]], [src_ids["beta"], src_ids["alpha"]], []):
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records",
            headers=auth_headers,
            json={"values": {link_name: targets} if targets else {}},
        )
        assert r.status_code == 201, r.text
        row_ids.append(r.json()["id"])
    return wid, dst_tid, link_name, lookup_name, row_ids


class TestLookupFilterSort:
    def test_filter_lookup_contains(self, client, auth_headers, _lookup_env):
        """lookup 字段 contains 过滤：命中包含 'beta' 的行."""
        wid, dst_tid, _link, lookup_name, row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={
                "filters": [{"field_name": lookup_name, "op": "contains", "value": "beta"}],
                "sorts": [],
                "limit": 10,
                "offset": 0,
            },
        )
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["total"] == 1
        assert [r["id"] for r in body["rows"]] == [row_ids[1]]

    def test_filter_lookup_eq_scalar(self, client, auth_headers, _lookup_env):
        """lookup 字段 = 过滤：multiple link 下标量为列表精确匹配."""
        wid, dst_tid, _link, lookup_name, row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={
                "filters": [{"field_name": lookup_name, "op": "=", "value": ["alpha"]}],
                "sorts": [],
                "limit": 10,
                "offset": 0,
            },
        )
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["total"] == 1
        assert [r["id"] for r in body["rows"]] == [row_ids[0]]

    def test_filter_lookup_is_empty(self, client, auth_headers, _lookup_env):
        """lookup 字段 is_empty 过滤：命中无关联行."""
        wid, dst_tid, _link, lookup_name, row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={
                "filters": [{"field_name": lookup_name, "op": "is_empty", "value": None}],
                "sorts": [],
                "limit": 10,
                "offset": 0,
            },
        )
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["total"] == 1
        assert [r["id"] for r in body["rows"]] == [row_ids[2]]

    def test_sort_lookup_asc_desc(self, client, auth_headers, _lookup_env):
        """lookup 字段排序：asc/desc 按解析值比较，None 值排最后."""
        wid, dst_tid, _link, lookup_name, row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)

        def _list(direction: str) -> list[int]:
            listing = client.post(
                f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
                headers=auth_headers,
                json={
                    "filters": [],
                    "sorts": [{"field_name": lookup_name, "direction": direction}],
                    "limit": 10,
                    "offset": 0,
                },
            )
            assert listing.status_code == 200, listing.text
            return [r["id"] for r in listing.json()["rows"]]

        asc = _list("asc")
        desc = _list("desc")
        assert asc == [row_ids[0], row_ids[1], row_ids[2]]  # alpha < beta.. < None
        assert desc == [row_ids[1], row_ids[0], row_ids[2]]  # None 仍排最后

    def test_lookup_filter_with_pagination(self, client, auth_headers, _lookup_env):
        """lookup 过滤后 total 与分页一致."""
        wid, dst_tid, _link, lookup_name, _row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={
                "filters": [{"field_name": lookup_name, "op": "contains", "value": "a"}],
                "sorts": [],
                "limit": 1,
                "offset": 0,
            },
        )
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["total"] == 2  # alpha 出现于行 1、行 2
        assert len(body["rows"]) == 1


# ── C2: 嵌套分组（or/and）中的 lookup 条件 ────────────


def _setup_lookup_rows_with_tag(client, auth_headers, _lookup_env):
    """在 _setup_lookup_rows 基础上给 dst 表加 text 字段 dst_tag 并赋值.

    dst 行 1：lookup=[alpha]，dst_tag=x；行 2：lookup=[beta, alpha]，dst_tag=y；
    行 3：无关联，dst_tag=z。
    """
    wid, dst_tid, _link_name, lookup_name, row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
    _add_field(client, auth_headers, wid, dst_tid, "dst_tag", "text")
    tags = ["x", "y", "z"]
    for rid, tag in zip(row_ids, tags, strict=True):
        r = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/{rid}",
            headers=auth_headers,
            json={"values": {"dst_tag": tag}},
        )
        assert r.status_code == 200, r.text
    return wid, dst_tid, lookup_name, row_ids


class TestLookupNestedFilter:
    def test_or_group_with_lookup(self, client, auth_headers, _lookup_env):
        """__or__ 分组含 lookup 条件：命中 lookup 含 beta 或 dst_tag=x 的行."""
        wid, dst_tid, lookup_name, row_ids = _setup_lookup_rows_with_tag(client, auth_headers, _lookup_env)
        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={
                "filters": [
                    {
                        "__or__": [
                            {"field_name": lookup_name, "op": "contains", "value": "beta"},
                            {"field_name": "dst_tag", "op": "=", "value": "x"},
                        ]
                    }
                ],
                "sorts": [],
                "limit": 10,
                "offset": 0,
            },
        )
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["total"] == 2
        assert [r["id"] for r in body["rows"]] == [row_ids[0], row_ids[1]]

    def test_and_group_with_lookup(self, client, auth_headers, _lookup_env):
        """__and__ 分组含 lookup 条件：组内物理列条件一并内存求值."""
        wid, dst_tid, lookup_name, row_ids = _setup_lookup_rows_with_tag(client, auth_headers, _lookup_env)
        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={
                "filters": [
                    {
                        "__and__": [
                            {"field_name": lookup_name, "op": "contains", "value": "a"},
                            {"field_name": "dst_tag", "op": "=", "value": "y"},
                        ]
                    }
                ],
                "sorts": [],
                "limit": 10,
                "offset": 0,
            },
        )
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["total"] == 1
        assert [r["id"] for r in body["rows"]] == [row_ids[1]]

    def test_or_logic_mixing_sql_and_lookup(self, client, auth_headers, _lookup_env):
        """filter_logic=OR 且顶层 SQL 条件与 lookup 条件混合：整体 OR 语义."""
        wid, dst_tid, lookup_name, row_ids = _setup_lookup_rows_with_tag(client, auth_headers, _lookup_env)
        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={
                "filters": [
                    {"field_name": lookup_name, "op": "contains", "value": "beta"},
                    {"field_name": "dst_tag", "op": "=", "value": "z"},
                ],
                "filter_logic": "OR",
                "sorts": [],
                "limit": 10,
                "offset": 0,
            },
        )
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["total"] == 2
        assert [r["id"] for r in body["rows"]] == [row_ids[1], row_ids[2]]

    def test_and_logic_mixing_sql_and_lookup(self, client, auth_headers, _lookup_env):
        """filter_logic=AND 混合：SQL 条件下推，lookup 条件内存过滤，取交集."""
        wid, dst_tid, lookup_name, _row_ids = _setup_lookup_rows_with_tag(client, auth_headers, _lookup_env)
        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={
                "filters": [
                    {"field_name": lookup_name, "op": "contains", "value": "a"},
                    {"field_name": "dst_tag", "op": "=", "value": "z"},
                ],
                "filter_logic": "AND",
                "sorts": [],
                "limit": 10,
                "offset": 0,
            },
        )
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["total"] == 0


# ── B4: 源字段失效 → lookup broken ───────────────────


def _setup_lookup(client, auth_headers, _lookup_env):
    """引入 lookup 并造 1 条源行 + 1 条关联行，返回上下文."""
    wid, src_tid, dst_tid, src_field = _lookup_env
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{src_tid}/records",
        headers=auth_headers,
        json={"values": {"src_title": "v1"}},
    )
    src_row_id = r.json()["id"]
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
        headers=auth_headers,
        json={"source_table_id": src_tid, "field_ids": [src_field["id"]], "import_mode": "link"},
    )
    created = r.json()["created"]
    link_name = next(f["name"] for f in created if f["field_type"] == "link")
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records",
        headers=auth_headers,
        json={"values": {link_name: [src_row_id]}},
    )
    return wid, src_tid, dst_tid, src_field


class TestLookupBrokenSource:
    def test_delete_source_field_marks_broken(self, client, auth_headers, _lookup_env):
        """删除源字段后：lookup config.broken=True，读取返回 None 不抛错."""
        wid, src_tid, dst_tid, src_field = _setup_lookup(client, auth_headers, _lookup_env)
        r = client.delete(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields/{src_field['id']}",
            headers=auth_headers,
        )
        assert r.status_code == 204, r.text

        dst_fields = _get_fields(client, auth_headers, wid, dst_tid)
        lookup_f = next(f for f in dst_fields if f["field_type"] == "lookup")
        assert lookup_f["config"]["broken"] is True

        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={"filters": [], "sorts": [], "limit": 10, "offset": 0},
        )
        assert listing.status_code == 200
        assert listing.json()["rows"][0]["src_title"] is None

    def test_change_source_field_type_marks_broken(self, client, auth_headers, _lookup_env):
        """源字段改类型后：lookup config.broken=True."""
        wid, src_tid, dst_tid, src_field = _setup_lookup(client, auth_headers, _lookup_env)
        r = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields/{src_field['id']}",
            headers=auth_headers,
            json={"field_type": "number"},
        )
        assert r.status_code == 200, r.text
        dst_fields = _get_fields(client, auth_headers, wid, dst_tid)
        lookup_f = next(f for f in dst_fields if f["field_type"] == "lookup")
        assert lookup_f["config"]["broken"] is True


# ── B5: preview_only + link 模式组合 ─────────────────


class TestLinkModePreview:
    def test_preview_link_mode_returns_plan_without_creating(self, client, auth_headers, _lookup_env):
        """预览返回将创建的 link/lookup 字段清单，且不落库."""
        wid, src_tid, dst_tid, src_field = _lookup_env
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "field_ids": [src_field["id"]],
                "import_mode": "link",
                "preview_only": True,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["created"] == []
        planned = body["gap_analysis"]["planned_fields"]
        planned_types = sorted(p["field_type"] for p in planned)
        assert planned_types == ["link", "lookup"]
        # 未实际创建
        assert _get_fields(client, auth_headers, wid, dst_tid) == []


# ── 写入回归：整行表单回传 lookup 值不得 500 ─────────


def _setup_dept_emp_single_link(client, auth_headers):
    """构造「部门表 → 员工表」单选关联 + 负责人 lookup 环境.

    复刻 seed 业务形态：部门表（部门名称/负责人），员工表
    （姓名/部门=单选 link/负责人=lookup 经部门字段解析）。
    返回 (wid, dept_tid, emp_tid, dept_rows)，dept_rows 为 {部门名称: 行id}。
    """
    r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WS_LOOKUP_WRITE"})
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    dept_tid = _create_table(client, auth_headers, wid, "部门表")
    emp_tid = _create_table(client, auth_headers, wid, "员工表")

    _add_field(client, auth_headers, wid, dept_tid, "部门名称", "text")
    _add_field(client, auth_headers, wid, dept_tid, "负责人", "text")
    _add_field(client, auth_headers, wid, emp_tid, "姓名", "text")
    link_field = _add_field(
        client,
        auth_headers,
        wid,
        emp_tid,
        "部门",
        "link",
        {"target_table_id": dept_tid, "multiple": False},
    )
    _add_field(
        client,
        auth_headers,
        wid,
        emp_tid,
        "负责人",
        "lookup",
        {
            "source_table_id": dept_tid,
            "source_field_id": next(
                f for f in _get_fields(client, auth_headers, wid, dept_tid) if f["name"] == "负责人"
            )["id"],
            "via_link_field_id": link_field["id"],
        },
    )

    dept_rows: dict[str, int] = {}
    for dname, head in [("技术部", "张三"), ("市场部", "李四")]:
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dept_tid}/records",
            headers=auth_headers,
            json={"values": {"部门名称": dname, "负责人": head}},
        )
        assert r.status_code == 201, r.text
        dept_rows[dname] = r.json()["id"]
    return wid, dept_tid, emp_tid, dept_rows


class TestLookupWritePayloadIgnored:
    """整行表单（含 lookup 原值回传）写入场景 —— 历史上曾 500（CompileError）."""

    def test_create_row_echo_lookup_value_ok(self, client, auth_headers):
        """新建行 values 同时携带单选 link 与 lookup 回传值：201 且 lookup 实时解析."""
        wid, _dept_tid, emp_tid, dept_rows = _setup_dept_emp_single_link(client, auth_headers)
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{emp_tid}/records",
            headers=auth_headers,
            json={"values": {"姓名": "李四", "部门": [dept_rows["市场部"]], "负责人": "李四"}},
        )
        assert r.status_code == 201, r.text
        row = r.json()
        assert row["负责人"] == "李四"

    def test_update_row_echo_lookup_value_ok(self, client, auth_headers):
        """编辑修改部门字段（整行表单回传 lookup 原值）：200 且 lookup 随新关联重算."""
        wid, _dept_tid, emp_tid, dept_rows = _setup_dept_emp_single_link(client, auth_headers)
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{emp_tid}/records",
            headers=auth_headers,
            json={"values": {"姓名": "张三", "部门": [dept_rows["技术部"]]}},
        )
        assert r.status_code == 201, r.text
        row_id = r.json()["id"]
        assert r.json()["负责人"] == "张三"

        # 改部门为市场部（同时把表单中的 lookup 原值回传，模拟整行编辑提交）
        r = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{emp_tid}/records/{row_id}",
            headers=auth_headers,
            json={"values": {"姓名": "张三", "部门": [dept_rows["市场部"]], "负责人": "张三"}},
        )
        assert r.status_code == 200, r.text
        assert r.json()["负责人"] == "李四"

    def test_bulk_create_echo_lookup_value_ok(self, client, auth_headers):
        """批量创建行携带 lookup 值：201，逐行解析正确."""
        wid, _dept_tid, emp_tid, dept_rows = _setup_dept_emp_single_link(client, auth_headers)
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{emp_tid}/records/bulk-create",
            headers=auth_headers,
            json={
                "rows": [
                    {"values": {"姓名": "张三", "部门": [dept_rows["技术部"]], "负责人": "张三"}},
                    {"values": {"姓名": "李四", "部门": [dept_rows["市场部"]], "负责人": "李四"}},
                ]
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["created"] == 2

        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{emp_tid}/records/list",
            headers=auth_headers,
            json={"filters": [], "sorts": [], "limit": 10, "offset": 0},
        )
        assert listing.status_code == 200, listing.text
        heads = {row["姓名"]: row["负责人"] for row in listing.json()["rows"]}
        assert heads == {"张三": "张三", "李四": "李四"}
