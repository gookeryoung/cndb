"""审计日志写入 — 独立模块，records.py 末尾调用.

设计：AuditLog 写入独立 Session 提交（不与行数据事务绑定），
行操作成功后由 records.py 追加调用，失败不回滚主操作.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.tables.models import AuditLog, DataTable

ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_TRASH = "trash"
ACTION_RESTORE = "restore"
ACTION_DELETE = "delete"


def log_action(  # noqa: PLR0913
    db: Session,
    table: DataTable,
    action: str,
    *,
    target_id: int | None = None,
    actor_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """向 AuditLog 追加一条记录（尽力而为，失败吞掉）."""
    try:
        entry = AuditLog(
            table_id=table.id,
            action=action,
            actor_id=actor_id,
            target_id=target_id,
            detail=detail or {},
        )
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()


def query_row_history(
    db: Session,
    table_id: int,
    target_id: int,
    limit: int = 50,
) -> list[AuditLog]:
    """查询某行的操作历史."""
    return (
        db.query(AuditLog)
        .filter(AuditLog.table_id == table_id, AuditLog.target_id == target_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )


def query_table_history(
    db: Session,
    table_id: int,
    limit: int = 100,
) -> list[AuditLog]:
    """查询整张表的操作历史."""
    return (
        db.query(AuditLog)
        .filter(AuditLog.table_id == table_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )


__all__ = [
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_RESTORE",
    "ACTION_TRASH",
    "ACTION_UPDATE",
    "log_action",
    "query_row_history",
    "query_table_history",
]

