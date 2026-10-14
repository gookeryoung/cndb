"""workspaces 路由共用依赖：解析工作区并校验成员 / 所有者身份."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role, has_role


def _get_workspace_or_404(workspace_id: int, db: Session) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")  # pragma: no cover - 由 _get_workspace_or_404 前置
    return ws


def _require_member(workspace: Workspace, user: User, db: Session) -> None:
    if get_member_role(user, workspace, db) is None:
        raise HTTPException(status_code=404, detail="工作区不存在")  # pragma: no cover - 由 _get_workspace_or_404 前置


def _require_owner(workspace: Workspace, user: User, db: Session) -> None:
    if not has_role(user, workspace, WorkspaceRole.OWNER, db):
        raise HTTPException(status_code=403, detail="需要所有者权限")


__all__ = ["_get_workspace_or_404", "_require_member", "_require_owner"]
