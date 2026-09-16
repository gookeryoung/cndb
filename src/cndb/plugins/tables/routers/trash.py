"""回收站路由 —— 工作区级 + 表级，支持表/字段/行三段恢复.

对齐旧项目 trash_views.py：
- 工作区级 GET /trash 返回所有已软删的表、已软删的字段列表 + 行数概览
- POST /trash/tables/{id}/restore 恢复软删的 DataTable
- POST /trash/fields/{id}/restore 恢复软删的 DataField
- GET /trash/tables/{id}/rows 列出某表的软删行
- POST /trash/tables/{id}/rows/restore 批量恢复软删行
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import MetaData, func, select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.access import TableAction
from cndb.plugins.tables.audit import ACTION_RESTORE, log_action
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.records import restore_row
from cndb.plugins.tables.routers.tables import _check_table_permission, _get_table_or_404
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(tags=["trash"])


# ── 工作区级回收站概览 ─────────────────────────────


@router.get("/{workspace_id}/trash")
def list_workspace_trash(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """工作区级回收站概览：软删表列表 + 软删字段列表 + 各表软删行计数.

    仅工作区管理员可见（避免普通成员看到已删除的敏感元数据）.
    """
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)

    # 1. 软删表
    trashed_tables = (
        db.query(DataTable)
        .filter(DataTable.workspace_id == workspace_id, DataTable.trashed == True)  # noqa: E712
        .order_by(DataTable.trashed_at.desc().nullslast(), DataTable.id.desc())
        .all()
    )

    # 2. 软删字段（属于当前工作区但被软删）
    trashed_fields = (
        db.query(DataField)
        .join(DataTable, DataField.table_id == DataTable.id)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataField.trashed == True,  # noqa: E712
            DataTable.trashed == False,  # noqa: E712 — 表本身被删就不列出其字段
        )
        .order_by(DataField.trashed_at.desc().nullslast(), DataField.id.desc())
        .all()
    )

    # 3. 各表软删行数概览（对每个未软删的表扫一行计数）
    active_tables = (
        db.query(DataTable)
        .filter(DataTable.workspace_id == workspace_id, DataTable.trashed == False)  # noqa: E712
        .all()
    )
    row_counts: list[dict[str, Any]] = []
    engine: Any = db.get_bind()
    for dt in active_tables:
        try:
            metadata = MetaData()
            metadata.reflect(bind=engine, only=[dt.db_table_name])
            sa_table = metadata.tables.get(dt.db_table_name)
            if sa_table is None:
                continue
            with engine.connect() as _conn:
                count = (
                    _conn.execute(
                        select(func.count()).select_from(sa_table).where(sa_table.c._trashed.is_(True))
                    ).scalar()
                    or 0
                )
            if count > 0:
                row_counts.append({"table_id": dt.id, "table_name": dt.name, "trashed_rows": count})
        except Exception:
            continue

    return {
        "tables": [
            {
                "id": t.id,
                "name": t.name,
                "trashed_at": t.trashed_at.isoformat() if t.trashed_at else None,
            }
            for t in trashed_tables
        ],
        "fields": [
            {
                "id": f.id,
                "name": f.name,
                "table_id": f.table_id,
                "table_name": f.table.name if f.table else None,
                "field_type": f.field_type,
                "trashed_at": f.trashed_at.isoformat() if f.trashed_at else None,
            }
            for f in trashed_fields
        ],
        "row_counts": row_counts,
    }


# ── 表恢复 ─────────────────────────────────────────


@router.post("/{workspace_id}/trash/tables/{table_id}/restore")
def restore_trashed_table(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """恢复软删的表（仅工作区管理员）."""
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    dt = db.query(DataTable).filter(DataTable.id == table_id, DataTable.workspace_id == workspace_id).first()
    if dt is None or not dt.trashed:
        raise HTTPException(status_code=404, detail="表不在回收站中")

    dt.trashed = False
    dt.trashed_at = None
    # 同步恢复其下所有被软删的字段
    for f in dt.fields:
        if f.trashed:
            f.trashed = False
            f.trashed_at = None
    db.commit()
    db.refresh(dt)
    return {"restored_table_id": dt.id, "restored_table_name": dt.name}


# ── 字段恢复 ───────────────────────────────────────


@router.post("/{workspace_id}/trash/fields/{field_id}/restore")
def restore_trashed_field(
    workspace_id: int,
    field_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """恢复软删的字段（仅工作区管理员）."""
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    f = db.get(DataField, field_id)
    if f is None:
        raise HTTPException(status_code=404, detail="字段不存在")
    dt = f.table
    if dt is None or dt.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="字段不属于此工作区")
    if not f.trashed:
        raise HTTPException(status_code=400, detail="字段不在回收站中")

    f.trashed = False
    f.trashed_at = None
    db.commit()
    return {"restored_field_id": f.id, "restored_field_name": f.name, "table_id": dt.id}


# ── 表级软删行列表 ──────────────────────────────────


@router.get("/{workspace_id}/tables/{table_id}/trash-rows")
def list_trashed_rows(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """列出某表的软删行（普通成员也可见 —— 让用户能恢复自己误删的行）."""
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    from sqlalchemy import and_, func

    from cndb.plugins.tables.access import apply_field_hiding_rows, get_hidden_field_names
    from cndb.plugins.tables.records import _build_row_scope_where

    engine: Any = db.get_bind()
    try:
        metadata = MetaData()
        metadata.reflect(bind=engine, only=[dt.db_table_name])
        sa_table = metadata.tables.get(dt.db_table_name)
        if sa_table is None:
            return {"rows": [], "total": 0}

        # 构建 WHERE: _trashed=True AND row_scope（避免绕过行级权限）
        row_scope = _build_row_scope_where(dt, sa_table, db)
        where_clauses: list[Any] = [sa_table.c._trashed.is_(True)]
        if row_scope is not None:
            where_clauses.append(row_scope)
        final_where = and_(*where_clauses)

        with engine.connect() as conn:
            count = conn.execute(select(func.count()).select_from(sa_table).where(final_where)).scalar() or 0
            raw_rows = conn.execute(
                sa_table.select()
                .where(final_where)
                .order_by(sa_table.c._trashed_at.desc().nullslast(), sa_table.c.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()

        from cndb.plugins.tables.records import _row_to_dict, attach_links

        rows = [_row_to_dict(dt, sa_table, r) for r in raw_rows]
        rows = attach_links(engine, dt, rows, db=db)

        # 字段隐藏（避免泄漏 hidden_fields 配置的列）
        hidden = get_hidden_field_names(db, dt, current_user)
        apply_field_hiding_rows(rows, hidden)

        return {"rows": rows, "total": count}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"读取回收站失败: {exc}") from exc


# ── 批量恢复 / 清理软删行 ──────────────────────────


@router.post("/{workspace_id}/tables/{table_id}/trash-rows/restore")
def restore_trashed_rows_batch(
    workspace_id: int,
    table_id: int,
    payload: dict[str, Any],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    """批量恢复软删行。payload: {row_ids: [int, ...]}；row_ids 为空时恢复全部（受行级权限约束）."""

    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)

    row_ids: list[int] = payload.get("row_ids", [])
    engine: Any = db.get_bind()
    restored = 0

    if row_ids:
        for rid in row_ids:
            if restore_row(engine, dt, rid, db=db):
                restored += 1
    else:
        # 恢复全部软删行（同样受 row_filters 约束，避免权限绕过）
        try:
            metadata = MetaData()
            metadata.reflect(bind=engine, only=[dt.db_table_name])
            sa_table = metadata.tables.get(dt.db_table_name)
            if sa_table is not None:
                from cndb.plugins.tables.records import _build_row_scope_where

                row_scope = _build_row_scope_where(dt, sa_table, db)
                base_where: list[Any] = [sa_table.c._trashed.is_(True)]
                if row_scope is not None:
                    base_where.append(row_scope)
                with engine.begin() as conn:
                    result = conn.execute(
                        sa_table.update()
                        .where(*base_where)
                        .values(
                            _trashed=False,
                            _trashed_at=None,
                        )
                    )
                    restored = result.rowcount
                    # 逐条写 audit
                    for _ in range(restored):
                        with suppress(Exception):
                            log_action(db, dt, ACTION_RESTORE)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"恢复失败: {exc}") from exc

    return {"restored": restored}


@router.delete(
    "/{workspace_id}/tables/{table_id}/trash-rows",
    status_code=status.HTTP_200_OK,
)
def purge_trashed_rows(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(default=30, ge=0, description="清理多少天前的软删行"),
) -> dict[str, int]:
    """硬删除超过 N 天的软删行（最终清理，不可恢复）.

    仅工作区 ADMIN 可用.
    """
    dt = _get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)

    cutoff = datetime.now(UTC)
    engine: Any = db.get_bind()
    try:
        metadata = MetaData()
        metadata.reflect(bind=engine, only=[dt.db_table_name])
        sa_table = metadata.tables.get(dt.db_table_name)
        if sa_table is None:
            return {"purged": 0}

        with engine.begin() as conn:
            from datetime import timedelta

            cutoff_dt = cutoff - timedelta(days=days)
            result = conn.execute(
                sa_table.delete().where(
                    sa_table.c._trashed.is_(True),
                    (sa_table.c._trashed_at < cutoff_dt) | sa_table.c._trashed_at.is_(None),
                )
            )
            purged = result.rowcount
        return {"purged": purged, "older_than_days": days}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"清理失败: {exc}") from exc


__all__ = ["router"]
