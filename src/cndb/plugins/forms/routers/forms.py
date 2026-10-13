"""forms 插件路由：表单定义 CRUD + 运行器提交.

挂载路径：/api/v1/workspaces/{wid}/forms
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.forms.models import FormDefinition
from cndb.plugins.forms.schemas import (
    FormCreate,
    FormListResponse,
    FormResponse,
    FormSubmitRequest,
    FormSubmitResponse,
    FormUpdate,
)
from cndb.plugins.tables.services.core.access import (
    TableAction,
    check_action,
    check_workspace_permission,
    get_table_or_404,
)
from cndb.plugins.tables.services.core.records import create_row
from cndb.plugins.workspaces.models import WorkspaceRole

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/{workspace_id}/forms", tags=["forms"])


def _get_workspace_or_404(workspace_id: int, db: Session) -> Any:
    """校验工作区存在并返回；不存在返回 404."""
    from cndb.plugins.workspaces.models import Workspace

    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return ws


def _authorize_workspace(workspace_id: int, user: User, db: Session) -> None:
    """校验用户对工作区的 VIEWER 级最低权限."""
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.VIEWER)


def _get_form_or_404(form_id: int, workspace_id: int, db: Session) -> FormDefinition:
    """按 form_id + workspace_id 联合查询表单定义."""
    stmt = select(FormDefinition).where(
        FormDefinition.id == form_id,
        FormDefinition.workspace_id == workspace_id,
        FormDefinition.trashed.is_(False),
    )
    form = db.scalar(stmt)
    if form is None:
        raise HTTPException(status_code=404, detail="表单不存在")
    return form


@router.get("", response_model=list[FormListResponse])
def list_forms(
    workspace_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[FormDefinition]:
    """列出工作区内的表单定义."""
    _authorize_workspace(workspace_id, current_user, db)
    stmt = (
        select(FormDefinition)
        .where(FormDefinition.workspace_id == workspace_id, FormDefinition.trashed.is_(False))
        .order_by(FormDefinition.order, FormDefinition.id)
    )
    return list(db.scalars(stmt).all())


@router.get("/{form_id}", response_model=FormResponse)
def get_form(
    workspace_id: int,
    form_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> FormDefinition:
    """获取表单定义详情."""
    _authorize_workspace(workspace_id, current_user, db)
    return _get_form_or_404(form_id, workspace_id, db)


@router.post("", response_model=FormResponse, status_code=status.HTTP_201_CREATED)
def create_form(
    workspace_id: int,
    payload: FormCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> FormDefinition:
    """创建表单定义."""
    _authorize_workspace(workspace_id, current_user, db)
    # 校验目标表存在且用户有 READ 权限
    get_table_or_404(payload.table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 校验表内无同名表单（唯一约束）
    existing = db.scalar(
        select(FormDefinition).where(
            FormDefinition.workspace_id == workspace_id,
            FormDefinition.table_id == payload.table_id,
            FormDefinition.name == payload.name,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=400, detail=f"该表下已存在同名表单: {payload.name}")

    form = FormDefinition(
        workspace_id=workspace_id,
        table_id=payload.table_id,
        name=payload.name,
        description=payload.description,
        field_config=[fc.model_dump() for fc in payload.field_config],
        use_role=payload.use_role,
        edit_role=payload.edit_role,
        delete_role=payload.delete_role,
        approval_workflow_id=payload.approval_workflow_id,
    )
    db.add(form)
    db.commit()
    db.refresh(form)
    return form


@router.put("/{form_id}", response_model=FormResponse)
def update_form(
    workspace_id: int,
    form_id: int,
    payload: FormUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> FormDefinition:
    """更新表单定义."""
    _authorize_workspace(workspace_id, current_user, db)
    form = _get_form_or_404(form_id, workspace_id, db)

    ud = payload.model_dump(exclude_unset=True)
    # field_config 从 Pydantic 对象转 dict
    if "field_config" in ud and ud["field_config"] is not None:
        ud["field_config"] = [fc.model_dump() if hasattr(fc, "model_dump") else fc for fc in ud["field_config"]]

    for k, v in ud.items():
        setattr(form, k, v)
    db.commit()
    db.refresh(form)
    return form


@router.delete("/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_form(
    workspace_id: int,
    form_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """软删除表单定义（设置 trashed=True）."""
    _authorize_workspace(workspace_id, current_user, db)
    form = _get_form_or_404(form_id, workspace_id, db)
    form.trashed = True
    db.commit()


@router.post("/{form_id}/submit", response_model=FormSubmitResponse)
def submit_form(
    workspace_id: int,
    form_id: int,
    payload: FormSubmitRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> FormSubmitResponse:
    """表单运行器提交：将字段值写入所属表的新行.

    权限链：用户对表单所属表须有 READ + CREATE 权限；表单字段配置中的
    required 字段如未提供值则返回 400.
    """
    form = _get_form_or_404(form_id, workspace_id, db)
    # 校验表权限（提交创建记录需要 EDIT_RECORDS 权限）
    dt = get_table_or_404(form.table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    if not check_action(db, dt, current_user, TableAction.EDIT_RECORDS):
        raise HTTPException(status_code=403, detail="无权创建记录")

    # 校验必填字段
    field_names = {f.name for f in dt.active_fields()}
    required_by_form = {
        fc["field_name"]
        for fc in form.field_config
        if isinstance(fc, dict) and fc.get("required") and fc.get("visible", True)
    }
    missing = [n for n in required_by_form if n not in payload.values or payload.values[n] in (None, "")]
    if missing:
        raise HTTPException(status_code=400, detail=f"必填字段缺失: {missing}")

    # 只取表单配置中 visible=true 的字段值
    visible_names = {
        fc["field_name"]
        for fc in form.field_config
        if isinstance(fc, dict) and fc.get("visible", True)
    }
    filtered_values = {k: v for k, v in payload.values.items() if k in visible_names and k in field_names}

    try:
        row = create_row(db.get_bind(), dt, filtered_values, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if row is None:
        raise HTTPException(status_code=500, detail="创建记录失败")
    rid = row.get("id", row.get("row_id")) if isinstance(row, dict) else row.id
    return FormSubmitResponse(record_id=rid, message="提交成功")
