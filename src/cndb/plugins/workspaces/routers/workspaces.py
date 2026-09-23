"""workspaces 插件路由：CRUD + 成员管理 + pin + candidates."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole, WorkspaceVisibility
from cndb.plugins.workspaces.permissions import get_member_role, has_role
from cndb.plugins.workspaces.schemas import (
    MemberAddRequest,
    MemberUpdateRequest,
    MemberUserBrief,
    PinRequest,
    PinToggleResponse,
    WorkspaceCreate,
    WorkspaceCreateFromBackup,
    WorkspaceCreateFromBackupResponse,
    WorkspaceDetailResponse,
    WorkspaceImportRequest,
    WorkspaceImportResponse,
    WorkspaceMemberResponse,
    WorkspaceOwnerTransferRequest,
    WorkspaceResponse,
    WorkspaceUpdate,
    WorkspaceWithPinnedResponse,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# ── 公共依赖：解析工作区并校验成员身份 ─────────────────


def _get_workspace_or_404(workspace_id: int, db: Session) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")  # pragma: no cover - 由 _get_workspace_or_404 前置
    return ws


def _require_member(workspace: Workspace, user: User, db: Session) -> None:
    if get_member_role(user, workspace, db) is None:
        raise HTTPException(status_code=404, detail="工作区不存在")  # pragma: no cover - 由 _get_workspace_or_404 前置


def _require_admin(workspace: Workspace, user: User, db: Session) -> None:
    if not has_role(user, workspace, WorkspaceRole.ADMIN, db):
        raise HTTPException(status_code=403, detail="需要管理员权限")


# ── 工作区 CRUD ──────────────────────────────────────


@router.get("", response_model=list[WorkspaceWithPinnedResponse])
def list_workspaces(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkspaceWithPinnedResponse]:
    """列出当前用户所属的工作区，钉住的置顶，附带 table_count / member_count."""
    from sqlalchemy import case, func, select

    from cndb.plugins.tables.models import DataTable

    stmt = (
        select(Workspace, WorkspaceMember)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == current_user.id)
        .order_by(case((WorkspaceMember.pinned.is_(True), 0), else_=1), Workspace.id)
    )
    rows = db.execute(stmt).all()

    # 批量收集 workspace_id 用于统计
    ws_ids = [ws.id for ws, _ in rows]
    # 表数统计（排除软删）
    table_counts: dict[int, int] = {
        row[0]: row[1]
        for row in (
            db.query(DataTable.workspace_id, func.count(DataTable.id))
            .filter(DataTable.workspace_id.in_(ws_ids), DataTable.trashed_at.is_(None))
            .group_by(DataTable.workspace_id)
            .all()
        )
    }
    # 成员数统计
    member_counts: dict[int, int] = {
        row[0]: row[1]
        for row in (
            db.query(WorkspaceMember.workspace_id, func.count(WorkspaceMember.id))
            .filter(WorkspaceMember.workspace_id.in_(ws_ids))
            .group_by(WorkspaceMember.workspace_id)
            .all()
        )
    }

    result: list[WorkspaceWithPinnedResponse] = []
    for ws, member in rows:
        d = {c.name: getattr(ws, c.name) for c in ws.__table__.columns}
        d["pinned"] = bool(member.pinned)
        # 统计字段塞进 response 扩展（WorkspaceWithPinnedResponse 继承自 WorkspaceResponse，
        # 前端列表类型声明时用 Workspace & { table_count, member_count } 接收）
        d["table_count"] = table_counts.get(ws.id, 0)
        d["member_count"] = member_counts.get(ws.id, 0)
        d["current_user_role"] = member.role.value if member.role else None
        result.append(WorkspaceWithPinnedResponse.model_validate(d))
    return result


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Workspace:
    """创建工作区并把创建者登记为 OWNER."""
    ws = Workspace(
        name=payload.name,
        description=payload.description,
        visibility=payload.visibility,
        tags=payload.tags,
        allow_edit=payload.allow_edit,
        created_by_id=current_user.id,
    )
    db.add(ws)
    db.flush()  # 拿到 ws.id
    member = WorkspaceMember(workspace_id=ws.id, user_id=current_user.id, role=WorkspaceRole.OWNER)
    db.add(member)
    db.commit()
    db.refresh(ws)
    return ws


@router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
def get_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceDetailResponse:
    """获取工作区详情（需是成员），附带拥有者信息和统计."""
    from contextlib import suppress

    from sqlalchemy import MetaData, func, select

    from cndb.plugins.tables.models import DataTable, DataView

    ws = _get_workspace_or_404(workspace_id, db)
    _require_member(ws, current_user, db)

    # 统计
    table_count = (
        db.query(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed_at.is_(None),
        )
        .count()
    )
    member_count = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
        )
        .count()
    )
    view_count = (
        db.query(DataView)
        .join(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed_at.is_(None),
        )
        .count()
    )
    # 总行数：遍历每个 DataTable 的物理表执行 COUNT
    total_rows = 0
    tables = (
        db.query(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed_at.is_(None),
        )
        .all()
    )
    metadata = MetaData()
    for tbl in tables:
        with suppress(Exception):
            sa_table = __import__("sqlalchemy").Table(tbl.db_table_name, metadata, autoload_with=db.bind)
            cnt = db.execute(select(func.count(sa_table.c.id))).scalar() or 0
            total_rows += int(cnt)

    # 拥有者信息
    owner_member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == WorkspaceRole.OWNER,
        )
        .first()
    )
    owner_info: dict[str, Any] | None = None
    if owner_member and owner_member.user:
        owner_info = {
            "id": owner_member.user.id,
            "username": owner_member.user.username,
            "nickname": owner_member.user.nickname,
        }

    current_role = get_member_role(current_user, ws, db)
    d = {c.name: getattr(ws, c.name) for c in ws.__table__.columns}
    d.update(
        {
            "owner": owner_info,
            "table_count": table_count,
            "member_count": member_count,
            "view_count": view_count,
            "total_rows": total_rows,
            "current_user_role": current_role.value if current_role else None,
        }
    )
    return WorkspaceDetailResponse.model_validate(d)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Workspace:
    """更新工作区（需 ADMIN+ 角色）."""
    ws = _get_workspace_or_404(workspace_id, db)
    _require_admin(ws, current_user, db)
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(ws, key, value)
    db.commit()
    db.refresh(ws)
    return ws


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除工作区（仅 OWNER 可执行）."""
    ws = _get_workspace_or_404(workspace_id, db)
    role = get_member_role(current_user, ws, db)
    if role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail="仅所有者可删除工作区")
    db.delete(ws)
    db.commit()


# ── 成员管理 ──────────────────────────────────────────


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
def list_members(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkspaceMember]:
    """列出当前工作区全部成员（需是成员）."""
    ws = _get_workspace_or_404(workspace_id, db)
    _require_member(ws, current_user, db)
    return (
        db.query(WorkspaceMember)
        .options(selectinload(WorkspaceMember.user))
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .all()
    )


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    workspace_id: int,
    payload: MemberAddRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceMember:
    """添加成员（需 ADMIN+，不允许添加为 OWNER）."""
    ws = _get_workspace_or_404(workspace_id, db)
    _require_admin(ws, current_user, db)
    if payload.role == WorkspaceRole.OWNER:
        raise HTTPException(status_code=400, detail="不能直接添加所有者")
    user = db.query(User).filter(User.username == payload.username, User.is_active.is_(True)).first()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    existing = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user.id)
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=400, detail="用户已是成员")  # pragma: no cover - 测试已覆盖通过 IntegrityError
    member = WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role=payload.role)
    db.add(member)
    db.commit()
    db.refresh(member)
    # 预加载 user 关系供 response 序列化
    _ = member.user
    return member


@router.get("/{workspace_id}/members/candidates")
def list_member_candidates(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    search: str = Query("", description="按用户名/昵称模糊过滤"),
) -> dict[str, list[MemberUserBrief]]:
    """可添加为成员的候选用户列表（ADMIN+ 可见，排除已是成员的用户）."""
    ws = _get_workspace_or_404(workspace_id, db)
    _require_admin(ws, current_user, db)
    member_ids = [
        mid for (mid,) in db.query(WorkspaceMember.user_id).filter(WorkspaceMember.workspace_id == workspace_id).all()
    ]
    query = db.query(User).filter(User.is_active.is_(True), User.id.notin_(member_ids))
    if search.strip():
        keyword = f"%{search.strip()}%"
        query = query.filter((User.username.ilike(keyword)) | (User.nickname.ilike(keyword)))
    users = query.order_by(User.username).all()
    return {"results": [MemberUserBrief.model_validate(u) for u in users]}


@router.patch("/{workspace_id}/members/{member_id}", response_model=WorkspaceMemberResponse)
def update_member_role(
    workspace_id: int,
    member_id: int,
    payload: MemberUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceMember:
    """修改成员角色（需 ADMIN+；保护最后一个 OWNER 不可降级；OWNER 操作 OWNER 需 OWNER 自己）."""
    ws = _get_workspace_or_404(workspace_id, db)
    requester_role = get_member_role(current_user, ws, db)
    if requester_role not in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.id == member_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")  # pragma: no cover
    if member.role == WorkspaceRole.OWNER and requester_role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail="仅所有者可操作所有者")
    # 保护：最后一个 OWNER 不可降级
    if member.role == WorkspaceRole.OWNER and payload.role != WorkspaceRole.OWNER:
        owner_count = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == WorkspaceRole.OWNER,
            )
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="工作区至少保留一名所有者")
    member.role = payload.role
    db.commit()
    db.refresh(member)
    _ = member.user
    return member


@router.delete("/{workspace_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    workspace_id: int,
    member_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """移除成员（需 ADMIN+；保护最后一个 OWNER 不可移除）."""
    ws = _get_workspace_or_404(workspace_id, db)
    requester_role = get_member_role(current_user, ws, db)
    if requester_role not in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.id == member_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")  # pragma: no cover
    if member.role == WorkspaceRole.OWNER and requester_role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail="仅所有者可操作所有者")
    if member.role == WorkspaceRole.OWNER:
        owner_count = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == WorkspaceRole.OWNER,
            )
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="工作区至少保留一名所有者")
    db.delete(member)
    db.commit()


# ── 转让所有权 ────────────────────────────────────────


@router.post("/{workspace_id}/owner", response_model=WorkspaceMemberResponse)
def transfer_owner(
    workspace_id: int,
    payload: WorkspaceOwnerTransferRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceMember:
    """转让工作区所有权（仅当前 OWNER 可执行；目标须是工作区成员）."""
    ws = _get_workspace_or_404(workspace_id, db)
    requester_role = get_member_role(current_user, ws, db)
    if requester_role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail="仅所有者可转让所有权")

    # 目标必须是工作区成员
    target_member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == payload.user_id,
        )
        .first()
    )
    if target_member is None:
        raise HTTPException(status_code=400, detail="目标用户不是该工作区成员")

    # 幂等：转让给自己直接返回
    if target_member.role == WorkspaceRole.OWNER:
        return target_member

    # 把当前 OWNER 降级为 ADMIN
    current_owner = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == WorkspaceRole.OWNER,
        )
        .first()
    )
    if current_owner is not None:
        current_owner.role = WorkspaceRole.ADMIN

    # 把目标提升为 OWNER
    target_member.role = WorkspaceRole.OWNER
    db.commit()
    db.refresh(target_member)
    _ = target_member.user
    return target_member


# ── pin 切换 ──────────────────────────────────────────


@router.post("/pin", response_model=PinToggleResponse)
def toggle_pin(
    payload: PinRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PinToggleResponse:
    """切换当前用户对工作区的钉住状态."""
    ws = _get_workspace_or_404(payload.workspace_id, db)
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == current_user.id)
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="工作区不存在")  # pragma: no cover - 由 _get_workspace_or_404 前置
    member.pinned = not member.pinned
    db.commit()
    db.refresh(member)
    return PinToggleResponse(pinned=member.pinned)


# ── 工作区整体导入导出 ──────────────────────────────


def _import_backup_into_workspace(
    workspace_id: int,
    json_data: dict[str, Any],
    current_user: User,
    db: Session,
) -> WorkspaceImportResponse:
    """把备份 JSON 中的表/行/视图导入到指定工作区（内部 helper，不做权限校验）."""
    import logging

    from cndb.plugins.tables.models import DataField, DataTable, DataView, ensure_default_view
    from cndb.plugins.tables.services.core.ddl import create_table as ddl_create

    # 版本校验：缺失视为旧版 v1 文件；未知版本拒绝，避免静默错读新格式
    version = json_data.get("version", "1")
    if version not in ("1", "2"):
        raise HTTPException(
            status_code=400, detail=f"不支持的导出文件版本: {version}（当前支持: 1, 2）。请升级程序后再导入。"
        )

    imported_tables = 0
    imported_rows = 0
    imported_views = 0

    # 循环前先提交任何待处理事务，确保连接以干净状态进入逐表循环。
    # 原因：SQLite 的隐式事务（由 flush() 开启）会持有 RESERVED 锁，
    # 阻止任何连接（包括 engine 新创建的）执行需要 EXCLUSIVE 锁的 DDL。
    # 参考：tables.py 正常建表流程也是先 commit 再 ddl_create。
    if db.in_transaction():
        db.commit()

    try:
        for tbl_data in json_data.get("tables", []):
            table_name = tbl_data.get("name", "").strip()
            if not table_name:
                continue
            # 同名表跳过
            existing = (
                db.query(DataTable)
                .filter(
                    DataTable.workspace_id == workspace_id,
                    DataTable.name == table_name,
                    DataTable.trashed_at.is_(None),
                )
                .first()
            )
            if existing:
                continue

            table = DataTable(
                workspace_id=workspace_id,
                owner_id=current_user.id,
                name=table_name,
                description=tbl_data.get("description", ""),
            )
            table.ensure_db_name()
            db.add(table)
            db.flush()

            # 创建 DataField
            fields_data = tbl_data.get("fields", [])
            fields_order = []
            for fd in fields_data:
                field = DataField(
                    table_id=table.id,
                    name=fd.get("name", ""),
                    field_type=fd.get("field_type", "text"),
                    config=fd.get("config", {}) or {},
                    required=fd.get("required", False),
                    is_unique=fd.get("is_unique", False),
                    default_value=fd.get("default_value"),
                    hidden=fd.get("hidden", False),
                    order=fd.get("order", 0),
                )
                field.ensure_db_name()
                db.add(field)
                fields_order.append(field)

            db.flush()

            # ★ 关键：在执行 DDL 前先提交 flush 出的 DataTable / DataField 元数据。
            # SQLite flush() 隐式开启的事务会持有 RESERVED 锁，
            # 必须释放才能让 DDL 获取 EXCLUSIVE 锁（CREATE TABLE 需要）。
            # —— 逐表 commit 而非循环外统一 commit，使导入具备部分成功能力：
            # 单表失败不影响已成功表；整体失败时上层（create_workspace_from_backup）
            # 会回滚整个工作区级联清理。
            db.commit()

            # DDL 创建物理表（create_table 自动从 table.fields 拿字段）
            try:
                ddl_create(db.get_bind(), table)
            except Exception as exc:
                db.rollback()
                raise HTTPException(status_code=400, detail=f"创建表 {table_name} 失败: {exc}") from exc

            # 自动生成默认视图「全部」（若导入的 views 里已存在同名则跳过，
            # 避免与 uniq_table_view_name 约束冲突）
            views_data = tbl_data.get("views", [])
            if not any(vd.get("name") == "全部" for vd in views_data):
                ensure_default_view(db, table, owner_id=current_user.id, commit=False)

            # 插入数据行（用 raw INSERT 避免依赖 transfer.py 的复杂逻辑）
            rows_data = tbl_data.get("rows", [])
            if rows_data and fields_order:
                try:
                    from sqlalchemy import MetaData, insert
                    from sqlalchemy import Table as SATable

                    metadata = MetaData()
                    sa_table = SATable(table.db_table_name, metadata, autoload_with=db.bind)
                    row_values = []
                    for raw in rows_data:
                        values = {}
                        for f in fields_order:
                            if f.db_column_name in raw:
                                values[f.db_column_name] = raw[f.db_column_name]
                        if values:
                            row_values.append(values)
                    if row_values:
                        db.execute(insert(sa_table), row_values)
                        imported_rows += len(row_values)
                except Exception as exc:
                    logging.getLogger(__name__).warning("表 %s 数据行导入失败: %s", table_name, exc)

            # 创建视图（is_default 兼容 v1 旧键名 default）
            for vd in views_data:
                view = DataView(
                    table_id=table.id,
                    name=vd.get("name", ""),
                    view_type=vd.get("view_type", "grid"),
                    filter_type=vd.get("filter_type", "AND"),
                    filters=vd.get("filters", []) or [],
                    sortings=vd.get("sortings", []) or [],
                    field_options=vd.get("field_options", {}) or {},
                    view_options=vd.get("view_options", {}) or {},
                    field_order=vd.get("field_order"),
                    is_default=vd.get("is_default", vd.get("default", False)),
                )
                db.add(view)
                imported_views += 1

            # 每个表的视图/行数据独立提交，避免再次持锁影响后续 DDL
            db.commit()
            imported_tables += 1
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"导入失败: {exc}") from exc

    return WorkspaceImportResponse(
        imported_tables=imported_tables,
        imported_rows=imported_rows,
        imported_views=imported_views,
    )


@router.get("/{workspace_id}/export")
def export_workspace(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """导出整个工作区为 JSON：工作区元信息 + 所有表结构 + 数据行 + 视图配置."""
    import datetime as dt

    from sqlalchemy import MetaData, select

    from cndb.plugins.tables.models import DataField, DataTable, DataView

    ws = _get_workspace_or_404(workspace_id, db)
    _require_member(ws, current_user, db)

    # 工作区元信息
    workspace_meta = {
        "name": ws.name,
        "description": ws.description,
        "visibility": ws.visibility.value,
        "tags": ws.tags,
        "allow_edit": ws.allow_edit,
    }

    # 导出所有表（含字段、数据、视图）
    tables_data: list[dict[str, Any]] = []
    tables = (
        db.query(DataTable)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed_at.is_(None),
        )
        .all()
    )

    metadata = MetaData()
    for tbl in tables:
        # 字段定义
        fields = (
            db.query(DataField)
            .filter(
                DataField.table_id == tbl.id,
                DataField.trashed.is_(False),
            )
            .order_by(DataField.order, DataField.id)
            .all()
        )
        fields_data = [
            {
                "name": f.name,
                "field_type": f.field_type,
                "config": f.config,
                "required": f.required,
                "is_unique": f.is_unique,
                "default_value": f.default_value,
                "hidden": f.hidden,
                "order": f.order,
            }
            for f in fields
        ]

        # 数据行
        rows_data: list[dict[str, Any]] = []
        try:
            sa_table = __import__("sqlalchemy").Table(tbl.db_table_name, metadata, autoload_with=db.bind)
            if "trashed_at" in sa_table.columns:
                result = db.execute(select(sa_table).where(sa_table.c.trashed_at.is_(None))).mappings().all()
            else:
                result = db.execute(select(sa_table)).mappings().all()
            rows_data = [dict(r) for r in result]
        except Exception:  # pragma: no cover - 表结构异常
            pass

        # 视图配置
        views = db.query(DataView).filter(DataView.table_id == tbl.id).all()
        views_data = [
            {
                "name": v.name,
                "view_type": v.view_type,
                "filter_type": v.filter_type,
                "filters": v.filters,
                "sortings": v.sortings,
                "field_options": v.field_options,
                "view_options": getattr(v, "view_options", None),
                "field_order": getattr(v, "field_order", None),
                "is_default": v.is_default,
            }
            for v in views
        ]

        tables_data.append(
            {
                "name": tbl.name,
                "description": tbl.description,
                "fields": fields_data,
                "views": views_data,
                "rows": rows_data,
            }
        )

    return {
        "version": "2",
        "exported_at": dt.datetime.now(dt.UTC).isoformat(),
        "workspace": workspace_meta,
        "tables": tables_data,
    }


@router.post("/import", response_model=WorkspaceCreateFromBackupResponse, status_code=status.HTTP_201_CREATED)
def create_workspace_from_backup(
    payload: WorkspaceCreateFromBackup,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceCreateFromBackupResponse:
    """从备份 JSON 创建全新工作区：先创建工作区（owner 为当前用户），再把备份中的表结构、数据和视图导入."""
    data = payload.json_data
    if not isinstance(data, dict) or "tables" not in data:
        raise HTTPException(status_code=400, detail="无效的备份文件格式")

    # 从备份里读取 workspace meta 作为创建工作区的默认值
    ws_meta = data.get("workspace") or {}
    backup_name = payload.name or (ws_meta.get("name") or "").strip() or "未命名工作区"

    try:
        visibility_str = ws_meta.get("visibility", "member")
        visibility = WorkspaceVisibility(visibility_str)
    except (ValueError, TypeError):
        visibility = WorkspaceVisibility.MEMBER

    ws = Workspace(
        name=backup_name,
        description=ws_meta.get("description", "") or "",
        visibility=visibility,
        tags=ws_meta.get("tags", []) or [],
        allow_edit=bool(ws_meta.get("allow_edit", True)),
        created_by_id=current_user.id,
    )
    db.add(ws)
    db.flush()  # 拿到 ws.id

    member = WorkspaceMember(workspace_id=ws.id, user_id=current_user.id, role=WorkspaceRole.OWNER)
    db.add(member)
    db.commit()
    db.refresh(ws)

    # 导入备份中的表/数据/视图
    try:
        import_result = _import_backup_into_workspace(ws.id, data, current_user, db)
    except HTTPException:
        # 导入失败：清理刚创建的工作区，避免脏数据残留
        db.delete(ws)
        db.commit()
        raise

    return WorkspaceCreateFromBackupResponse(
        workspace=ws,
        imported_tables=import_result.imported_tables,
        imported_rows=import_result.imported_rows,
        imported_views=import_result.imported_views,
    )


@router.post("/{workspace_id}/import", response_model=WorkspaceImportResponse)
def import_workspace(
    workspace_id: int,
    payload: WorkspaceImportRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceImportResponse:
    """从 JSON 数据导入表结构、视图和数据行到指定工作区（ADMIN+）."""
    _require_admin(_get_workspace_or_404(workspace_id, db), current_user, db)
    data = payload.json_data
    if not isinstance(data, dict) or "tables" not in data:
        raise HTTPException(status_code=400, detail="无效的导入数据格式")

    return _import_backup_into_workspace(workspace_id, data, current_user, db)


__all__ = ["router"]
