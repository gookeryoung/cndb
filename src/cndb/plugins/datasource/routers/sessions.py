"""datasource 凭证会话与领域模板包路由.

- ``sessions``：请求头 + 密钥集中管理（密钥只写不回显；**不随工作区导出**）
- ``domain-templates``：按 provider 返回可直接套用的分析模板（公式 / 图表 / 汇总）

权限：读 viewer、写 editor（与同步任务同口径）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.datasource.models import DatasourceSession, DatasourceSyncJob
from cndb.plugins.datasource.schemas import (
    DomainTemplateListResponse,
    SessionCreate,
    SessionListResponse,
    SessionOut,
    SessionUpdate,
)
from cndb.plugins.datasource.services.domain_templates import list_domain_templates
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/datasource", tags=["datasource"])


def _session_or_404(db: Session, workspace_id: int, session_id: int) -> DatasourceSession:
    session = db.get(DatasourceSession, session_id)
    if session is None or session.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="凭证会话不存在")
    return session


@router.get("/sessions", response_model=SessionListResponse)
def list_sessions(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SessionListResponse:
    """列出工作区内的凭证会话（**只回显密钥键名，不返回值**）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    sessions = list(
        db.execute(
            select(DatasourceSession)
            .where(DatasourceSession.workspace_id == workspace_id)
            .order_by(DatasourceSession.id)
        ).scalars()
    )
    return SessionListResponse(
        total=len(sessions),
        sessions=[SessionOut.from_model(item) for item in sessions],
    )


@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(
    workspace_id: int,
    payload: SessionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SessionOut:
    """新建凭证会话（同名不允许，避免运行时取错密钥）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    exists = db.execute(
        select(DatasourceSession.id).where(
            DatasourceSession.workspace_id == workspace_id,
            DatasourceSession.name == payload.name,
        )
    ).first()
    if exists is not None:
        raise HTTPException(status_code=400, detail=f"会话名称已存在: {payload.name}")
    session = DatasourceSession(
        workspace_id=workspace_id,
        created_by=current_user.id,
        name=payload.name,
        headers=dict(payload.headers),
        secrets=dict(payload.secrets),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return SessionOut.from_model(session)


@router.put("/sessions/{session_id}", response_model=SessionOut)
def update_session(
    workspace_id: int,
    session_id: int,
    payload: SessionUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SessionOut:
    """局部更新；``secrets`` 一旦提供即整体替换（传空对象等于清空密钥）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    session = _session_or_404(db, workspace_id, session_id)
    if payload.name is not None:
        session.name = payload.name
    if payload.headers is not None:
        session.headers = dict(payload.headers)
    if payload.secrets is not None:
        session.secrets = dict(payload.secrets)
    db.add(session)
    db.commit()
    db.refresh(session)
    return SessionOut.from_model(session)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    workspace_id: int,
    session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除会话；引用它的同步任务自动解绑（不级联删任务）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    session = _session_or_404(db, workspace_id, session_id)
    db.execute(
        update(DatasourceSyncJob)
        .where(DatasourceSyncJob.session_id == session.id)
        .values(session_id=None)
        .execution_options(synchronize_session=False)
    )
    db.delete(session)
    db.commit()


@router.get("/domain-templates", response_model=DomainTemplateListResponse)
def get_domain_templates(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    provider: Annotated[str | None, Query(description="只看某个 provider 的模板")] = None,
) -> DomainTemplateListResponse:
    """领域模板包：可直接作为分析模板的 ``config`` 提交（字段名按 provider 默认输出）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    return DomainTemplateListResponse(templates=list_domain_templates(provider))


__all__ = ["router"]
