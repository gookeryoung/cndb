"""实时协作连接中枢（进程内）—— 房间、在线状态、消息广播.

**能力边界（重要）**：本模块是**进程内**中枢，与编辑锁同一取舍 —— 单机单进程部署下工作正常；
多实例部署需要外接 Redis pub/sub 之类的跨进程通道（这也是"什么时候才真的需要 Redis"的答案之一：
**实时协作是 Redis 的首个真实触发场景**）。

设计要点：

- **房间**：``workspace:{id}``；同一用户多标签页 = 多条连接，在线状态按用户聚合；
- **在线状态（presence）**：``user_id → {username, document_id, mode}``，``mode`` 为
  ``viewing`` / ``editing``，用于"谁正在编辑这份文档"的可见性；
- **线程安全的广播**：业务代码（A4 事件写入、编辑锁获取）跑在**线程池**里，不能直接 await websocket，
  因此每条连接自带 ``asyncio.Queue`` + 所属 event loop；广播只做
  ``loop.call_soon_threadsafe(queue.put_nowait, msg)``，**全程同步且可在任意线程调用**，
  由端点里的 sender 任务在自己的 loop 上真正发送；
- **心跳**：端点周期性发 ``ping``，客户端回 ``pong``；超时未回视为半开连接并断开；
- **信封**：``{"type": ..., "ts": ISO8601, "payload": {...}}``，前后端共用同一套类型名。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

MODE_VIEWING = "viewing"
MODE_EDITING = "editing"

# ── 服务端 → 客户端 ──
MSG_PRESENCE_SYNC = "presence.sync"
MSG_PRESENCE_JOIN = "presence.join"
MSG_PRESENCE_LEAVE = "presence.leave"
MSG_PRESENCE_UPDATE = "presence.update"
MSG_EVENT_CREATED = "event.created"
MSG_DOC_LOCK = "doc.lock"
MSG_PING = "ping"
MSG_PONG = "pong"
MSG_ERROR = "error"

# ── 客户端 → 服务端 ──
CLIENT_PING = "ping"
CLIENT_PONG = "pong"
CLIENT_PRESENCE_UPDATE = "presence.update"

# 心跳周期与容忍的静默时长（秒）
HEARTBEAT_SECONDS = 25
HEARTBEAT_TIMEOUT_SECONDS = 75


def now_iso() -> str:
    """统一时间戳（UTC ISO8601，带 Z）."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def make_message(msg_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """构造消息信封."""
    return {"type": msg_type, "ts": now_iso(), "payload": payload or {}}


def workspace_room(workspace_id: int) -> str:
    """工作区房间名（所有工作区级广播都发到这里）."""
    return f"workspace:{workspace_id}"


@dataclass
class Presence:
    """某用户在房间内的在线状态（同用户多连接聚合）."""

    user_id: int
    username: str
    connections: int = 0
    document_id: int | None = None
    mode: str | None = None
    last_seen: float = field(default_factory=time.monotonic)

    def as_dict(self) -> dict[str, Any]:
        """序列化在线状态（按文档过滤由调用方筛选）."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "connections": self.connections,
            "document_id": self.document_id,
            "mode": self.mode,
        }


class Connection:
    """一条 WebSocket 连接（含跨线程投递队列）."""

    def __init__(
        self,
        websocket: Any,
        *,
        user_id: int,
        username: str,
        room: str,
        loop: asyncio.AbstractEventLoop,
        max_queue: int = 200,
    ) -> None:
        self.websocket = websocket
        self.user_id = user_id
        self.username = username
        self.room = room
        self.loop = loop
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue)
        self.document_id: int | None = None
        self.mode: str | None = None

    def offer(self, message: dict[str, Any]) -> None:
        """把消息放进队列（**线程安全**：可在任意线程调用）.

        队列满（客户端读取过慢）时丢弃最旧的一条，避免内存无限增长。
        """
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(message)
            except Exception:
                logger.debug("实时消息投递失败（队列已满）", exc_info=True)


class RealtimeHub:
    """进程内房间中枢（线程安全）."""

    def __init__(self) -> None:
        # room -> {user_id: Presence}
        self._presence: dict[str, dict[int, Presence]] = {}
        # room -> set[Connection]
        self._connections: dict[str, set[Connection]] = {}
        self._lock = threading.Lock()

    # ── 连接生命周期 ──

    def register(self, conn: Connection) -> list[dict[str, Any]]:
        """登记连接并返回当前房间的在线快照（供 presence.sync）."""
        with self._lock:
            self._connections.setdefault(conn.room, set()).add(conn)
            presence = self._presence.setdefault(conn.room, {}).get(conn.user_id)
            if presence is None:
                presence = Presence(user_id=conn.user_id, username=conn.username)
                self._presence[conn.room][conn.user_id] = presence
            presence.connections += 1
            presence.last_seen = time.monotonic()
            return self.snapshot_locked(conn.room)

    def unregister(self, conn: Connection) -> bool:
        """注销连接；返回该用户是否已完全离开房间（用于广播 leave）."""
        with self._lock:
            room_conns = self._connections.get(conn.room)
            if room_conns is not None:
                room_conns.discard(conn)
                if not room_conns:
                    self._connections.pop(conn.room, None)

            presence = self._presence.get(conn.room, {}).get(conn.user_id)
            if presence is None:
                return False
            presence.connections = max(0, presence.connections - 1)
            if presence.connections > 0:
                return False
            self._presence.get(conn.room, {}).pop(conn.user_id, None)
            if not self._presence.get(conn.room):
                self._presence.pop(conn.room, None)
            return True

    def update_presence(self, conn: Connection, *, document_id: int | None, mode: str | None) -> dict[str, Any]:
        """更新连接的"正在看/编辑哪份文档"，返回该用户的在线状态."""
        conn.document_id = document_id
        conn.mode = mode
        with self._lock:
            presence = self._presence.get(conn.room, {}).get(conn.user_id)
            if presence is None:
                return {}
            presence.document_id = document_id
            presence.mode = mode
            presence.last_seen = time.monotonic()
            return presence.as_dict()

    # ── 查询 ──

    def snapshot_locked(self, room: str) -> list[dict[str, Any]]:
        """房间在线快照（调用方需已持锁；内部使用）."""
        return [p.as_dict() for p in self._presence.get(room, {}).values()]

    def snapshot(self, room: str) -> list[dict[str, Any]]:
        """房间在线成员快照."""
        with self._lock:
            return self.snapshot_locked(room)

    def document_viewers(self, room: str, document_id: int) -> list[dict[str, Any]]:
        """正在查看/编辑某文档的成员（按编辑优先、用户 id 排序）."""
        with self._lock:
            members = [p.as_dict() for p in self._presence.get(room, {}).values() if p.document_id == document_id]
        members.sort(key=lambda m: (m.get("mode") != MODE_EDITING, m["user_id"]))
        return members

    def connection_count(self, room: str | None = None) -> int:
        """连接数（不传房间则为全局）."""
        with self._lock:
            if room is None:
                return sum(len(c) for c in self._connections.values())
            return len(self._connections.get(room, ()))

    # ── 广播 ──

    def broadcast(self, room: str, message: dict[str, Any], *, exclude_user: int | None = None) -> int:
        """向房间广播（**同步、线程安全**：任意线程可调用），返回投递连接数."""
        with self._lock:
            targets = [c for c in self._connections.get(room, ()) if c.user_id != exclude_user]
        for conn in targets:
            conn.offer(message)
        return len(targets)

    def broadcast_workspace(self, workspace_id: int | None, message: dict[str, Any]) -> int:
        """按工作区广播；``workspace_id`` 为空（平台级事件）时不广播."""
        if workspace_id is None:
            return 0
        return self.broadcast(workspace_room(workspace_id), message)

    def reset(self) -> None:
        """清空全部房间状态（shutdown / 测试隔离用）."""
        with self._lock:
            self._connections.clear()
            self._presence.clear()


# 进程级单例（与编辑锁同一取舍：单机足够，多实例需外接共享通道）
realtime_hub = RealtimeHub()


# 事件动作 → 房间工作区（A4 事件桥接用）
def notify_event(event: Any) -> int:
    """把一条 A4 统一事件广播给对应工作区的在线成员（best-effort）."""
    try:
        message = make_message(
            MSG_EVENT_CREATED,
            {
                "id": getattr(event, "id", None),
                "action": getattr(event, "action", ""),
                "summary": getattr(event, "summary", ""),
                "actor_id": getattr(event, "actor_id", None),
                "actor_name": getattr(event, "actor_name", None),
                "target_type": getattr(event, "target_type", ""),
                "target_id": getattr(event, "target_id", None),
                "workspace_id": getattr(event, "workspace_id", None),
                "request_id": getattr(event, "request_id", None),
            },
        )
        return realtime_hub.broadcast_workspace(getattr(event, "workspace_id", None), message)
    except Exception:
        logger.debug("实时广播事件失败", exc_info=True)
        return 0


def notify_document_lock(
    workspace_id: int | None,
    document_id: int,
    *,
    locked: bool,
    user_id: int | None = None,
    username: str | None = None,
) -> int:
    """广播文档编辑锁变化（让其他查看者立刻看到"谁在编辑/已释放"）."""
    try:
        message = make_message(
            MSG_DOC_LOCK,
            {
                "document_id": document_id,
                "locked": locked,
                "user_id": user_id,
                "username": username,
            },
        )
        return realtime_hub.broadcast_workspace(workspace_id, message)
    except Exception:
        logger.debug("实时广播编辑锁失败", exc_info=True)
        return 0


__all__ = [
    "CLIENT_PING",
    "CLIENT_PONG",
    "CLIENT_PRESENCE_UPDATE",
    "HEARTBEAT_SECONDS",
    "HEARTBEAT_TIMEOUT_SECONDS",
    "MODE_EDITING",
    "MODE_VIEWING",
    "MSG_DOC_LOCK",
    "MSG_ERROR",
    "MSG_EVENT_CREATED",
    "MSG_PING",
    "MSG_PONG",
    "MSG_PRESENCE_JOIN",
    "MSG_PRESENCE_LEAVE",
    "MSG_PRESENCE_SYNC",
    "MSG_PRESENCE_UPDATE",
    "Connection",
    "Presence",
    "RealtimeHub",
    "make_message",
    "notify_document_lock",
    "notify_event",
    "now_iso",
    "realtime_hub",
    "workspace_room",
]
