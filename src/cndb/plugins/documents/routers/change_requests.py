"""documents 插件路由：文档修改申请 API.

端点（挂 ``/{workspace_id}/document-change-requests``，独立于 documents 路径，
避免与 ``/{doc_id}`` 通配冲突）：

- GET    ""                          列表（成员；可按 document_id / scope 过滤）
- POST   ""                          手动发起修改申请（成员）
- GET    /{request_id}               详情（含内容 DIFF 与待审正文）
- POST   /{request_id}/merge         通过并生效（owner/editor）
- POST   /{request_id}/close         驳回 / 关闭（owner/editor 或提交人）
- POST   /{request_id}/update-base   刷新内容基准（提交人本人）
- DELETE /{request_id}               删除草稿（提交人本人或 owner；仅待审核）

保存路径的自动分派（viewer / 关闭直编的 editor → 202 + 申请）见
``documents.routers.documents.update_document_content``。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.documents import services
from cndb.plugins.documents.schemas import (
    DocumentChangeRequestCreate,
    DocumentChangeRequestReview,
    DocumentChangeRequestUpdateBase,
)

router = APIRouter(prefix="/{workspace_id}/document-change-requests", tags=["documents"])


@router.get("")
def list_change_requests(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    document_id: Annotated[int | None, Query(description="仅列出该文档的申请")] = None,
    scope: Annotated[str, Query(description="open / merged / closed / mine / all")] = "open",
) -> dict[str, Any]:
    """列出工作区（或指定文档）的修改申请."""
    items = services.change_requests.list_requests(db, workspace_id, current_user, document_id=document_id, scope=scope)
    return {
        "items": [services.change_requests.serialize_request(db, cr) for cr in items],
        "total": len(items),
    }


@router.post("", status_code=201)
def create_change_request(
    workspace_id: int,
    payload: DocumentChangeRequestCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """手动发起文档修改申请（自动分派路径之外的显式入口）."""
    cr = services.change_requests.create_request(
        db,
        workspace_id,
        payload.document_id,
        current_user,
        content=payload.content,
        title=payload.title,
        description=payload.description,
        change_summary=payload.change_summary,
        base_version_number=payload.base_version_number,
    )
    return services.change_requests.serialize_request(db, cr, with_diff=True)


@router.get("/{request_id}")
def get_change_request(
    workspace_id: int,
    request_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """修改申请详情：含内容 DIFF（基准版本 → 待审正文）与待审正文全文."""
    services.change_requests.require_member(db, workspace_id, current_user)
    cr = services.change_requests.get_request_or_404(db, workspace_id, request_id)
    return services.change_requests.serialize_request(db, cr, with_diff=True, with_content=True)


@router.post("/{request_id}/merge")
def merge_change_request(
    workspace_id: int,
    request_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: DocumentChangeRequestReview | None = None,
) -> dict[str, Any]:
    """通过申请：待审正文落库为新的文档版本（owner/editor）."""
    cr, version_number = services.change_requests.merge_request(
        db,
        workspace_id,
        request_id,
        current_user,
        review_comment=(payload.review_comment if payload else ""),
    )
    return {
        "request": services.change_requests.serialize_request(db, cr, with_diff=True),
        "version_number": version_number,
    }


@router.post("/{request_id}/close")
def close_change_request(
    workspace_id: int,
    request_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: DocumentChangeRequestReview | None = None,
) -> dict[str, Any]:
    """驳回 / 关闭申请（owner/editor 或提交人本人）."""
    cr = services.change_requests.close_request(
        db,
        workspace_id,
        request_id,
        current_user,
        review_comment=(payload.review_comment if payload else ""),
    )
    return services.change_requests.serialize_request(db, cr, with_diff=True)


@router.post("/{request_id}/update-base")
def update_change_request_base(
    workspace_id: int,
    request_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: DocumentChangeRequestUpdateBase | None = None,
) -> dict[str, Any]:
    """刷新内容基准（提交人本人；缺省以当前最新版本为基准）."""
    cr = services.change_requests.update_base(
        db,
        workspace_id,
        request_id,
        current_user,
        base_version_number=(payload.base_version_number if payload else None),
    )
    return services.change_requests.serialize_request(db, cr, with_diff=True)


@router.delete("/{request_id}", status_code=204)
def delete_change_request(
    workspace_id: int,
    request_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除草稿（提交人本人或 owner；仅待审核的申请可删除）."""
    services.change_requests.delete_request(db, workspace_id, request_id, current_user)


__all__ = ["router"]
