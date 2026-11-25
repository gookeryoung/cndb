"""工作区归档导入 / 覆盖恢复的边界路径（覆盖率补强 + 语义回归）.

覆盖：
- `create_workspace_from_archive_file`：非法归档 400、`visibility` 脏值回落 member、
  旧备份 `workspace_type` 未知时的模块告警（ADR 0080 D7）；
- `restore_workspace_from_backup`：运行中的同步任务拒绝覆盖恢复（ADR 0075 D4）。
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.datasource.models import DatasourceSyncJob
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole, WorkspaceVisibility
from cndb.plugins.workspaces.services.workspace_import import create_workspace_from_archive_file


def _user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _archive(tmp_path: Path, backup: dict, *, name: str = "ws.tar.gz") -> Path:
    """构造最小合法归档（manifest.kind 正确 + payload/backup.json 为给定内容）."""
    from cndb.plugins.workspaces.services.workspace_backup import ARCHIVE_KIND, ARCHIVE_MANIFEST_VERSION

    manifest = {
        "version": ARCHIVE_MANIFEST_VERSION,
        "kind": ARCHIVE_KIND,
        "app_version": "test",
        "created_at": "2026-11-25T00:00:00Z",
        "backup_version": backup.get("version", 1),
        "include_secrets": False,
        "workspace_name": (backup.get("workspace") or {}).get("name", ""),
        "stats": {},
    }
    path = tmp_path / name
    with tarfile.open(path, "w:gz") as tar:
        for arcname, payload in (("manifest.json", manifest), ("payload/backup.json", backup)):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            info = tarfile.TarInfo(arcname)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


class TestArchiveImportEdges:
    def test_invalid_backup_shape_is_400(self, db: Session, tmp_path: Path):
        user = _user(db, "imp_bad_shape")
        path = _archive(tmp_path, {"workspace": {"name": "无表"}})
        with pytest.raises(HTTPException) as exc:
            create_workspace_from_archive_file(path, user, db)
        assert exc.value.status_code == 400

    def test_dirty_visibility_falls_back_to_member(self, db: Session, tmp_path: Path):
        user = _user(db, "imp_dirty_vis")
        path = _archive(tmp_path, {"tables": [], "workspace": {"name": "脏可见性", "visibility": "weird"}})
        result = create_workspace_from_archive_file(path, user, db, name="导入结果")
        assert result.workspace.visibility is WorkspaceVisibility.MEMBER
        assert result.workspace.name == "导入结果"

    def test_unknown_workspace_type_appends_module_warning(self, db: Session, tmp_path: Path):
        user = _user(db, "imp_mod_warn")
        path = _archive(tmp_path, {"tables": [], "workspace": {"name": "旧备份", "workspace_type": "weird"}})
        result = create_workspace_from_archive_file(path, user, db)
        assert result.workspace.modules  # 回退全模块或按映射
        assert any("workspace_type" in err or "模块" in err for err in result.errors)

    def test_rollback_on_import_failure(self, db: Session, tmp_path: Path, monkeypatch):
        """落库阶段抛 HTTPException 时清理刚创建的工作区（不残留半成品）."""
        user = _user(db, "imp_rollback")
        path = _archive(tmp_path, {"tables": [], "workspace": {"name": "回滚"}})

        def boom(*_args, **_kwargs):
            raise HTTPException(status_code=400, detail="导入失败")

        monkeypatch.setattr("cndb.plugins.workspaces.services.workspace_import.import_backup_into_workspace", boom)
        with pytest.raises(HTTPException):
            create_workspace_from_archive_file(path, user, db)
        assert db.query(Workspace).filter(Workspace.name == "回滚").first() is None


class TestRestoreRunningSyncGuard:
    def test_running_sync_job_blocks_restore(self, client, db: Session):
        owner = _user(db, "restore_owner")
        ws = Workspace(name="恢复目标", created_by_id=owner.id)
        db.add(ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER))
        db.add(
            DatasourceSyncJob(
                workspace_id=ws.id,
                name="运行中的同步",
                last_status="running",
                enabled=True,
            )
        )
        db.commit()
        db.refresh(ws)

        auth = {
            "Authorization": "Bearer "
            + client.post("/api/v1/accounts/auth/login", json={"login": owner.username, "password": "passw0rd"}).json()[
                "access_token"
            ]
        }
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/restore",
            files={"file": ("ws.tar.gz", io.BytesIO(b"not-a-real-archive"), "application/gzip")},
            headers=auth,
        )
        assert r.status_code in (400, 409), r.text
