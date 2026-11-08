"""工作区备份 v15：项目模式 / 项目状态 / 项目文档映射（ADR 0122 I6）."""

from __future__ import annotations

from sqlalchemy import select

from cndb.plugins.workspaces.services.backup_io import _import_backup_into_workspace
from cndb.plugins.workspaces.services.workspace_backup import build_workspace_backup_v9
from tests.test_workspace_project_context import PROJECT_SPEC

PROJECT_TEMPLATE_NAME = "v15 项目模板"


def _setup_project_workspace(client, headers) -> dict:
    template = client.post(
        "/api/v1/workspace-templates",
        json={"name": PROJECT_TEMPLATE_NAME, "description": "v15", "spec": PROJECT_SPEC},
        headers=headers,
    )
    assert template.status_code == 201, template.text
    ws = client.post(
        "/api/v1/workspaces",
        json={"name": "v15 源工作区", "template_id": template.json()["id"]},
        headers=headers,
    )
    assert ws.status_code == 201, ws.text
    workspace = ws.json()

    tables = client.get(f"/api/v1/workspaces/{workspace['id']}/tables", headers=headers).json()
    apply_id = next(t["id"] for t in tables if t["name"] == "申报表")
    created = client.post(
        f"/api/v1/workspaces/{workspace['id']}/tables/{apply_id}/records",
        json={"values": {"项目名称": "备份项目"}},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    docs = client.post(f"/api/v1/workspaces/{workspace['id']}/projects/{project_id}/documents", headers=headers)
    assert docs.status_code == 200, docs.text
    advanced = client.post(
        f"/api/v1/workspaces/{workspace['id']}/lifecycle/advance",
        json={"project_id": project_id},
        headers=headers,
    )
    assert advanced.status_code == 200, advanced.text
    return workspace


def _blank_workspace(client, headers, name: str) -> dict:
    r = client.post("/api/v1/workspaces", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _owner(db):
    from cndb.plugins.accounts.models import User

    return db.query(User).filter(User.username == "testuser").first()


def test_v15_export_and_restore_project_context(client, auth_headers, db):
    from cndb.plugins.workspaces.models import (
        Workspace,
        WorkspaceProjectDocument,
        WorkspaceProjectState,
    )

    workspace = _setup_project_workspace(client, auth_headers)
    backup, _files = build_workspace_backup_v9(db, workspace["id"], _owner(db), include_secrets=False)

    assert backup["version"] == "15"
    assert backup["workspace"]["project_mode"] == "project"
    assert len(backup["project_states"]) == 1
    assert backup["project_states"][0]["stage_key"] == "execution"
    assert len(backup["project_documents"]) == 2

    target = _blank_workspace(client, auth_headers, "v15 目标工作区")
    result = _import_backup_into_workspace(target["id"], backup, _owner(db), db)
    assert result.errors == []

    restored = db.get(Workspace, target["id"])
    assert restored is not None and restored.project_mode == "project"
    states = (
        db.execute(select(WorkspaceProjectState).where(WorkspaceProjectState.workspace_id == target["id"]))
        .scalars()
        .all()
    )
    assert len(states) == 1
    assert states[0].stage_key == "execution"
    docs = (
        db.execute(select(WorkspaceProjectDocument).where(WorkspaceProjectDocument.workspace_id == target["id"]))
        .scalars()
        .all()
    )
    assert len(docs) == 2
    assert {d.doc_key for d in docs} == {"proposal", "midterm"}


def test_v14_backup_restores_as_workspace_mode(client, auth_headers, db):
    from cndb.plugins.workspaces.models import Workspace, WorkspaceProjectState

    workspace = _setup_project_workspace(client, auth_headers)
    backup, _files = build_workspace_backup_v9(db, workspace["id"], _owner(db), include_secrets=False)

    old = dict(backup)
    old["version"] = "14"
    old["workspace"] = {k: v for k, v in backup["workspace"].items() if k != "project_mode"}
    old.pop("project_states", None)
    old.pop("project_documents", None)

    target = _blank_workspace(client, auth_headers, "v14 回退目标")
    result = _import_backup_into_workspace(target["id"], old, _owner(db), db)
    assert result.errors == []

    restored = db.get(Workspace, target["id"])
    assert restored is not None and restored.project_mode == "workspace"
    states = (
        db.execute(select(WorkspaceProjectState).where(WorkspaceProjectState.workspace_id == target["id"]))
        .scalars()
        .all()
    )
    assert states == []
