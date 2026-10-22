"""datasource M2：工作区备份 v5/v6 —— 同步任务与大模型连接随导出 / 导入往返."""

from __future__ import annotations

import json

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.datasource.models import DatasourceLlmConfig, DatasourceSyncJob
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def owner_env(client, db):
    """工作区 + OWNER + 一张表 + 一条同步任务."""
    user = User(username="backup_user", nickname="Backup User")
    user.set_password("passw0rd")
    db.add(user)
    db.flush()
    ws = Workspace(name="同步备份源", created_by_id=user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER))
    db.commit()

    table = DataTable(workspace_id=ws.id, name="天气日表")
    table.ensure_db_name()
    db.add(table)
    db.commit()
    db.refresh(table)
    field = DataField(table_id=table.id, name="city", field_type="text", order=0)
    field.ensure_db_name()
    db.add(field)
    db.commit()

    job = DatasourceSyncJob(
        workspace_id=ws.id,
        created_by=user.id,
        name="天气同步",
        provider="http_json",
        table_id=table.id,
        request_spec={"url_template": "https://api.example.com/w?city={city}", "time_window": {"mode": "none"}},
        parser="json",
        entrant_param="city",
        entrant_keys=["北京"],
        match_keys=["city"],
        field_mapping={"city": {"name": "city", "field_type": "text"}},
        cursor={"strategy": "key_set"},
        schedule={"mode": "daily", "at": "07:00"},
        enabled=True,
    )
    db.add(job)
    db.commit()

    response = client.post("/api/v1/accounts/auth/login", json={"login": "backup_user", "password": "passw0rd"})
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    return ws.id, table.id, headers


class TestBackupV5:
    def test_export_carries_sync_jobs(self, client, owner_env):
        wid, _table_id, headers = owner_env
        backup = client.get(f"/api/v1/workspaces/{wid}/export", headers=headers).json()
        assert backup["version"] == "6"
        jobs = backup["sync_jobs"]
        assert len(jobs) == 1
        assert jobs[0]["name"] == "天气同步"
        # 跨工作区 id 不可移植 → 导出用表名引用
        assert jobs[0]["table_name"] == "天气日表"
        assert jobs[0]["match_keys"] == ["city"]

    def test_import_restores_and_rebinds_table(self, client, db, owner_env):
        wid, table_id, headers = owner_env
        backup = client.get(f"/api/v1/workspaces/{wid}/export", headers=headers).json()

        target = Workspace(name="同步备份目标")
        db.add(target)
        db.commit()
        db.refresh(target)
        db.add(WorkspaceMember(workspace_id=target.id, user_id=1, role=WorkspaceRole.OWNER))
        db.commit()

        response = client.post(f"/api/v1/workspaces/{target.id}/import", json={"json_data": backup}, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["imported_sync_jobs"] == 1

        restored = (
            db.query(DatasourceSyncJob)
            .filter(DatasourceSyncJob.workspace_id == target.id, DatasourceSyncJob.name == "天气同步")
            .one()
        )
        new_table = db.query(DataTable).filter(DataTable.workspace_id == target.id, DataTable.name == "天气日表").one()
        assert restored.table_id == new_table.id
        assert restored.table_id != table_id
        assert restored.cursor == {"strategy": "key_set"}
        assert restored.schedule["at"] == "07:00"

    def test_import_is_idempotent_by_name(self, client, db, owner_env):
        wid, _table_id, headers = owner_env
        backup = client.get(f"/api/v1/workspaces/{wid}/export", headers=headers).json()
        client.post(f"/api/v1/workspaces/{wid}/import", json={"json_data": backup}, headers=headers)
        assert db.query(DatasourceSyncJob).filter(DatasourceSyncJob.workspace_id == wid).count() == 1

    def test_old_backup_without_sync_jobs(self, client, db, owner_env):
        wid, _table_id, headers = owner_env
        legacy = {"version": "4", "tables": [], "documents": []}
        response = client.post(f"/api/v1/workspaces/{wid}/import", json={"json_data": legacy}, headers=headers)
        assert response.status_code == 200
        assert response.json()["imported_sync_jobs"] == 0

    def test_invalid_job_config_skipped_with_error(self, client, db, owner_env):
        wid, _table_id, headers = owner_env
        backup = client.get(f"/api/v1/workspaces/{wid}/export", headers=headers).json()
        backup["sync_jobs"][0]["cursor"] = {"strategy": "weekly"}
        # 先清掉同名任务，避免走「同名跳过」分支而绕过配置校验
        db.query(DatasourceSyncJob).filter(DatasourceSyncJob.workspace_id == wid).delete()
        db.commit()
        response = client.post(f"/api/v1/workspaces/{wid}/import", json={"json_data": backup}, headers=headers)
        assert response.status_code == 200
        assert response.json()["imported_sync_jobs"] == 0
        assert any("配置非法" in item for item in response.json()["errors"])


class TestBackupV6LlmConfig:
    """ADR 0019：备份 v6 携带工作区「大模型连接」（不含 api_key）."""

    def _configure_llm(self, client, wid: int, headers: dict[str, str]) -> dict[str, str]:
        response = client.put(
            f"/api/v1/workspaces/{wid}/datasource/llm-config",
            json={
                "base_url": "https://llm.example.com/v1",
                "model": "model-a",
                "api_key": "sk-secret",
                "system_prompt": "你是天气数据助手",
            },
            headers=headers,
        )
        assert response.status_code == 200
        return response.json()

    def test_export_carries_llm_config_without_api_key(self, client, owner_env):
        wid, _table_id, headers = owner_env
        self._configure_llm(client, wid, headers)

        backup = client.get(f"/api/v1/workspaces/{wid}/export", headers=headers).json()

        assert backup["version"] == "6"
        assert backup["llm_config"] == {
            "base_url": "https://llm.example.com/v1",
            "model": "model-a",
            "system_prompt": "你是天气数据助手",
        }
        # 密钥绝不随备份导出
        assert "sk-secret" not in json.dumps(backup)
        assert "api_key" not in json.dumps(backup["llm_config"])

    def test_import_restores_llm_config_without_key(self, client, db, owner_env):
        wid, _table_id, headers = owner_env
        self._configure_llm(client, wid, headers)
        backup = client.get(f"/api/v1/workspaces/{wid}/export", headers=headers).json()

        target = Workspace(name="连接备份目标")
        db.add(target)
        db.commit()
        db.refresh(target)
        db.add(WorkspaceMember(workspace_id=target.id, user_id=1, role=WorkspaceRole.OWNER))
        db.commit()

        response = client.post(f"/api/v1/workspaces/{target.id}/import", json={"json_data": backup}, headers=headers)
        assert response.status_code == 200

        restored = db.query(DatasourceLlmConfig).filter(DatasourceLlmConfig.workspace_id == target.id).one()
        assert restored.base_url == "https://llm.example.com/v1"
        assert restored.model == "model-a"
        assert restored.system_prompt == "你是天气数据助手"
        # Key 不导出，还原后留空待重新配置
        assert restored.api_key == ""

    def test_old_backup_without_llm_config(self, client, db, owner_env):
        wid, _table_id, headers = owner_env
        legacy = {"version": "5", "tables": [], "documents": [], "sync_jobs": []}
        response = client.post(f"/api/v1/workspaces/{wid}/import", json={"json_data": legacy}, headers=headers)
        assert response.status_code == 200
        assert db.query(DatasourceLlmConfig).filter(DatasourceLlmConfig.workspace_id == wid).count() == 0
