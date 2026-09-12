"""行评论路由."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables import records as rec
from cndb.plugins.tables.models import RowComment
from cndb.plugins.tables.routers.tables import _check_table_permission, _get_table_or_404
from cndb.plugins.tables.schemas.comments import CommentCreate, CommentResponse, CommentUpdate
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(tags=["comments"])


@router.get(
    "/{workspace_id}/tables/{table_id}/records/{record_id}/comments",
    response_model=list[CommentResponse],
)
def list_comments(
    workspace_id: int,
    table_id: int,
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=500),
) -> list[RowComment]:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    _get_table_or_404(table_id, workspace_id, db)
    return (
        db.query(RowComment)
        .filter(RowComment.table_id == table_id, RowComment.row_id == record_id)
        .order_by(RowComment.id.asc())
        .limit(limit)
        .all()
    )


@router.post(
    "/{workspace_id}/tables/{table_id}/records/{record_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    workspace_id: int,
    table_id: int,
    record_id: int,
    payload: CommentCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RowComment:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    dt = _get_table_or_404(table_id, workspace_id, db)
    row = rec.get_row(db.get_bind(), dt, record_id, db=db)
    if row is None:
        raise HTTPException(status_code=404, detail="行不存在")
    if payload.parent_id is not None:
        parent = db.query(RowComment).filter(RowComment.id == payload.parent_id).first()
        if parent is None:
            raise HTTPException(status_code=400, detail="父评论不存在")
    comment = RowComment(
        table_id=table_id,
        row_id=record_id,
        user_id=current_user.id,
        content=payload.content,
        parent_id=payload.parent_id,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.patch(
    "/{workspace_id}/tables/{table_id}/comments/{comment_id}",
    response_model=CommentResponse,
)
def update_comment(
    workspace_id: int,
    table_id: int,
    comment_id: int,
    payload: CommentUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RowComment:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    _get_table_or_404(table_id, workspace_id, db)
    c = db.query(RowComment).filter(RowComment.id == comment_id, RowComment.table_id == table_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="评论不存在")
    if c.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="仅作者可修改")
    c.content = payload.content
    db.commit()
    db.refresh(c)
    return c


@router.delete(
    "/{workspace_id}/tables/{table_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_comment(
    workspace_id: int,
    table_id: int,
    comment_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    c = db.query(RowComment).filter(RowComment.id == comment_id, RowComment.table_id == table_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="评论不存在")
    db.delete(c)
    db.commit()


__all__ = ["router"]
