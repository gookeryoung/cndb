"""ADR 0020 P3：分析 / 搜索 AI（suggest_template / explain / search rewrite）."""

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

SUGGEST_URL = "/api/v1/workspaces/{ws}/analytics/ai/suggest-template"
EXPLAIN_URL = "/api/v1/workspaces/{ws}/analytics/ai/explain"
REWRITE_URL = "/api/v1/workspaces/{ws}/search/ai/rewrite"

VALID_CONFIG: dict[str, Any] = {
    "formulas": [{"key": "temp_span", "label": "温差", "expr": "[temp_high] - [temp_low]"}],
    "chart": {"type": "bar", "x": "city", "y": "temp_high", "aggregation": "avg"},
    "summary": {
        "group_by": "city",
        "metrics": [{"field": "temp_high", "agg": "avg", "label": "平均最高温"}],
        "sort_order": "desc",
        "top_n": 3,
    },
    "fields": ["city", "temp_high", "temp_low"],
    "limit": 1000,
}


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
        return llm_client.LlmResponse(content=content, model="model-a", usage={"total_tokens": 30})

    monkeypatch.setattr(gateway.client, "complete", fake)
    return captured


@pytest.fixture
def analytics_ctx(client, db):
    owner = _make_user(db, "an_owner")
    headers = _login(client, "an_owner")
    ws = client.post("/api/v1/workspaces", headers=headers, json={"name": "AnWS"}).json()
    table = client.post(f"/api/v1/workspaces/{ws['id']}/tables", headers=headers, json={"name": "天气"}).json()
    tid = table["id"]
    for order, (name, field_type) in enumerate([("city", "text"), ("temp_high", "number"), ("temp_low", "number")]):
        client.post(
            f"/api/v1/workspaces/{ws['id']}/tables/{tid}/fields",
            headers=headers,
            json={"name": name, "field_type": field_type, "order": order},
        )
    for city, high, low in [("北京", 28, 17), ("上海", 27, 21), ("广州", 31, 24)]:
        client.post(
            f"/api/v1/workspaces/{ws['id']}/tables/{tid}/records",
            headers=headers,
            json={"values": {"city": city, "temp_high": high, "temp_low": low}},
        )
    _give_connection(db, owner)
    return ws["id"], tid, headers, owner


class TestSuggestTemplate:
    def test_valid_config_returned_normalized(self, client, db, analytics_ctx, monkeypatch):
        ws_id, tid, headers, _owner = analytics_ctx
        import json

        _patch_complete(
            monkeypatch,
            json.dumps(
                {
                    "name": "各城市平均气温",
                    "description": "按城市看最高温",
                    "config": VALID_CONFIG,
                    "warnings": ["气温单位按摄氏度理解"],
                }
            ),
        )
        response = client.post(
            SUGGEST_URL.format(ws=ws_id),
            json={"table_id": tid, "question": "按城市看平均最高温"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["action"] == "analytics.suggest_template"
        assert body["result"]["name"] == "各城市平均气温"
        assert body["result"]["config"]["summary"]["group_by"] == "city"
        assert body["result"]["warnings"] == ["气温单位按摄氏度理解"]
        assert body["run_id"]

    def test_invalid_config_rejected_with_422(self, client, db, analytics_ctx, monkeypatch):
        ws_id, tid, headers, _owner = analytics_ctx
        import json

        bad = {**VALID_CONFIG, "chart": {"type": "bar", "x": "city", "y": "not_a_field", "aggregation": "avg"}}
        _patch_complete(monkeypatch, json.dumps({"name": "坏配置", "config": bad}))
        response = client.post(
            SUGGEST_URL.format(ws=ws_id),
            json={"table_id": tid, "question": "x"},
            headers=headers,
        )
        assert response.status_code == 422
        assert "未通过校验" in response.json()["detail"]

    def test_non_member_denied(self, client, db, analytics_ctx, monkeypatch):
        ws_id, tid, _headers, _owner = analytics_ctx
        _make_user(db, "an_outsider")
        outsider = _login(client, "an_outsider")
        response = client.post(
            SUGGEST_URL.format(ws=ws_id),
            json={"table_id": tid, "question": "x"},
            headers=outsider,
        )
        assert response.status_code == 403


class TestExplain:
    def test_explain_returns_insight(self, client, db, analytics_ctx, monkeypatch):
        ws_id, _tid, headers, _owner = analytics_ctx
        import json

        captured = _patch_complete(
            monkeypatch,
            json.dumps({"insight": "北京最高温领先上海 1 度。", "caveats": ["样本仅 3 个城市"]}),
        )
        response = client.post(
            EXPLAIN_URL.format(ws=ws_id),
            json={"summary_rows": [{"city": "北京", "avg_temp": 28}], "chart_type": "bar"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["result"]["insight"].startswith("北京")
        assert body["result"]["caveats"] == ["样本仅 3 个城市"]
        assert "北京" in captured["messages"][1]["content"]

    def test_missing_template_404(self, client, db, analytics_ctx, monkeypatch):
        ws_id, _tid, headers, _owner = analytics_ctx
        _patch_complete(monkeypatch, '{"insight": "x", "caveats": []}')
        response = client.post(
            EXPLAIN_URL.format(ws=ws_id),
            json={"summary_rows": [{"a": 1}], "template_id": 999999},
            headers=headers,
        )
        assert response.status_code == 404


class TestSearchRewrite:
    def test_rewrites_query(self, client, db, analytics_ctx, monkeypatch):
        ws_id, _tid, headers, _owner = analytics_ctx
        _patch_complete(monkeypatch, '{"query": "流程优化 审批节点"}')
        response = client.post(
            REWRITE_URL.format(ws=ws_id),
            json={"query": "我想看看那个流程优化相关的审批节点"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body == {"query": "流程优化 审批节点", "rewritten": True}

    def test_falls_back_to_original_without_key(self, client, db, analytics_ctx):
        ws_id, _tid, headers, owner = analytics_ctx
        db.query(LlmUserConfig).filter(LlmUserConfig.user_id == owner.id).delete()
        db.commit()
        response = client.post(
            REWRITE_URL.format(ws=ws_id),
            json={"query": "流程优化"},
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["query"] == "流程优化"
        assert body["rewritten"] is False
        assert "个人设置" in body["reason"]
