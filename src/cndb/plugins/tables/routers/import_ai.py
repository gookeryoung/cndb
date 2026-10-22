"""导入 AI 动作路由（ADR 0020 P2）：列映射建议.

端点：``POST /api/v1/workspaces/{wid}/import-file/ai/mapping-suggestion``

**只生成建议，不修改 ``ImportTask`` / 不写数据**；前端把建议回填到映射编辑态，用户仍需
走「分析 → 预览 → 确认导入」。候选目标字段剔除隐藏字段。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import BadRequestError, CndbError
from cndb.plugins.accounts.models import User
from cndb.plugins.llm.services import gateway as llm_gateway
from cndb.plugins.llm.services.errors import LlmError
from cndb.plugins.llm.services.gateway import LlmContext
from cndb.plugins.tables.services import ai as ai_service
from cndb.plugins.tables.services.core.access import (
    TableAction,
    check_workspace_permission,
    get_hidden_field_names,
    get_table_or_404,
)
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/import-file/ai", tags=["import-file"])


class MappingSuggestionRequest(BaseModel):
    """列映射建议请求（表头 + 少量抽样行，不含整表数据）."""

    target_table_id: int = Field(description="目标数据表 id")
    headers: list[str] = Field(min_length=1, max_length=ai_service.MAX_HEADERS, description="源文件表头")
    sample_rows: list[list[Any]] = Field(default_factory=list, description="抽样数据行（≤20 行）")
    existing_mapping: dict[str, str | None] = Field(default_factory=dict, description="已手工配置的映射")


@router.post("/mapping-suggestion")
def suggest_mapping(
    workspace_id: int,
    payload: MappingSuggestionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """生成列映射建议（只读，不改导入任务）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    table = get_table_or_404(payload.target_table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    hidden = get_hidden_field_names(db, table, current_user)
    target_fields = [
        (field.name, field.field_type)
        for field in table.active_fields()
        if not field.hidden and field.name not in hidden
    ]
    if not target_fields:
        raise BadRequestError("目标表没有可用于映射的字段")

    headers = [header.strip() for header in payload.headers if header.strip()]
    if not headers:
        raise BadRequestError("源表头不能为空")
    if len(headers) > ai_service.MAX_HEADERS:
        raise BadRequestError(f"表头过多（{len(headers)} > {ai_service.MAX_HEADERS}），请分批处理")
    sample_rows = [list(row[: len(headers)]) for row in payload.sample_rows[: ai_service.MAX_SAMPLE_ROWS]]
    user_content = ai_service.build_mapping_content(
        headers,
        sample_rows,
        target_fields,
        payload.existing_mapping,
    )

    try:
        result = llm_gateway.invoke(
            db,
            current_user,
            ai_service.MAPPING_SUGGESTION,
            user_content=user_content,
            context=LlmContext(workspace_id=workspace_id, target_type="import", target_id=table.id),
        )
    except LlmError as exc:
        raise CndbError(str(exc), status_code=exc.status_code, code=exc.code) from exc

    allowed_fields = {name for name, _field_type in target_fields}
    header_set = set(headers)
    used_sources: set[str] = set()
    used_targets: set[str] = set()
    mappings: list[dict[str, Any]] = []
    for item in sorted(result.parsed.mappings, key=lambda mapping: -mapping.confidence):
        # 只接受真实存在的表头 / 目标字段；同源同目标各保留一条最高置信度
        if item.source not in header_set or item.target not in allowed_fields:
            continue
        if item.source in used_sources or item.target in used_targets:
            continue
        used_sources.add(item.source)
        used_targets.add(item.target)
        mappings.append(item.model_dump())
    unmapped = [header for header in headers if header not in used_sources]
    return {
        "action": ai_service.MAPPING_SUGGESTION.name,
        "run_id": result.run_id,
        "model": result.model,
        "usage": result.usage,
        "result": {"mappings": mappings, "unmapped": unmapped},
    }


__all__ = ["MappingSuggestionRequest", "router"]
