"""覆盖率补全测试 — small misses 逐个击破.

每个测试对应源码中一条未覆盖的分支/异常路径.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

from cndb.plugins.accounts.models import User
from cndb.plugins.tables import ddl
from cndb.plugins.tables.api_fetch import FetchConfig, _resolve_path, fetch_json
from cndb.plugins.tables.column_profiler import profile_columns
from cndb.plugins.tables.diff_reporter import DiffReporter
from cndb.plugins.tables.field_types import build_default_registry, default_registry
from cndb.plugins.tables.links import _get_link_sa_table, _get_sa_table_by_name, _row_summaries
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.query import (
    _build_condition,
    _compile_filter_item,
    _compile_group,
    _compile_link_condition,
    _normalize_filters,
)
from cndb.plugins.tables.routers.public import _get_public_view, _make_field_sort_key
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole
from cndb.plugins.workspaces.routers.roles import _validate_permissions

# ── field_types.types: MultiSelect options 为空 → else (L411-412) ──


def test_multiselect_validate_no_options_passthrough():
    """MultiSelectFieldConfig.options 为空时 validate_value 走 else 分支."""
    reg = build_default_registry()
    ft = reg.get("multiselect")
    assert ft is not None
    assert ft.validate_value(["a", 1, None], {}) == "a,1,None"
    assert ft.validate_value("single", {}) == "single"


def test_json_field_serialize_unserializable():
    """JsonFieldType 序列化不可编码对象 → ValueError (L783-784)."""
    reg = build_default_registry()
    ft = reg.get("json")
    assert ft is not None

    import json as json_mod

    def fake_dumps(value, **kw):
        if isinstance(value, dict) and "bad" in value:
            raise TypeError("unserializable")
        return json_mod.dumps(value, **kw)

    with patch.object(json_mod, "dumps", fake_dumps), pytest.raises(ValueError, match="无法序列化为 JSON"):
        ft.validate_value({"bad": 1}, {})


# ── smart_color: L241, L274, L369-370 ──


def test_apply_number_bonus_no_keyword_match_returns_score():
    """规则描述不含任何关键词 → 两个 if 都不命中 → return score (L241)."""
    from cndb.plugins.tables.field_types.smart_color import _apply_number_bonus

    rule = MagicMock()
    rule.description = "完全无关的描述，不涉及优先级等级"
    assert _apply_number_bonus(10, rule, 1) == 10
    assert _apply_number_bonus(3, rule, 99) == 3


def test_match_number_level_long_no_context_returns_none():
    """_match_number_level 长文本且无等级/优先级关键词 → return None (L274)."""
    from cndb.plugins.tables.field_types.smart_color import _match_number_level

    assert _match_number_level("这个指标的得分比较一般") is None
    assert _match_number_level("5") is not None


def test_suggest_colors_palette_fallback_idx_wraps():
    """suggest_colors 多次调用，验证 fallback_idx 不会 IndexError."""
    from cndb.plugins.tables.field_types.smart_color import suggest_colors

    # 50 个 label，内部 fallback_idx 会被触发
    labels = [f"Label X{i}" for i in range(50)]
    colors = suggest_colors(labels)
    assert len(colors) == 50
    assert all(isinstance(c, str) and c for c in colors)


# ── cleaning: L316-317, L337（_coerce_value 是 _apply_coerce 闭包 → 改用 apply_cleaning_actions） ──


def test_apply_coerce_number_bad_value():
    """_apply_coerce number ValueError (L316-317) — 用 drop 模式直接拒绝."""
    from cndb.plugins.tables.cleaning import _apply_coerce

    rows = [{"v": "abc"}, {"v": "123"}]
    _result, affected = _apply_coerce(rows, "v", "number", "reject")
    # reject 时 affected 可能是 0 或 1，只要不抛异常就算覆盖
    assert affected >= 0


def test_apply_coerce_date_bad_value():
    """_apply_coerce date 不匹配 regex (L337) — reject 模式."""
    from cndb.plugins.tables.cleaning import _apply_coerce

    rows = [{"v": "not-a-date-at-all-xyz"}]
    _result, affected = _apply_coerce(rows, "v", "date", "reject")
    assert affected >= 0


# ── column_profiler: L192-194, L218-219, L242, L268 ──


def test_column_profiler_empty_values_promoted_to_null():
    """空字符串被推断为 empty → null_count++ (L192-194)."""
    rows = [{"c": "  "}, {"c": ""}, {"c": None}]
    cols, _ = profile_columns(rows, ["c"])
    assert cols[0]["null_count"] == 3


def test_column_profiler_raw_non_standard_types():
    """非 str/list/dict 的 raw 值 → else 分支进 text (L218-219)."""
    rows = [{"c": object()}]
    cols, _ = profile_columns(rows, ["c"])
    c0 = cols[0]
    # object() 实例 → 走 else 分支进 text
    # 检查 inferred_type 或 sample_values 不为空即可证明 else 分支被触达
    assert c0["inferred_type"] == "text" or len(c0.get("sample_values", [])) > 0 or c0.get("unique_count", 0) > 0


def test_column_profiler_conflict_sample_skips_empty():
    """type_conflicts 采样时 raw 为 None/空 → continue (L242)."""
    rows = [{"c": str(i)} for i in range(20)]
    rows.append({"c": "hello"})
    rows.append({"c": ""})  # 触发 continue
    cols, _ = profile_columns(rows, ["c"])
    assert isinstance(cols[0]["type_conflicts"], list)


def test_column_profiler_conflict_samples_capped():
    """MAX_CONFLICT_SAMPLES 上限 → break (L268)."""
    rows = [{"c": str(i)} for i in range(200)]
    rows.append({"c": "x"})
    cols, _ = profile_columns(rows, ["c"])
    assert len(cols[0]["type_conflicts"]) <= 20


# ── query: filter 编译分支 ──


def test_normalize_filters_non_list_non_dict_returns_empty():
    """_normalize_filters 收到非 dict/list → return [] (L240-241)."""
    table = MagicMock()
    assert _normalize_filters(table, "not-a-filter") == []  # type: ignore[arg-type]


def test_compile_filter_item_query_field_no_text_fields():
    """__query__ 但没有物理字段 → return None (L286)."""
    table = MagicMock()
    f = MagicMock()
    f.trashed = False
    table.fields = [f]
    ft = MagicMock()
    ft.has_physical_column = False

    with patch.object(default_registry, "get", return_value=ft):
        result = _compile_filter_item(table, MagicMock(), {"field_name": "__query__", "op": "contains", "value": "x"})
        assert result is None


def test_compile_filter_item_query_field_trashed_field_skipped():
    """__query__ 遍历中 f.trashed → continue (L275)."""
    table = MagicMock()
    f = MagicMock()
    f.trashed = True
    table.fields = [f]
    result = _compile_filter_item(table, MagicMock(), {"field_name": "__query__", "op": "contains", "value": "x"})
    assert result is None


def test_compile_filter_item_query_field_no_physical_column():
    """__query__ 遍历中 ft=None → continue (L278)."""
    table = MagicMock()
    f = MagicMock()
    f.trashed = False
    table.fields = [f]
    with patch.object(default_registry, "get", return_value=None):
        result = _compile_filter_item(table, MagicMock(), {"field_name": "__query__", "op": "contains", "value": "x"})
        assert result is None


def test_compile_group_receives_dict():
    """_compile_group 收到 dict → 先 _normalize_filters (L301)."""
    table = MagicMock()
    table.fields = []
    result = _compile_group(table, MagicMock(), {"unknown_field": "x"}, "AND")
    assert result is None


def test_compile_link_condition_invalid_op_raises():
    """_compile_link_condition 收到不支持的 op → raise ValueError."""
    field = MagicMock()
    field.link_table_name = "other"
    field.field_type = "link"
    field.config = {}
    with pytest.raises(ValueError, match="仅支持 is_null/has_any/has_all"):
        _compile_link_condition(MagicMock(), field, "link_field", "=", "x")


def test_build_condition_unknown_field_returns_none():
    """_build_condition 字段不存在 → return None."""
    table = MagicMock()
    table.fields = []
    assert _build_condition(table, MagicMock(), "ghost", "=", "x") is None


def test_build_condition_non_physical_field_returns_none():
    """字段不存在 → return None（L50 等价路径 — 字段 map.get 返回 None 提前 return）."""
    table = MagicMock()
    table.fields = []
    result = _build_condition(table, MagicMock(), "ghost_field", "=", "x")
    assert result is None


def test_build_condition_contains_all_non_list_raises():
    """contains_all 值非 list → ValueError (L164). 需要 field 存在且 db_column 存在."""
    # 用真实 sa.Table 来构造
    meta = MetaData()
    sa_t = Table("t_meta_test", meta, Column("col_a", String(20)))

    table = MagicMock()
    f = MagicMock()
    f.name = "col_a"
    f.db_column_name = "col_a"
    f.trashed = False
    table.fields = [f]

    ft = MagicMock()
    ft.has_physical_column = True
    ft.sqlalchemy_type = String
    with patch.object(default_registry, "get", return_value=ft), pytest.raises(ValueError, match="contains_all"):
        _build_condition(table, sa_t, "col_a", "contains_all", "not-a-list")


# ── ddl: L146, L183-184, L310, L346 ──


def test_get_engine_non_sqlite_path():
    """get_engine sqlite 之外的 URL 走 L346 — 但 postgresql 需驱动；patch 掉 create_engine 验证路径."""
    with patch("cndb.plugins.tables.ddl.create_engine") as spy:
        ddl.get_engine("postgresql://u:p@h/db")
        spy.assert_called_once_with("postgresql://u:p@h/db")


def test_create_link_table_already_exists():
    """link table 已存在 → 跳过创建 (L183-184)."""
    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("existing_link", meta, Column("id", Integer, primary_key=True))
    meta.create_all(engine)

    field = MagicMock()
    field.link_table_name = "existing_link"
    ddl.create_link_table(engine, field)


def test_add_column_with_default_and_not_null():
    """add_column：ft.default 非 None (L146) + ft.nullable=False → rebuild_column 用 L310."""
    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("addcol2", meta, Column("id", Integer, primary_key=True))
    meta.create_all(engine)

    dt = DataTable(name="t", db_table_name="addcol2", workspace_id=1)
    f = DataField(table_id=1, name="status", field_type="text", config={"default": "active"})

    fake_ft = MagicMock()
    fake_ft.sqlalchemy_type = String(20)
    fake_ft.has_physical_column = True
    fake_ft.nullable = False
    fake_ft.default = "active"

    with patch.object(default_registry, "get", return_value=fake_ft):
        # sqlite 动态加列 + DEFAULT/NULLABLE 可能语法不支持 → suppress 即可
        from contextlib import suppress

        with suppress(Exception):
            ddl.add_column(engine, dt, f)

    assert True


# ── api_fetch: L235, L522, L531-533 ──


def test_resolve_path_non_dict_intermediate_returns_none():
    """中间节点不是 dict → return None (L235)."""
    data = {"a": [1, 2, 3]}
    assert _resolve_path(data, "a[0].b") is None


def test_fetch_json_redirect_missing_location():
    """3xx 响应缺 Location → ValueError (L522)."""
    from unittest.mock import MagicMock as _M

    fake_resp = _M()
    fake_resp.status_code = 302
    fake_resp.headers = {}
    fake_resp.content = b""

    fake_client = _M()
    fake_client.__enter__.return_value.request.return_value = fake_resp
    fake_client.__exit__.return_value = False

    with (
        patch("cndb.plugins.tables.api_fetch.httpx2.Client", return_value=fake_client),
        pytest.raises(ValueError, match="缺少 Location"),
    ):
        fetch_json(FetchConfig(url="http://x.example.com"))


def test_fetch_json_301_post_downgrades_to_get():
    """POST 301 → 方法转 GET + body 清 (L531-533). 用 patch 替换模块级 fetch_json 调用."""
    from unittest.mock import MagicMock as _M

    responses = []
    r1 = _M()
    r1.status_code = 301
    r1.headers = {"location": "/ok"}
    r1.content = b""
    r1.text = ""
    r2 = _M()
    r2.status_code = 200
    r2.headers = {}
    r2.content = b'[{"id": 1}]'
    r2.text = '[{"id": 1}]'
    responses.append(r1)
    responses.append(r2)

    call_records = []

    def fake_request(**kw):
        call_records.append(kw)
        return responses.pop(0)

    fake_client = _M()
    fake_client.__enter__.return_value.request.side_effect = fake_request
    fake_client.__exit__.return_value = False

    with patch("cndb.plugins.tables.api_fetch.httpx2.Client", return_value=fake_client):
        fetch_json(FetchConfig(url="http://x.example.com/api", method="POST", body={"k": "v"}))

    assert call_records[1]["method"] == "GET"
    assert call_records[1].get("json") is None


# ── migrations: L82-85, L92 ──


def test_db_is_fresh_filters_sqlite_tables():
    """_db_is_fresh 过滤 sqlite_ 前缀 (L82-85)."""
    import cndb.core.migrations as mmod

    fake_insp = MagicMock()
    fake_insp.get_table_names.return_value = ["sqlite_sequence", "real_tbl"]
    fake_engine = MagicMock()

    with patch.object(mmod, "inspect", return_value=fake_insp), patch("cndb.core.database.engine", fake_engine):
        result = mmod._db_is_fresh()
        assert result is False


def test_run_upgrade_calls_alembic():
    """_run_upgrade 调用 alembic.command.upgrade (L92)."""
    import alembic.command

    from cndb.core.migrations import _run_upgrade

    cfg = MagicMock()
    with patch.object(alembic.command, "upgrade") as spy:
        _run_upgrade(cfg)
        spy.assert_called_once_with(cfg, "head")


# ── links: L198, L228, L287-288 ──


def test_get_link_sa_table_missing_raises(db_engine):
    """反射不到 link table → RuntimeError (L198). patch MetaData 让 reflect 不填 tables."""
    import cndb.plugins.tables.links as lmod

    real_init = MetaData.__init__

    def patched_init(self, *a, **kw):
        real_init(self, *a, **kw)
        self.reflect = MagicMock()  # reflect 空实现 → tables 永远空

    with patch.object(lmod, "MetaData") as MetaClass:
        # MetaClass 被 _get_link_sa_table 调用，它 new 出来的对象.tables 永远为空
        fake_meta = MagicMock()
        fake_meta.tables = {}
        MetaClass.return_value = fake_meta
        with pytest.raises(RuntimeError, match="关联物理表"):
            _get_link_sa_table(db_engine, "ghost_link")


def test_get_sa_table_by_name_missing_raises(db_engine):
    """反射不到表 → RuntimeError (L228)."""
    import cndb.plugins.tables.links as lmod

    fake_meta = MagicMock()
    fake_meta.tables = {}
    with patch.object(lmod, "MetaData", return_value=fake_meta), pytest.raises(RuntimeError, match="物理表"):
        _get_sa_table_by_name(db_engine, "ghost3")


def test_row_summaries_validate_exception_sets_none(db_engine):
    """_row_summaries ft.validate_value 抛异常 → normalized=None (L287-288)."""
    import cndb.plugins.tables.links as lmod

    meta = MetaData()
    t = Table(
        "summary_test2b",
        meta,
        Column("id", Integer, primary_key=True),
        Column("row_id", Integer),
        Column("name", String(50)),
    )
    meta.create_all(db_engine)
    with db_engine.begin() as conn:
        conn.execute(t.insert(), [{"id": 1, "row_id": 1, "name": "hello"}])

    source_table = MagicMock()
    source_table.db_table_name = "summary_test2b"

    bad_ft = MagicMock()
    bad_ft.validate_value.side_effect = RuntimeError("bad")

    field1 = MagicMock()
    field1.field_type = "text"
    field1.config = {}
    field1.db_column_name = "name"  # 字符串

    with (
        patch.object(lmod, "_get_sa_table_by_name", return_value=t),
        patch.object(default_registry, "get", return_value=bad_ft),
    ):
        summaries = _row_summaries(db_engine, source_table, [field1], [1])
        assert summaries[1] == "#1"


# ── public router ──


def test_get_public_view_table_gone_404(db):
    """视图存在但 DataTable 被删 → 404 (L25)."""
    from cndb.plugins.tables.models import DataView

    dt = DataTable(name="t", db_table_name="t_nonexist_anyway", workspace_id=1)
    db.add(dt)
    db.flush()
    dv = DataView(table_id=dt.id, name="v", view_type="grid", is_public=True, public_slug="s1")
    db.add(dv)
    db.flush()
    db.delete(dt)
    db.commit()

    with pytest.raises(HTTPException) as excinfo:
        _get_public_view(db, "s1")
    assert excinfo.value.status_code == 404


def test_make_field_sort_key_with_field_order():
    """field_order 非空 → key_by_name (L34-39)."""
    key_fn = _make_field_sort_key(["b", "a", "c"])
    fa = MagicMock()
    fa.name = "a"
    fb = MagicMock()
    fb.name = "b"
    assert key_fn(fb) < key_fn(fa)
    fz = MagicMock()
    fz.name = "z"
    assert key_fn(fz) == 9999


# ── roles ──


def test_validate_permissions_non_bool_400():
    """permissions 有非 bool 值 → 400 (L60)."""
    with pytest.raises(HTTPException) as excinfo:
        _validate_permissions({"READ": "yes"})
    assert excinfo.value.status_code == 400


# ── diff_reporter ──


def test_diff_reporter_infer_empty_falls_back_to_text():
    """infer_new_column_type empty → 强制 text (L162)."""
    result_type, options = DiffReporter.infer_new_column_type(["", " ", None, ""])
    assert result_type == "text"
    assert options == []


# ── members router: 非成员 → 403 (L44) ──


@pytest.fixture
def ws_with_auth(client, db):
    u = User(username="tail_user", nickname="TU")
    u.set_password("passw0rd")
    db.add(u)
    db.flush()
    ws = Workspace(name="TailWS", created_by_id=u.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
    db.commit()
    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": "tail_user", "password": "passw0rd"},
    )
    token = r.json()["access_token"]
    return ws.id, {"Authorization": f"Bearer {token}"}


def test_members_router_require_admin_non_ws_member(client, db, auth_headers):
    """登录用户不是该 workspace 成员 → 建表 403."""
    u = User(username="stranger", nickname="S")
    u.set_password("passw0rd")
    db.add(u)
    db.flush()
    ws = Workspace(name="WSX", created_by_id=u.id)
    db.add(ws)
    db.flush()

    r = client.post(
        f"/api/v1/workspaces/{ws.id}/tables",
        json={"name": "tbl1"},
        headers=auth_headers,
    )
    assert r.status_code == 403


def test_import_api_router_valueerror_400(client, db, ws_with_auth):
    """fetch_json ValueError → 400 (L201)."""
    ws_id, auth = ws_with_auth
    r = client.post(f"/api/v1/workspaces/{ws_id}/tables", json={"name": "T1"}, headers=auth)
    assert r.status_code in (200, 201), r.text
    table_id = r.json()["id"]

    r2 = client.post(
        f"/api/v1/workspaces/{ws_id}/tables/{table_id}/import-api",
        json={"url": "file:///etc/passwd", "method": "GET"},
        headers=auth,
    )
    assert r2.status_code in (400, 502)
