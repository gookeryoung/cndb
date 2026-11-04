"""工作区模板路由（需求 0094）：CRUD / 版本 / diff 与影响预览.

权限口径：
- 读：任意登录用户（模板是公共资产）；
- 写：模板创建者或系统管理员（内置模板仅系统管理员可改）；
- 删除：有工作区在用时拒绝（避免工作区丢失生命周期定义）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User, UserRole
from cndb.plugins.workspaces.models import Workspace, WorkspaceTemplate, WorkspaceTemplateRevision
from cndb.plugins.workspaces.schemas.templates import (
    TemplateCreate,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    TemplateResponse,
    TemplateRevisionResponse,
    TemplateUpdate,
    TemplateUpdateResponse,
)
from cndb.plugins.workspaces.services.templates.diff import diff_specs
from cndb.plugins.workspaces.services.templates.engine import (
    apply_spec_to_workspace,
    preview_impact,
)
from cndb.plugins.workspaces.services.templates.spec import (
    TemplateSpecError,
    normalize_spec,
    spec_counts,
)

router = APIRouter(prefix="/workspace-templates", tags=["workspace-templates"])


def _is_admin(user: User) -> bool:
    return bool(user.is_superuser or user.role == UserRole.SYSTEM_ADMIN.value)


def _can_manage(template: WorkspaceTemplate, user: User) -> bool:
    if template.is_builtin:
        return _is_admin(user)
    return _is_admin(user) or template.created_by_id == user.id


def _require_manage(template: WorkspaceTemplate, user: User) -> None:
    if not _can_manage(template, user):
        raise HTTPException(status_code=403, detail="仅模板创建者或系统管理员可修改该模板")


def _get_template_or_404(db: Session, template_id: int) -> WorkspaceTemplate:
    template = db.get(WorkspaceTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    return template


def _workspace_counts(db: Session, template_ids: list[int]) -> dict[int, int]:
    if not template_ids:
        return {}
    rows = (
        db.query(Workspace.template_id, func.count(Workspace.id))
        .filter(Workspace.template_id.in_(template_ids))
        .group_by(Workspace.template_id)
        .all()
    )
    return {int(tid): int(count) for tid, count in rows if tid is not None}


def _to_response(template: WorkspaceTemplate, workspace_count: int = 0) -> TemplateResponse:
    return TemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        category=template.category,
        modules=list(template.modules or []),
        spec=template.spec or {},
        version=template.version,
        is_builtin=template.is_builtin,
        created_by_id=template.created_by_id,
        updated_at=template.updated_at,
        counts=spec_counts(template.spec or {}),
        workspace_count=workspace_count,
    )


def _validate_spec(raw: Any) -> dict[str, Any]:
    try:
        return normalize_spec(raw)
    except TemplateSpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _name_conflict(db: Session, name: str, *, exclude_id: int | None = None) -> bool:
    query = db.query(WorkspaceTemplate).filter(WorkspaceTemplate.name == name)
    if exclude_id is not None:
        query = query.filter(WorkspaceTemplate.id != exclude_id)
    return query.first() is not None


@router.get("", response_model=list[TemplateResponse])
def list_templates(
    _current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: str | None = Query(default=None, max_length=120),
) -> list[TemplateResponse]:
    """列出全部模板（按内置优先、更新时间倒序），附带使用中工作区数."""
    query = db.query(WorkspaceTemplate)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(WorkspaceTemplate.name.like(like) | WorkspaceTemplate.category.like(like))
    templates = query.order_by(WorkspaceTemplate.is_builtin.desc(), WorkspaceTemplate.updated_at.desc()).all()
    counts = _workspace_counts(db, [t.id for t in templates])
    return [_to_response(t, counts.get(t.id, 0)) for t in templates]


@router.get("/{template_id}", response_model=TemplateResponse)
def get_template(
    template_id: int,
    _current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TemplateResponse:
    template = _get_template_or_404(db, template_id)
    return _to_response(template, _workspace_counts(db, [template.id]).get(template.id, 0))


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: TemplateCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TemplateResponse:
    """创建模板并落 v1 版本快照."""
    if _name_conflict(db, payload.name.strip()):
        raise HTTPException(status_code=409, detail=f"模板名称已存在：{payload.name}")
    spec = _validate_spec(payload.spec)
    template = WorkspaceTemplate(
        name=payload.name.strip(),
        description=payload.description,
        category=payload.category.strip(),
        modules=payload.modules,
        spec=spec,
        version=1,
        is_builtin=False,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
    )
    db.add(template)
    db.flush()
    db.add(
        WorkspaceTemplateRevision(
            template_id=template.id,
            version=1,
            spec=spec,
            change_summary=payload.change_summary or "初始版本",
            created_by_id=current_user.id,
        )
    )
    db.commit()
    db.refresh(template)
    return _to_response(template)


@router.post("/{template_id}/preview", response_model=TemplatePreviewResponse)
def preview_template_update(
    template_id: int,
    payload: TemplatePreviewRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TemplatePreviewResponse:
    """对拟保存的 spec 计算 diff 与已有数据影响（不落库）."""
    template = _get_template_or_404(db, template_id)
    _require_manage(template, current_user)
    spec = _validate_spec(payload.spec)
    diff = diff_specs(template.spec or {}, spec)
    impact = preview_impact(db, template, spec)
    return TemplatePreviewResponse(
        diff=diff,
        impact=impact,
        requires_force=bool(diff["requires_force"] or impact["requires_force"]),
        spec=spec,
    )


@router.put("/{template_id}", response_model=TemplateUpdateResponse)
def update_template(
    template_id: int,
    payload: TemplateUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TemplateUpdateResponse:
    """更新模板；spec 变化时先预览，破坏性变更需 ``force=true``.

    保存后对所有使用该模板的工作区做一次**增量同步**（缺表建表、缺字段加列、
    缺文档建占位），绝不删除已有表 / 字段 / 文档。
    """
    template = _get_template_or_404(db, template_id)
    _require_manage(template, current_user)

    new_name = payload.name.strip() if payload.name is not None else template.name
    if new_name != template.name and _name_conflict(db, new_name, exclude_id=template.id):
        raise HTTPException(status_code=409, detail=f"模板名称已存在：{new_name}")
    new_spec = _validate_spec(payload.spec) if payload.spec is not None else (template.spec or {})
    diff = diff_specs(template.spec or {}, new_spec)
    impact = preview_impact(db, template, new_spec)
    requires_force = bool(diff["requires_force"] or impact["requires_force"])
    if requires_force and not payload.force:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "模板变更包含破坏性影响，请确认后再保存",
                "diff": diff,
                "impact": impact,
                "requires_force": True,
            },
        )

    template.name = new_name
    if payload.description is not None:
        template.description = payload.description
    if payload.category is not None:
        template.category = payload.category.strip()
    if payload.modules is not None:
        template.modules = payload.modules
    spec_changed = new_spec != (template.spec or {})
    sync_totals = {"created_tables": 0, "added_fields": 0, "created_documents": 0}
    if spec_changed:
        template.spec = new_spec
        template.version += 1
    template.updated_by_id = current_user.id
    db.add(template)
    db.flush()
    if spec_changed:
        db.add(
            WorkspaceTemplateRevision(
                template_id=template.id,
                version=template.version,
                spec=new_spec,
                change_summary=payload.change_summary or f"更新到 v{template.version}",
                created_by_id=current_user.id,
            )
        )
    db.commit()
    db.refresh(template)

    # 增量同步所有使用中的工作区（含本次版本）；模板定义的变更不影响存量数据
    workspaces = db.query(Workspace).filter(Workspace.template_id == template.id).all()
    for ws in workspaces:
        result = apply_spec_to_workspace(db, ws, new_spec, current_user, template=template, version=template.version)
        for key in sync_totals:
            sync_totals[key] += int(result.get(key, 0))
    db.refresh(template)
    return TemplateUpdateResponse(
        template=_to_response(template, len(workspaces)),
        diff=diff,
        impact=impact,
        requires_force=requires_force,
        applied=True,
        sync=sync_totals,
    )


@router.get("/{template_id}/revisions", response_model=list[TemplateRevisionResponse])
def list_revisions(
    template_id: int,
    _current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkspaceTemplateRevision]:
    """模板历史版本（供 diff 追溯）."""
    _get_template_or_404(db, template_id)
    return (
        db.query(WorkspaceTemplateRevision)
        .filter(WorkspaceTemplateRevision.template_id == template_id)
        .order_by(WorkspaceTemplateRevision.version.desc())
        .all()
    )


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除模板；仍有工作区在用时拒绝（避免丢失生命周期定义）."""
    template = _get_template_or_404(db, template_id)
    _require_manage(template, current_user)
    in_use = _workspace_counts(db, [template.id]).get(template.id, 0)
    if in_use:
        raise HTTPException(status_code=409, detail=f"仍有 {in_use} 个工作区使用该模板，无法删除")
    db.delete(template)
    db.commit()


__all__ = ["router"]
