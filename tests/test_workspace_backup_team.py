"""工作区备份与团队边界（ADR 0153 D7 / H14）.

口径：团队是**环境级配置**，不进工作区备份；manifest 只记提示性 ``{name, slug}``。
导入 / 覆盖恢复都不自动挂团队（跨环境错挂风险）。
"""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Team, TeamMember, TeamRole, Workspace, WorkspaceMember, WorkspaceRole
from cndb.plugins.workspaces.services.workspace_backup import parse_workspace_archive

WS = "/api/v1/workspaces"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class Env:
    def __init__(self, db: Session) -> None:
        self.owner = User(username="p1_backup_owner", nickname="张三")
        self.owner.set_password("passw0rd")
        db.add(self.owner)
        db.commit()
        self.team = Team(name="研发部", slug="rd", description="", policy={}, created_by_id=self.owner.id)
        db.add(self.team)
        db.flush()
        db.add(TeamMember(team_id=self.team.id, user_id=self.owner.id, role=TeamRole.OWNER))
        self.ws = Workspace(name="研发部备份工作区", created_by_id=self.owner.id, team_id=self.team.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        db.commit()
        db.refresh(self.ws)


def _export_archive(client: TestClient, headers: dict[str, str], wid: int, tmp_path: Path) -> Path:
    r = client.get(f"{WS}/{wid}/export/archive", headers=headers)
    assert r.status_code == 200, r.text
    path = tmp_path / "ws.tar.gz"
    path.write_bytes(r.content)
    return path


class TestBackupTeamBoundary:
    def test_manifest_has_hint_but_payload_has_no_team(self, client, db, tmp_path: Path):
        env = Env(db)
        archive = parse_workspace_archive(
            _export_archive(client, _login(client, env.owner.username), env.ws.id, tmp_path)
        )
        try:
            assert archive.manifest["team"] == {"name": "研发部", "slug": "rd"}
            backup = archive.backup
            # 团队配置不进工作区备份（D7）：既不落 backup.json 顶层键，也不进 workspace meta
            assert "team" not in backup
            assert "teams" not in backup
            assert "team_members" not in backup
            assert "team" not in (backup.get("workspace") or {})
        finally:
            archive.cleanup()

    def test_personal_workspace_manifest_team_is_null(self, client, db, tmp_path: Path):
        env = Env(db)
        personal_id = client.post(WS, json={"name": "个人工作区"}, headers=_login(client, env.owner.username)).json()[
            "id"
        ]
        archive = parse_workspace_archive(
            _export_archive(client, _login(client, env.owner.username), personal_id, tmp_path)
        )
        try:
            assert archive.manifest["team"] is None
        finally:
            archive.cleanup()

    def test_import_into_new_workspace_does_not_attach_team(self, client, db, tmp_path: Path):
        env = Env(db)
        auth = _login(client, env.owner.username)
        path = _export_archive(client, auth, env.ws.id, tmp_path)

        with path.open("rb") as fh:
            r = client.post(
                f"{WS}/import/archive",
                files={"file": ("ws.tar.gz", io.BytesIO(fh.read()), "application/gzip")},
                data={"name": "导入的新工作区"},
                headers=auth,
            )
        assert r.status_code in (200, 201), r.text
        created = r.json()["workspace"]
        assert created["team_id"] is None  # 不自动挂团队（D7）
        assert created["team"] is None


class TestOverwriteRestoreKeepsTeam:
    def test_restore_keeps_team_binding(self, client, db, tmp_path: Path):
        """覆盖恢复只重建业务数据，不改 `team_id`（D7 边界 6）."""
        env = Env(db)
        auth = _login(client, env.owner.username)
        path = _export_archive(client, auth, env.ws.id, tmp_path)

        with path.open("rb") as fh:
            r = client.post(
                f"{WS}/{env.ws.id}/restore",
                files={"file": ("ws.tar.gz", io.BytesIO(fh.read()), "application/gzip")},
                headers=auth,
            )
        assert r.status_code == 200, r.text
        db.expire_all()
        ws = db.get(Workspace, env.ws.id)
        assert ws is not None
        assert ws.team_id == env.team.id
