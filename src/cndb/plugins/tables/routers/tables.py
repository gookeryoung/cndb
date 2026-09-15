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
from cndb.plugins.tables.models import DataField, DataTable, DataView, TableMember
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


def _fill_table_stats(
    db: Session,
    table: DataTable,
    current_user: User | None = None,
    owner_map: dict[int, User] | None = None,
    member_count_map: dict[int, int] | None = None,
    my_member_map: dict[int, TableMember] | None = None,
) -> TableResponse:
    """为单张表填充统计 + 数据资产目录字段."""
    field_count = (
        db.query(func.count(DataField.id))
        .filter(DataField.table_id == table.id, DataField.trashed == False)  # noqa: E712
        .scalar()
        or 0
    )
    view_count = db.query(func.count(DataView.id)).filter(DataView.table_id == table.id).scalar() or 0
    # 物理表 COUNT —— 表结构异常时用 None
    record_count: int | None = None
    try:
        result = db.execute(text(f"SELECT COUNT(*) FROM {table.db_table_name}"))
        record_count = result.scalar() or 0
    except Exception:
        record_count = None

    base = TableResponse.model_validate(table, from_attributes=True)
    base.field_count = int(field_count)
    base.record_count = int(record_count) if record_count is not None else None
    base.view_count = int(view_count)

    # 数据资产目录字段（list_tables 会批量预查，单表 get_table 时回退懒查）
    if owner_map is not None:
        owner = owner_map.get(table.owner_id) if table.owner_id else None
    else:
        owner = db.get(User, table.owner_id) if table.owner_id else None
    if owner is not None:
        base.owner_id = owner.id
        base.owner_username = owner.username

    if member_count_map is not None:
        base.member_count = member_count_map.get(table.id, 0)
    else:
        base.member_count = db.query(func.count(TableMember.id)).filter(TableMember.table_id == table.id).scalar() or 0

    # my_access
    if current_user is not None:
        if table.owner_id == current_user.id:
            base.my_access = "owner"
        elif my_member_map is not None and table.id in my_member_map:
            base.my_access = my_member_map[table.id].role  # "read" | "write"
        else:
            base.my_access = "none"
    else:
        base.my_access = None

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
    dt = DataTable(
        workspace_id=workspace_id,
        owner_id=current_user.id,
        name=payload.name,
        description=payload.description,
    )
    dt.ensure_db_name()
    db.add(dt)
    db.commit()
    db.refresh(dt)

    # 执行物理建表
    ddl_create(db.get_bind(), dt)

    # 可选：从其他表引入字段 schema（建表即带字段）
    if payload.import_from_table_id is not None:
        _import_fields_on_create(
            db,
            dt,
            source_table_id=payload.import_from_table_id,
            field_ids=payload.import_field_ids,
            field_names=payload.import_field_names,
            import_all_fields=payload.import_all_fields,
        )

    return dt


def _import_fields_on_create(
    db: Session,
    dst: DataTable,
    *,
    source_table_id: int,
    field_ids: list[int] | None = None,
    field_names: list[str] | None = None,
    import_all_fields: bool = False,
) -> None:
    """create_table 建表后立即从其他表引入字段.

    失败时自动回滚（删除新创建的 DataTable + DROP 物理表），
    不让一个半初始化的表残留在数据库里。
    """
    from cndb.plugins.tables import field_ops as _fo
    from cndb.plugins.tables.ddl import drop_table as ddl_drop

    src = db.get(DataTable, source_table_id)
    if src is None or src.trashed:
        # 源表不存在则静默跳过（不影响建表本身）
        return

    try:
        if import_all_fields:
            _created, _ = _fo.clone_fields_between_tables(db.get_bind(), db, src, dst)
        elif field_ids:
            _created, _ = _fo.clone_fields_between_tables(db.get_bind(), db, src, dst, field_ids=field_ids)
        elif field_names:
            _created, _ = _fo.clone_fields_between_tables(db.get_bind(), db, src, dst, field_names=field_names)
        else:
            return  # 无指定则不导入
    except Exception:
        # 回滚：删除 DataTable metadata + DROP 物理表
        db.delete(dst)
        db.commit()
        ddl_drop(db.get_bind(), dst.db_table_name)
        raise


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

    # 批量预查 owner / member_count / my_member，避免 N+1
    table_ids = [t.id for t in tables]
    owner_ids = {t.owner_id for t in tables if t.owner_id}
    owner_map: dict[int, User] = {}
    if owner_ids:
        for u in db.query(User).filter(User.id.in_(owner_ids)).all():
            owner_map[u.id] = u

    member_count_map: dict[int, int] = {}
    if table_ids:
        rows = (
            db.query(TableMember.table_id, func.count(TableMember.id))
            .filter(TableMember.table_id.in_(table_ids))
            .group_by(TableMember.table_id)
            .all()
        )
        for tid, cnt in rows:
            member_count_map[int(tid)] = int(cnt)

    my_member_map: dict[int, TableMember] = {}
    if table_ids:
        my_members = db.query(TableMember).filter(
            TableMember.table_id.in_(table_ids), TableMember.user_id == current_user.id
        )
        for m in my_members:
            my_member_map[m.table_id] = m

    return [
        _fill_table_stats(
            db,
            t,
            current_user=current_user,
            owner_map=owner_map,
            member_count_map=member_count_map,
            my_member_map=my_member_map,
        )
        for t in tables
    ]


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
    base = _fill_table_stats(db, dt, current_user=current_user)

    # 2) 字段（复用 relationship，已自动加载）
    def _field_sort_key(f: DataField) -> tuple[int, int]:
        return (f.order, f.id)

    active_fields = sorted([f for f in dt.fields if not f.trashed], key=_field_sort_key)

    # 3) 视图精简摘要
    def _view_sort_key(v: DataView) -> tuple[int, int]:
        return (v.order, v.id)

    views = sorted(dt.views, key=_view_sort_key)
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
    mode: str = "structure",
    view_id: int | None = None,
    include_data: bool = False,
) -> DataTable:
    """复制表 — 支持三种模式.

    - mode=structure（默认）: 仅复制表结构和字段，不携带任何数据
    - mode=all: 复制表结构 + 全部数据（默认 10000 行上限，可扩展）
    - mode=view: 复制表结构 + 指定视图过滤后的数据（需传 view_id）

    向后兼容：旧客户端传 include_data=true 等价于 mode=all.
    """
    from cndb.plugins.tables import field_ops as _fo

    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    src = _get_table_or_404(table_id, workspace_id, db)

    # 兼容旧参数：include_data=true 等价于 mode=all
    effective_mode = mode
    if include_data and mode == "structure":
        effective_mode = "all"

    # 校验 mode
    valid_modes = {"structure", "all", "view"}
    if effective_mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"无效的 mode: {mode}，可选值: {sorted(valid_modes)}")

    # mode=view 时必须有 view_id，且 view 属于该表
    view_filters: list[dict[str, Any]] | None = None
    view_filter_logic: str = "AND"
    if effective_mode == "view":
        if view_id is None:
            raise HTTPException(status_code=400, detail="mode=view 时必须提供 view_id")
        dv = db.query(DataView).filter(DataView.id == view_id, DataView.table_id == src.id).first()
        if dv is None:
            raise HTTPException(status_code=404, detail=f"视图 {view_id} 不存在或不属于该表")
        view_filters = dv.filters or None
        view_filter_logic = dv.filter_type or "AND"

    # 创建新表元数据 + 物理表（空表，随后批量加列）
    dst = DataTable(
        workspace_id=src.workspace_id,
        owner_id=current_user.id,
        name=f"{src.name} (副本)",
        description=src.description,
    )
    dst.ensure_db_name()
    db.add(dst)
    db.commit()
    db.refresh(dst)
    ddl_create(db.get_bind(), dst)

    # 克隆全部非回收字段
    src_active = src.active_fields()
    try:
        _created_fields, _skipped = _fo.clone_fields_between_tables(
            db.get_bind(), db, src, dst, field_ids=[f.id for f in src_active]
        )
    except Exception as exc:
        # 回滚：删除 DataTable metadata + DROP 物理表
        from cndb.plugins.tables.ddl import drop_table as _ddl_drop

        db.delete(dst)
        db.commit()
        _ddl_drop(db.get_bind(), dst.db_table_name)
        raise HTTPException(status_code=500, detail=f"字段克隆失败: {exc}") from exc

    # 建立字段映射（用于复制数据时按 src 字段名写入 dst）
    db.refresh(dst)
    dst_field_by_name = {f.name: f for f in dst.active_fields()}

    # 复制数据（all 或 view）
    if effective_mode in ("all", "view"):
        from cndb.plugins.tables import records as rec

        rows, _ = rec.list_rows(
            db.get_bind(),
            src,
            filters=view_filters,
            filter_logic=view_filter_logic,
            include_trashed=False,
            limit=10000,
            db=db,
        )
        if rows:
            for r in rows:
                values: dict[str, object] = {}
                for src_f in src_active:
                    if src_f.name not in r:
                        continue
                    # src.name == dst.name（同名字段克隆），直接用 dst.name 作 key
                    if src_f.name in dst_field_by_name:
                        values[src_f.name] = r[src_f.name]
                if values:
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
    from cndb.plugins.tables.models import TableMember
    from cndb.plugins.workspaces.models import WorkspaceMember

    _check_table_permission(workspace_id, current_user, db, WorkspaceRole.EDITOR)
    _check_table_permission(target_workspace_id, current_user, db, WorkspaceRole.EDITOR)

    dt = _get_table_or_404(table_id, workspace_id, db)
    dt.workspace_id = target_workspace_id

    # 跨工作区移动后清空表级成员列表（成员授权不跨工作区）
    db.query(TableMember).filter(TableMember.table_id == dt.id).delete(synchronize_session=False)

    # 如果原 owner 不是目标工作区成员，则清空 owner_id
    if dt.owner_id is not None:
        is_target_member = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == target_workspace_id,
                WorkspaceMember.user_id == dt.owner_id,
            )
            .first()
            is not None
        )
        if not is_target_member:
            dt.owner_id = None

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
