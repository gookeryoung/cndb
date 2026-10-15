"""实时协作 WebSocket 端点（``GET /api/v1/ws``）.

**鉴权**：浏览器 ``WebSocket`` 无法自定义请求头，因此 access token 走查询参数 ``?token=``。
为此做了两点缓解：访问日志只记 ``scope["path"]``（不含 query，token 不会进日志），
以及在连接建立后立即校验（失败即 1008 关闭）。

**协议**（信封 ``{"type", "ts", "payload"}``）：
- 服务端 → 客户端：``presence.sync``（连接即发，房间在线快照）、``presence.join`` / ``presence.leave``、
  ``presence.update``、``event.created``（A4 统一事件实时推送）、``doc.lock``（编辑锁变化）、``ping``、``pong``
- 客户端 → 服务端：``presence.update``（``payload.document_id`` / ``payload.mode``）、``pong``（**回应 ping，
  否则连接会在心跳超时后关闭**）、``ping``（可选，用于客户端侧探活）

**单进程假设**：房间状态在进程内存（``core/realtime.py``），多实例部署需要外接共享通道。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from cndb.api.deps import authenticate_jwt, local_user_for
from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.core.realtime import (
    CLIENT_PING,
    CLIENT_PONG,
    CLIENT_PRESENCE_UPDATE,
    HEARTBEAT_SECONDS,
    HEARTBEAT_TIMEOUT_SECONDS,
    MODE_EDITING,
    MODE_VIEWING,
    MSG_ERROR,
    MSG_PING,
    MSG_PONG,
    MSG_PRESENCE_JOIN,
    MSG_PRESENCE_LEAVE,
    MSG_PRESENCE_SYNC,
    MSG_PRESENCE_UPDATE,
    Connection,
    make_message,
    realtime_hub,
    workspace_room,
)
from cndb.plugins.accounts.models import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

_VALID_MODES = {MODE_VIEWING, MODE_EDITING}


class _AuthError(Exception):
    """连接鉴权失败（关闭码 1008）."""


def _resolve_user(db: Session, token: str | None) -> tuple[int, str]:
    """解析连接身份，返回 (user_id, username).

    - ``LOCAL_MODE``：单机免登录，映射内置本地用户；
    - 否则要求有效 access token（复用 HTTP 侧同一套校验：解码 + 用户可用 + 令牌代次）；
    - ``AUTH_ENABLED=False``：允许匿名连接（user_id=0）。
    """

    if settings.LOCAL_MODE:
        local_user = local_user_for(db)
        return int(local_user.id), str(local_user.username)

    if not settings.AUTH_ENABLED:
        return 0, "anonymous"

    if not token:
        raise _AuthError("缺少认证信息，请先登录")

    user: User | None = authenticate_jwt(token, db)
    if user is None:
        raise _AuthError("无效或过期的令牌")
    return int(user.id), str(user.username)


def _is_workspace_member(db: Any, workspace_id: int, user_id: int) -> bool:
    """工作区成员校验（LOCAL_MODE / 匿名跳过）."""
    if settings.LOCAL_MODE or not settings.AUTH_ENABLED:
        return True
    from cndb.plugins.workspaces.models import WorkspaceMember

    row = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
        .first()
    )
    return row is not None


async def _sender(conn: Connection) -> None:
    """把队列里的消息真正发出去（在本连接的 event loop 上运行）."""
    while True:
        message = await conn.queue.get()
        await conn.websocket.send_json(message)


async def _heartbeat(conn: Connection) -> None:
    """周期发送 ping.

    连接是否存活由接收侧判定：客户端需回应 ``pong``（协议要求），
    因此接收循环的 ``wait_for`` 超时即视为半开连接并关闭。
    """
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        conn.offer(make_message(MSG_PING))


@router.websocket("/api/v1/ws")
async def realtime_ws(
    websocket: WebSocket,
    workspace_id: int = Query(..., description="工作区 id"),
    token: str | None = Query(default=None, description="访问令牌（浏览器 WS 无法设置请求头）"),
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> None:
    """工作区实时通道：在线状态 + 事件推送.

    ``db`` 走 ``Depends(get_db)`` 而不是自建 ``SessionLocal()``：
    后者会**绕过**测试与部署侧对 get_db 的覆写（曾经导致本地通过、CI 上
    ``no such table: accounts_user``），依赖注入才是与其他端点一致的取会话方式。
    """
    try:
        try:
            # 注意：这里刻意**不**放进线程池（run_in_threadpool）。实测教训：
            # 40 线程池并发建连会同时争抢 DB 连接池（pool_size=5 + max_overflow=10），
            # 超出部分等待 pool_timeout=30s → 300 连接只成功 71 条、耗时 210s。
            # 串行执行时每条连接约 2.4ms（含 JWT + 成员查询），300 条 0.73s 完成，
            # 客户端侧的抖动退避（realtimeClient 的 0.7~1.3 倍）已能打散重连风暴。
            user_id, username = _resolve_user(db, token)
        except _AuthError as exc:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc))
            return

        if not _is_workspace_member(db, workspace_id, user_id):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="非该工作区成员")
            return
    except Exception:
        logger.warning("实时连接建立失败（workspace_id=%s）", workspace_id, exc_info=True)
        with suppress(Exception):
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="服务器内部错误")
        return

    await websocket.accept()

    room = workspace_room(workspace_id)
    conn = Connection(
        websocket,
        user_id=user_id,
        username=username,
        room=room,
        loop=asyncio.get_running_loop(),
    )
    snapshot = realtime_hub.register(conn)

    sender_task = asyncio.create_task(_sender(conn))
    heartbeat_task = asyncio.create_task(_heartbeat(conn))
    try:
        # 连接即同步在线快照（含自己）
        await websocket.send_json(make_message(MSG_PRESENCE_SYNC, {"members": snapshot, "workspace_id": workspace_id}))
        realtime_hub.broadcast(
            room,
            make_message(
                MSG_PRESENCE_JOIN, {"user_id": user_id, "username": username, "members": realtime_hub.snapshot(room)}
            ),
            exclude_user=user_id,
        )

        while True:
            raw = await asyncio.wait_for(websocket.receive_json(), timeout=HEARTBEAT_TIMEOUT_SECONDS)
            msg_type = str((raw or {}).get("type") or "")
            payload = (raw or {}).get("payload") or {}

            if msg_type == CLIENT_PING:
                conn.offer(make_message(MSG_PONG))
                continue
            if msg_type == CLIENT_PONG:
                continue
            if msg_type == CLIENT_PRESENCE_UPDATE:
                document_id = payload.get("document_id")
                mode = payload.get("mode")
                if mode is not None and mode not in _VALID_MODES:
                    mode = None
                presence = realtime_hub.update_presence(
                    conn,
                    document_id=int(document_id) if document_id is not None else None,
                    mode=mode,
                )
                realtime_hub.broadcast(
                    room,
                    make_message(MSG_PRESENCE_UPDATE, {"member": presence, "members": realtime_hub.snapshot(room)}),
                    exclude_user=user_id,
                )
                continue
            conn.offer(make_message(MSG_ERROR, {"detail": f"未知消息类型：{msg_type}"}))
    except WebSocketDisconnect:
        pass
    except TimeoutError:
        logger.info("实时连接静默超时，主动关闭（user_id=%s room=%s）", user_id, room)
        with suppress(Exception):  # 连接可能已断开
            await websocket.close(code=status.WS_1001_GOING_AWAY, reason="心跳超时")
    except Exception:
        logger.warning("实时连接异常（user_id=%s room=%s）", user_id, room, exc_info=True)
    finally:
        for task in (heartbeat_task, sender_task):
            task.cancel()
        left = realtime_hub.unregister(conn)
        if left:
            realtime_hub.broadcast(
                room,
                make_message(
                    MSG_PRESENCE_LEAVE,
                    {"user_id": user_id, "username": username, "members": realtime_hub.snapshot(room)},
                ),
            )


def register_realtime_routes(app: Any) -> None:
    """挂载实时通道路由."""
    app.include_router(router)


__all__ = ["register_realtime_routes", "router"]
