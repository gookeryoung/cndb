"""表单定义 CRUD + 表单行增删查改路由.

权限模型（不变量：表单只收紧、不放宽表级限制）：
- 表单定义管理 = TableAction.EDIT_VIEWS（经 get_table_or_404）
- 表单使用三动作（USE/EDIT/DELETE）= 表级动作（READ/EDIT_RECORDS）
  与表单阈值（check_form_access）取交集
- 行读写委托 tables.services.core.records，行级过滤/审计行为与 records API 一致
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.forms.models import FormDefinition
from cndb.plugins.forms.schemas import (
    FormCreate,
    FormListItemResponse,
    FormMetaResponse,
    FormResponse,
    FormUpdate,
    FormValuesUpdate,
)
from cndb.plugins.forms.services.field_config import (
    apply_form_defaults,
    filter_payload_keys,
    resolve_form_fields,
    validate_field_config,
)
from cndb.plugins.forms.services.permissions import (
    FormAction,
    check_form_access,
    ensure_form_access,
    get_form_or_404,
)
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core.access import TableAction, get_table_or_404
from cndb.plugins.workflows.models import Workflow
from cndb.plugins.workflows.services.approval import (
    ApprovalConflictError,
    submit_for_approval,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/{workspace_id}/forms", tags=["forms"])


def _form_to_response(form: FormDefinition) -> FormResponse:
    """FormDefinition → FormResponse（datetime 由 Pydantic 序列化）."""
    return FormResponse.model_validate(form)


def _validate_workflow_binding(
    db: Session,
    workspace_id: int,
    workflow_id: int | None,
) -> None:
    """校验表单绑定的审批流：必须存在于同一工作区（None = 解绑/不启用）."""
    if workflow_id is None:
        return
    wf = db.get(Workflow, workflow_id)
    if wf is None or wf.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="绑定的审批流不存在或不属于当前工作区")


def _validate_or_400(db: Session, table_id: int, field_config: list[dict[str, Any]]) -> None:
    """字段配置校验失败时抛 400 带明细."""
    errors = validate_field_config(db, table_id, field_config)
    if errors:
        raise HTTPException(status_code=400, detail=f"表单字段校验失败: {'; '.join(errors)}")


# ── 表单定义 CRUD ────────────────────────────────────────


@router.get("", response_model=list[FormListItemResponse])
def list_forms(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[FormListItemResponse]:
    """列出工作区内当前用户可读表上的全部表单（不含软删）."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要认证",
            headers={"WWW-Authenticate": "Bearer"},
        )
    forms = (
        db.query(FormDefinition)
        .filter(FormDefinition.workspace_id == workspace_id, FormDefinition.trashed.is_(False))
        .order_by(FormDefinition.order, FormDefinition.id)
        .all()
    )
    items: list[FormListItemResponse] = []
    for form in forms:
        table = db.get(DataTable, form.table_id)
        if table is None:  # pragma: no cover - FK CASCADE 保证存在
            continue
        if not get_table_or_404_guarded(db, table, current_user):
            continue
        items.append(
            FormListItemResponse(
                id=form.id,
                table_id=form.table_id,
                table_name=table.name,
                name=form.name,
                description=form.description,
                use_role=form.use_role,
                edit_role=form.edit_role,
                delete_role=form.delete_role,
                approval_workflow_id=form.approval_workflow_id,
                order=form.order,
                updated_at=form.updated_at,
            )
        )
    return items


def get_table_or_404_guarded(db: Session, table: DataTable, user: User) -> bool:
    """静默版表级 READ 判定（列表过滤用，不抛异常）."""
    from cndb.plugins.tables.services.core.access import check_action

    return check_action(db, table, user, TableAction.READ)


@router.post("", response_model=FormResponse, status_code=status.HTTP_201_CREATED)
def create_form(
    workspace_id: int,
    payload: FormCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FormResponse:
    """创建表单定义（需表级 EDIT_VIEWS 权限）."""
    get_table_or_404(payload.table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_VIEWS)

    existing = (
        db.query(FormDefinition)
        .filter(FormDefinition.table_id == payload.table_id, FormDefinition.name == payload.name)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="同表下表单名已存在")

    _validate_workflow_binding(db, workspace_id, payload.approval_workflow_id)
    field_config = [item.model_dump() for item in payload.field_config]
    _validate_or_400(db, payload.table_id, field_config)

    form = FormDefinition(
        workspace_id=workspace_id,
        table_id=payload.table_id,
        name=payload.name,
        description=payload.description,
        field_config=field_config,
        layout=payload.layout,
        use_role=payload.use_role,
        edit_role=payload.edit_role,
        delete_role=payload.delete_role,
        approval_workflow_id=payload.approval_workflow_id,
        order=payload.order,
    )
    db.add(form)
    db.commit()
    db.refresh(form)
    return _form_to_response(form)


@router.get("/{form_id}", response_model=FormResponse)
def get_form(
    workspace_id: int,
    form_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FormResponse:
    """获取表单定义详情（需表级 READ 权限）."""
    ctx = _load_form_with_table(db, form_id, workspace_id, current_user, TableAction.READ)
    return _form_to_response(ctx.form)


@router.patch("/{form_id}", response_model=FormResponse)
def update_form(
    workspace_id: int,
    form_id: int,
    payload: FormUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FormResponse:
    """更新表单定义（需表级 EDIT_VIEWS 权限）."""
    ctx = _load_form_with_table(db, form_id, workspace_id, current_user, TableAction.EDIT_VIEWS)
    form, table = ctx.form, ctx.table

    update_data = payload.model_dump(exclude_unset=True)
    if "approval_workflow_id" in update_data:
        _validate_workflow_binding(db, workspace_id, update_data["approval_workflow_id"])
    if "field_config" in update_data:
        field_config = [item if isinstance(item, dict) else item.model_dump() for item in update_data["field_config"]]
        _validate_or_400(db, table.id, field_config)
        update_data["field_config"] = field_config
    if "name" in update_data and update_data["name"] != form.name:
        dup = (
            db.query(FormDefinition)
            .filter(
                FormDefinition.table_id == form.table_id,
                FormDefinition.name == update_data["name"],
                FormDefinition.id != form.id,
            )
            .first()
        )
        if dup:
            raise HTTPException(status_code=400, detail="同表下表单名已存在")

    for key, value in update_data.items():
        setattr(form, key, value)
    db.commit()
    db.refresh(form)
    return _form_to_response(form)


@router.delete("/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_form(
    workspace_id: int,
    form_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """软删表单定义（需表级 EDIT_VIEWS 权限）."""
    ctx = _load_form_with_table(db, form_id, workspace_id, current_user, TableAction.EDIT_VIEWS)
    form = ctx.form
    form.trashed = True
    form.trashed_at = dt.datetime.now(dt.UTC)
    db.commit()


# ── 表单运行时（meta + 行操作） ───────────────────────────


class _FormTableCtx:
    """表单 + 所属表加载上下文（表级动作已校验）."""

    __slots__ = ("form", "table")

    def __init__(self, form: FormDefinition, table: DataTable) -> None:
        self.form = form
        self.table = table


def _load_form_with_table(
    db: Session,
    form_id: int,
    workspace_id: int,
    user: User,
    action: TableAction,
) -> _FormTableCtx:
    """加载非软删表单 + 所属表，并完成表级动作校验."""
    form = get_form_or_404(db, form_id, workspace_id)
    table = get_table_or_404(form.table_id, workspace_id, db, user=user, action=action)
    return _FormTableCtx(form, table)


@router.get("/{form_id}/meta", response_model=FormMetaResponse)
def get_form_meta(
    workspace_id: int,
    form_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FormMetaResponse:
    """表单运行时元数据：解析后字段 + 失效清单 + 当前用户操作位."""
    ctx = _load_form_with_table(db, form_id, workspace_id, current_user, TableAction.READ)
    form, table = ctx.form, ctx.table
    ensure_form_access(db, form, current_user, FormAction.USE)

    fields, invalid_fields = resolve_form_fields(db, form, table, current_user)
    can_submit = rec_check(db, table, current_user, TableAction.EDIT_RECORDS) and (
        check_form_access(db, form, current_user, FormAction.USE)
    )
    can_edit = rec_check(db, table, current_user, TableAction.EDIT_RECORDS) and (
        check_form_access(db, form, current_user, FormAction.EDIT)
    )
    can_delete = rec_check(db, table, current_user, TableAction.EDIT_RECORDS) and (
        check_form_access(db, form, current_user, FormAction.DELETE)
    )
    return FormMetaResponse(
        id=form.id,
        table_id=form.table_id,
        table_name=table.name,
        name=form.name,
        description=form.description,
        layout=form.layout or {},
        fields=fields,
        invalid_fields=invalid_fields,
        can_submit=can_submit,
        can_edit=can_edit,
        can_delete=can_delete,
        approval_workflow_id=form.approval_workflow_id,
    )


def rec_check(db: Session, table: DataTable, user: User, action: TableAction) -> bool:
    """静默版表级动作判定（meta 操作位计算用，不抛异常）."""
    from cndb.plugins.tables.services.core.access import check_action

    return check_action(db, table, user, action)


@router.post("/{form_id}/rows", status_code=status.HTTP_201_CREATED)
def create_form_row(
    workspace_id: int,
    form_id: int,
    payload: FormValuesUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """经表单新建行（表级 EDIT_RECORDS + 表单 USE）；绑定审批流时进入审批而非直接落库."""
    ctx = _load_form_with_table(db, form_id, workspace_id, current_user, TableAction.EDIT_RECORDS)
    form, table = ctx.form, ctx.table
    ensure_form_access(db, form, current_user, FormAction.USE)

    values = filter_payload_keys(db, table, current_user, form.field_config or [], payload.values)
    values = apply_form_defaults(form.field_config or [], values)

    # 绑定审批流：值入审批实例快照，不直接落库
    workflow = db.get(Workflow, form.approval_workflow_id) if form.approval_workflow_id else None
    if workflow is not None:
        try:
            instance = submit_for_approval(db, form, table, workflow, values, current_user)
        except ApprovalConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.commit()
        return {
            "approval": {
                "id": instance.id,
                "workflow_id": workflow.id,
                "workflow_name": workflow.name,
                "status": instance.status,
                "current_approver_role": instance.current_approver_role,
            }
        }

    try:
        row = rec.create_row(db.get_bind(), table, values, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.exception("表单新建行运行时异常")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=500, detail="创建失败")
    return row


@router.get("/{form_id}/rows")
def list_form_rows(
    workspace_id: int,
    form_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    """经表单查行列表（表级 READ + 表单 USE；行级过滤生效）."""
    ctx = _load_form_with_table(db, form_id, workspace_id, current_user, TableAction.READ)
    form, table = ctx.form, ctx.table
    ensure_form_access(db, form, current_user, FormAction.USE)

    try:
        rows, total = rec.list_rows(
            db.get_bind(),
            table,
            limit=limit,
            offset=offset,
            db=db,
            user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("表单行列表运行时异常")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"rows": rows, "total": total, "form_id": form_id}


@router.patch("/{form_id}/rows/{record_id}")
def update_form_row(
    workspace_id: int,
    form_id: int,
    record_id: int,
    payload: FormValuesUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """经表单编辑行（表级 EDIT_RECORDS + 表单 EDIT；只读字段被剔除）."""
    ctx = _load_form_with_table(db, form_id, workspace_id, current_user, TableAction.EDIT_RECORDS)
    form, table = ctx.form, ctx.table
    ensure_form_access(db, form, current_user, FormAction.EDIT)

    # 编辑态：editable=False 的配置字段视为只读，从载荷剔除
    editable_config = [item for item in (form.field_config or []) if item.get("editable", True)]
    values = filter_payload_keys(db, table, current_user, editable_config, payload.values)
    # field_config 为空时 filter_payload_keys 不做配置过滤，但仍需应用 editable 限制
    if form.field_config:
        editable_names = {str(item.get("field_name")) for item in editable_config if item.get("visible", True)}
        values = {k: v for k, v in values.items() if k in editable_names}
    try:
        row = rec.update_row(db.get_bind(), table, record_id, values, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.exception("表单编辑行运行时异常")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="行不存在")
    return row


@router.delete("/{form_id}/rows/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_form_row(
    workspace_id: int,
    form_id: int,
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """经表单删除行（表级 EDIT_RECORDS + 表单 DELETE；默认软删）."""
    ctx = _load_form_with_table(db, form_id, workspace_id, current_user, TableAction.EDIT_RECORDS)
    form, table = ctx.form, ctx.table
    ensure_form_access(db, form, current_user, FormAction.DELETE)

    ok = rec.trash_row(db.get_bind(), table, record_id, db=db)
    if not ok:
        raise HTTPException(status_code=404, detail="行不存在")


__all__ = ["router"]
