"""行级权限规则管理路由（ADR 0004 §5，P2）.

- **敏感信息**：规则配置属敏感信息，所有端点（含只读列表 / subjects / preview）
  一律要求表 ``EDIT_SCHEMA``（与现有 ``/permissions`` PUT 同级），普通成员不应读到规则明文；
- **审计**：规则增删改写 ``tables_auditlog``（``row_rule_create/update/delete``，ADR §7-8）
  并同步统一事件 ``row_rule.*``；
- **缓存**：变更后失效所在工作区的**表列表 + 记录列表**缓存（ADR §7-7），避免收紧后旧缓存短暂泄漏；
- **校验**：授权约束见 ``row_access.assert_row_rule_valid``（ADR §6）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import AuditLog, DataTable, RowPermission, RowSubject
from cndb.plugins.tables.schemas import (
    RowRuleCreate,
    RowRulePreviewRequest,
    RowRulePreviewResponse,
    RowRuleResponse,
    RowRuleSubjectOut,
    RowRuleUpdate,
)
from cndb.plugins.tables.services.core.access import (
    TableAction,
    apply_field_hiding,
    get_hidden_field_names,
    get_table_or_404,
)
from cndb.plugins.tables.services.core.audit import (
    ACTION_ROW_RULE_CREATE,
    ACTION_ROW_RULE_DELETE,
    ACTION_ROW_RULE_UPDATE,
)
from cndb.plugins.tables.services.core.records import _get_sa_table
from cndb.plugins.tables.services.core.row_access import (
    MEMBER_ROLE_LABELS,
    assert_row_rule_valid,
    row_read_scope_where,
    row_rule_subject_label,
)
from cndb.plugins.tables.services.core.view_access import shareable_members

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/row-permissions", tags=["row-permissions"])

#: 预览样例行数上限
_PREVIEW_SAMPLE_LIMIT = 5


# ── 审计 + 缓存失效 ───────────────────────────────────


def _invalidate_row_caches(workspace_id: int) -> None:
    """规则变更后失效表列表 + 记录列表缓存（ADR §7-7）."""
    from cndb.core.cache import cache_key, list_cache

    list_cache.clear(cache_key("tables", workspace_id))
    list_cache.clear(cache_key("records", workspace_id))


def _after_rule_change(
    db: Session,
    table: DataTable,
    action: str,
    actor_id: int,
    detail: dict[str, Any],
) -> None:
    """写审计（随主事务提交）→ 写统一事件（触发事件驱动失效）→ 显式清缓存."""
    from cndb.core.events import TARGET_TABLE, record_event

    db.add(AuditLog(table_id=table.id, action=action, actor_id=actor_id, detail=detail))
    db.commit()
    record_event(
        db,
        f"row_rule.{action.removeprefix('row_rule_')}",
        summary=f"行级权限规则变更（表 {table.id}）",
        target_type=TARGET_TABLE,
        target_id=table.id,
        workspace_id=table.workspace_id,
        actor_id=actor_id,
        detail=detail,
    )
    _invalidate_row_caches(int(table.workspace_id))


# ── 序列化 ────────────────────────────────────────────


def _get_rule_or_404(db: Session, table_id: int, rule_id: int) -> RowPermission:
    rule = db.query(RowPermission).filter(RowPermission.id == rule_id, RowPermission.table_id == table_id).first()
    if rule is None:
        raise HTTPException(status_code=404, detail="行级权限规则不存在")
    return rule


def _to_response(db: Session, rule: RowPermission) -> RowRuleResponse:
    data = RowRuleResponse.model_validate(rule)
    data.subject_name = row_rule_subject_label(db, rule)
    return data


# ── CRUD ──────────────────────────────────────────────


@router.get("", response_model=list[RowRuleResponse])
def list_row_rules(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[RowRuleResponse]:
    """列出该表的行级权限规则（需表 ``EDIT_SCHEMA``）."""
    get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)
    rules = db.query(RowPermission).filter(RowPermission.table_id == table_id).order_by(RowPermission.id).all()
    return [_to_response(db, r) for r in rules]


@router.post("", response_model=RowRuleResponse, status_code=status.HTTP_201_CREATED)
def create_row_rule(
    workspace_id: int,
    table_id: int,
    payload: RowRuleCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RowRuleResponse:
    """创建一条行级权限规则（需表 ``EDIT_SCHEMA``，每主体每动作至多一条，ADR D6）."""
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)
    assert_row_rule_valid(
        db,
        dt,
        current_user,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        action=payload.action,
    )

    duplicate = (
        db.query(RowPermission)
        .filter(
            RowPermission.table_id == table_id,
            RowPermission.subject_type == payload.subject_type,
            RowPermission.subject_id == payload.subject_id,
            RowPermission.action == payload.action,
        )
        .first()
    )
    if duplicate is not None:
        raise HTTPException(status_code=400, detail="该主体该动作的规则已存在，请改用 PATCH 修改")

    rule = RowPermission(
        table_id=table_id,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        action=payload.action,
        filters=payload.filters,
        filter_type=payload.filter_type,
        granted_by_id=current_user.id,
    )
    db.add(rule)
    db.flush()
    rule_id = int(rule.id)
    _after_rule_change(
        db,
        dt,
        ACTION_ROW_RULE_CREATE,
        current_user.id,
        {
            "rule_id": rule_id,
            "subject_type": payload.subject_type,
            "subject_id": payload.subject_id,
            "action": payload.action,
            "filters": payload.filters,
            "filter_type": payload.filter_type,
        },
    )
    db.refresh(rule)
    return _to_response(db, rule)


@router.patch("/{rule_id}", response_model=RowRuleResponse)
def update_row_rule(
    workspace_id: int,
    table_id: int,
    rule_id: int,
    payload: RowRuleUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RowRuleResponse:
    """修改规则的条件（主体 / 动作不可改，需表 ``EDIT_SCHEMA``）."""
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)
    rule = _get_rule_or_404(db, table_id, rule_id)

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(rule, key, value)
    rule.granted_by_id = current_user.id
    _after_rule_change(
        db,
        dt,
        ACTION_ROW_RULE_UPDATE,
        current_user.id,
        {
            "rule_id": int(rule.id),
            "subject_type": rule.subject_type,
            "subject_id": rule.subject_id,
            "action": rule.action,
            "filters": rule.filters,
            "filter_type": rule.filter_type,
        },
    )
    db.refresh(rule)
    return _to_response(db, rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_row_rule(
    workspace_id: int,
    table_id: int,
    rule_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除一条行级权限规则（需表 ``EDIT_SCHEMA``）."""
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)
    rule = _get_rule_or_404(db, table_id, rule_id)

    detail = {
        "rule_id": int(rule.id),
        "subject_type": rule.subject_type,
        "subject_id": rule.subject_id,
        "action": rule.action,
    }
    db.delete(rule)
    db.flush()
    _after_rule_change(db, dt, ACTION_ROW_RULE_DELETE, current_user.id, detail)


# ── 可授权主体 / 命中预览 ─────────────────────────────


@router.get("/subjects", response_model=list[RowRuleSubjectOut])
def list_row_rule_subjects(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[RowRuleSubjectOut]:
    """可授权主体列表（选择器数据源，需表 ``EDIT_SCHEMA``）.

    = 固定成员档 ``read`` / ``write`` + 本工作区成员 ∧ 对该表有 ``READ``（排除操作者本人）。
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)
    out: list[RowRuleSubjectOut] = [
        RowRuleSubjectOut(subject_type=RowSubject.MEMBER_ROLE, subject_id="read", name=MEMBER_ROLE_LABELS["read"]),
        RowRuleSubjectOut(subject_type=RowSubject.MEMBER_ROLE, subject_id="write", name=MEMBER_ROLE_LABELS["write"]),
    ]
    for member in shareable_members(db, dt, current_user):
        out.append(
            RowRuleSubjectOut(
                subject_type=RowSubject.USER,
                subject_id=str(member["user_id"]),
                name=member["nickname"] or member["username"],
            )
        )
    return out


@router.post("/preview", response_model=RowRulePreviewResponse)
def preview_row_rule(
    workspace_id: int,
    table_id: int,
    payload: RowRulePreviewRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RowRulePreviewResponse:
    """规则命中行 dry-run 预览（需表 ``EDIT_SCHEMA``）.

    返回命中行数 + 样例若干（均与调用者的读范围求交，避免越界取数）。
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_SCHEMA)
    sa_table = _get_sa_table(db.get_bind(), dt)

    from cndb.plugins.tables.services.core.query import compile_filters

    parts: list[Any] = []
    read_scope = row_read_scope_where(db, dt, sa_table, current_user)
    if read_scope is not None:
        parts.append(read_scope)
    if payload.filters:
        try:
            compiled = compile_filters(dt, sa_table, payload.filters, payload.filter_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if compiled is not None:
            parts.append(compiled)

    where = and_(sa_table.c._trashed.is_(False), *parts)
    engine: Any = db.get_bind()
    with engine.connect() as conn:
        matched = int(conn.execute(select(func.count()).select_from(sa_table).where(where)).scalar() or 0)
        rows = conn.execute(select(sa_table).where(where).limit(_PREVIEW_SAMPLE_LIMIT)).mappings().all()

    colname_to_field = {f.db_column_name: f.name for f in dt.active_fields()}
    hidden = get_hidden_field_names(db, dt, current_user)
    sample: list[dict[str, Any]] = []
    for row in rows:
        values = {colname_to_field[k]: v for k, v in dict(row).items() if k in colname_to_field}
        apply_field_hiding(values, hidden)
        sample.append(values)
    return RowRulePreviewResponse(matched=matched, sample=sample)


__all__ = ["router"]
