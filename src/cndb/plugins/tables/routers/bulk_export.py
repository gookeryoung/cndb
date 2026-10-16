"""表数据导出端点（xlsx / csv / json）与导出文件名构造."""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.services import transfer
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core.access import TableAction, get_table_or_404
from cndb.plugins.tables.services.core.view_access import ViewAction, get_view_or_404
from cndb.plugins.workspaces.models import Workspace

logger = logging.getLogger(__name__)

router = APIRouter()


_SAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')


def _sanitize_filename_part(s: str, fallback: str = "未命名") -> str:
    """清洗文件名片段：替换 Windows 非法字符，去首尾空白；空值回退."""
    cleaned = _SAFE_FILENAME_RE.sub("_", s).strip()
    return cleaned or fallback


def _build_export_filename(
    ws_name: str,
    table_name: str,
    view_name: str | None,
    fmt: str,
) -> str:
    """构造导出文件名：工作区-数据表-视图-YYYYMMDD_HHMMSS.扩展名."""
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    ext_map = {"json": ".json", "csv": ".csv", "xlsx": ".xlsx"}
    parts = [_sanitize_filename_part(ws_name), _sanitize_filename_part(table_name)]
    if view_name:
        parts.append(_sanitize_filename_part(view_name))
    parts.append(ts)
    return "-".join(parts) + ext_map.get(fmt, f".{fmt}")


# ── 导出 ──────────────────────────────────────────────


@router.get("/export")
def export_table(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    format: str = "json",
    view_id: int | None = None,
) -> Response:
    """导出当前表的数据，支持按视图筛选条件导出.

    下载文件名格式：`工作区-数据表-视图-YYYYMMDD_HHMMSS.扩展名`，
    中文名称经 RFC 5987 编码，浏览器正确解码；非法字符替换为下划线.

    Args:
        workspace_id: 工作区 ID
        table_id: 表 ID
        current_user: 当前登录用户
        db: 数据库会话
        format: 导出格式（json/csv/xlsx），默认 json
        view_id: 可选的视图 ID；传入后按该视图的 filters/sortings/filter_type 过滤结果

    Returns:
        对应格式的文件二进制响应（含 Content-Disposition 下载头）
    """
    table = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    filters: list[dict[str, Any]] | None = None
    sorts: list[dict[str, Any]] | None = None
    filter_logic = "AND"
    view_name: str | None = None

    if view_id is not None:
        # 视图可见性校验：他人个人视图一律 404 —— 原实现只比对 table_id，
        # 凭 id 即可套用他人视图的筛选规则导出数据，视图名还会出现在下载文件名里（缺陷 ① 同类）
        dv = get_view_or_404(db, table, current_user, view_id, ViewAction.VIEW_READ)
        filters = dv.filters or None
        sorts = dv.sortings or None
        filter_logic = dv.filter_type or "AND"
        view_name = dv.name

    rows, total = rec.list_rows(
        db.get_bind(),
        table,
        limit=None,
        db=db,
        user=current_user,
        filters=filters,
        sorts=sorts,
        filter_logic=filter_logic,
    )

    # 内存安全上限：导出函数将全量行载入 Python 内存再序列化，超过此上限拒绝服务
    _EXPORT_ROW_CAP = 500_000
    if total > _EXPORT_ROW_CAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"当前表有 {total} 行，超过导出上限 {_EXPORT_ROW_CAP} 行，请分批导出或联系管理员.",
        )

    fmt = format.lower()
    ext_map = {"json": "json", "csv": "csv", "xlsx": "xlsx"}
    if fmt not in ext_map:
        raise HTTPException(status_code=400, detail=f"不支持的导出格式: {format}")

    # 获取工作区名 + 构造导出文件名（工作区-数据表-视图-日期时间.扩展名）
    ws = db.get(Workspace, table.workspace_id)
    ws_name = ws.name if ws else f"workspace-{table.workspace_id}"
    filename = _build_export_filename(ws_name, table.name, view_name, fmt)
    # filename* 带完整中文，filename 放 ASCII 安全回退（非 ASCII 替换为 _ 以满足 latin-1 编码约束）
    ascii_fallback = "".join(c if ord(c) < 128 else "_" for c in filename)
    quoted = quote(filename)
    disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quoted}"

    media_map = {
        "json": "application/json",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    body_map = {
        "json": lambda: transfer.export_rows_to_json(rows),
        "csv": lambda: transfer.export_rows_to_csv(rows),
        "xlsx": lambda: transfer.export_rows_to_xlsx(rows),
    }

    body = body_map[fmt]()
    return Response(
        content=body,
        media_type=media_map[fmt],
        headers={"Content-Disposition": disposition},
    )


__all__ = ["router"]
