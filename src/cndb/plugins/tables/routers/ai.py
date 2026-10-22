"""数据表 AI 动作路由（ADR 0020 P2）：字段批量填充.

端点：``POST /api/v1/workspaces/{wid}/tables/{table_id}/ai/actions/fill_field``

**只生成建议值，不写库**：前端预览确认后逐行调用既有记录更新接口（直编落库 / 无直编资格
自动 202 修改申请）。输入按行级读范围与字段隐藏裁剪。
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
from cndb.plugins.tables.services.core.access import TableAction, get_hidden_field_names, get_table_or_404
from cndb.plugins.tables.services.core.records import get_row

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/ai", tags=["tables"])


class FillFieldRequest(BaseModel):
    """字段批量填充请求（单字段、最多 20 行）."""

    field_name: str = Field(min_length=1, max_length=255, description="目标字段名")
    row_ids: list[int] = Field(min_length=1, max_length=ai_service.MAX_FILL_ROWS, description="待填充行 id")
    instruction: str | None = Field(default=None, max_length=500, description="可选的生成要求")


@router.post("/actions/fill_field")
def fill_field(
    workspace_id: int,
    table_id: int,
    payload: FillFieldRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """生成字段填充建议（只读，不写任何行）."""
    table = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    fields = {field.name: field for field in table.active_fields()}
    target = fields.get(payload.field_name)
    if target is None:
        raise BadRequestError(f"目标字段不存在: {payload.field_name}")

    hidden = get_hidden_field_names(db, table, current_user)
    if target.hidden or target.name in hidden:
        raise BadRequestError("隐藏字段不支持 AI 填充")

    row_ids = list(dict.fromkeys(payload.row_ids))[: ai_service.MAX_FILL_ROWS]
    rows: list[tuple[int, dict[str, Any]]] = []
    skipped: list[int] = []
    for row_id in row_ids:
        row = get_row(db.get_bind(), table, row_id, db=db, user=current_user)
        if row is None:  # 不存在 / 已软删 / 行级读范围外：不进入模型输入
            skipped.append(row_id)
            continue
        rows.append((row_id, row))
    if not rows:
        raise BadRequestError("所选行均不可读（不存在或超出你的行级权限）")

    context_fields = [
        field.name
        for field in table.active_fields()
        if not field.hidden and field.name not in hidden and field.name != target.name
    ][: ai_service.FILL_CONTEXT_FIELDS]
    user_content = ai_service.build_fill_content(
        table.name,
        target.name,
        target.field_type,
        context_fields,
        rows,
        payload.instruction,
    )

    try:
        result = llm_gateway.invoke(
            db,
            current_user,
            ai_service.FILL_FIELD,
            user_content=user_content,
            context=LlmContext(workspace_id=workspace_id, target_type="table", target_id=table.id),
        )
    except LlmError as exc:
        raise CndbError(str(exc), status_code=exc.status_code, code=exc.code) from exc

    allowed = {row_id for row_id, _row in rows}
    values = [item for item in result.parsed.values if item.row_id in allowed]
    return {
        "action": ai_service.FILL_FIELD.name,
        "run_id": result.run_id,
        "model": result.model,
        "usage": result.usage,
        "result": {"values": [item.model_dump() for item in values]},
        "skipped_row_ids": skipped,
        "row_count": len(rows),
    }


__all__ = ["FillFieldRequest", "router"]
