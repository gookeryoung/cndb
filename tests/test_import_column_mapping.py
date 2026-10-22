"""ADR 0020 P2/P3 补全：导入列映射（column_mapping）真正落库.

把 AI 列映射建议从「前端参考态」接到导入链路：analyze / confirm 接收
``{源列名: 目标字段名 | null}``，execute 阶段经 ``Importer(field_mapping=...)`` 写入目标字段。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from tests.helpers import wait_import_settled

ANALYZE_URL = "/api/v1/workspaces/{ws}/tables/{tid}/import/analyze"
CONFIRM_URL = "/api/v1/workspaces/{ws}/tables/{tid}/import/{task}/confirm"
TASK_URL = "/api/v1/workspaces/{ws}/tables/{tid}/import/async/{task}"
RECORDS_URL = "/api/v1/workspaces/{ws}/tables/{tid}/records"


def _make_user(db: Session, username: str = "map_import_user") -> User:
    user = User(username=username, nickname=username)
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login(client: TestClient, username: str = "map_import_user") -> dict[str, str]:
    response = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def import_ctx(client, db):
    _make_user(db)
    headers = _login(client)
    ws = client.post("/api/v1/workspaces", headers=headers, json={"name": "MapImportWS"}).json()
    table = client.post(f"/api/v1/workspaces/{ws['id']}/tables", headers=headers, json={"name": "城市天气"}).json()
    tid = table["id"]
    for order, (name, field_type) in enumerate([("city", "text"), ("temp_high", "number")]):
        client.post(
            f"/api/v1/workspaces/{ws['id']}/tables/{tid}/fields",
            headers=headers,
            json={"name": name, "field_type": field_type, "order": order},
        )
    return ws["id"], tid, headers


def _csv_files() -> dict[str, Any]:
    content = "城市,温度\n北京,28\n上海,31\n".encode()
    return {"file": ("weather.csv", content, "text/csv")}


class TestColumnMappingImport:
    def test_confirm_with_mapping_writes_target_fields(self, client, import_ctx):
        ws_id, tid, headers = import_ctx
        analyze = client.post(
            ANALYZE_URL.format(ws=ws_id, tid=tid),
            headers=headers,
            files=_csv_files(),
            data={"column_mapping": json.dumps({"城市": "city", "温度": "temp_high"})},
        )
        assert analyze.status_code == 200, analyze.text
        task_id = analyze.json()["task_id"]
        settled = wait_import_settled(client, TASK_URL.format(ws=ws_id, tid=tid, task=task_id), headers)
        assert settled["status"] == "pending_confirm", settled.get("error_message")

        confirm = client.post(
            CONFIRM_URL.format(ws=ws_id, tid=tid, task=task_id),
            headers=headers,
            params={"column_mapping": json.dumps({"城市": "city", "温度": "temp_high"})},
            json={},
        )
        assert confirm.status_code == 200, confirm.text
        done = wait_import_settled(client, TASK_URL.format(ws=ws_id, tid=tid, task=task_id), headers)
        assert done["status"] == "done", done.get("error_message")
        assert done["imported_rows"] == 2

        rows = client.get(f"{RECORDS_URL.format(ws=ws_id, tid=tid)}?limit=10", headers=headers).json()["rows"]
        assert {(row["city"], row["temp_high"]) for row in rows} == {("北京", 28), ("上海", 31)}

    def test_invalid_mapping_json_rejected(self, client, import_ctx):
        ws_id, tid, headers = import_ctx
        response = client.post(
            ANALYZE_URL.format(ws=ws_id, tid=tid),
            headers=headers,
            files=_csv_files(),
            data={"column_mapping": "not-json"},
        )
        assert response.status_code == 400
        assert "column_mapping" in response.json()["detail"]

    def test_reanalyze_accepts_mapping(self, client, import_ctx):
        ws_id, tid, headers = import_ctx
        analyze = client.post(
            ANALYZE_URL.format(ws=ws_id, tid=tid),
            headers=headers,
            files=_csv_files(),
            data={"column_mapping": json.dumps({"城市": "city"})},
        )
        task_id = analyze.json()["task_id"]
        wait_import_settled(client, TASK_URL.format(ws=ws_id, tid=tid, task=task_id), headers)
        reanalyze = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{tid}/import/{task_id}/reanalyze",
            headers=headers,
            params={"column_mapping": json.dumps({"城市": "city", "温度": "temp_high"})},
        )
        assert reanalyze.status_code == 200, reanalyze.text
        settled = wait_import_settled(client, TASK_URL.format(ws=ws_id, tid=tid, task=task_id), headers)
        assert settled["status"] == "pending_confirm", settled.get("error_message")
        report = settled["validation_report"]
        assert "city" not in (report.get("skipped_columns") or [])
