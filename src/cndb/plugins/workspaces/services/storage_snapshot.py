"""工作区存储用量快照的读写与刷新（ADR 0024）.

用量本身由 ``services/storage.py`` 计算（口径唯一），本模块只负责**把结果持久化**，
并提供三种触发方式：

- 定时：``core/storage_refresh`` 的后台线程按周期调 ``refresh_all``；
- 脏唤醒：配额调整 / 上传 / 删除后 ``mark_dirty(workspace_id)``，下一轮只刷脏集合；
- 手动：管理台「立即刷新」端点调 ``request_refresh`` 后由同一线程执行。

读路径（管理台列表 / 工作区详情 / 上传配额预判）只读本表，不在请求内做全量统计。
缺行 = 尚未统计：``snapshot_used_bytes(lazy=False)`` 返回 ``None``（由调用方展示
「统计中」），``lazy=True`` 时懒计算一次并落库（详情与上传预判用）。
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from cndb.core.database import SessionLocal
from cndb.plugins.workspaces.models import Workspace, WorkspaceStorageSnapshot
from cndb.plugins.workspaces.services.storage import workspace_storage_bytes

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RefreshReport:
    """一轮刷新的结果（用于日志与接口返回）."""

    refreshed: int
    failed: int
    duration_ms: int
    workspace_ids: tuple[int, ...] = ()


# ── 脏集合与唤醒信号（进程内） ──


class _RefreshState:
    """进程内待刷新状态（用实例属性代替模块级 ``global``，便于单测重置）."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.dirty: set[int] = set()
        self.all_requested = False
        self.wakeup: threading.Event | None = None


_state = _RefreshState()


def register_wakeup(event: threading.Event | None) -> None:
    """由后台刷新器登记唤醒信号（``None`` 表示停止后解绑）."""
    _state.wakeup = event


def mark_dirty(workspace_id: int | None = None) -> None:
    """标记工作区待刷新（``None`` = 请求全量刷新），并唤醒后台线程."""
    with _state.lock:
        if workspace_id is None:
            _state.all_requested = True
        else:
            _state.dirty.add(workspace_id)
    event = _state.wakeup
    if event is not None:
        event.set()


def pop_dirty() -> tuple[set[int], bool]:
    """取出并清空脏集合，返回 ``(工作区 id 集合, 是否要求全量)``."""
    with _state.lock:
        dirty = set(_state.dirty)
        _state.dirty.clear()
        all_flag = _state.all_requested
        _state.all_requested = False
    return dirty, all_flag


def has_pending_work() -> bool:
    """当前是否有待刷新请求（供后台线程判断忙闲）."""
    with _state.lock:
        return bool(_state.dirty) or _state.all_requested


def reset_state() -> None:
    """清空进程内状态（测试用；不影响已落库快照）."""
    with _state.lock:
        _state.dirty.clear()
        _state.all_requested = False
    _state.wakeup = None


def request_refresh(workspace_ids: list[int] | None = None) -> list[int]:
    """接口层入口：投递刷新请求（异步），返回被投递的工作区 id（空 = 全量）."""
    ids: list[int] = sorted({int(i) for i in workspace_ids}) if workspace_ids else []
    if not ids:
        mark_dirty(None)
    for workspace_id in ids:
        mark_dirty(workspace_id)
    return ids


# ── 读取 ──


def _as_utc(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite 读回的是 naive datetime，统一按 UTC 解释."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def read_snapshot(db: Session, workspace_id: int) -> WorkspaceStorageSnapshot | None:
    """读单个工作区快照（缺行返回 None，不触发计算）."""
    return db.get(WorkspaceStorageSnapshot, workspace_id)


def read_snapshots(db: Session, workspace_ids: list[int] | tuple[int, ...]) -> dict[int, WorkspaceStorageSnapshot]:
    """批量读快照（一次 IN 查询，避免逐工作区往返）."""
    ids = list(dict.fromkeys(int(i) for i in workspace_ids))
    if not ids:
        return {}
    rows = (
        db.execute(select(WorkspaceStorageSnapshot).where(WorkspaceStorageSnapshot.workspace_id.in_(ids)))
        .scalars()
        .all()
    )
    return {row.workspace_id: row for row in rows}


def snapshot_age_seconds(snapshot: WorkspaceStorageSnapshot | None, *, now: dt.datetime | None = None) -> int | None:
    """快照年龄（秒，向上取整、不为负）；无快照返回 None."""
    computed_at = _as_utc(snapshot.computed_at) if snapshot is not None else None
    if computed_at is None:
        return None
    current = now or dt.datetime.now(dt.UTC)
    return max(0, int((current - computed_at).total_seconds()))


def snapshot_computed_at(snapshot: WorkspaceStorageSnapshot | None) -> str | None:
    """快照时间的 ISO 字符串（UTC aware），无快照返回 None."""
    computed_at = _as_utc(snapshot.computed_at) if snapshot is not None else None
    return computed_at.isoformat() if computed_at is not None else None


# ── 刷新 ──


def refresh_workspace(db: Session, workspace_id: int) -> WorkspaceStorageSnapshot:
    """重算单工作区用量并 upsert 快照（调用方负责 commit）."""
    started = time.perf_counter()
    used = workspace_storage_bytes(db, workspace_id)
    duration_ms = int((time.perf_counter() - started) * 1000)
    snapshot = db.get(WorkspaceStorageSnapshot, workspace_id)
    if snapshot is None:
        snapshot = WorkspaceStorageSnapshot(
            workspace_id=workspace_id,
            used_bytes=used,
            computed_at=dt.datetime.now(dt.UTC),
            duration_ms=duration_ms,
        )
        db.add(snapshot)
    else:
        snapshot.used_bytes = used
        snapshot.computed_at = dt.datetime.now(dt.UTC)
        snapshot.duration_ms = duration_ms
    return snapshot


def refresh_all(db: Session | None = None, *, only_dirty: bool = False) -> RefreshReport:
    """刷新一批工作区：默认全量，``only_dirty`` 且有脏集合时只刷脏.

    单个工作区失败只记日志与计数，不影响其余工作区（ADR 0024 I4）。
    """
    started = time.perf_counter()
    dirty, all_flag = pop_dirty()
    session = db
    owns_session = session is None
    if session is None:
        session = SessionLocal()
    refreshed: list[int] = []
    failed = 0
    try:
        if only_dirty and dirty and not all_flag:
            targets: list[int] = sorted(dirty)
        else:
            targets = [row[0] for row in session.query(Workspace.id).order_by(Workspace.id).all()]
        existing = set(targets)
        for workspace_id in targets:
            try:
                refresh_workspace(session, workspace_id)
                session.commit()
                refreshed.append(workspace_id)
            except Exception:
                session.rollback()
                failed += 1
                logger.warning("刷新工作区 %s 存储用量失败（跳过，等下一轮）", workspace_id, exc_info=True)
        # 刷新期间被删除的工作区留在脏集合里没有意义：直接丢弃
        stale = {i for i in dirty if i not in existing}
        if stale:
            logger.debug("丢弃已不存在工作区的脏标记: %s", sorted(stale))
    finally:
        if owns_session:
            session.close()
    duration_ms = int((time.perf_counter() - started) * 1000)
    report = RefreshReport(
        refreshed=len(refreshed),
        failed=failed,
        duration_ms=duration_ms,
        workspace_ids=tuple(refreshed),
    )
    if refreshed or failed:
        logger.info("存储用量快照刷新完成: %s", report)
    return report


def snapshot_used_bytes(db: Session, workspace_id: int, *, lazy: bool = True) -> int | None:
    """读用量（字节）：快照缺失时 ``lazy=True`` 现场算一次并落库，否则返回 None."""
    snapshot = read_snapshot(db, workspace_id)
    if snapshot is not None:
        return snapshot.used_bytes
    if not lazy:
        return None
    try:
        snapshot = refresh_workspace(db, workspace_id)
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("懒计算工作区 %s 存储用量失败", workspace_id, exc_info=True)
        return None
    return snapshot.used_bytes


def bump_used_bytes(db: Session, workspace_id: int, delta: int) -> None:
    """乐观累加快照用量（上传 / 删除后立即生效，后台下一轮再校正）.

    快照缺失时不创建（等懒计算或定时刷新填真值），只置脏。
    """
    if delta == 0:
        return
    new_value = WorkspaceStorageSnapshot.used_bytes + int(delta)
    db.execute(
        update(WorkspaceStorageSnapshot)
        .where(WorkspaceStorageSnapshot.workspace_id == workspace_id)
        .values(used_bytes=case((new_value < 0, 0), else_=new_value))
    )
    mark_dirty(workspace_id)


def set_used_bytes(db: Session, workspace_id: int, used_bytes: int) -> None:
    """直接写入已知用量（测试 / 迁移补数用，不重算）."""
    snapshot = db.get(WorkspaceStorageSnapshot, workspace_id)
    now = dt.datetime.now(dt.UTC)
    if snapshot is None:
        db.add(
            WorkspaceStorageSnapshot(
                workspace_id=workspace_id,
                used_bytes=max(0, int(used_bytes)),
                computed_at=now,
                duration_ms=0,
            )
        )
    else:
        snapshot.used_bytes = max(0, int(used_bytes))
        snapshot.computed_at = now


def delete_snapshot(db: Session, workspace_id: int) -> None:
    """删除快照（工作区删除时的兜底；正常情况下 FK 级联已处理）."""
    snapshot = db.get(WorkspaceStorageSnapshot, workspace_id)
    if snapshot is not None:
        db.delete(snapshot)


def snapshot_payload(snapshot: WorkspaceStorageSnapshot | None) -> dict[str, Any]:
    """快照 → 接口字段（缺快照时 used_bytes 为 None，前端显示「统计中」）."""
    return {
        "used_bytes": None if snapshot is None else snapshot.used_bytes,
        "computed_at": snapshot_computed_at(snapshot),
        "age_seconds": snapshot_age_seconds(snapshot),
        "duration_ms": None if snapshot is None else snapshot.duration_ms,
    }


__all__ = [
    "RefreshReport",
    "bump_used_bytes",
    "delete_snapshot",
    "has_pending_work",
    "mark_dirty",
    "pop_dirty",
    "read_snapshot",
    "read_snapshots",
    "refresh_all",
    "refresh_workspace",
    "register_wakeup",
    "request_refresh",
    "reset_state",
    "set_used_bytes",
    "snapshot_age_seconds",
    "snapshot_computed_at",
    "snapshot_payload",
    "snapshot_used_bytes",
]
