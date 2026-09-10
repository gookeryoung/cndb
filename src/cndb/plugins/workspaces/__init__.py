"""workspaces 插件."""

from __future__ import annotations

from cndb.plugins.workspaces.models import (
    ROLE_RANK,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)

__all__ = ["ROLE_RANK", "Workspace", "WorkspaceMember", "WorkspaceRole"]
