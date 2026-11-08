"""工作区项目上下文路由（ADR 0122）：项目清单 / 启用项目级管理 / 项目文档."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import WorkspaceRole
from cndb.plugins.workspaces.routers.deps import _get_workspace_or_404, _require_owner
from cndb.plugins.workspaces.routers.lifecycle import _template_for_workspace
from cndb.plugins.workspaces.schemas.projects import (
    ProjectDocumentsResponse,
    ProjectListResponse,
    ProjectModeEnableRequest,
    ProjectModeEnableResponse,
)
from cndb.plugins.workspaces.services.templates import project_context
from cndb.plugins.workspaces.services.templates.engine import (
    ProjectModeError,
    enable_project_mode,
    ensure_project_documents,
    project_list,
)

router = APIRouter(prefix="/workspaces", tags=["workspace-projects"])


@router.get("/{workspace_id}/projects", response_model=ProjectListResponse)
def get_projects(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectListResponse:
    """项目清单：根表单行 + 阶段 + 门禁摘要（成员可读）."""
    workspace = _get_workspace_or_404(workspace_id, db)
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    template = _template_for_workspace(db, workspace)
    data = project_list(db, workspace, template, limit=limit, offset=offset)
    return ProjectListResponse(**data)


@router.post("/{workspace_id}/project-mode/enable", response_model=ProjectModeEnableResponse)
def post_enable_project_mode(
    workspace_id: int,
    payload: ProjectModeEnableRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectModeEnableResponse:
    """显式启用项目级管理（仅所有者；幂等）."""
    workspace = _get_workspace_or_404(workspace_id, db)
    _require_owner(workspace, current_user, db)
    template = _template_for_workspace(db, workspace)
    try:
        data = enable_project_mode(
            db,
            workspace,
            template,
            current_user,
            generate_documents=payload.generate_documents,
        )
    except ProjectModeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ProjectModeEnableResponse(**data)


@router.post("/{workspace_id}/projects/{project_row_id}/documents", response_model=ProjectDocumentsResponse)
def post_project_documents(
    workspace_id: int,
    project_row_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectDocumentsResponse:
    """按规则补建单个项目的缺失文档（编辑者+；不覆盖正文）."""
    workspace = _get_workspace_or_404(workspace_id, db)
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    template = _template_for_workspace(db, workspace)
    try:
        data = ensure_project_documents(db, workspace, template, current_user, project_row_id)
    except project_context.ProjectContextError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProjectModeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ProjectDocumentsResponse(**data)


__all__ = ["router"]
