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
