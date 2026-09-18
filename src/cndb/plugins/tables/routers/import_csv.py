"""通用文件导入建表路由 — 工作区级别端点.

支持格式：CSV / TSV / JSON / XLSX（根据文件扩展名或内容自动识别）.

提供四个端点：
- POST /{workspace_id}/import-file/analyze    — 纯分析（multipart 上传文件，不写数据库）
- POST /{workspace_id}/import-file            — 分析 + 建表 + 导入数据（multipart）
- POST /{workspace_id}/import-csv/analyze     — 旧端点兼容（JSON body 传 csv_text）
- POST /{workspace_id}/import-csv             — 旧端点兼容（JSON body 传 csv_text）
"""

from __future__ import annotations

import json as _json
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.transfer import (
    analyze_csv_columns,
    analyze_file_columns,
    create_table_from_csv,
    create_table_from_file,
    parse_file_to_rows,
)
from cndb.plugins.workspaces.models import ROLE_RANK, Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role

# 新通用路由 prefix —— 主入口
router = APIRouter(prefix="/{workspace_id}", tags=["import-file"])

# 旧路由 prefix 别名 —— 为向后兼容保留，在 tables 插件注册时挂载为 import-csv
compat_router = APIRouter(prefix="/{workspace_id}", tags=["import-csv"])


def _check_workspace_permission(
    workspace_id: int,
    user: User,
    db: Session,
    min_role: WorkspaceRole,
) -> Workspace:
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    role = get_member_role(user, ws, db)
    if role is None or ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise HTTPException(status_code=403, detail="权限不足")
    return ws


def _guess_table_name(filename: str) -> str:
    """从文件名推断表名：去扩展名 + 保留主名."""
    from pathlib import Path

    name = Path(filename).stem
    return name or "导入数据表"


# ── 通用 multipart 端点（新） ─────────────────────


@router.post("/import-file/analyze")
async def import_file_analyze(
    workspace_id: int,
    file: Annotated[UploadFile, File(..., description="上传的数据文件（csv/tsv/json/xlsx）")],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """上传文件 + 分析列类型（不写库）.

    格式自动识别：优先用文件名扩展名，退化到内容特征.

    额外返回 sample_rows（前 50 行）供前端渲染"典型数据 + 实时转换预览".
    """
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)

    filename = file.filename or ""
    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取文件失败: {exc}") from exc

    if not content:
        raise HTTPException(status_code=400, detail="文件为空")

    # 先快速判断是否拒绝的格式（旧版 .xls — openpyxl 无法解析 BIFF 格式）
    if filename.lower().endswith(".xls"):
        raise HTTPException(status_code=400, detail="不支持旧版 .xls 格式，请在 Excel 中另存为 .xlsx")

    columns, total_rows, actual_fmt = analyze_file_columns(content, filename=filename)

    valid_cols = [c for c in columns if c["name"].strip()]
    if not valid_cols:
        raise HTTPException(status_code=400, detail="文件没有有效列名")

    # 额外解析前 50 行作为 sample_rows —— 前端用来做"典型数据 + 实时转换预览"
    sample_rows, _cols, _ = parse_file_to_rows(content, filename=filename)
    SAMPLE_ROWS_LIMIT = 50
    sample_rows_preview: list[dict[str, Any]] = sample_rows[:SAMPLE_ROWS_LIMIT]

    return {
        "columns": columns,
        "total_rows": total_rows,
        "format": actual_fmt,
        "filename": filename,
        "sample_rows": sample_rows_preview,
    }


@router.post("/import-file")
async def import_file_create_table(
    workspace_id: int,
    file: Annotated[UploadFile, File(..., description="上传的数据文件（csv/tsv/json/xlsx）")],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    table_name: Optional[str] = Form(default=None, description="新建表名 — 留空则用文件名"),
    column_overrides: Optional[str] = Form(
        default=None,
        description="前端回传的字段类型覆盖映射（JSON 字符串），"
        "格式 {\"列名\": {\"field_type\": \"select\", \"options\": [...]}}",
    ),
) -> dict[str, Any]:
    """上传文件 + 自动建表 + 导入数据（通用入口）."""
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)

    filename = file.filename or ""
    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取文件失败: {exc}") from exc

    if not content:
        raise HTTPException(status_code=400, detail="文件为空")

    # 判断是否拒绝的格式（旧版 .xls）
    if filename.lower().endswith(".xls"):
        raise HTTPException(status_code=400, detail="不支持旧版 .xls 格式，请在 Excel 中另存为 .xlsx")

    name = table_name or _guess_table_name(filename)
    if not name.strip():
        raise HTTPException(status_code=400, detail="表名不能为空")

    # 解析 column_overrides（可选）
    overrides: dict[str, dict[str, Any]] | None = None
    if column_overrides:
        try:
            parsed = _json.loads(column_overrides)
            if isinstance(parsed, dict):
                overrides = {k: v for k, v in parsed.items() if isinstance(v, dict)}
        except _json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"column_overrides JSON 格式错误: {exc}") from exc

    try:
        engine = db.get_bind()
        dt, ids, columns = create_table_from_file(
            engine,
            db,
            workspace_id,
            name.strip(),
            content,
            filename=filename,
            owner_id=current_user.id,
            column_overrides=overrides,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"建表或导入失败: {exc}") from exc

    return {
        "table_id": dt.id,
        "table_name": dt.name,
        "imported_rows": len(ids),
        "field_count": len(dt.fields),
        "format": dt.name,  # 后端暂未持久化 format，占位
        "columns": columns,
    }


# ── 旧 JSON body 端点（兼容保留） ──────────────────


class AnalyzeRequest(BaseModel):
    csv_text: str = Field(..., description="CSV 文本内容（含表头）")


class ImportRequest(BaseModel):
    table_name: str = Field(..., description="新建表的名称")
    csv_text: str = Field(..., description="CSV 文本内容（含表头）")
    skip_first_row: bool = Field(default=False, description="是否跳过第一行（作为数据）")


@compat_router.post("/import-csv/analyze")
def analyze_csv(
    workspace_id: int,
    payload: AnalyzeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """纯分析 CSV 列类型，不写数据库（旧端点）."""
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)

    csv_text = payload.csv_text.strip()
    if not csv_text:
        raise HTTPException(status_code=400, detail="CSV 内容为空")

    # 跳过首行选项（旧兼容参数）
    text = csv_text
    skip_first = getattr(payload, "skip_first_row", False)
    if skip_first:
        lines = csv_text.splitlines(True)
        if len(lines) > 1:
            text = "".join(lines[1:])

    columns, total_rows = analyze_csv_columns(text)

    valid_cols = [c for c in columns if c["name"].strip()]
    if not valid_cols:
        raise HTTPException(status_code=400, detail="CSV 没有有效列名")

    return {"columns": columns, "total_rows": total_rows}


@compat_router.post("/import-csv")
def import_csv_create_table(
    workspace_id: int,
    payload: ImportRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """分析 CSV + 自动建表 + 导入数据（旧端点）."""
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)

    csv_text = payload.csv_text.strip()
    if not csv_text:
        raise HTTPException(status_code=400, detail="CSV 内容为空")

    columns, _total = analyze_csv_columns(csv_text)
    valid_cols = [c for c in columns if c["name"].strip()]
    if not valid_cols:
        raise HTTPException(status_code=400, detail="CSV 没有有效列名")

    try:
        engine = db.get_bind()
        dt, ids = create_table_from_csv(
            engine, db, workspace_id, payload.table_name, csv_text, owner_id=current_user.id
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"建表或导入失败: {exc}") from exc

    return {
        "table_id": dt.id,
        "table_name": dt.name,
        "imported_rows": len(ids),
        "field_count": len(dt.fields),
    }


# 为了 re-export 给旧路由注册
__all__ = ["compat_router", "router"]
