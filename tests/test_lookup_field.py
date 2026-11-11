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
    assert cfg.source_field_type == ""
    assert cfg.broken is False
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
        # 引入时缓存源字段类型，供前端按源类型渲染 / 筛选
        assert lookup_f["config"]["source_field_type"] == "text"
        assert lookup_f["config"].get("broken", False) is False

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


# ── B2b: 手工创建 lookup 时派生源字段类型 ──────────────


class TestLookupCreateDerivesSourceType:
    def test_create_lookup_caches_source_field_type(self, client, auth_headers, _lookup_env):
        """POST /fields 创建 lookup：后端从源字段派生并缓存 source_field_type."""
        wid, src_tid, dst_tid, _src_field = _lookup_env
        select_f = _add_field(
            client,
            auth_headers,
            wid,
            src_tid,
            "src_status",
            "select",
            config={"options": [{"label": "进行中", "value": "进行中"}]},
        )
        link_f = _add_field(
            client,
            auth_headers,
            wid,
            dst_tid,
            "关联源表",
            "link",
            config={"target_table_id": src_tid, "multiple": False},
        )
        lookup_f = _add_field(
            client,
            auth_headers,
            wid,
            dst_tid,
            "src_status",
            "lookup",
            config={
                "source_table_id": src_tid,
                "source_field_id": select_f["id"],
                "via_link_field_id": link_f["id"],
            },
        )
        assert lookup_f["config"]["source_field_type"] == "select"
        assert lookup_f["config"]["broken"] is False

    def test_create_lookup_with_missing_source_keeps_empty_type(self, client, auth_headers, _lookup_env):
        """源字段 id 解析不到时留空（不阻断创建），读取侧沿用既有容错回退 None."""
        wid, _src_tid, dst_tid, _src_field = _lookup_env
        link_f = _add_field(
            client,
            auth_headers,
            wid,
            dst_tid,
            "关联源表",
            "link",
            config={"target_table_id": _src_tid, "multiple": False},
        )
        lookup_f = _add_field(
            client,
            auth_headers,
            wid,
            dst_tid,
            "ghost",
            "lookup",
            config={"source_table_id": _src_tid, "source_field_id": 999999, "via_link_field_id": link_f["id"]},
        )
        assert lookup_f["config"]["source_field_type"] == ""


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

    def test_lookup_filter_no_longer_limited_by_scan_limit(self, client, auth_headers, _lookup_env, monkeypatch):
        """ADR 0131：冗余列下推后不再触碰全表 attach，TABLES_LOOKUP_SCAN_LIMIT 不再拦截."""
        from cndb.core.config import settings

        wid, dst_tid, _link, lookup_name, _row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        monkeypatch.setattr(settings, "TABLES_LOOKUP_SCAN_LIMIT", 2)
        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={
                "filters": [{"field_name": lookup_name, "op": "contains", "value": "a"}],
                "sorts": [],
                "limit": 10,
                "offset": 0,
            },
        )
        assert listing.status_code == 200, listing.text
        # 行 1 [alpha] 与行 2 [beta, alpha] 均含 'a'，行 3 无关联
        assert listing.json()["total"] == 2

    def test_lookup_fallback_respects_scan_limit_when_columns_disabled(
        self, client, auth_headers, _lookup_env, monkeypatch
    ):
        """回滚开关：关闭冗余列后回到内存路径，超上限仍 400 并提示收窄筛选."""
        from cndb.core.config import settings

        wid, dst_tid, _link, lookup_name, _row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)

        def _list() -> object:
            return client.post(
                f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
                headers=auth_headers,
                json={
                    "filters": [{"field_name": lookup_name, "op": "contains", "value": "a"}],
                    "sorts": [],
                    "limit": 10,
                    "offset": 0,
                },
            )

        monkeypatch.setattr(settings, "LOOKUP_COLUMNS_ENABLED", False)
        monkeypatch.setattr(settings, "TABLES_LOOKUP_SCAN_LIMIT", 2)
        rejected = _list()
        assert rejected.status_code == 400
        detail = rejected.json()["detail"]
        assert "超过上限" in detail
        # 400 正文要能定位问题：命中行数、生效上限、可操作建议
        assert "命中 3 行" in detail
        assert "上限 2 行" in detail
        assert "TABLES_LOOKUP_SCAN_LIMIT" in detail
        assert "补充普通字段筛选" in detail

        # 上限恰好等于命中行数时放行（边界不误伤）
        monkeypatch.setattr(settings, "TABLES_LOOKUP_SCAN_LIMIT", 3)
        assert _list().status_code == 200

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


class TestReadPathConnectionReuse:
    def test_list_rows_checks_out_single_connection(self, client, auth_headers, _lookup_env, db):
        """连接收敛：一次列表请求的 count / select / link 摘要 / lookup 解析共用一个连接.

        旧实现每个 link 字段 3 次、每个 lookup 字段 2 次 check-out（1 link + 1 lookup 时 6 次），
        收敛后整条读路径只在最外层取 1 个连接。
        """
        from sqlalchemy import event

        from cndb.core.cache import list_cache

        wid, dst_tid, _link, _lookup_name, _row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        url = f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list"
        payload = {"limit": 10, "offset": 0}
        assert client.post(url, headers=auth_headers, json=payload).status_code == 200
        list_cache.clear()  # 预热元数据反射后只测读路径本身，避免把反射连接算进来

        opened: list[int] = []

        def _on_connect(_conn: object) -> None:
            opened.append(1)

        engine = db.get_bind()
        event.listen(engine, "engine_connect", _on_connect)
        try:
            r = client.post(url, headers=auth_headers, json=payload)
        finally:
            event.remove(engine, "engine_connect", _on_connect)

        assert r.status_code == 200, r.text
        assert len(opened) == 1


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


# ── B4: 源字段类型同步 / 源字段失效 → lookup broken ────


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
        # 删除不等于类型变更：缓存类型保持删除前快照
        assert lookup_f["config"]["source_field_type"] == "text"

        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={"filters": [], "sorts": [], "limit": 10, "offset": 0},
        )
        assert listing.status_code == 200
        assert listing.json()["rows"][0]["src_title"] is None

    def test_change_source_type_to_select_syncs_lookup(self, client, auth_headers, _lookup_env):
        """源字段 text→select：引用字段同步缓存类型为 select，且不再标记失效."""
        wid, src_tid, dst_tid, src_field = _setup_lookup(client, auth_headers, _lookup_env)
        r = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields/{src_field['id']}",
            headers=auth_headers,
            json={"field_type": "select"},
        )
        assert r.status_code == 200, r.text

        lookup_f = next(f for f in _get_fields(client, auth_headers, wid, dst_tid) if f["field_type"] == "lookup")
        assert lookup_f["config"]["source_field_type"] == "select"
        assert lookup_f["config"].get("broken", False) is False

    def test_change_source_type_keeps_lookup_resolving(self, client, auth_headers, _lookup_env):
        """源字段 text→select 后引用值仍实时解析（不被类型变更打断）."""
        wid, src_tid, dst_tid, src_field = _setup_lookup(client, auth_headers, _lookup_env)
        r = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields/{src_field['id']}",
            headers=auth_headers,
            json={"field_type": "select", "config": {"options": [{"label": "v1", "value": "v1"}]}},
        )
        assert r.status_code == 200, r.text

        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={"filters": [], "sorts": [], "limit": 10, "offset": 0},
        )
        assert listing.status_code == 200
        assert listing.json()["rows"][0]["src_title"] == ["v1"]

    def test_change_source_type_to_link_marks_broken(self, client, auth_headers, _lookup_env):
        """源字段改为 link（无物理列）：引用字段标记失效，读取回退 None."""
        wid, src_tid, dst_tid, src_field = _setup_lookup(client, auth_headers, _lookup_env)
        r = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields/{src_field['id']}",
            headers=auth_headers,
            json={"field_type": "link", "config": {"target_table_id": dst_tid, "multiple": False}},
        )
        assert r.status_code == 200, r.text

        lookup_f = next(f for f in _get_fields(client, auth_headers, wid, dst_tid) if f["field_type"] == "lookup")
        assert lookup_f["config"]["source_field_type"] == "link"
        assert lookup_f["config"]["broken"] is True

        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={"filters": [], "sorts": [], "limit": 10, "offset": 0},
        )
        assert listing.status_code == 200
        assert listing.json()["rows"][0]["src_title"] is None

    def test_source_type_switch_back_self_heals_broken(self, client, auth_headers, _lookup_env):
        """源字段 link→text：引用字段清除失效标记并回填类型（无需重新引入）."""
        wid, src_tid, dst_tid, src_field = _setup_lookup(client, auth_headers, _lookup_env)
        base = f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields/{src_field['id']}"
        assert (
            client.patch(
                base, headers=auth_headers, json={"field_type": "link", "config": {"target_table_id": dst_tid}}
            ).status_code
            == 200
        )
        assert (
            next(f for f in _get_fields(client, auth_headers, wid, dst_tid) if f["field_type"] == "lookup")["config"][
                "broken"
            ]
            is True
        )

        r = client.patch(base, headers=auth_headers, json={"field_type": "text"})
        assert r.status_code == 200, r.text
        lookup_f = next(f for f in _get_fields(client, auth_headers, wid, dst_tid) if f["field_type"] == "lookup")
        assert lookup_f["config"]["source_field_type"] == "text"
        assert lookup_f["config"].get("broken", False) is False


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


class TestLookupScanLimitConfig:
    """TABLES_LOOKUP_SCAN_LIMIT 的取值与回退规则（默认值即原硬编码 20000）."""

    def test_default_matches_constant(self):
        from cndb.plugins.tables.services.core import records

        assert records.POST_FILTER_SCAN_LIMIT == 20_000
        assert records.post_filter_scan_limit() == 20_000

    def test_reads_setting(self, monkeypatch):
        from cndb.core.config import settings
        from cndb.plugins.tables.services.core import records

        monkeypatch.setattr(settings, "TABLES_LOOKUP_SCAN_LIMIT", 50000)
        assert records.post_filter_scan_limit() == 50000

    def test_non_positive_falls_back(self, monkeypatch):
        from cndb.core.config import settings
        from cndb.plugins.tables.services.core import records

        for bad in (0, -5):
            monkeypatch.setattr(settings, "TABLES_LOOKUP_SCAN_LIMIT", bad)
            assert records.post_filter_scan_limit() == records.POST_FILTER_SCAN_LIMIT

    def test_non_integer_falls_back(self, monkeypatch):
        from cndb.core.config import settings
        from cndb.plugins.tables.services.core import records

        for bad in ("abc", None):
            monkeypatch.setattr(settings, "TABLES_LOOKUP_SCAN_LIMIT", bad)
            assert records.post_filter_scan_limit() == records.POST_FILTER_SCAN_LIMIT


# ── B7: ADR 0131 lookup 冗余列（写入同步 / 级联 / 回填 / 新旧对拍） ──


def _lookup_storage(db, table_id: int, lookup_name: str) -> tuple[str, tuple[str, str, str]]:
    """返回 (物理表名, (joined, first, max) 列名)."""
    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.tables.services.core.lookup_columns import lookup_column_names

    table = db.get(DataTable, table_id)
    assert table is not None
    field = next(f for f in table.active_fields() if f.name == lookup_name)
    return table.db_table_name, lookup_column_names(field)


def _read_lk_rows(db, table_name: str, names: tuple[str, str, str]) -> list[tuple]:
    """直接读物理表的冗余列（绕过接口，验证落库值）."""
    from sqlalchemy import text

    db.expire_all()
    cols = ", ".join(f'"{name}"' for name in names)
    rows = db.execute(text(f'SELECT "id", {cols} FROM "{table_name}" ORDER BY "id"')).all()
    db.rollback()
    return [tuple(row) for row in rows]


def _src_ids(client, auth_headers, wid: int, src_tid: int) -> dict[str, int]:
    listing = client.post(
        f"/api/v1/workspaces/{wid}/tables/{src_tid}/records/list",
        headers=auth_headers,
        json={"filters": [], "sorts": [], "limit": 50, "offset": 0},
    )
    assert listing.status_code == 200, listing.text
    return {row["src_title"]: row["id"] for row in listing.json()["rows"]}


class TestLookupRedundantColumns:
    def test_create_writes_redundant_columns(self, client, auth_headers, _lookup_env, db):
        """创建行时同事务写入 joined / first / max；无关联多值落 ''、first/max 为 NULL."""
        _wid, dst_tid, _link, lookup_name, row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        table_name, names = _lookup_storage(db, dst_tid, lookup_name)
        rows = _read_lk_rows(db, table_name, names)
        assert rows == [
            (row_ids[0], "alpha", "alpha", "alpha"),
            (row_ids[1], "beta\x1falpha", "alpha", "beta"),
            (row_ids[2], "", None, None),
        ]

    def test_columns_are_internal_and_api_stays_live(self, client, auth_headers, _lookup_env):
        """冗余列不出现在接口返回里；lookup 输出仍是实时解析值."""
        wid, dst_tid, _link, lookup_name, row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={"sorts": [], "limit": 10, "offset": 0},
        )
        assert listing.status_code == 200, listing.text
        row = next(r for r in listing.json()["rows"] if r["id"] == row_ids[1])
        assert row[lookup_name] == ["beta", "alpha"]
        assert not any(str(key).startswith("_lk_") for key in row)

    def test_update_link_resyncs_columns(self, client, auth_headers, _lookup_env, db):
        """修改 link 值后冗余列同步重算（清空关联 → joined=''）."""
        wid, dst_tid, link_name, lookup_name, row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        r = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/{row_ids[1]}",
            headers=auth_headers,
            json={"values": {link_name: []}},
        )
        assert r.status_code == 200, r.text
        table_name, names = _lookup_storage(db, dst_tid, lookup_name)
        rows = _read_lk_rows(db, table_name, names)
        assert rows[1] == (row_ids[1], "", None, None)

    def test_source_value_change_cascades(self, client, auth_headers, _lookup_env, db):
        """源表字段值更新 → 引用它的消费方冗余列级联重算."""
        wid, src_tid, dst_tid, _src_field = _lookup_env
        _wid, _dst, _link, lookup_name, row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        alpha_id = _src_ids(client, auth_headers, wid, src_tid)["alpha"]
        r = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/records/{alpha_id}",
            headers=auth_headers,
            json={"values": {"src_title": "zeta"}},
        )
        assert r.status_code == 200, r.text

        table_name, names = _lookup_storage(db, dst_tid, lookup_name)
        rows = _read_lk_rows(db, table_name, names)
        assert rows[0] == (row_ids[0], "zeta", "zeta", "zeta")
        assert rows[1] == (row_ids[1], "beta\x1fzeta", "beta", "zeta")

        listing = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list",
            headers=auth_headers,
            json={
                "filters": [{"field_name": lookup_name, "op": "contains", "value": "zeta"}],
                "sorts": [],
                "limit": 10,
                "offset": 0,
            },
        )
        assert listing.status_code == 200, listing.text
        assert listing.json()["total"] == 2

    def test_target_row_delete_cascades(self, client, auth_headers, _lookup_env, db):
        """目标行硬删除后，消费方 lookup 值同步失效（不再返回已删目标的值）."""
        from cndb.plugins.tables.models import DataTable
        from cndb.plugins.tables.services.core.records import delete_row

        wid, src_tid, dst_tid, _src_field = _lookup_env
        _wid, _dst, _link, lookup_name, row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        alpha_id = _src_ids(client, auth_headers, wid, src_tid)["alpha"]
        src_table = db.get(DataTable, src_tid)
        assert delete_row(db.get_bind(), src_table, alpha_id, db=db) is True

        table_name, names = _lookup_storage(db, dst_tid, lookup_name)
        rows = _read_lk_rows(db, table_name, names)
        assert rows[0] == (row_ids[0], "", None, None)
        assert rows[1] == (row_ids[1], "beta", "beta", "beta")

    def test_bulk_create_syncs_columns(self, client, auth_headers, _lookup_env, db):
        """批量创建路径同样维护冗余列."""
        wid, src_tid, dst_tid, _src_field = _lookup_env
        _wid, _dst, link_name, lookup_name, _row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        beta_id = _src_ids(client, auth_headers, wid, src_tid)["beta"]
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/bulk-create",
            headers=auth_headers,
            json={"rows": [{"values": {link_name: [beta_id]}}, {"values": {}}]},
        )
        assert r.status_code == 201, r.text
        assert r.json()["created"] == 2

        table_name, names = _lookup_storage(db, dst_tid, lookup_name)
        rows = _read_lk_rows(db, table_name, names)
        assert rows[-2][1:] == ("beta", "beta", "beta")
        assert rows[-1][1:] == ("", None, None)

    def test_backfill_restores_stale_columns(self, client, auth_headers, _lookup_env, db):
        """回填命令把人为清空的冗余列恢复为正确值（幂等可重入）."""
        from sqlalchemy import text

        from cndb.plugins.tables.models import DataTable
        from cndb.plugins.tables.services.core.lookup_sync import backfill_lookup_columns

        _wid, dst_tid, _link, lookup_name, _row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        table_name, names = _lookup_storage(db, dst_tid, lookup_name)
        expected = _read_lk_rows(db, table_name, names)

        joined = ", ".join(f'"{name}" = NULL' for name in names)
        db.execute(text(f'UPDATE "{table_name}" SET {joined}'))
        db.commit()
        assert all(row[1:] == (None, None, None) for row in _read_lk_rows(db, table_name, names))

        table = db.get(DataTable, dst_tid)
        assert backfill_lookup_columns(db.get_bind(), table, db=db) == 3
        assert _read_lk_rows(db, table_name, names) == expected
        # 再跑一次仍幂等
        assert backfill_lookup_columns(db.get_bind(), table, db=db) == 3
        assert _read_lk_rows(db, table_name, names) == expected

    def test_cli_backfill_reports_tables(self, client, auth_headers, _lookup_env, db, monkeypatch):
        """cndb lookup backfill：按表回填并返回结构化报告."""
        import argparse

        from cndb.cli import lookup as cli_lookup

        _wid, dst_tid, _link, _lookup_name, _row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        monkeypatch.setattr(cli_lookup, "_get_session", lambda: db)
        payload = cli_lookup.cmd_backfill(argparse.Namespace(workspace=None, table=str(dst_tid), batch_size=None))
        assert payload["failures"] == 0
        assert payload["processed_tables"] == 1
        assert payload["tables"][0]["table_id"] == dst_tid
        assert payload["tables"][0]["rows"] == 3

    @pytest.mark.parametrize(
        ("filters", "filter_logic"),
        [
            ([{"field_name": "__lookup__", "op": "contains", "value": "a"}], "AND"),
            ([{"field_name": "__lookup__", "op": "contains_any", "value": ["beta", "gamma"]}], "AND"),
            ([{"field_name": "__lookup__", "op": "contains_all", "value": ["alpha", "beta"]}], "AND"),
            ([{"field_name": "__lookup__", "op": "=", "value": ["beta", "alpha"]}], "AND"),
            ([{"field_name": "__lookup__", "op": "!=", "value": ["alpha"]}], "AND"),
            ([{"field_name": "__lookup__", "op": "in", "value": ["alpha"]}], "AND"),
            ([{"field_name": "__lookup__", "op": "not_in", "value": ["alpha"]}], "AND"),
            ([{"field_name": "__lookup__", "op": "is_empty", "value": None}], "AND"),
            ([{"field_name": "__lookup__", "op": "is_not_empty", "value": None}], "AND"),
            ([{"field_name": "__lookup__", "op": "starts_with", "value": "b"}], "AND"),
            ([{"field_name": "__lookup__", "op": "ends_with", "value": "a"}], "AND"),
            ([{"field_name": "__lookup__", "op": ">", "value": "b"}], "AND"),
            ([{"field_name": "__lookup__", "op": "<=", "value": "alpha"}], "AND"),
            ([{"field_name": "__lookup__", "op": "contains", "value": "beta"}], "OR"),
        ],
    )
    def test_pushdown_matches_memory_path(self, client, auth_headers, _lookup_env, monkeypatch, filters, filter_logic):
        """同一数据下新旧路径的命中行与总数一致（ADR 0131 一致性对拍）."""
        from cndb.core.config import settings

        wid, dst_tid, _link, lookup_name, _row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        payload = {
            "filters": [{**item, "field_name": lookup_name} for item in filters],
            "filter_logic": filter_logic,
            "sorts": [],
            "limit": 10,
            "offset": 0,
        }
        url = f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list"

        monkeypatch.setattr(settings, "LOOKUP_COLUMNS_ENABLED", True)
        pushed = client.post(url, headers=auth_headers, json=payload)
        assert pushed.status_code == 200, pushed.text

        monkeypatch.setattr(settings, "LOOKUP_COLUMNS_ENABLED", False)
        memory = client.post(url, headers=auth_headers, json=payload)
        assert memory.status_code == 200, memory.text

        assert pushed.json()["total"] == memory.json()["total"]
        assert [r["id"] for r in pushed.json()["rows"]] == [r["id"] for r in memory.json()["rows"]]

    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_pushdown_sort_matches_memory_path(self, client, auth_headers, _lookup_env, monkeypatch, direction):
        """lookup 排序下推（asc 用 first / desc 用 max，NULL 最后）与内存排序一致."""
        from cndb.core.config import settings

        wid, dst_tid, _link, lookup_name, _row_ids = _setup_lookup_rows(client, auth_headers, _lookup_env)
        url = f"/api/v1/workspaces/{wid}/tables/{dst_tid}/records/list"
        payload = {"sorts": [{"field_name": lookup_name, "direction": direction}], "limit": 10, "offset": 0}

        monkeypatch.setattr(settings, "LOOKUP_COLUMNS_ENABLED", True)
        pushed = client.post(url, headers=auth_headers, json=payload)
        assert pushed.status_code == 200, pushed.text

        monkeypatch.setattr(settings, "LOOKUP_COLUMNS_ENABLED", False)
        memory = client.post(url, headers=auth_headers, json=payload)
        assert memory.status_code == 200, memory.text

        assert [r["id"] for r in pushed.json()["rows"]] == [r["id"] for r in memory.json()["rows"]]
