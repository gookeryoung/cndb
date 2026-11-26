"""documents 插件路由：工作区附件管理（需求 0174）.

端点挂 ``/{workspace_id}/documents/attachments``，必须在 documents_router 之前注册，
否则 ``/attachments`` 会被 ``/{doc_id}`` 当成文档 id 解析。

- GET  ""       列表（editor+）
- POST /scan    体检（editor+，只读）
- POST /purge   回收孤儿（owner，默认 dry-run）
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.services import attachments as attachments_service
from cndb.plugins.documents.services.content import require_editor
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import raise_permission_denied, workspace_data_role

router = APIRouter(prefix="/{workspace_id}/documents/attachments", tags=["documents"])


class PurgeRequest(BaseModel):
    """回收孤儿附件：默认 dry-run，需显式 false 才实际删除."""

    dry_run: bool = True


def _require_owner(db: Session, workspace_id: int, user: User) -> None:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise NotFoundError("工作区不存在")
    if workspace_data_role(user, workspace, db) != WorkspaceRole.OWNER:
        raise_permission_denied(db, workspace, user, requirement="仅工作区所有者可回收附件")


@router.get("")
def list_attachments(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """工作区附件列表（editor+）：文件名 / 大小 / 归属文档 / 上传时间."""
    require_editor(db, workspace_id, current_user)
    return attachments_service.list_workspace_attachments(db, workspace_id, q=q, limit=limit, offset=offset)


@router.post("/scan")
def scan_attachments(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """附件体检（editor+，只读）：引用次数与孤儿清单."""
    require_editor(db, workspace_id, current_user)
    return attachments_service.scan_workspace_attachments(db, workspace_id)


@router.post("/purge")
def purge_attachments(
    workspace_id: int,
    payload: PurgeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """回收孤儿附件（owner）：默认 dry-run，`dry_run=false` 才删除."""
    _require_owner(db, workspace_id, current_user)
    return attachments_service.purge_orphan_attachments(db, workspace_id, dry_run=payload.dry_run)
