"""数据表元数据路由."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.access import TableAction, check_action
from cndb.plugins.tables.ddl import create_table as ddl_create
from cndb.plugins.tables.models import DataField, DataTable, DataView
from cndb.plugins.tables.schemas import (
    OwnerBrief,
    TableCreate,
    TableDetailResponse,
    TableResponse,
    TableUpdate,
    ViewBrief,
    WorkspaceBrief,
)
from cndb.plugins.workspaces.models import (
    ROLE_RANK,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from cndb.plugins.workspaces.permissions import get_member_role

router = APIRouter(prefix="/{workspace_id}/tables", tags=["tables"])

# TableAction 名称 → 前端展示字符串
_ACTION_LABEL: dict[TableAction, str] = {
    TableAction.READ: "read",
    TableAction.EDIT_RECORDS: "edit_records",
    TableAction.EDIT_VIEWS: "edit_views",
    TableAction.EDIT_SCHEMA: "edit_schema",
    TableAction.COMMENT: "comment",
}


def _fill_table_stats(db: Session, table: DataTable) -> TableResponse:
    """为单张表填充 field_count / record_count / view_count 并返回 TableResponse.

    行数通过物理表 COUNT 查询，字段/视图直接查元数据表。
    """
    field_count = (
        db.query(func.count(DataField.id))
        .filter(DataField.table_id == table.id, DataField.trashed == False)  # noqa: E712
        .scalar()
        or 0
    )
    view_count = db.query(func.count(DataView.id)).filter(DataView.table_id == table.id).scalar() or 0
    # 物理表 COUNT —— 表结构异常（比如 DDL 没建出来）时用 None
    record_count: int | None = None
    try:
        result = db.execute(text(f"SELECT COUNT(*) FROM {table.db_table_name}"))
        record_count = result.scalar() or 0
    except Exception:
        record_count = None

    # 先把 ORM 对象转成 TableResponse 基本字段，再注入统计
    base = TableResponse.model_validate(table, from_attributes=True)
    base.field_count = int(field_count)
    base.record_count = int(record_count) if record_count is not None else None
    base.view_count = int(view_count)
    return base


def _check_table_permission(workspace_id: int, user: User, db: Session, min_role: WorkspaceRole) -> None:
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    role = get_member_role(user, ws, db)
    if role is None or ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise HTTPException(status_code=403, detail="权限不足")


def _get_table_or_404(table_id: int, workspace_id: int, db: Session) -> DataTable:
    dt = db.query(DataTable).filter(DataTable.id == table_id, DataTable.workspace_id == workspace_id).first()
    if dt is None:
        raise HTTPException(status_code=404, detail="表不存在")
    return dt


@router.post("", response_model=TableResponse, status_code=status.HTTP_201_CREATED)
def create_table(
    workspace_id: int,
    payload: TableCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataTable:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)
    dt = DataTable(workspace_id=workspace_id, name=payload.name, description=payload.description)
    dt.ensure_db_name()
    db.add(dt)
    db.commit()
    db.refresh(dt)

    # 执行物理建表
    ddl_create(db.get_bind(), dt)
    return dt


@router.get("", response_model=list[TableResponse])
def list_tables(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_trashed: bool = False,
) -> list[TableResponse]:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    query = db.query(DataTable).filter(DataTable.workspace_id == workspace_id)
    if not include_trashed:
        query = query.filter(DataTable.trashed == False)  # noqa: E712
    tables = query.order_by(DataTable.order, DataTable.id).all()
    return [_fill_table_stats(db, t) for t in tables]


@router.post("/reorder", response_model=list[TableResponse])
def reorder_tables(
    workspace_id: int,
    table_ids: list[int],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DataTable]:
    """批量调整表顺序（按传入顺序赋值 order 字段）."""
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.ADMIN)

    tables = (
        db.query(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.id.in_(table_ids),
        )
        .all()
    )

    table_map = {t.id: t for t in tables}
    for idx, tid in enumerate(table_ids):
        if tid in table_map:
            table_map[tid].order = idx

    db.commit()
    return (
        db.query(DataTable).filter(DataTable.workspace_id == workspace_id).order_by(DataTable.order, DataTable.id).all()
    )


@router.get("/graph")
def get_tables_graph(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """返回工作区内所有表的 link 字段关系图."""
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)

    tables = (
        db.query(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed == False,  # noqa: E712
        )
        .all()
    )

    edges: list[dict[str, Any]] = []
    for t in tables:
        for f in t.fields:
            if f.trashed or f.field_type != "link":
                continue
            target_tid = f.config.get("target_table_id") if f.config else None
            if target_tid is not None:
                edges.append(
                    {
                        "from_table": t.id,
                        "from_table_name": t.name,
                        "from_field": f.name,
                        "to_table": target_tid,
                    }
                )

    nodes: list[dict[str, Any]] = [{"id": t.id, "name": t.name, "db_table_name": t.db_table_name} for t in tables]

    return {"nodes": nodes, "edges": edges}


@router.get("/{table_id}", response_model=TableDetailResponse)
def get_table(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TableDetailResponse:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    dt = _get_table_or_404(table_id, workspace_id, db)

    # 1) 统计 + 基础 TableResponse 字段
    base = _fill_table_stats(db, dt)

    # 2) 字段（复用 relationship，已自动加载）
    active_fields = sorted([f for f in dt.fields if not f.trashed], key=lambda f: (f.order, f.id))

    # 3) 视图精简摘要
    views = sorted(dt.views, key=lambda v: (v.order, v.id))
    view_briefs = [ViewBrief.model_validate(v, from_attributes=True) for v in views]

    # 4) 工作区 + 当前用户角色 + owner（复用 _check_table_permission 已查过的 ws）
    ws = db.get(Workspace, workspace_id)
    member_role = get_member_role(current_user, ws, db) if ws else None
    actions: list[str] = []
    for action in TableAction:
        if check_action(db, dt, current_user, action, member_role=member_role):
            actions.append(_ACTION_LABEL[action])

    # 5) 所属工作区摘要（让前端不用再调 workspaceApi.get）
    ws_brief: WorkspaceBrief | None = None
    owner: OwnerBrief | None = None
    if ws is not None:
        ws_brief = WorkspaceBrief(
            id=ws.id,
            name=ws.name,
            visibility=ws.visibility.value if hasattr(ws.visibility, "value") else str(ws.visibility),
            allow_edit=ws.allow_edit,
            current_user_role=member_role.value if member_role else None,
        )
        # owner — 查 OWNER 角色的 WorkspaceMember
        owner_member = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.role == WorkspaceRole.OWNER,
            )
            .first()
        )
        if owner_member and owner_member.user:
            owner = OwnerBrief(
                id=owner_member.user.id,
                username=owner_member.user.username,
                nickname=owner_member.user.nickname,
            )

    return TableDetailResponse(
        **base.model_dump(),
        fields=active_fields,
        views=view_briefs,
        current_user_actions=actions,
        owner=owner,
        workspace=ws_brief,
    )


@router.patch("/{table_id}", response_model=TableResponse)
def update_table(
    workspace_id: int,
    table_id: int,
    payload: TableUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataTable:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    dt = _get_table_or_404(table_id, workspace_id, db)
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(dt, key, value)
    db.commit()
    db.refresh(dt)
    return dt


@router.delete("/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_table(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.OWNER)
    dt = _get_table_or_404(table_id, workspace_id, db)
    dt.trashed = True
    db.commit()


# ── 表复制 ─────────────────────────────────────────────


@router.post("/{table_id}/copy", response_model=TableDetailResponse, status_code=status.HTTP_201_CREATED)
def copy_table(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_data: bool = False,
) -> DataTable:
    """复制表结构（可选含数据）."""
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    src = _get_table_or_404(table_id, workspace_id, db)

    # 创建新表元数据
    dst = DataTable(workspace_id=src.workspace_id, name=f"{src.name} (副本)", description=src.description)
    dst.ensure_db_name()
    db.add(dst)
    db.commit()
    db.refresh(dst)

    # 复制字段
    field_map: dict[int, DataField] = {}
    for src_field in src.fields:
        if src_field.trashed:
            continue
        f = DataField(
            table_id=dst.id,
            name=src_field.name,
            field_type=src_field.field_type,
            config=src_field.config,
            required=src_field.required,
            is_unique=src_field.is_unique,
            default_value=src_field.default_value,
            order=src_field.order,
        )
        f.ensure_db_name()
        db.add(f)
        db.flush()  # 获取 id
        field_map[src_field.id] = f

    db.commit()
    db.refresh(dst)

    # 物理建表
    ddl_create(db.get_bind(), dst)

    # 可选：复制数据
    if include_data:
        from cndb.plugins.tables import records as rec

        rows, _ = rec.list_rows(db.get_bind(), src, include_trashed=False, limit=10000, db=db)
        if rows:
            # 用新表的 field_name 作为 key 重建 values
            for r in rows:
                values: dict[str, object] = {}
                for src_f in src.fields:
                    if src_f.trashed or src_f.name not in r:
                        continue
                    values[field_map[src_f.id].name] = r[src_f.name]
                rec.create_row(db.get_bind(), dst, values, db=db)

    return dst


# ── 表移动 ─────────────────────────────────────────────


@router.post("/{table_id}/move", response_model=TableResponse)
def move_table(
    workspace_id: int,
    table_id: int,
    target_workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataTable:
    """跨工作区移动表（需同时是源和目标工作区的成员）."""
    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    _check_table_permission(target_workspace_id, current_user, db, WorkspaceRole.EDITOR)

    dt = _get_table_or_404(table_id, workspace_id, db)
    dt.workspace_id = target_workspace_id
    db.commit()
    db.refresh(dt)
    return dt


# ── 表排序 ─────────────────────────────────────────────


# ── 表关系图 ────────────────────────────────────────────


# ── 行引用（反向 link 查询） ─────────────────────────────


@router.get("/{table_id}/records/{record_id}/references")
def get_record_references(
    workspace_id: int,
    table_id: int,
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """查询哪些表的哪些行通过 link 字段引用了当前行（跨工作区反查）."""
    from cndb.plugins.tables.links import find_back_references

    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.VIEWER)
    dt = _get_table_or_404(table_id, workspace_id, db)

    refs = find_back_references(db, cast("Engine", db.get_bind()), dt, record_id)
    return {
        "references": [
            {
                "table_id": item["table_id"],
                "table_name": item["table_name"],
                "record_id": item["row_id"],
                "link_field": item["field_name"],
                "summary": item["summary"],
            }
            for item in refs
        ]
    }
