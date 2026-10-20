"""datasource 数据源适配器路由：列出可用 provider 与参数表单描述."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.datasource.providers.registry import list_providers
from cndb.plugins.datasource.schemas import ProviderInfo, ProviderListResponse
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/datasource", tags=["datasource"])


@router.get("/providers", response_model=ProviderListResponse)
def get_providers(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProviderListResponse:
    """可用数据源适配器 + ``params_schema``（工作区成员即可读）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    return ProviderListResponse(providers=[ProviderInfo(**item) for item in list_providers()])


__all__ = ["router"]
