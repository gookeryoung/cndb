"""行级历史与撤销（ADR 0144）.

口径：
- 一次用户写操作（create / update / trash / restore / revert）= 一条版本记录，``version``
  从 1 起严格递增（``(row_id, version)`` 唯一）；
- ``diff`` 只存**变化字段**：``{字段名: {"old": ..., "new": ...}}``；隐藏字段不在 diff 里
  （写入口只拿到调用方可写字段，隐藏字段由服务端保留原值，不产生"变化"）；
- 撤销 = 按目标版本的 ``old`` 值生成**新的一版**（不删除 / 不回退历史），因此可反复撤销；
- 导入 / 数据同步等批量链路默认 ``history=False``，避免写放大；
- 历史随表删除级联清理；行被物理删除（purge）后历史保留（``row_id`` 无外键），供审计追溯。
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.plugins.tables.models import DataTable, RecordRevision

logger = logging.getLogger(__name__)

#: 支持的写操作（与审计 action 口径对齐，额外区分 revert）
OP_CREATE = "create"
OP_UPDATE = "update"
OP_TRASH = "trash"
OP_RESTORE = "restore"
OP_REVERT = "revert"

#: 单次 diff 允许的最大字段数（超大整行改写不记历史，避免表爆炸）
MAX_DIFF_FIELDS = 200


def build_diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    """构造 ``{字段名: {old, new}}`` 的变化集（只保留真正变化的业务字段）.

    ``_`` 开头的是系统 / 派生键（`_etag` / `_trashed_at` / `_rev` 等）：它们的"变化"
    是并发控制与可见性的副产物，不属于用户改动，必须排除（否则每次编辑都会多出噪声字段）。
    """
    before = before or {}
    after = after or {}
    diff: dict[str, Any] = {}
    for key in list(after.keys()) + [k for k in before if k not in after]:
        if key.startswith("_"):
            continue
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        diff[key] = {"old": old, "new": new}
        if len(diff) >= MAX_DIFF_FIELDS:
            logger.warning("行历史 diff 超过 %d 个字段，截断记录", MAX_DIFF_FIELDS)
            break
    return diff


def _next_version(db: Session, row_id: int) -> int:
    with db.bind.connect() as conn:  # type: ignore[union-attr]
        current = conn.execute(select(func.max(RecordRevision.version)).where(RecordRevision.row_id == row_id)).scalar()
    return int(current or 0) + 1


def record_revision(
    db: Session | None,
    table: DataTable | None,
    row_id: int,
    op: str,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    user: Any = None,
) -> RecordRevision | None:
    """追加一条版本记录（尽力而为：失败只记日志，不影响主写路径）."""
    if db is None or table is None:
        return None
    try:
        diff = build_diff(before, after)
        if op == OP_UPDATE and not diff:
            return None  # 无变化不记版本（避免噪声版本）
        entry = RecordRevision(
            table_id=int(table.id),
            row_id=int(row_id),
            version=_next_version(db, int(row_id)),
            op=op,
            actor_id=getattr(user, "id", None),
            actor_name=getattr(user, "nickname", None) or getattr(user, "username", None),
            diff=diff,
        )
        db.add(entry)
        db.commit()
        return entry
    except Exception as exc:  # pragma: no cover - 历史失败不得影响写入
        logger.warning("写入行历史失败（忽略）: %s", exc)
        with contextlib.suppress(Exception):
            db.rollback()
        return None


def list_revisions(db: Session, table: DataTable, row_id: int, *, limit: int = 50) -> list[RecordRevision]:
    """按版本倒序列出该行历史（最新在前）."""
    return (
        db.query(RecordRevision)
        .filter(RecordRevision.table_id == int(table.id), RecordRevision.row_id == int(row_id))
        .order_by(RecordRevision.version.desc())
        .limit(max(int(limit), 1))
        .all()
    )


def revert_values(revision: RecordRevision) -> dict[str, Any]:
    """把一条版本记录折算成"撤销它"要写回的值（取该条的 old）."""
    values: dict[str, Any] = {}
    for field_name, change in (revision.diff or {}).items():
        if not isinstance(change, dict):
            continue
        values[field_name] = change.get("old")
    return values


def revert_revision(
    db: Session,
    table: DataTable,
    row_id: int,
    version: int,
    *,
    user: Any = None,
    enforce_row_rules: bool | None = None,
) -> dict[str, Any] | None:
    """把行恢复到指定版本之前的值（生成新版本，不改历史）.

    Returns:
        更新后的行；目标版本不存在 / 行不可写时返回 None（由路由转 404）。
    """
    from cndb.plugins.tables.services.core import records as rec

    revision = (
        db.query(RecordRevision)
        .filter(
            RecordRevision.table_id == int(table.id),
            RecordRevision.row_id == int(row_id),
            RecordRevision.version == int(version),
        )
        .first()
    )
    if revision is None:
        return None
    values = revert_values(revision)
    if not values:
        return rec.get_row(db.get_bind(), table, row_id, db=db, user=user)

    # 无用户上下文（内部 / 运维调用）时不做写范围过滤；有用户时沿用写范围口径
    rules = bool(user) if enforce_row_rules is None else enforce_row_rules
    row = rec.update_row(
        db.get_bind(),
        table,
        row_id,
        values,
        db=db,
        user=user,
        enforce_row_rules=rules,
        history_op=OP_REVERT,
    )
    return row


__all__ = [
    "MAX_DIFF_FIELDS",
    "OP_CREATE",
    "OP_RESTORE",
    "OP_REVERT",
    "OP_TRASH",
    "OP_UPDATE",
    "build_diff",
    "list_revisions",
    "record_revision",
    "revert_revision",
    "revert_values",
]
