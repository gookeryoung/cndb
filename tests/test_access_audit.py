"""Phase D 后端断链补测 — access.py + audit.py."""

from __future__ import annotations

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, TablePermission
from cndb.plugins.tables.services.core.access import (
    TableAction,
    apply_field_hiding,
    apply_field_hiding_rows,
    check_action,
    get_hidden_field_names,
    get_row_scope,
    row_filter_conjunction,
)
from cndb.plugins.tables.services.core.audit import (
    ACTION_CREATE,
    ACTION_UPDATE,
    log_action,
    query_row_history,
    query_table_history,
)
from cndb.plugins.workspaces.models import WorkspaceRole

# ── access.py 基础工具函数 ──────────────────────────────


class TestTableActionEnum:
    def test_values(self):
        assert TableAction.READ.value == "READ"
        assert TableAction.EDIT_RECORDS.value == "EDIT_RECORDS"


class TestFieldHiding:
    def test_apply_single(self):
        row = {"a": 1, "b": 2, "c": 3}
        result = apply_field_hiding(row, ["b"])
        assert result == {"a": 1, "c": 3}
        assert "b" not in result

    def test_apply_batch(self):
        rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        result = apply_field_hiding_rows(rows, ["b"])
        for r in result:
            assert "b" not in r


# ── access.py + DataTable 创建（手动 ensure_db_name）────


def _make_table(db, ws_id, name="t_x"):
    tbl = DataTable(workspace_id=ws_id, name=name)
    tbl.ensure_db_name()
    db.add(tbl)
    db.commit()
    db.refresh(tbl)
    return tbl


class TestGetRowScope:
    def test_no_permission(self, db):
        tbl = _make_table(db, 1, "t_scope_none")
        assert get_row_scope(db, tbl) == []

    def test_with_rules(self, db):
        tbl = _make_table(db, 1, "t_scope_rules")
        perm = TablePermission(table_id=tbl.id, row_filters=[{"col": "x", "op": "=", "val": 1}])
        db.add(perm)
        db.commit()
        assert get_row_scope(db, tbl) == [{"col": "x", "op": "=", "val": 1}]


class TestRowFilterConjunction:
    def test_no_permission_default_and(self, db):
        tbl = _make_table(db, 1, "t_conj_none")
        assert row_filter_conjunction(db, tbl) == "AND"

    def test_explicit_or(self, db):
        tbl = _make_table(db, 1, "t_conj_or")
        perm = TablePermission(table_id=tbl.id, row_filter_type="OR")
        db.add(perm)
        db.commit()
        assert row_filter_conjunction(db, tbl) == "OR"

    def test_invalid_falls_back_and(self, db):
        tbl = _make_table(db, 1, "t_conj_bogus")
        perm = TablePermission(table_id=tbl.id, row_filter_type="XOR")
        db.add(perm)
        db.commit()
        assert row_filter_conjunction(db, tbl) == "AND"


class TestCheckAction:
    def test_no_permission_fallback(self, db, client, auth_headers):
        """无表级覆盖走默认角色 — VIEWER 可读但不可改 schema."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_fb"})
        wid = ws.json()["id"]
        client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_fb"})
        tbl = db.query(DataTable).filter_by(workspace_id=wid).first()
        # 让表 owner 为空，避免 owner 权限短路，专注测试 member_role 路径
        tbl.owner_id = None
        db.commit()
        user = db.query(User).first()
        assert check_action(db, tbl, user, TableAction.READ, member_role=WorkspaceRole.VIEWER)
        assert check_action(db, tbl, user, TableAction.EDIT_SCHEMA, member_role=WorkspaceRole.VIEWER) is False

    def test_permission_override(self, db, client, auth_headers):
        """表级覆盖 — EDIT_SCHEMA 需 admin."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_ovr"})
        wid = ws.json()["id"]
        client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_ovr"})
        tbl = db.query(DataTable).filter_by(workspace_id=wid).first()
        tbl.owner_id = None
        db.commit()
        perm = TablePermission(table_id=tbl.id, edit_schema_role="admin")
        db.add(perm)
        db.commit()
        user = db.query(User).first()
        # EDITOR 走 TablePermission 阈值，edit_schema_role=admin 要求更高 → False
        assert check_action(db, tbl, user, TableAction.EDIT_SCHEMA, member_role=WorkspaceRole.EDITOR) is False

    def test_permission_invalid_role(self, db, client, auth_headers):
        """表级指定无效角色字符串 → False（当用户走 TablePermission 阈值路径时）."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_bogus"})
        wid = ws.json()["id"]
        client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_bogus"})
        tbl = db.query(DataTable).filter_by(workspace_id=wid).first()
        tbl.owner_id = None
        db.commit()
        perm = TablePermission(table_id=tbl.id, edit_records_role="bogus_role")
        db.add(perm)
        db.commit()
        user = db.query(User).first()
        # EDITOR 走 TablePermission 阈值，bogus_role 无法解析 → False
        assert check_action(db, tbl, user, TableAction.EDIT_RECORDS, member_role=WorkspaceRole.EDITOR) is False


class TestGetHiddenFieldNames:
    def test_no_permission(self, db, client, auth_headers):
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_h"})
        wid = ws.json()["id"]
        client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_h"})
        tbl = db.query(DataTable).filter_by(workspace_id=wid).first()
        user = db.query(User).first()
        assert get_hidden_field_names(db, tbl, user) == set()


# ── audit.py ─────────────────────────────────────────


class TestAuditLog:
    def test_constants(self):
        assert ACTION_CREATE == "create"
        assert ACTION_UPDATE == "update"

    def test_log_and_query(self, db):
        tbl = _make_table(db, 1, "t_audit_ok")
        log_action(db, tbl, ACTION_CREATE, target_id=1, actor_id=None, detail={"x": 1})
        log_action(db, tbl, ACTION_UPDATE, target_id=1, actor_id=None, detail={"x": 2})
        log_action(db, tbl, ACTION_CREATE, target_id=2, actor_id=None)

        hist = query_row_history(db, tbl.id, 1, limit=10)
        assert len(hist) == 2

        t_hist = query_table_history(db, tbl.id, limit=10)
        assert len(t_hist) == 3

    def test_query_empty(self, db):
        tbl = _make_table(db, 1, "t_audit_empty")
        assert query_row_history(db, tbl.id, 999) == []
        assert query_table_history(db, tbl.id) == []
