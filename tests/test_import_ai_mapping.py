"""ADR 0020 P2：导入列映射建议（`import.mapping_suggestion`）.

覆盖：只读建议、隐藏字段不进候选 / 不进提示词、未知目标过滤、同源同目标去重、权限与留痕。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.core.crypto import encrypt_secret
from cndb.plugins.accounts.models import User
from cndb.plugins.llm.models import LlmUserConfig
from cndb.plugins.llm.services import client as llm_client
from cndb.plugins.llm.services import gateway
from cndb.plugins.tables.models import DataField, ImportTask

MAPPING_URL = "/api/v1/workspaces/{ws}/import-file/ai/mapping-suggestion"


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
        return llm_client.LlmResponse(content=content, model="model-a", usage={"total_tokens": 20})

    monkeypatch.setattr(gateway.client, "complete", fake)
    return captured


@pytest.fixture
def mapping_ctx(client, db):
    owner = _make_user(db, "map_owner")
    headers = _login(client, "map_owner")
    ws = client.post("/api/v1/workspaces", headers=headers, json={"name": "MapWS"}).json()
    table = client.post(f"/api/v1/workspaces/{ws['id']}/tables", headers=headers, json={"name": "行情表"}).json()
    tid = table["id"]
    for order, (name, field_type) in enumerate(
        [("trade_date", "date"), ("symbol", "text"), ("close", "number"), ("internal_note", "text")]
    ):
        client.post(
            f"/api/v1/workspaces/{ws['id']}/tables/{tid}/fields",
            headers=headers,
            json={"name": name, "field_type": field_type, "order": order},
        )
    # 隐藏字段不应出现在候选与提示词中
    note = db.query(DataField).filter(DataField.table_id == tid, DataField.name == "internal_note").one()
    note.hidden = True
    db.commit()
    _give_connection(db, owner)
    return ws["id"], tid, headers, owner


class TestMappingSuggestion:
    def test_suggestions_are_filtered_and_deduped(self, client, db, mapping_ctx, monkeypatch):
        ws_id, tid, headers, _owner = mapping_ctx
        _patch_complete(
            monkeypatch,
            '{"mappings": ['
            '{"source": "日期", "target": "trade_date", "confidence": 0.9, "reason": "列名一致"},'
            '{"source": "日期", "target": "symbol", "confidence": 0.4, "reason": "重复源"},'
            '{"source": "代码", "target": "symbol", "confidence": 0.8, "reason": "语义一致"},'
            '{"source": "隐藏列", "target": "internal_note", "confidence": 0.99, "reason": "隐藏字段"},'
            '{"source": "价格", "target": "not_a_field", "confidence": 0.9, "reason": "不存在"}'
            '], "unmapped": []}',
        )
        response = client.post(
            MAPPING_URL.format(ws=ws_id),
            json={
                "target_table_id": tid,
                "headers": ["日期", "代码", "价格", "隐藏列"],
                "sample_rows": [["2026-10-20", "600519", "1277.96", "x"]],
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        mappings = body["result"]["mappings"]
        assert mappings == [
            {
                "source": "日期",
                "target": "trade_date",
                "confidence": 0.9,
                "reason": "列名一致",
            },
            {
                "source": "代码",
                "target": "symbol",
                "confidence": 0.8,
                "reason": "语义一致",
            },
        ]
        assert body["result"]["unmapped"] == ["价格", "隐藏列"]
        assert body["action"] == "import.mapping_suggestion"
        assert body["run_id"]

    def test_hidden_field_excluded_from_prompt(self, client, db, mapping_ctx, monkeypatch):
        ws_id, tid, headers, _owner = mapping_ctx
        captured = _patch_complete(monkeypatch, '{"mappings": [], "unmapped": []}')
        client.post(
            MAPPING_URL.format(ws=ws_id),
            json={"target_table_id": tid, "headers": ["日期", "代码"], "sample_rows": []},
            headers=headers,
        )
        prompt = captured["messages"][1]["content"]
        assert "internal_note" not in prompt
        assert "trade_date" in prompt and "symbol" in prompt

    def test_no_db_write(self, client, db, mapping_ctx, monkeypatch):
        ws_id, tid, headers, _owner = mapping_ctx
        _patch_complete(monkeypatch, '{"mappings": [], "unmapped": []}')
        before_rows = db.query(DataField).filter(DataField.table_id == tid).count()
        before_tasks = db.query(ImportTask).count()
        client.post(
            MAPPING_URL.format(ws=ws_id),
            json={"target_table_id": tid, "headers": ["日期"], "sample_rows": []},
            headers=headers,
        )
        assert db.query(DataField).filter(DataField.table_id == tid).count() == before_rows
        assert db.query(ImportTask).count() == before_tasks

    def test_non_member_denied(self, client, db, mapping_ctx):
        ws_id, tid, _headers, _owner = mapping_ctx
        _make_user(db, "map_outsider")
        outsider = _login(client, "map_outsider")
        response = client.post(
            MAPPING_URL.format(ws=ws_id),
            json={"target_table_id": tid, "headers": ["日期"], "sample_rows": []},
            headers=outsider,
        )
        assert response.status_code == 403

    def test_missing_target_table_404(self, client, mapping_ctx, monkeypatch):
        ws_id, _tid, headers, _owner = mapping_ctx
        _patch_complete(monkeypatch, '{"mappings": [], "unmapped": []}')
        response = client.post(
            MAPPING_URL.format(ws=ws_id),
            json={"target_table_id": 999999, "headers": ["日期"], "sample_rows": []},
            headers=headers,
        )
        assert response.status_code == 404

    def test_unconfigured_key_reports_hint(self, client, db, mapping_ctx):
        ws_id, tid, headers, owner = mapping_ctx
        db.query(LlmUserConfig).filter(LlmUserConfig.user_id == owner.id).delete()
        db.commit()
        response = client.post(
            MAPPING_URL.format(ws=ws_id),
            json={"target_table_id": tid, "headers": ["日期"], "sample_rows": []},
            headers=headers,
        )
        assert response.status_code == 400
        assert "个人设置" in response.json()["detail"]
