"""工作区生命周期路由（需求 0094）：状态 / 阶段推进 / 应用模板."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import WorkspaceRole, WorkspaceTemplate
from cndb.plugins.workspaces.routers.deps import _get_workspace_or_404, _require_owner
from cndb.plugins.workspaces.routers.workspaces import invalidate_workspace_list_cache
from cndb.plugins.workspaces.schemas.templates import (
    AdvanceStageRequest,
    ApplyTemplateRequest,
    ApplyTemplateResponse,
    LifecycleResponse,
)
from cndb.plugins.workspaces.services.templates.engine import (
    GateError,
    advance_stage,
    apply_spec_to_workspace,
    lifecycle_state,
)
from cndb.plugins.workspaces.services.templates.spec import normalize_spec

router = APIRouter(prefix="/workspaces", tags=["workspace-lifecycle"])


def _template_for_workspace(db: Session, workspace: object) -> WorkspaceTemplate:
    template_id = getattr(workspace, "template_id", None)
    if template_id is None:
        raise HTTPException(status_code=404, detail="该工作区未使用模板")
    template = db.get(WorkspaceTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="工作区引用的模板已不存在")
    return template


@router.get("/{workspace_id}/lifecycle", response_model=LifecycleResponse)
def get_lifecycle(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LifecycleResponse:
    """读取当前生命周期状态（成员可读；逐阶段门禁明细）."""
    workspace = _get_workspace_or_404(workspace_id, db)
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    template = _template_for_workspace(db, workspace)
    return LifecycleResponse(**lifecycle_state(db, workspace, template))


@router.post("/{workspace_id}/lifecycle/advance", response_model=LifecycleResponse)
def post_advance_stage(
    workspace_id: int,
    payload: AdvanceStageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LifecycleResponse:
    """推进阶段（编辑者+）；门禁未通过时 409，需显式 ``force``."""
    workspace = _get_workspace_or_404(workspace_id, db)
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    template = _template_for_workspace(db, workspace)
    try:
        state = advance_stage(
            db,
            workspace,
            template,
            current_user,
            target_stage=payload.target_stage,
            force=payload.force,
            reason=payload.reason,
        )
    except GateError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), **exc.details}) from exc
    invalidate_workspace_list_cache(workspace_id)
    return LifecycleResponse(**state)


@router.post("/{workspace_id}/lifecycle/apply", response_model=ApplyTemplateResponse)
def apply_template(
    workspace_id: int,
    payload: ApplyTemplateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ApplyTemplateResponse:
    """把模板应用到已有工作区（仅所有者；增量同步，不删除任何存量数据）.

    从另一个模板切换过来时要求 ``force=true``（旧模板的阶段履历会保留在 history）。
    """
    workspace = _get_workspace_or_404(workspace_id, db)
    _require_owner(workspace, current_user, db)
    template = db.get(WorkspaceTemplate, payload.template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    if workspace.template_id and workspace.template_id != template.id and not payload.force:
        raise HTTPException(
            status_code=409,
            detail="该工作区已使用其他模板，切换模板会改变流程口径，请传 force=true 确认",
        )
    spec = normalize_spec(template.spec)
    sync = apply_spec_to_workspace(db, workspace, spec, current_user, template=template, version=template.version)
    db.refresh(workspace)
    invalidate_workspace_list_cache(workspace_id)
    return ApplyTemplateResponse(
        workspace_id=workspace.id,
        template_id=template.id,
        template_version=workspace.template_version or template.version,
        template_stage=workspace.template_stage,
        sync=sync,
    )


__all__ = ["router"]
