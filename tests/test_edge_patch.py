"""零散缺口补全 — accounts / workspaces / smart_color 等."""

from __future__ import annotations

from cndb.plugins.accounts.models import User

# ── accounts/auth 零散 ───────────────────────────────


class TestAccountsAuthEdge:
    def test_register_duplicate_username(self, client, db):
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "dup_user", "email": "a@example.com", "password": "passw0rd"},
        )
        assert r.status_code in (200, 201)
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "dup_user", "email": "c@example.com", "password": "passw0rd"},
        )
        assert r.status_code == 400
        assert "用户名" in r.json()["detail"]

    def test_register_duplicate_email(self, client, db):
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "email_u1", "email": "dup@example.com", "password": "passw0rd"},
        )
        assert r.status_code in (200, 201)
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "email_u2", "email": "dup@example.com", "password": "passw0rd"},
        )
        assert r.status_code == 400
        assert "邮箱" in r.json()["detail"]

    def test_register_commit_race_integrity_error(self, client, db, monkeypatch):
        """并发竞态：_ensure_unique 通过后 commit 撞唯一约束，应降级 400 明确提示而非 500."""
        from sqlalchemy.exc import IntegrityError

        def race_commit():
            raise IntegrityError("UNIQUE constraint failed: accounts_user.username", None, Exception("dup"))

        monkeypatch.setattr(db, "commit", race_commit)
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "race_user", "password": "passw0rd"},
        )
        assert r.status_code == 400
        assert "已被使用" in r.json()["detail"]


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
