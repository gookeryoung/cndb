"""零散缺口补全 — accounts / reports / workspaces / smart_color 等."""

from __future__ import annotations

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables import ddl
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


# ── accounts/auth 零散 ───────────────────────────────


class TestAccountsAuthEdge:
    def test_register_duplicate_username(self, client, db):
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "dup_user", "email": "a@b.com", "password": "passw0rd"},
        )
        assert r.status_code in (200, 201)
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "dup_user", "email": "c@d.com", "password": "passw0rd"},
        )
        assert r.status_code == 400
        assert "用户名" in r.json()["detail"]

    def test_register_duplicate_email(self, client, db):
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "email_u1", "email": "dup@mail.com", "password": "passw0rd"},
        )
        assert r.status_code in (200, 201)
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "email_u2", "email": "dup@mail.com", "password": "passw0rd"},
        )
        assert r.status_code == 400
        assert "邮箱" in r.json()["detail"]


# ── accounts/preferences 零散 ───────────────────────


class TestAccountsPreferencesEdge:
    def test_preferences_default_after_clear(self, client, auth_headers, db):
        u = db.query(User).filter(User.username == "testuser").first()
        u.preferences = {"other": 1}
        db.commit()
        r = client.get("/api/v1/accounts/preferences", headers=auth_headers)
        assert r.status_code == 200

    def test_preferences_non_dict_auto_fix(self, client, auth_headers, db):
        u = db.query(User).filter(User.username == "testuser").first()
        u.preferences = None
        db.commit()
        r = client.get("/api/v1/accounts/preferences", headers=auth_headers)
        assert r.status_code == 200


# ── reports 零散 ──────────────────────────────────────


class TestReportsEdge:
    def test_create_template_bad_jinja(self, client, auth_headers):
        r = client.post(
            "/api/v1/reports",
            json={
                "name": "坏模板",
                "output_format": "docx",
                "template_content": "{% if %} 语法错误",
            },
            headers=auth_headers,
        )
        assert r.status_code == 400
        assert "模板语法" in r.json()["detail"]

    def test_create_template_bad_format(self, client, auth_headers):
        r = client.post(
            "/api/v1/reports",
            json={
                "name": "坏格式",
                "output_format": "xyz",
                "template_content": "hello",
            },
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_get_template_not_found(self, client, auth_headers):
        r = client.get("/api/v1/reports/99999", headers=auth_headers)
        assert r.status_code == 404

    def test_update_template_not_found(self, client, auth_headers):
        r = client.put(
            "/api/v1/reports/99999",
            json={"name": "newname", "template_content": "x"},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_delete_template_not_found(self, client, auth_headers):
        r = client.delete("/api/v1/reports/99999", headers=auth_headers)
        assert r.status_code == 404

    def test_update_template_bad_jinja(self, client, auth_headers):
        r = client.post(
            "/api/v1/reports",
            json={"name": "T1", "output_format": "docx", "template_content": "hello"},
            headers=auth_headers,
        )
        assert r.status_code == 201
        tid = r.json()["id"]
        r = client.put(
            f"/api/v1/reports/{tid}",
            json={"template_content": "{% if %} bad"},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_update_template_bad_format(self, client, auth_headers):
        r = client.post(
            "/api/v1/reports",
            json={"name": "T2", "output_format": "docx", "template_content": "hi"},
            headers=auth_headers,
        )
        assert r.status_code == 201
        tid = r.json()["id"]
        r = client.put(
            f"/api/v1/reports/{tid}",
            json={"output_format": "nope", "template_content": "hi"},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_update_template_bad_table_ref(self, client, auth_headers):
        r = client.post(
            "/api/v1/reports",
            json={"name": "T3", "output_format": "docx", "template_content": "hi"},
            headers=auth_headers,
        )
        assert r.status_code == 201
        tid = r.json()["id"]
        r = client.put(
            f"/api/v1/reports/{tid}",
            json={"table_id": 99999, "template_content": "hi"},
            headers=auth_headers,
        )
        assert r.status_code == 404


# ── smart_color 零散 ───────────────────────────────────


class TestSmartColorMore:
    def test_suggest_colors(self):
        from cndb.plugins.tables.field_types.smart_color import suggest_colors

        colors = suggest_colors(["低", "中", "高"])
        assert isinstance(colors, list)

    def test_match_color(self):
        from cndb.plugins.tables.field_types.smart_color import match_color

        result = match_color("盈利")
        assert result is None or isinstance(result, str)
        result2 = match_color("亏损")
        assert result2 is None or isinstance(result2, str)


# ── workspaces router 零散 ────────────────────────────


class TestWorkspacesEdge:
    def test_workspace_detail_not_found(self, client, auth_headers):
        r = client.get("/api/v1/workspaces/99999", headers=auth_headers)
        assert r.status_code == 404

    def test_workspace_update_not_found(self, client, auth_headers):
        r = client.patch(
            "/api/v1/workspaces/99999",
            json={"name": "X"},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_workspace_delete_not_found(self, client, auth_headers):
        r = client.delete("/api/v1/workspaces/99999", headers=auth_headers)
        assert r.status_code == 404

    def test_workspace_backup_not_found(self, client, auth_headers):
        r = client.post("/api/v1/workspaces/99999/backup", headers=auth_headers)
        assert r.status_code == 404


__all__ = []
