"""ADR 0020 P2：表格字段批量填充（`table.fill_field`）.

覆盖：只读生值、行级读范围裁剪、字段隐藏拒绝、未知行丢弃、schema 失败零副作用、留痕。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.core.crypto import encrypt_secret
from cndb.plugins.accounts.models import User
from cndb.plugins.llm.models import LlmRun, LlmUserConfig
from cndb.plugins.llm.services import client as llm_client
from cndb.plugins.llm.services import gateway
from cndb.plugins.tables.models import DataField, TablePermission
from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole

FILL_URL = "/api/v1/workspaces/{ws}/tables/{tid}/ai/actions/fill_field"


def _make_user(db: Session, username: str) -> User:
    user = User(username=username, nickname=username)
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _give_connection(db: Session, user: User) -> None:
    db.add(
        LlmUserConfig(
            user_id=user.id,
            base_url="https://llm.example.com",
            model="model-a",
            api_key=encrypt_secret("sk-test"),
            system_prompt="",
        )
    )
    db.commit()


def _patch_complete(monkeypatch: pytest.MonkeyPatch, content: str) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake(_connection, **kwargs):
        captured["messages"] = kwargs.get("messages") or []
        return llm_client.LlmResponse(content=content, model="model-a", usage={"total_tokens": 12})

    monkeypatch.setattr(gateway.client, "complete", fake)
    return captured


@pytest.fixture
def fill_ctx(client, db):
    """owner + workspace + 表（标题/正文/摘要）+ 两行；返回 (ws_id, table_id, rows, headers, owner).."""
    owner = _make_user(db, "fill_owner")
    headers = _login(client, "fill_owner")
    ws = client.post("/api/v1/workspaces", headers=headers, json={"name": "FillWS"}).json()
    table = client.post(f"/api/v1/workspaces/{ws['id']}/tables", headers=headers, json={"name": "资讯表"}).json()
    tid = table["id"]
    for order, (name, field_type) in enumerate([("标题", "text"), ("正文", "text"), ("摘要", "text")]):
        client.post(
            f"/api/v1/workspaces/{ws['id']}/tables/{tid}/fields",
            headers=headers,
            json={"name": name, "field_type": field_type, "order": order},
        )
    rows = []
    for title, body in [("流程优化", "现有五个审批节点"), ("指标看板", "建议建立周度指标")]:
        response = client.post(
            f"/api/v1/workspaces/{ws['id']}/tables/{tid}/records",
            headers=headers,
            json={"values": {"标题": title, "正文": body}},
        )
        assert response.status_code == 201, response.text
        rows.append(response.json()["id"])
    _give_connection(db, owner)
    return ws["id"], tid, rows, headers, owner


class TestFillField:
    def test_generates_values_and_records_run(self, client, db, fill_ctx, monkeypatch):
        ws_id, tid, rows, headers, _owner = fill_ctx
        _patch_complete(monkeypatch, f'{{"values": [{{"row_id": {rows[0]}, "value": "流程优化摘要"}}]}}')
        response = client.post(
            FILL_URL.format(ws=ws_id, tid=tid),
            json={"field_name": "摘要", "row_ids": rows},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["action"] == "table.fill_field"
        assert body["result"]["values"] == [{"row_id": rows[0], "value": "流程优化摘要"}]
        assert body["row_count"] == 2
        run = db.query(LlmRun).filter(LlmRun.id == body["run_id"]).one()
        assert run.action == "table.fill_field"
        assert run.status == "success"

    def test_model_extra_row_id_is_dropped(self, client, db, fill_ctx, monkeypatch):
        ws_id, tid, rows, headers, _owner = fill_ctx
        _patch_complete(
            monkeypatch,
            f'{{"values": [{{"row_id": {rows[0]}, "value": "ok"}}, {{"row_id": 999999, "value": "bad"}}]}}',
        )
        response = client.post(
            FILL_URL.format(ws=ws_id, tid=tid),
            json={"field_name": "摘要", "row_ids": [rows[0]]},
            headers=headers,
        )
        assert response.status_code == 200
        assert [item["row_id"] for item in response.json()["result"]["values"]] == [rows[0]]

    def test_hidden_field_rejected(self, client, db, fill_ctx):
        ws_id, tid, rows, headers, _owner = fill_ctx
        field = db.query(DataField).filter(DataField.table_id == tid, DataField.name == "摘要").one()
        field.hidden = True
        db.commit()
        response = client.post(
            FILL_URL.format(ws=ws_id, tid=tid),
            json={"field_name": "摘要", "row_ids": rows},
            headers=headers,
        )
        assert response.status_code == 400
        assert "隐藏字段" in response.json()["detail"]

    def test_missing_field_rejected(self, client, fill_ctx):
        ws_id, tid, rows, headers, _owner = fill_ctx
        response = client.post(
            FILL_URL.format(ws=ws_id, tid=tid),
            json={"field_name": "不存在", "row_ids": rows},
            headers=headers,
        )
        assert response.status_code == 400

    def test_unreadable_rows_are_skipped(self, client, db, fill_ctx, monkeypatch):
        """行级读范围外的行不进入模型输入（改用非 owner 的编辑者 + 默认档过滤）."""
        ws_id, tid, rows, _headers, _owner = fill_ctx
        editor = _make_user(db, "fill_editor")
        db.add(WorkspaceMember(workspace_id=ws_id, user_id=editor.id, role=WorkspaceRole.EDITOR))
        db.add(
            TablePermission(
                table_id=tid,
                row_filters=[{"field_name": "标题", "op": "eq", "value": "流程优化"}],
            )
        )
        db.commit()
        _give_connection(db, editor)
        captured = _patch_complete(
            monkeypatch,
            f'{{"values": [{{"row_id": {rows[0]}, "value": "v"}}]}}',
        )
        editor_headers = _login(client, "fill_editor")
        response = client.post(
            FILL_URL.format(ws=ws_id, tid=tid),
            json={"field_name": "摘要", "row_ids": rows},
            headers=editor_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["row_count"] == 1
        assert body["skipped_row_ids"] == [rows[1]]
        prompt = captured["messages"][1]["content"]
        assert "流程优化" in prompt
        assert "指标看板" not in prompt

    def test_schema_failure_has_no_side_effect(self, client, db, fill_ctx, monkeypatch):
        ws_id, tid, rows, headers, _owner = fill_ctx
        _patch_complete(monkeypatch, '{"values": [{"row_id": "not-a-number"}]}')
        response = client.post(
            FILL_URL.format(ws=ws_id, tid=tid),
            json={"field_name": "摘要", "row_ids": rows},
            headers=headers,
        )
        assert response.status_code == 422
        failed = db.query(LlmRun).filter(LlmRun.status == "failed").one()
        assert failed.action == "table.fill_field"
        # 行数据未被写入
        rows_now = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{tid}/records/list",
            headers=headers,
            json={"limit": 10},
        ).json()["rows"]
        assert all(not row.get("摘要") for row in rows_now)

    def test_unconfigured_key_reports_hint(self, client, db, fill_ctx):
        ws_id, tid, rows, headers, owner = fill_ctx
        db.query(LlmUserConfig).filter(LlmUserConfig.user_id == owner.id).delete()
        db.commit()
        response = client.post(
            FILL_URL.format(ws=ws_id, tid=tid),
            json={"field_name": "摘要", "row_ids": rows},
            headers=headers,
        )
        assert response.status_code == 400
        assert "个人设置" in response.json()["detail"]


class TestCatalog:
    def test_table_actions_registered(self, client, db, fill_ctx):
        from cndb.plugins.llm.services import actions as action_registry
        from cndb.plugins.tables.services import ai as tables_ai

        # 其它用例可能 reset 过全局动作注册表：这里重新注册（幂等）
        action_registry.register(tables_ai.FILL_FIELD)
        action_registry.register(tables_ai.MAPPING_SUGGESTION)
        _ws, _tid, _rows, headers, _owner = fill_ctx
        response = client.get("/api/v1/llm/actions", headers=headers)
        names = {item["name"] for item in response.json()["items"]}
        assert {"table.fill_field", "import.mapping_suggestion"} <= names
