"""文档事件审计（需求 0173）测试.

覆盖：创建 / 更新正文 / 删除 / 恢复 / 回滚 / 复制 / 跨区移动写入 ``document.*`` 事件；
detail 不含正文；审计写入失败不影响主流程。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

API = "/api/v1/workspaces/{wid}/documents"


def _ws(client: TestClient, auth: dict[str, str], name: str) -> int:
    r = client.post("/api/v1/workspaces", json={"name": name}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create(client: TestClient, auth: dict[str, str], wid: int, title: str, content: str = "") -> dict:
    r = client.post(API.format(wid=wid), json={"title": title, "content": content}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def _events(db: Session, action: str) -> list:
    from cndb.core.events import CoreEvent

    return db.query(CoreEvent).filter(CoreEvent.action == action).order_by(CoreEvent.id).all()


class TestDocumentEventAudit:
    def test_create_and_update_write_events_without_content(self, client, auth_headers, db):
        wid = _ws(client, auth_headers, "审计-增改")
        doc = _create(client, auth_headers, wid, "审计文档", "机密正文不应进事件")
        assert [e.target_id for e in _events(db, "document.create")] == [str(doc["id"])]
        create_event = _events(db, "document.create")[0]
        assert create_event.target_type == "document"
        assert create_event.workspace_id == wid
        assert "机密正文" not in str(create_event.detail)

        r = client.put(
            f"{API.format(wid=wid)}/{doc['id']}/content",
            json={"content": "第二版机密正文"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        update_event = _events(db, "document.update_content")[-1]
        assert update_event.target_id == str(doc["id"])
        assert "机密" not in str(update_event.detail)
        assert update_event.detail["version_number"] == 2

    def test_delete_restore_rollback_and_duplicate(self, client, auth_headers, db):
        wid = _ws(client, auth_headers, "审计-生命周期")
        doc = _create(client, auth_headers, wid, "生命周期文档", "v1")
        client.put(
            f"{API.format(wid=wid)}/{doc['id']}/content",
            json={"content": "v2"},
            headers=auth_headers,
        )
        r = client.post(
            f"{API.format(wid=wid)}/{doc['id']}/rollback",
            json={"target_version": 1},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        assert client.delete(f"{API.format(wid=wid)}/{doc['id']}", headers=auth_headers).status_code == 200
        assert client.post(f"{API.format(wid=wid)}/{doc['id']}/restore", headers=auth_headers).status_code == 200
        copy = client.post(f"{API.format(wid=wid)}/{doc['id']}/duplicate", json={}, headers=auth_headers)
        assert copy.status_code == 201, copy.text

        assert len(_events(db, "document.rollback")) == 1
        assert len(_events(db, "document.delete")) == 1
        assert len(_events(db, "document.restore")) == 1
        assert len(_events(db, "document.duplicate")) == 1

    def test_event_failure_does_not_break_request(self, client, auth_headers, monkeypatch):
        from cndb.plugins.documents.routers import documents as documents_router

        def _boom(*args, **kwargs):
            raise RuntimeError("audit down")

        monkeypatch.setattr(documents_router, "record_event", _boom)
        wid = _ws(client, auth_headers, "审计-降级")
        r = client.post(API.format(wid=wid), json={"title": "降级文档", "content": "正文"}, headers=auth_headers)
        assert r.status_code == 201, r.text
