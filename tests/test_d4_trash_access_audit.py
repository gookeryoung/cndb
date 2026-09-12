"""D 阶段综合测试：trash + access + audit + links + field_types 新类型.

覆盖 D1 links.py / D2 access.py / D3 audit.py / D4 routers/trash.py / D5 新 field_types.
"""

from __future__ import annotations

import pytest

from cndb.plugins.tables.access import (
    TableAction,
    apply_field_hiding,
    apply_field_hiding_rows,
)
from cndb.plugins.tables.audit import ACTION_CREATE, query_row_history, query_table_history
from cndb.plugins.tables.field_types import (
    EmailFieldType,
    PercentageFieldType,
    PhoneFieldType,
    TimestampFieldType,
    UrlFieldType,
    default_registry,
)
from cndb.plugins.tables.links import (
    is_link_field,
    link_table_exists,
)

# ── D5 新字段类型单元测试 ────────────────────────────


class TestEmailFieldType:
    def test_valid_email(self):
        ft = EmailFieldType()
        assert ft.validate_value("a.b@c.com", {}) == "a.b@c.com"

    def test_uppercase_normalized(self):
        ft = EmailFieldType()
        assert ft.validate_value("USER@EXAMPLE.COM", {}) == "user@example.com"

    def test_invalid_email(self):
        ft = EmailFieldType()
        with pytest.raises(ValueError):
            ft.validate_value("not-an-email", {})

    def test_none_passthrough(self):
        ft = EmailFieldType()
        assert ft.validate_value(None, {}) is None


class TestUrlFieldType:
    def test_valid_url(self):
        ft = UrlFieldType()
        assert ft.validate_value("https://example.com/path", {}) == "https://example.com/path"

    def test_http_prefix_required(self):
        ft = UrlFieldType()
        with pytest.raises(ValueError):
            ft.validate_value("example.com", {})

    def test_none_passthrough(self):
        ft = UrlFieldType()
        assert ft.validate_value(None, {}) is None


class TestPhoneFieldType:
    def test_valid_phone(self):
        ft = PhoneFieldType()
        assert ft.validate_value("13800138000", {}) == "13800138000"

    def test_invalid_phone_too_short(self):
        ft = PhoneFieldType()
        with pytest.raises(ValueError):
            ft.validate_value("1380013800", {})

    def test_none_passthrough(self):
        ft = PhoneFieldType()
        assert ft.validate_value(None, {}) is None


class TestPercentageFieldType:
    def test_valid_range(self):
        ft = PercentageFieldType()
        assert ft.validate_value(0.5, {}) == 0.5

    def test_out_of_range(self):
        ft = PercentageFieldType()
        with pytest.raises(ValueError):
            ft.validate_value(1.5, {})

    def test_none_passthrough(self):
        ft = PercentageFieldType()
        assert ft.validate_value(None, {}) is None


class TestTimestampFieldType:
    def test_valid_timestamp(self):
        ft = TimestampFieldType()
        assert ft.validate_value(1700000000, {}) == 1700000000

    def test_out_of_range(self):
        ft = TimestampFieldType()
        with pytest.raises(ValueError):
            ft.validate_value(-1, {})

    def test_reject_bool(self):
        ft = TimestampFieldType()
        with pytest.raises(ValueError):
            ft.validate_value(True, {})

    def test_none_passthrough(self):
        ft = TimestampFieldType()
        assert ft.validate_value(None, {}) is None


# ── D2 access.py 单元测试 ────────────────────────────


class TestAccessHelpers:
    def test_apply_field_hiding(self):
        row = {"a": 1, "b": 2, "c": 3}
        apply_field_hiding(row, ["b"])
        assert row == {"a": 1, "c": 3}

    def test_apply_field_hiding_noop_for_missing(self):
        row = {"a": 1}
        apply_field_hiding(row, ["nonexistent"])
        assert row == {"a": 1}

    def test_apply_field_hiding_rows(self):
        rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        apply_field_hiding_rows(rows, ["b"])
        assert rows == [{"a": 1}, {"a": 3}]

    def test_table_action_enum(self):
        assert TableAction.READ.value == "READ"
        assert TableAction.EDIT_SCHEMA.value == "EDIT_SCHEMA"


# ── D3 audit 端到端测试（records 写 AuditLog） ────────


def test_audit_on_row_crud(client, auth_headers, db):
    """行 CRUD 应自动写 AuditLog."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_audit"})
    wid = ws.json()["id"]
    tbl = client.post(
        f"/api/v1/workspaces/{wid}/tables",
        headers=auth_headers,
        json={"name": "t_audit"},
    )
    tid = tbl.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "name", "field_type": "text", "order": 0},
    )

    # create
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records",
        headers=auth_headers,
        json={"values": {"name": "hello"}},
    )
    row_id = r.json()["id"]

    audit_list = query_table_history(db, tid, limit=10)
    assert any(a.action == ACTION_CREATE for a in audit_list)

    # update
    client.patch(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/{row_id}",
        headers=auth_headers,
        json={"values": {"name": "updated"}},
    )
    audit_list = query_row_history(db, tid, row_id, limit=10)
    assert len(audit_list) >= 2  # create + update

    # trash (soft delete)
    client.delete(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/{row_id}?soft=true",
        headers=auth_headers,
    )
    audit_list = query_row_history(db, tid, row_id, limit=10)
    assert any(a.action == "trash" for a in audit_list)

    # restore
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/{row_id}/restore",
        headers=auth_headers,
    )
    audit_list = query_row_history(db, tid, row_id, limit=10)
    assert any(a.action == "restore" for a in audit_list)


# ── D4 trash 路由端到端测试 ───────────────────────────


def _setup_workspace_with_table_and_fields(client, auth_headers):
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_trash"})
    wid = ws.json()["id"]
    tbl = client.post(
        f"/api/v1/workspaces/{wid}/tables",
        headers=auth_headers,
        json={"name": "t_trash"},
    )
    tid = tbl.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "name", "field_type": "text", "order": 0},
    )
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "age", "field_type": "number", "order": 1},
    )
    # create 3 rows
    for i in range(3):
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records",
            headers=auth_headers,
            json={"values": {"name": f"row{i}", "age": i}},
        )
    return wid, tid


def test_workspace_trash_empty(client, auth_headers):
    """全新工作区的回收站应为空."""
    wid, _ = _setup_workspace_with_table_and_fields(client, auth_headers)
    r = client.get(f"/api/v1/workspaces/{wid}/trash", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["tables"] == []
    assert data["fields"] == []
    assert data["row_counts"] == []


def test_trash_row_via_delete_and_list(client, auth_headers):
    """软删行后应出现在回收站列表里."""
    wid, tid = _setup_workspace_with_table_and_fields(client, auth_headers)

    # 软删第二行（先找到 id）
    list_r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/list",
        headers=auth_headers,
        json={"filters": [], "sorts": [], "limit": 10, "offset": 0},
    )
    row_ids = [r["id"] for r in list_r.json()["rows"]]
    assert len(row_ids) == 3

    client.delete(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/{row_ids[1]}?soft=true",
        headers=auth_headers,
    )

    # 工作区回收站应显示 row_count > 0
    trash = client.get(f"/api/v1/workspaces/{wid}/trash", headers=auth_headers)
    assert trash.status_code == 200
    row_counts = trash.json()["row_counts"]
    assert any(item["trashed_rows"] >= 1 for item in row_counts)

    # 表级回收站列表应返回该行
    rows = client.get(
        f"/api/v1/workspaces/{wid}/tables/{tid}/trash-rows",
        headers=auth_headers,
    )
    assert rows.status_code == 200
    assert rows.json()["total"] == 1


def test_trash_restore_rows_batch(client, auth_headers):
    """批量恢复软删行."""
    wid, tid = _setup_workspace_with_table_and_fields(client, auth_headers)

    # 软删前两行
    list_r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/list",
        headers=auth_headers,
        json={"filters": [], "sorts": [], "limit": 10, "offset": 0},
    )
    row_ids = [r["id"] for r in list_r.json()["rows"]]

    for rid in row_ids[:2]:
        client.delete(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/{rid}?soft=true",
            headers=auth_headers,
        )

    # 批量恢复全部
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/trash-rows/restore",
        headers=auth_headers,
        json={},
    )
    assert r.status_code == 200
    assert r.json()["restored"] >= 2

    # 回收站应清空
    rows = client.get(
        f"/api/v1/workspaces/{wid}/tables/{tid}/trash-rows",
        headers=auth_headers,
    )
    assert rows.json()["total"] == 0


def test_trash_restore_specific_rows(client, auth_headers):
    """按指定 row_ids 恢复."""
    wid, tid = _setup_workspace_with_table_and_fields(client, auth_headers)

    list_r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/list",
        headers=auth_headers,
        json={"filters": [], "sorts": [], "limit": 10, "offset": 0},
    )
    row_ids = [r["id"] for r in list_r.json()["rows"]]

    for rid in row_ids:
        client.delete(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/{rid}?soft=true",
            headers=auth_headers,
        )

    # 只恢复第一个
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/trash-rows/restore",
        headers=auth_headers,
        json={"row_ids": [row_ids[0]]},
    )
    assert r.status_code == 200
    assert r.json()["restored"] == 1

    # 回收站还剩 2 行
    rows = client.get(
        f"/api/v1/workspaces/{wid}/tables/{tid}/trash-rows",
        headers=auth_headers,
    )
    assert rows.json()["total"] == 2


def test_trash_purge_old_rows(client, auth_headers):
    """硬清理超期软删行."""
    wid, tid = _setup_workspace_with_table_and_fields(client, auth_headers)

    list_r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/list",
        headers=auth_headers,
        json={"filters": [], "sorts": [], "limit": 10, "offset": 0},
    )
    row_ids = [r["id"] for r in list_r.json()["rows"]]

    for rid in row_ids:
        client.delete(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/{rid}?soft=true",
            headers=auth_headers,
        )

    # purge days=0（清理所有，包括没带时间戳的）
    r = client.delete(
        f"/api/v1/workspaces/{wid}/tables/{tid}/trash-rows?days=0",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["purged"] >= 3


def test_trash_table_soft_delete_and_restore(client, auth_headers, db):
    """软删表后应出现在工作区回收站并可恢复."""
    wid, tid = _setup_workspace_with_table_and_fields(client, auth_headers)

    # 软删表（通过 routers/tables.py 的 delete_table）
    client.delete(
        f"/api/v1/workspaces/{wid}/tables/{tid}",
        headers=auth_headers,
    )

    # 回收站应包含该表
    trash = client.get(f"/api/v1/workspaces/{wid}/trash", headers=auth_headers)
    assert trash.status_code == 200
    tables = trash.json()["tables"]
    assert any(t["id"] == tid for t in tables)

    # 恢复表
    restore = client.post(
        f"/api/v1/workspaces/{wid}/trash/tables/{tid}/restore",
        headers=auth_headers,
    )
    assert restore.status_code == 200
    assert restore.json()["restored_table_id"] == tid

    # 回收站应再次清空表段
    trash = client.get(f"/api/v1/workspaces/{wid}/trash", headers=auth_headers)
    assert trash.json()["tables"] == []


def test_trash_field_soft_delete_and_restore(client, auth_headers, db):
    """软删字段后应出现在工作区回收站并可恢复."""
    wid, tid = _setup_workspace_with_table_and_fields(client, auth_headers)

    # 先拿到 field id
    fields = client.get(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
    )
    field_ids = [f["id"] for f in fields.json()]

    # 软删第一个字段
    client.delete(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{field_ids[0]}",
        headers=auth_headers,
    )

    # 回收站应包含该字段
    trash = client.get(f"/api/v1/workspaces/{wid}/trash", headers=auth_headers)
    assert trash.status_code == 200
    field_list = trash.json()["fields"]
    assert any(f["id"] == field_ids[0] for f in field_list)

    # 恢复字段
    restore = client.post(
        f"/api/v1/workspaces/{wid}/trash/fields/{field_ids[0]}/restore",
        headers=auth_headers,
    )
    assert restore.status_code == 200
    assert restore.json()["restored_field_id"] == field_ids[0]

    # 回收站应再次清空字段段
    trash = client.get(f"/api/v1/workspaces/{wid}/trash", headers=auth_headers)
    assert trash.json()["fields"] == []


# ── D1 links.py 单元测试 ─────────────────────────────


def test_is_link_field_non_link():
    """非 link 字段应返回 False."""
    from cndb.plugins.tables.models import DataField

    f = DataField(name="a", field_type="text", db_column_name="field_abc")
    assert is_link_field(f) is False


def test_link_table_exists_unknown_engine(db_engine):
    """未知关联表应返回 False."""
    assert link_table_exists(db_engine, "link_never_created_hex12345") is False


def test_default_registry_has_all_new_types():
    """确认 16 个字段类型都已注册."""
    names = sorted(ft.name for ft in default_registry.all())
    expected = sorted(
        [
            "text",
            "longtext",
            "number",
            "float",
            "boolean",
            "date",
            "datetime",
            "select",
            "link",
            "multiselect",
            "email",
            "url",
            "phone",
            "percentage",
            "timestamp",
            "attachment",
        ]
    )
    assert names == expected
