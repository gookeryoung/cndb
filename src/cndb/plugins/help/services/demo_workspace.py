"""示例工作区创建（需求 0106）.

帮助页「典型示例」提供一键创建：读取随包发布的示例归档，复用工作区归档
导入入口（ADR 0075）在当前登录用户名下新建工作区。非破坏：不读取、不修改
任何既有工作区。
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.help.services.assets import resolve_demo_pack
from cndb.plugins.help.services.examples import find_example
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole
from cndb.plugins.workspaces.services.workspace_import import (
    ArchiveWorkspaceImportResult,
    create_workspace_from_archive_file,
)


def _unique_workspace_name(db: Session, user_id: int, base: str) -> str:
    """在用户名下生成不重名的示例工作区名称：base / base（2）/ base（3）…"""
    names = set(
        db.execute(
            select(Workspace.name)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.role == WorkspaceRole.OWNER,
            )
        ).scalars()
    )
    if base not in names:
        return base
    index = 2
    while f"{base}（{index}）" in names:
        index += 1
    return f"{base}（{index}）"


def create_demo_workspace(
    scenario: str,
    current_user: User,
    db: Session,
) -> ArchiveWorkspaceImportResult:
    """按场景创建示例工作区；资产缺失或场景未知统一 404."""
    example = find_example(scenario)
    pack = resolve_demo_pack(scenario)
    if example is None or pack is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="示例工作区暂不可用")

    base_name = f"{example['name']}（示例）"
    name = _unique_workspace_name(db, current_user.id, base_name)
    result = create_workspace_from_archive_file(pack, current_user, db, name=name)

    from cndb.plugins.workspaces.routers.workspaces import invalidate_workspace_list_cache

    invalidate_workspace_list_cache(result.workspace.id)
    return result


__all__ = ["create_demo_workspace"]
