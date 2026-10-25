"""help 图示路由（ADR 0030 §4）.

- `GET /api/v1/help/figures`：图示清单（key / 标题 / 说明 / 指纹 / 生成时间）；
- `GET /api/v1/help/figures/{key}.svg`：单张 SVG（带 ETag，命中 `If-None-Match` 返回 304）；
- `POST /api/v1/help/figures/refresh`：立即重建全部图示（运维与内容核验用）。

三个端点均要求登录（与示例接口一致）；图示不查数据库、不依赖 seed。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response

from cndb.api.deps import get_current_user
from cndb.plugins.help.schemas import HelpFigureListResponse, HelpFigureRefreshResponse
from cndb.plugins.help.services.figures import get_figure_refresher, get_figure_store

router = APIRouter(prefix="/figures", tags=["help"])

_SVG_MEDIA_TYPE = "image/svg+xml; charset=utf-8"


@router.get("", response_model=HelpFigureListResponse, summary="帮助图示清单")
def list_figures(
    _current_user: Annotated[object, Depends(get_current_user)],
) -> dict[str, object]:
    """返回全部图示元信息；过期项已在内部按指纹重建."""
    items = get_figure_store().list_meta()
    latest = max((item["generatedAt"] for item in items), default=0.0)
    return {"items": items, "generatedAt": latest}


@router.post("/refresh", response_model=HelpFigureRefreshResponse, summary="立即重建帮助图示")
def refresh_figures(
    _current_user: Annotated[object, Depends(get_current_user)],
) -> dict[str, int]:
    """强制重建全部图示（幂等、廉价）；同时唤醒后台轮次重新计时."""
    rebuilt = get_figure_store().refresh(force=True)
    refresher = get_figure_refresher()
    if refresher is not None:
        refresher.wake()
    return {"rebuilt": rebuilt}


@router.get("/{key}.svg", response_class=Response, summary="获取帮助图示 SVG")
def get_figure_svg(
    key: str,
    request: Request,
    _current_user: Annotated[object, Depends(get_current_user)],
) -> Response:
    """返回单张图示 SVG；未登记的 key 一律 404."""
    try:
        record = get_figure_store().get(key)
    except Exception as exc:  # pragma: no cover - 构建异常已在仓库内降级为旧快照
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="图示生成失败") from exc
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图示不存在")

    etag = f'"{record.fingerprint}"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=300"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=record.svg, media_type=_SVG_MEDIA_TYPE, headers=headers)


__all__ = ["router"]
