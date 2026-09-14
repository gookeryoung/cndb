"""CSV 自动建表导入路由 — 工作区级别 POST 端点.

提供两个端点：
- POST /{workspace_id}/import-csv/analyze  — 纯分析，不写数据库
- POST /{workspace_id}/import-csv          — 分析 + 建表 + 导入数据
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.transfer import analyze_csv_columns, create_table_from_csv
from cndb.plugins.workspaces.models import ROLE_RANK, Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role

router = APIRouter(prefix="/{workspace_id}", tags=["import-csv"])


def _check_workspace_permission(workspace_id: int, user: User, db: Session, min_role: WorkspaceRole) -> Workspace:
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    role = get_member_role(user, ws, db)
    if role is None or ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise HTTPException(status_code=403, detail="权限不足")
    return ws


class AnalyzeRequest(BaseModel):
    csv_text: str = Field(..., description="CSV 文本内容（含表头）")


class ImportRequest(BaseModel):
    table_name: str = Field(..., description="新建表的名称")
    csv_text: str = Field(..., description="CSV 文本内容（含表头）")
    skip_first_row: bool = Field(default=False, description="是否跳过第一行（作为数据）")


@router.post("/import-csv/analyze")
def analyze_csv(
    workspace_id: int,
    payload: AnalyzeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """纯分析 CSV 列类型，不写数据库."""
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)

    csv_text = payload.csv_text.strip()
    if not csv_text:
        raise HTTPException(status_code=400, detail="CSV 内容为空")

    # 跳过首行选项
    text = csv_text
    if payload.__dict__.get("skip_first_row"):
        lines = csv_text.splitlines(True)
        if len(lines) > 1:
            text = "".join(lines[1:])

    columns, total_rows = analyze_csv_columns(text)

    # 检查列名是否全空
    valid_cols = [c for c in columns if c["name"].strip()]
    if not valid_cols:
        raise HTTPException(status_code=400, detail="CSV 没有有效列名")

    return {"columns": columns, "total_rows": total_rows}


@router.post("/import-csv")
def import_csv_create_table(
    workspace_id: int,
    payload: ImportRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """分析 CSV + 自动建表 + 导入数据."""
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)

    csv_text = payload.csv_text.strip()
    if not csv_text:
        raise HTTPException(status_code=400, detail="CSV 内容为空")

    # 检查列名有效性
    columns, _total = analyze_csv_columns(csv_text)
    valid_cols = [c for c in columns if c["name"].strip()]
    if not valid_cols:
        raise HTTPException(status_code=400, detail="CSV 没有有效列名")

    # 建表 + 导入
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


__all__ = ["router"]
