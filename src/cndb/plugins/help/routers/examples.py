"""help 示例路由（ADR 0029 §3 / 需求 0106）.

- `GET /api/v1/help/examples`：登录即可返回静态清单；
- `GET /api/v1/help/examples/{scenario}/files/{filename}`：只下载清单登记的 CSV，
  其余（未知场景 / 未登记文件 / 非 .csv / 路径穿越 / 文件缺失）统一 404；
- `POST /api/v1/help/examples/{scenario}/workspace`：在当前用户名下创建示例工作区
  （读取随包归档，复用工作区归档导入；不依赖 seed、不修改既有工作区）。

端点均依赖 `get_current_user`（未登录 401）。
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.help.schemas import HelpExampleListResponse, HelpExampleWorkspaceResponse
from cndb.plugins.help.services.assets import resolve_example_file
from cndb.plugins.help.services.demo_workspace import create_demo_workspace
from cndb.plugins.help.services.examples import HELP_EXAMPLE_MANIFEST

router = APIRouter(prefix="/examples", tags=["help"])


@router.get("", response_model=HelpExampleListResponse, summary="典型示例清单")
def list_examples(
    _current_user: Annotated[object, Depends(get_current_user)],
) -> dict[str, object]:
    """返回典型示例清单（登录即可，不查数据库）."""
    return {"items": HELP_EXAMPLE_MANIFEST}


@router.get("/{scenario}/files/{filename}", response_class=Response, summary="下载示例 CSV")
def download_example_file(
    scenario: str,
    filename: str,
    _current_user: Annotated[object, Depends(get_current_user)],
) -> Response:
    """下载清单登记的示例 CSV；非法参数或文件缺失一律 404."""
    path = resolve_example_file(scenario, filename)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="示例文件暂不可用")

    body = path.read_bytes()
    ascii_fallback = "".join(ch if ord(ch) < 128 else "_" for ch in filename)
    disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )


@router.post(
    "/{scenario}/workspace",
    response_model=HelpExampleWorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建示例工作区",
)
def create_example_workspace(
    scenario: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> HelpExampleWorkspaceResponse:
    """按场景创建示例工作区（owner 为当前用户；已有工作区不受影响）."""
    result = create_demo_workspace(scenario, current_user, db)
    return HelpExampleWorkspaceResponse(
        workspace_id=result.workspace.id,
        name=result.workspace.name,
        imported_tables=result.imported_tables,
        imported_rows=result.imported_rows,
        imported_views=result.imported_views,
        imported_documents=result.imported_documents,
        errors=result.errors,
    )


__all__ = ["router"]
