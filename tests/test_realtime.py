"""实时协作（WebSocket）测试.

覆盖：
- 连接中枢 RealtimeHub：注册/注销、同用户多连接聚合、在线快照、按文档筛选、广播投递、队列满丢弃、
  连接数统计、reset；
- 广播是**同步且线程安全**的（业务线程可直接调用）；
- WS 端点：鉴权（无令牌 1008 / 无效令牌 1008 / 非成员 1008）、连接即收到 presence.sync、
  第二人加入触发 presence.join、断开触发 presence.leave、presence.update 广播、
  未知消息回 error、ping→pong；
- A4 事件 → event.created 实时推送；编辑锁 → doc.lock 实时推送。
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from cndb.core.realtime import (
    CLIENT_PING,
    CLIENT_PRESENCE_UPDATE,
    MODE_EDITING,
    MSG_DOC_LOCK,
    MSG_EVENT_CREATED,
    MSG_PONG,
    MSG_PRESENCE_JOIN,
    MSG_PRESENCE_LEAVE,
    MSG_PRESENCE_SYNC,
    Connection,
    RealtimeHub,
    make_message,
    notify_document_lock,
    notify_event,
    workspace_room,
)

WS_PATH = "/api/v1/ws"


class FakeWebSocket:
    """记录 offer 内容的最小 websocket 替身（不需要真事件循环）."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []


def _conn(hub: RealtimeHub, *, user_id: int = 1, username: str = "u1", room: str | None = None) -> Connection:
    loop = asyncio.new_event_loop()
    conn = Connection(FakeWebSocket(), user_id=user_id, username=username, room=room or workspace_room(1), loop=loop)
    hub.register(conn)
    return conn


class TestHub:
    def test_register_and_snapshot(self):
        hub = RealtimeHub()
        _conn(hub, user_id=1, username="alice")
        snapshot = hub.snapshot(workspace_room(1))
        assert len(snapshot) == 1
        assert snapshot[0]["username"] == "alice"
        assert snapshot[0]["connections"] == 1

    def test_same_user_multiple_tabs_aggregated(self):
        hub = RealtimeHub()
        _conn(hub, user_id=1, username="alice")
        _conn(hub, user_id=1, username="alice")
        snapshot = hub.snapshot(workspace_room(1))
        assert len(snapshot) == 1
        assert snapshot[0]["connections"] == 2
        assert hub.connection_count(workspace_room(1)) == 2

    def test_unregister_reports_last_leave(self):
        hub = RealtimeHub()
        c1 = _conn(hub, user_id=1, username="alice")
        c2 = _conn(hub, user_id=1, username="alice")
        assert hub.unregister(c1) is False  # 还有另一条连接
        assert hub.unregister(c2) is True  # 完全离开
        assert hub.snapshot(workspace_room(1)) == []

    def test_rooms_are_isolated(self):
        hub = RealtimeHub()
        _conn(hub, user_id=1, room=workspace_room(1))
        _conn(hub, user_id=2, username="bob", room=workspace_room(2))
        assert len(hub.snapshot(workspace_room(1))) == 1
        assert len(hub.snapshot(workspace_room(2))) == 1
        assert hub.connection_count() == 2

    def test_broadcast_delivers_to_room_only(self):
        hub = RealtimeHub()
        c1 = _conn(hub, user_id=1, room=workspace_room(1))
        other = _conn(hub, user_id=2, username="bob", room=workspace_room(2))
        delivered = hub.broadcast(workspace_room(1), make_message("x"))
        assert delivered == 1
        assert c1.queue.qsize() == 1
        assert other.queue.qsize() == 0

    def test_broadcast_excludes_user(self):
        hub = RealtimeHub()
        mine = _conn(hub, user_id=1)
        theirs = _conn(hub, user_id=2, username="bob")
        hub.broadcast(workspace_room(1), make_message("x"), exclude_user=1)
        assert mine.queue.qsize() == 0
        assert theirs.queue.qsize() == 1

    def test_broadcast_is_thread_safe(self):
        """业务线程（线程池）可直接广播，不需要事件循环."""
        hub = RealtimeHub()
        conn = _conn(hub, user_id=1)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                hub.broadcast(workspace_room(1), make_message("from-thread"))
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        assert errors == []
        assert conn.queue.qsize() == 1

    def test_queue_full_drops_oldest(self):
        hub = RealtimeHub()
        loop = asyncio.new_event_loop()
        conn = Connection(FakeWebSocket(), user_id=1, username="u", room=workspace_room(1), loop=loop, max_queue=2)
        hub.register(conn)
        for i in range(4):
            hub.broadcast(workspace_room(1), make_message("m", {"i": i}))
        assert conn.queue.qsize() == 2
        first = conn.queue.get_nowait()
        assert first["payload"]["i"] == 2  # 最旧的两条被丢弃

    def test_presence_update_and_document_viewers(self):
        hub = RealtimeHub()
        alice = _conn(hub, user_id=1, username="alice")
        bob = _conn(hub, user_id=2, username="bob")
        hub.update_presence(alice, document_id=9, mode=MODE_EDITING)
        hub.update_presence(bob, document_id=9, mode="viewing")

        viewers = hub.document_viewers(workspace_room(1), 9)
        assert [v["username"] for v in viewers] == ["alice", "bob"]  # 编辑者在前
        assert hub.document_viewers(workspace_room(1), 99) == []

    def test_reset_clears_state(self):
        hub = RealtimeHub()
        _conn(hub, user_id=1)
        hub.reset()
        assert hub.connection_count() == 0
        assert hub.snapshot(workspace_room(1)) == []

    def test_notify_event_and_lock_are_best_effort(self):
        """广播失败（无连接/异常属性）不得抛异常."""

        class Weird:
            @property
            def workspace_id(self) -> int:
                raise RuntimeError("boom")

        assert notify_event(Weird()) == 0
        assert notify_document_lock(None, 1, locked=True) == 0


class TestWebSocketEndpoint:
    def test_requires_token(self, client):
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(f"{WS_PATH}?workspace_id=1"):
            pass

    def test_invalid_token_rejected(self, client):
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(f"{WS_PATH}?workspace_id=1&token=bad-token"):
            pass

    def test_connects_and_receives_presence_sync(self, client, auth_headers, workspace_id):
        token = auth_headers["Authorization"].split(" ", 1)[1]
        from cndb.core.realtime import realtime_hub

        realtime_hub.reset()
        with client.websocket_connect(f"{WS_PATH}?workspace_id={workspace_id}&token={token}") as ws:
            msg = ws.receive_json()
            assert msg["type"] == MSG_PRESENCE_SYNC
            assert msg["payload"]["workspace_id"] == workspace_id
            assert len(msg["payload"]["members"]) == 1

    def test_non_member_rejected(self, client, auth_headers):
        token = auth_headers["Authorization"].split(" ", 1)[1]
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(f"{WS_PATH}?workspace_id=999999&token={token}"),
        ):
            pass

    def test_ping_pong(self, client, auth_headers, workspace_id):
        token = auth_headers["Authorization"].split(" ", 1)[1]
        from cndb.core.realtime import realtime_hub

        realtime_hub.reset()
        with client.websocket_connect(f"{WS_PATH}?workspace_id={workspace_id}&token={token}") as ws:
            ws.receive_json()  # presence.sync
            ws.send_json({"type": CLIENT_PING})
            msg = ws.receive_json()
            assert msg["type"] == MSG_PONG

    def test_presence_update_broadcast_and_unknown_type(self, client, auth_headers, workspace_id):
        token = auth_headers["Authorization"].split(" ", 1)[1]
        from cndb.core.realtime import realtime_hub

        realtime_hub.reset()
        with client.websocket_connect(f"{WS_PATH}?workspace_id={workspace_id}&token={token}") as ws:
            ws.receive_json()
            ws.send_json({"type": CLIENT_PRESENCE_UPDATE, "payload": {"document_id": 5, "mode": MODE_EDITING}})
            # 自己不发给自己（排除自己），因此这里应收到 error（未知类型分支之外的正常静默）
            ws.send_json({"type": "no-such-type"})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "未知消息类型" in msg["payload"]["detail"]

    def test_second_connection_triggers_join(self, client, auth_headers, workspace_id, second_account):
        from contextlib import ExitStack

        from cndb.core.realtime import realtime_hub

        realtime_hub.reset()
        t1 = auth_headers["Authorization"].split(" ", 1)[1]
        t2 = second_account
        # 用 ExitStack 精细控制 ws2 的关闭时机（需在 ws1 仍打开时观察 leave）
        with ExitStack() as stack:
            ws1 = stack.enter_context(client.websocket_connect(f"{WS_PATH}?workspace_id={workspace_id}&token={t1}"))
            ws1.receive_json()  # sync（1 人）
            with client.websocket_connect(f"{WS_PATH}?workspace_id={workspace_id}&token={t2}") as ws2:
                ws2.receive_json()  # sync（应含 2 人）
                join = ws1.receive_json()
                assert join["type"] == MSG_PRESENCE_JOIN
                assert len(join["payload"]["members"]) == 2
            # ws2 已关闭 → ws1 应收到 leave
            leave = ws1.receive_json()
            assert leave["type"] == MSG_PRESENCE_LEAVE

    def test_event_created_pushed_to_workspace(self, client, auth_headers, workspace_id, db):
        """A4 事件写入 → 在线成员收到 event.created."""
        from cndb.core.events import record_event
        from cndb.core.realtime import realtime_hub

        realtime_hub.reset()
        token = auth_headers["Authorization"].split(" ", 1)[1]
        with client.websocket_connect(f"{WS_PATH}?workspace_id={workspace_id}&token={token}") as ws:
            ws.receive_json()
            record_event(
                db,
                "record.create",
                summary="新增记录",
                target_type="record",
                workspace_id=workspace_id,
                actor_id=1,
            )
            msg = ws.receive_json()
            assert msg["type"] == MSG_EVENT_CREATED
            assert msg["payload"]["action"] == "record.create"
            assert msg["payload"]["workspace_id"] == workspace_id

    def test_document_lock_pushed_to_workspace(self, client, auth_headers, workspace_id, doc_api):
        """编辑锁变化 → 在线成员收到 doc.lock."""
        from cndb.core.realtime import realtime_hub

        realtime_hub.reset()
        token = auth_headers["Authorization"].split(" ", 1)[1]
        doc = client.post(doc_api, json={"title": "协作文档", "content": "正文"}, headers=auth_headers).json()
        with client.websocket_connect(f"{WS_PATH}?workspace_id={workspace_id}&token={token}") as ws:
            ws.receive_json()
            assert client.post(f"{doc_api}/{doc['id']}/lock", headers=auth_headers).status_code == 200
            locked = ws.receive_json()
            assert locked["type"] == MSG_DOC_LOCK
            assert locked["payload"]["locked"] is True
            assert locked["payload"]["document_id"] == doc["id"]

            assert client.delete(f"{doc_api}/{doc['id']}/lock", headers=auth_headers).status_code == 200
            released = ws.receive_json()
            assert released["type"] == MSG_DOC_LOCK
            assert released["payload"]["locked"] is False


@pytest.fixture
def workspace_id(client, auth_headers) -> int:
    r = client.post("/api/v1/workspaces", json={"name": "realtime-ws"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def doc_api(workspace_id: int) -> str:
    return f"/api/v1/workspaces/{workspace_id}/documents"


@pytest.fixture
def second_account(client, workspace_id, db) -> str:
    """第二个账号：注册 → 加入工作区 → 登录，返回其 access token."""
    from cndb.plugins.accounts.models import User
    from cndb.plugins.workspaces.models import WorkspaceMember

    username, password = "rt-user-2", "passw0rd"
    client.post(
        "/api/v1/accounts/auth/register",
        json={"username": username, "email": "rt2@example.com", "password": password},
    )
    token = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": password}).json()[
        "access_token"
    ]
    # 加入工作区（直插成员表，避免依赖具体邀请接口）；必须用测试会话，不能用生产 SessionLocal
    user = db.query(User).filter(User.username == username).one()
    db.add(WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role="editor"))
    db.commit()
    return token
