"""API 自动建表导入路由 — 工作区级别端点.

提供三个端点：
- POST /{workspace_id}/import-api/analyze           — 抓 API + 分析列类型（不写库）
- POST /{workspace_id}/import-api                   — 抓 API + 自动建表 + 导入数据
- POST /{workspace_id}/tables/{table_id}/import-api — 抓 API + 追加数据到已有表
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.api_fetch import FetchConfig, fetch_json
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.transfer import (
    analyze_json_columns,
    import_rows_from_json,
)
from cndb.plugins.workspaces.models import ROLE_RANK, Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role

router = APIRouter(prefix="/{workspace_id}", tags=["import-api"])


def _check_workspace_permission(workspace_id: int, user: User, db: Session, min_role: WorkspaceRole) -> Workspace:
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    role = get_member_role(user, ws, db)
    if role is None or ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise HTTPException(status_code=403, detail="权限不足")
    return ws


class ApiFetchRequest(BaseModel):
    """API 抓取通用参数."""

    url: str = Field(..., description="目标 API URL（仅 http/https）")
    method: str = Field(default="GET", description="HTTP 方法：GET / POST / PUT / PATCH / DELETE")
    headers: dict[str, str] = Field(default_factory=dict, description="自定义请求头")
    params: dict[str, Any] = Field(default_factory=dict, description="URL 查询参数")
    body: Any = Field(default=None, description="请求体（dict/list 自动 JSON 序列化）")
    data_path: str | None = Field(
        default=None,
        description="响应内数组定位路径（如 data.items）。留空时自动尝试 data/items/results 等常见字段",
    )
    timeout: float = Field(default=15.0, description="请求超时（秒）")


class ApiAnalyzeRequest(ApiFetchRequest):
    pass


class ApiImportRequest(ApiFetchRequest):
    table_name: str = Field(..., description="新建表的名称")


@router.post("/import-api/analyze")
def api_analyze(
    workspace_id: int,
    payload: ApiAnalyzeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """抓 API 数据并分析列类型（不写库）."""
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)

    try:
        rows = fetch_json(
            FetchConfig(
                url=payload.url,
                method=payload.method,
                headers=payload.headers,
                params=payload.params,
                body=payload.body,
                timeout=payload.timeout,
                data_path=payload.data_path,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"API 抓取失败: {exc}") from exc

    if not rows:
        raise HTTPException(status_code=400, detail="API 未返回有效对象数组")

    columns = analyze_json_columns(rows)
    return {
        "columns": columns,
        "total_rows": len(rows),
        "sample_row_keys": list(rows[0].keys()) if rows else [],
    }


@router.post("/import-api")
def api_import_create_table(
    workspace_id: int,
    payload: ApiImportRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """抓 API + 自动建表 + 导入数据."""
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)

    from cndb.plugins.tables.transfer import ingest_from_api

    engine = db.get_bind()

    try:
        dt, ids, columns = ingest_from_api(
            engine,
            db,
            workspace_id,
            payload.table_name,
            api_url=payload.url,
            method=payload.method,
            headers=payload.headers,
            params=payload.params,
            body=payload.body,
            data_path=payload.data_path,
            timeout=payload.timeout,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"建表或导入失败: {exc}") from exc

    return {
        "table_id": dt.id,
        "table_name": dt.name,
        "imported_rows": len(ids),
        "field_count": len(dt.fields),
        "columns": columns,
    }


@router.post("/tables/{table_id}/import-api")
def api_import_append(
    workspace_id: int,
    table_id: int,
    payload: ApiFetchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """抓 API + 追加数据到已有表."""
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)

    table = db.get(DataTable, table_id)
    if table is None or table.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="表不存在")

    try:
        rows = fetch_json(
            FetchConfig(
                url=payload.url,
                method=payload.method,
                headers=payload.headers,
                params=payload.params,
                body=payload.body,
                timeout=payload.timeout,
                data_path=payload.data_path,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"API 抓取失败: {exc}") from exc

    if not rows:
        raise HTTPException(status_code=400, detail="API 未返回有效对象数组")

    # 追加到已有表（字段需与表定义对齐；未识别的 key 会被忽略）
    import json as _json

    json_text = _json.dumps(rows, ensure_ascii=False, default=str)
    try:
        engine = db.get_bind()
        ids = import_rows_from_json(engine, table, json_text, db=db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"导入失败: {exc}") from exc

    return {
        "table_id": table.id,
        "appended_rows": len(ids),
    }


__all__ = ["router"]
