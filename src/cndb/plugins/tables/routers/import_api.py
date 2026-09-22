"""API 自动建表导入路由 — 工作区级别端点.

提供五个端点：
- POST /{workspace_id}/import-api/analyze           — 抓 API + 分析列类型（不写库）
- POST /{workspace_id}/import-api                   — 抓 API + 自动建表 + 导入数据
- POST /{workspace_id}/tables/{table_id}/import-api — 抓 API + 追加数据到已有表
- POST /{workspace_id}/import-api/config            — 从 JSON 配置文件批量建表
- POST /{workspace_id}/import-api/config/validate   — 校验 JSON 配置文件（不建表）
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.importing.api_config_loader import (
    ApiConfigError,
    build_fetch_config,
    ingest_tables_from_config,
    load_api_config_text,
)
from cndb.plugins.tables.services.importing.api_fetch import FetchConfig, fetch_json
from cndb.plugins.tables.services.transfer import (
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
    response_handler: str = Field(default="json", description="响应处理器：json / tencent_stock / ...")
    encoding: str = Field(default="utf-8", description="响应编码，如 utf-8 / gbk")
    query_interval: float = Field(default=60.0, description="查询间隔（秒），默认60，最短6")


class ApiAnalyzeRequest(ApiFetchRequest):
    pass


class ApiImportRequest(ApiFetchRequest):
    table_name: str = Field(..., description="新建表的名称")


class ApiConfigRequest(BaseModel):
    """JSON 配置文件驱动的批量建表请求."""

    config_json: str = Field(..., description="API 建表配置 JSON 字符串")
    stop_on_error: bool = Field(default=True, description="遇错是否停止（True=停止/False=继续）")


# ── 原有端点 ────────────────────────────────────


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
                response_handler=payload.response_handler,
                encoding=payload.encoding,
                query_interval=payload.query_interval,
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

    from cndb.plugins.tables.services.transfer import ingest_from_api

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
            owner_id=current_user.id,
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
                response_handler=payload.response_handler,
                encoding=payload.encoding,
                query_interval=payload.query_interval,
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


# ── JSON 配置文件批量建表 ───────────────────────


@router.post("/import-api/config/validate")
def api_config_validate(
    workspace_id: int,
    payload: ApiConfigRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """校验 JSON 配置文件（不建表）."""
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)

    try:
        table_defs = load_api_config_text(payload.config_json)
    except ApiConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 返回概要信息
    summary = []
    for td in table_defs:
        fetch_cfg = build_fetch_config(td)
        summary.append(
            {
                "table_name": td["table_name"],
                "handler": fetch_cfg.response_handler if isinstance(fetch_cfg.response_handler, str) else "custom",
                "encoding": fetch_cfg.encoding,
                "query_interval": fetch_cfg.query_interval,
                "url": fetch_cfg.url[:80] + ("..." if len(fetch_cfg.url) > 80 else ""),
            }
        )

    return {
        "valid": True,
        "table_count": len(table_defs),
        "tables": summary,
    }


@router.post("/import-api/config")
def api_config_import(
    workspace_id: int,
    payload: ApiConfigRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """从 JSON 配置文件批量建表 + 导入数据."""
    _check_workspace_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)

    try:
        table_defs = load_api_config_text(payload.config_json)
    except ApiConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    engine = db.get_bind()
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for table_def in table_defs:
        table_name = table_def["table_name"]
        try:
            table_results = ingest_tables_from_config(engine, db, workspace_id, [table_def], owner_id=current_user.id)
            results.extend(table_results)
        except Exception as exc:
            err_info = {"table_name": table_name, "error": str(exc)}
            errors.append(err_info)
            if payload.stop_on_error:
                break
            # 继续下一个

    # 无论部分成功还是全部失败，都返回结果
    success_count = len(results)
    fail_count = len(errors)

    return {
        "success_count": success_count,
        "fail_count": fail_count,
        "results": results,
        "errors": errors,
        "stopped_on_error": payload.stop_on_error and fail_count > 0,
    }


__all__ = ["router"]
