"""统一事件/审计流 —— 跨插件的事件记录与查询.

**为什么需要**：改前审计是"分片"的 —— ``accounts_userauditlog``（用户管理操作）、
``tables_auditlog``（行级变更），加上文档/问题/修改申请各自的 event 表。想回答
"某人在这个系统里做过什么"必须逐个表翻，且各表字段语义不同（actor / target / detail 命名不一）。

本模块提供**一个**统一事件表 ``core_event`` 与写入/查询入口：

- 写入：``record_event(...)`` —— **尽力而为**（失败只记日志，绝不把业务事务带崩），
  与既有 ``record_audit`` / ``log_action`` 的追加式写法一致（独立提交，业务回滚不牵连）；
- 关联：自动带上当前请求的 ``request_id``（来自 core/observability 的 ContextVar），
  因此事件流可与访问日志、慢查询日志按同一 id 串联；
- 可读性：``actor_name`` 为**快照**（用户被删后事件仍可读）；``summary`` 是人类可读摘要；
- 覆盖矩阵：``action`` 采用 ``域.动作`` 命名（``auth.login`` / ``user.update`` / ``record.create``），
  既有两套审计表**保留不动**（域内查询仍走原表），统一流只做汇总视图。

**刻意不做**：不迁移/删除既有审计表（避免破坏既有 API 与历史数据），不做事件回填（历史痕迹仍可查原表），
不做订阅/推送（需要时的扩展点是 ``query_events`` 之上的轮询或后续加 in-process 订阅）。
"""

from __future__ import annotations

import logging
from contextlib import suppress
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Index, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from cndb.models.base import Base, TimestampMixin

logger = logging.getLogger(__name__)

# ── 动作常量（域.动作）─────────────────────────────────────────
ACTION_AUTH_LOGIN = "auth.login"
ACTION_AUTH_LOGIN_FAILED = "auth.login_failed"
ACTION_AUTH_LOGOUT = "auth.logout"
ACTION_AUTH_PASSWORD_CHANGED = "auth.password_changed"
ACTION_AUTH_TOKEN_REUSE = "auth.token_reuse_detected"
ACTION_AUTH_SESSION_REVOKED = "auth.session_revoked"
ACTION_AUTH_REGISTER = "auth.register"

# 目标类型
TARGET_USER = "user"
TARGET_SESSION = "session"
TARGET_DOCUMENT = "document"
TARGET_TABLE = "table"
TARGET_RECORD = "record"
TARGET_SYSTEM = "system"

# 摘要模板（域内动作 → 人类可读）
_USER_ACTION_SUMMARY = {
    "update": "更新用户资料",
    "role_change": "调整用户角色",
    "activate": "启用用户",
    "deactivate": "禁用用户",
    "batch": "批量操作用户",
    "import": "批量导入用户",
    "export": "导出用户列表",
}


class CoreEvent(TimestampMixin, Base):
    """统一事件（审计流）.

    字段语义刻意保持"宽而浅"，以便任一插件都能写进来：
    ``workspace_id`` / ``actor_id`` 可空（平台级事件无工作区；系统事件无操作人）。
    """

    __tablename__ = "core_event"
    __table_args__ = (
        Index("ix_core_event_created_action", "created_at", "action"),
        {"extend_existing": True},
    )

    # 事件发生的工作区（平台级事件为 None）
    workspace_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 操作人（系统事件为 None）；actor_name 为快照，用户删除后仍可读
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    actor_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # 域.动作，例如 auth.login / user.update / record.trash
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # 与访问日志 / 慢查询日志串联（core/observability）
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"CoreEvent(id={self.id}, action={self.action!r}, target={self.target_type}:{self.target_id})"


def _current_request_id() -> str | None:
    """当前请求 id（无请求上下文时为 None）；导入失败不应影响事件写入."""
    try:
        from cndb.core.observability import get_request_id

        return get_request_id() or None
    except Exception:
        return None


def record_event(
    db: Session,
    action: str,
    *,
    summary: str = "",
    target_type: str = TARGET_SYSTEM,
    target_id: str | int | None = None,
    workspace_id: int | None = None,
    actor_id: int | None = None,
    actor_name: str | None = None,
    detail: dict[str, Any] | None = None,
    request_id: str | None = None,
    commit: bool = True,
) -> CoreEvent | None:
    """追加一条统一事件（**尽力而为**：失败只记日志，不抛给调用方）.

    Args:
        db: 数据库会话
        action: ``域.动作``，如 ``auth.login`` / ``user.update`` / ``record.create``
        summary: 人类可读摘要（列表页直接展示）
        target_type: 目标类型（user/session/document/table/record/system）
        target_id: 目标 id（统一存字符串，便于跨类型复用）
        workspace_id: 所属工作区（平台级事件留空）
        actor_id: 操作人 id；``actor_name`` 建议同时传入快照
        detail: 结构化补充（before/after、原因等）
        request_id: 显式指定关联 id；缺省取当前请求的 request_id
        commit: 是否立即提交（默认 True；调用方已有事务时可传 False 交由外层提交）

    Returns:
        写入的事件对象；失败返回 None
    """
    try:
        event = CoreEvent(
            workspace_id=workspace_id,
            actor_id=actor_id,
            actor_name=(actor_name or None),
            action=action,
            target_type=target_type,
            target_id=(str(target_id) if target_id is not None else None),
            summary=(summary or "")[:255],
            detail=detail or {},
            request_id=request_id or _current_request_id(),
        )
        db.add(event)
        if commit:
            db.commit()
        # 同步推送给该工作区的在线成员（best-effort，绝不因广播失败影响业务）
        from cndb.core.realtime import notify_event

        notify_event(event)
        invalidate_for_event(event.action, event.workspace_id)
        return event
    except Exception:
        logger.warning("写入统一事件失败 action=%s", action, exc_info=True)
        with suppress(Exception):
            db.rollback()
        return None


def invalidate_for_event(action: str, workspace_id: int | None) -> int:
    """按事件动作失效对应的只读缓存（读写一致性；best-effort）.

    把失效挂在**事件写入**这一处，而不是逐个写端点手工清理：
    记录变更（``record.*``）等写路径都已在各自 choke point 写入统一事件，
    缓存的失效点因此天然集中、不易漏。
    """
    if workspace_id is None or not action:
        return 0
    try:
        from cndb.core.cache import cache_key, list_cache

        cleared = 0
        if action.startswith("record."):
            cleared += list_cache.clear(cache_key("records", workspace_id))
        if action.startswith(("table.", "record.")):
            cleared += list_cache.clear(cache_key("tables", workspace_id))
        if action.startswith("document."):
            cleared += list_cache.clear(cache_key("doc-tree", workspace_id))
        return cleared
    except Exception:
        logger.debug("事件驱动缓存失效失败 action=%s", action, exc_info=True)
        return 0


def summarize_user_action(action: str) -> str:
    """用户管理动作 → 中文摘要（未知动作回退为动作名）."""
    return _USER_ACTION_SUMMARY.get(action, f"用户操作 {action}")


def _parse_time(value: str | None) -> datetime | None:
    """解析 ISO 时间（容忍末尾 Z）；非法值忽略（返回 None）."""
    if not value:
        return None
    try:
        text = value.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def query_events(
    db: Session,
    *,
    action: str | None = None,
    actor_id: int | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    workspace_id: int | None = None,
    request_id: str | None = None,
    keyword: str | None = None,
    since: str | None = None,
    until: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[CoreEvent], int]:
    """按条件分页查询事件（新事件在前），返回 (items, total)."""
    conditions = []
    if action:
        conditions.append(CoreEvent.action == action)
    if actor_id is not None:
        conditions.append(CoreEvent.actor_id == actor_id)
    if target_type:
        conditions.append(CoreEvent.target_type == target_type)
    if target_id:
        conditions.append(CoreEvent.target_id == str(target_id))
    if workspace_id is not None:
        conditions.append(CoreEvent.workspace_id == workspace_id)
    if request_id:
        conditions.append(CoreEvent.request_id == request_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        conditions.append(CoreEvent.summary.like(like) | CoreEvent.actor_name.like(like))
    start, end = _parse_time(since), _parse_time(until)
    if start is not None:
        conditions.append(CoreEvent.created_at >= start)
    if end is not None:
        conditions.append(CoreEvent.created_at <= end)

    total = int(db.execute(select(func.count()).select_from(CoreEvent).where(*conditions)).scalar_one())
    items = list(
        db.execute(
            select(CoreEvent)
            .where(*conditions)
            .order_by(CoreEvent.id.desc())
            .limit(max(1, page_size))
            .offset(max(0, (max(1, page) - 1) * max(1, page_size)))
        ).scalars()
    )
    return items, total


def distinct_actions(db: Session) -> list[dict[str, Any]]:
    """列出出现过的动作及计数（供前端筛选下拉）."""
    rows = db.execute(
        select(CoreEvent.action, func.count(CoreEvent.id))
        .group_by(CoreEvent.action)
        .order_by(func.count(CoreEvent.id).desc())
    ).all()
    return [{"action": row[0], "count": int(row[1])} for row in rows]


__all__ = [
    "ACTION_AUTH_LOGIN",
    "ACTION_AUTH_LOGIN_FAILED",
    "ACTION_AUTH_LOGOUT",
    "ACTION_AUTH_PASSWORD_CHANGED",
    "ACTION_AUTH_REGISTER",
    "ACTION_AUTH_SESSION_REVOKED",
    "ACTION_AUTH_TOKEN_REUSE",
    "TARGET_DOCUMENT",
    "TARGET_RECORD",
    "TARGET_SESSION",
    "TARGET_SYSTEM",
    "TARGET_TABLE",
    "TARGET_USER",
    "CoreEvent",
    "distinct_actions",
    "invalidate_for_event",
    "query_events",
    "record_event",
    "summarize_user_action",
]
