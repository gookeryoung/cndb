"""统一事件/审计流测试（A4）.

覆盖：
- record_event 写入字段（含 request_id 自动关联、actor_name 快照、target_id 字符串化、summary 截断）；
- **尽力而为**：写入失败不抛给调用方；
- query_events 过滤（action / actor / target / workspace / request_id / keyword / 时间范围）与分页；
- distinct_actions 计数；
- API 权限（未登录 401、非审计角色 403、超管/审计管理员 200）与响应形状;
- 既有写入点接入：用户管理审计 → user.* 事件；表记录审计 → record.* 事件；认证动作 → auth.* 事件；
- 事件与观测 request_id 串联。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from cndb.core.events import (
    ACTION_AUTH_LOGIN,
    ACTION_AUTH_LOGIN_FAILED,
    ACTION_AUTH_LOGOUT,
    ACTION_AUTH_PASSWORD_CHANGED,
    TARGET_RECORD,
    TARGET_USER,
    CoreEvent,
    distinct_actions,
    query_events,
    record_event,
)
from cndb.plugins.accounts.models import User

EVENTS_API = "/api/v1/admin/events"
AUTH = "/api/v1/accounts/auth"


class TestRecordEvent:
    def test_writes_basic_fields(self, db: Session):
        event = record_event(
            db,
            "document.create",
            summary="新建文档",
            target_type="document",
            target_id=42,
            workspace_id=7,
            actor_id=3,
            actor_name="alice",
            detail={"title": "周报"},
        )
        assert event is not None
        assert event.id is not None
        assert event.target_id == "42"  # 统一字符串化
        assert event.summary == "新建文档"
        assert event.detail == {"title": "周报"}
        assert event.actor_name == "alice"
        assert event.created_at is not None

    def test_summary_truncated_to_255(self, db: Session):
        event = record_event(db, "x.y", summary="长" * 400)
        assert event is not None
        assert len(event.summary) == 255

    def test_request_id_taken_from_observation_context(self, db: Session):
        from cndb.core.observability import bind_request_id

        with bind_request_id("rid-abc"):
            event = record_event(db, "auth.login", summary="登录")
        assert event is not None
        assert event.request_id == "rid-abc"

    def test_explicit_request_id_wins(self, db: Session):
        event = record_event(db, "auth.login", request_id="explicit-1")
        assert event is not None and event.request_id == "explicit-1"

    def test_no_request_context_leaves_null(self, db: Session):
        event = record_event(db, "system.boot")
        assert event is not None and event.request_id is None

    def test_never_raises_on_failure(self, db: Session, monkeypatch):
        """写入失败只记日志：不得把业务事务带崩."""

        def boom(*_args, **_kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(Session, "commit", boom)
        assert record_event(db, "x.y", summary="应失败但不抛") is None

    def test_commit_false_defers(self, db: Session):
        event = record_event(db, "x.y", summary="延迟提交", commit=False)
        assert event is not None
        db.commit()
        assert db.get(CoreEvent, event.id) is not None


class TestQueryEvents:
    @pytest.fixture
    def seeded(self, db: Session) -> list[int]:
        ids = []
        for i in range(6):
            e = record_event(
                db,
                ACTION_AUTH_LOGIN if i % 2 == 0 else "user.update",
                summary=f"事件 {i}",
                target_type=TARGET_USER,
                target_id=i,
                actor_id=1 if i < 3 else 2,
                actor_name="alice" if i < 3 else "bob",
                workspace_id=5 if i < 2 else None,
            )
            assert e is not None
            ids.append(e.id)
        return ids

    def test_newest_first(self, db: Session, seeded):
        items, total = query_events(db)
        assert total == 6
        assert [i.id for i in items] == sorted(seeded, reverse=True)

    def test_filter_by_action(self, db: Session, seeded):
        items, total = query_events(db, action=ACTION_AUTH_LOGIN)
        assert total == 3
        assert all(i.action == ACTION_AUTH_LOGIN for i in items)

    def test_filter_by_actor_and_target(self, db: Session, seeded):
        _items, total = query_events(db, actor_id=2)
        assert total == 3
        _items, total = query_events(db, target_type=TARGET_USER, target_id="3")
        assert total == 1

    def test_filter_by_workspace(self, db: Session, seeded):
        _items, total = query_events(db, workspace_id=5)
        assert total == 2

    def test_keyword_matches_summary_and_actor(self, db: Session, seeded):
        _items, total = query_events(db, keyword="bob")
        assert total == 3
        _items, total = query_events(db, keyword="事件 5")
        assert total == 1

    def test_pagination(self, db: Session, seeded):
        page1, total = query_events(db, page=1, page_size=4)
        page2, _ = query_events(db, page=2, page_size=4)
        assert total == 6
        assert len(page1) == 4 and len(page2) == 2
        assert {i.id for i in page1}.isdisjoint({i.id for i in page2})

    def test_time_range(self, db: Session, seeded):
        future = (datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1)).isoformat()
        past = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)).isoformat()
        _items, total = query_events(db, since=future)
        assert total == 0
        _items, total = query_events(db, since=past)
        assert total == 6

    def test_distinct_actions_counts(self, db: Session, seeded):
        stats = {row["action"]: row["count"] for row in distinct_actions(db)}
        assert stats[ACTION_AUTH_LOGIN] == 3
        assert stats["user.update"] == 3


class TestEventsApiPermission:
    def test_requires_authentication(self, client):
        assert client.get(EVENTS_API).status_code == 401

    def test_ordinary_user_forbidden(self, client, auth_headers):
        assert client.get(EVENTS_API, headers=auth_headers).status_code == 403

    def test_audit_admin_can_read(self, client, auth_headers, db):
        user = db.query(User).filter(User.username == "testuser").one()
        user.role = "audit_admin"
        db.commit()
        r = client.get(EVENTS_API, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["items"] == [] or r.json()["total"] >= 0

    def test_superuser_can_read_and_shape(self, client, auth_headers, db):
        user = db.query(User).filter(User.username == "testuser").one()
        user.is_superuser = True
        db.commit()

        record_event(db, ACTION_AUTH_LOGIN, summary="登录成功：tester", target_type=TARGET_USER, actor_id=user.id)
        r = client.get(EVENTS_API, headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 1
        first = body["items"][0]
        assert set(first) >= {"id", "created_at", "action", "actor_id", "target_type", "summary", "detail"}
        assert first["action"] == ACTION_AUTH_LOGIN

    def test_filters_and_paging_via_api(self, client, auth_headers, db):
        user = db.query(User).filter(User.username == "testuser").one()
        user.is_superuser = True
        db.commit()

        for i in range(3):
            record_event(db, "record.create", summary=f"新增记录 {i}", target_type=TARGET_RECORD, actor_id=user.id)

        r = client.get(f"{EVENTS_API}?action=record.create&page_size=2&page=1", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["total"] == 3
        assert len(r.json()["items"]) == 2

        r = client.get(f"{EVENTS_API}/actions", headers=auth_headers)
        assert r.status_code == 200
        assert any(item["action"] == "record.create" for item in r.json()["items"])


class TestWiring:
    """既有写入点是否同步进统一流."""

    def test_user_admin_audit_emits_core_event(self, client, db, auth_headers):
        from cndb.plugins.accounts.services.users import record_audit

        actor = db.query(User).filter(User.username == "testuser").one()
        record_audit(db, action="update", actor_id=actor.id, target_user_id=actor.id, detail={"before": {}})

        event = db.query(CoreEvent).filter(CoreEvent.action == "user.update").order_by(CoreEvent.id.desc()).first()
        assert event is not None
        assert event.target_type == TARGET_USER
        assert event.target_id == str(actor.id)
        assert event.summary  # 中文摘要非空

    def test_record_audit_emits_core_event(self, client, db, auth_headers):
        from cndb.plugins.tables.models import DataTable
        from cndb.plugins.tables.services.core.audit import ACTION_CREATE, log_action

        actor = db.query(User).filter(User.username == "testuser").one()
        table = db.query(DataTable).first()
        if table is None:  # 测试库可能无表，直接构造一行（db_table_name 为非空列）
            table = DataTable(workspace_id=1, name="t", description="", db_table_name="t_evt_test")
            db.add(table)
            db.commit()

        log_action(db, table, ACTION_CREATE, target_id=1, actor_id=actor.id)

        event = db.query(CoreEvent).filter(CoreEvent.action == "record.create").order_by(CoreEvent.id.desc()).first()
        assert event is not None
        assert event.target_type == TARGET_RECORD
        assert event.workspace_id == table.workspace_id

    def test_login_emits_auth_event(self, client, db, account):
        event = db.query(CoreEvent).filter(CoreEvent.action == ACTION_AUTH_LOGIN).order_by(CoreEvent.id.desc()).first()
        assert event is not None
        assert event.actor_name == account["username"]
        assert event.request_id  # 由观测中间件注入

    def test_failed_login_emits_event(self, client, db, account):
        client.post(f"{AUTH}/login", json={"login": account["username"], "password": "wrong"})
        event = (
            db.query(CoreEvent)
            .filter(CoreEvent.action == ACTION_AUTH_LOGIN_FAILED)
            .order_by(CoreEvent.id.desc())
            .first()
        )
        assert event is not None
        assert account["username"] in event.summary

    def test_logout_and_password_change_emit_events(self, client, db, account):
        headers = {"Authorization": f"Bearer {account['access']}"}
        assert client.post(f"{AUTH}/logout", json={"refresh_token": account["refresh"]}).status_code == 200
        assert (
            client.post(
                f"{AUTH}/password",
                json={"current_password": account["password"], "new_password": "newpass456"},
                headers=headers,
            ).status_code
            == 200
        )

        # 注意：仅凭刷新令牌登出时没有认证用户，事件 actor_id 为空（预期行为）
        actions = {row[0] for row in db.query(CoreEvent.action).distinct().all()}
        assert ACTION_AUTH_LOGOUT in actions
        assert ACTION_AUTH_PASSWORD_CHANGED in actions


@pytest.fixture
def account(client, db: Session) -> dict[str, str]:
    """独立账号（每次用例新建，避免与 conftest 的 testuser 相互影响）."""
    username, password = "eventuser", "passw0rd"
    client.post(f"{AUTH}/register", json={"username": username, "email": "ev@example.com", "password": password})
    body = client.post(f"{AUTH}/login", json={"login": username, "password": password}).json()
    return {
        "username": username,
        "password": password,
        "access": body["access_token"],
        "refresh": body["refresh_token"],
    }
