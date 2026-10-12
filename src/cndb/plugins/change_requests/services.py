"""change_requests 插件服务层：修改申请业务逻辑（设计 3.3/3.4 节）.

核心语义：
- 创建：base_values 由服务端快照（update 取涉及字段当前值，delete 取整行字段快照）；
- merge：逐项 apply/skip，落库任一校验失败整体 409 保持 open；
- merge 成功后其余引用相同行的 open 申请置 stale；
- update-base：仅提交人，重新快照 base_values 保留 values，复位 stale。
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.change_requests.models import (
    CHANGE_OP_CREATE,
    CHANGE_OP_DELETE,
    CHANGE_OP_UPDATE,
    CHANGE_OPS,
    CR_ACTION_CLOSE,
    CR_ACTION_COMMENT,
    CR_ACTION_MERGE,
    CR_ACTION_REOPEN,
    CR_ACTION_UPDATE_BASE,
    CR_STATUS_CLOSED,
    CR_STATUS_MERGED,
    CR_STATUS_OPEN,
    ChangeItem,
    ChangeRequest,
    ChangeRequestAction,
)
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role

# ── 双轨写入分派（records.py / bulk.py 调用） ──────────


def can_write_directly(db: Session, table: DataTable, user: User) -> bool:
    """判定是否直编直存：owner 恒直编；editor 需工作区 allow_edit 开启；viewer 一律走修改申请."""
    ws = db.get(Workspace, table.workspace_id)
    if ws is None:  # pragma: no cover - 表必然挂在有效工作区下
        return False
    role = get_member_role(user, ws, db)
    if role is None:
        return False
    if role == WorkspaceRole.OWNER:
        return True
    return role == WorkspaceRole.EDITOR and bool(ws.allow_edit)


def create_dispatch_request(
    db: Session,
    table: DataTable,
    user: User,
    op: str,
    row_id: int | None,
    values: dict[str, Any],
) -> ChangeRequest:
    """单行写路径自动生成修改申请（viewer 或 allow_edit 关闭时调用）.

    标题自动生成：新增行 / 修改行 #N / 删除行 #N；
    base_values 服务端快照：update 取涉及字段当前值，delete 取整行字段快照。
    """
    engine = db.get_bind()
    base_values: dict[str, Any] = {}
    item_values: dict[str, Any] = dict(values or {})
    if op == CHANGE_OP_CREATE:
        title = "新增行"
        row_id = None
    elif op in (CHANGE_OP_UPDATE, CHANGE_OP_DELETE):
        if row_id is None:
            raise HTTPException(status_code=400, detail=f"{op} 必须提供 row_id")
        row = rec.get_row(engine, table, row_id, db=db)
        if row is None:
            raise HTTPException(status_code=404, detail="行不存在")
        if op == CHANGE_OP_UPDATE:
            base_values = {f: row.get(f) for f in item_values}
            title = f"修改行 #{row_id}"
        else:
            base_values = _snapshot_row_fields(table, row)
            item_values = {}
            title = f"删除行 #{row_id}"
    else:
        raise HTTPException(status_code=400, detail=f"非法操作类型: {op}")
    return _persist_request(db, table, user, title=title, items=[(op, row_id, base_values, item_values)])


def create_batch_delete_request(db: Session, table: DataTable, user: User, row_ids: list[int]) -> ChangeRequest:
    """批量删除自动生成一个含多个 delete item 的修改申请."""
    engine = db.get_bind()
    items: list[tuple[str, int | None, dict[str, Any], dict[str, Any]]] = []
    for rid in row_ids:
        row = rec.get_row(engine, table, rid, db=db)
        base = _snapshot_row_fields(table, row) if row is not None else {}
        items.append((CHANGE_OP_DELETE, rid, base, {}))
    title = f"删除 {len(row_ids)} 行"
    return _persist_request(db, table, user, title=title, items=items)


# ── 申请 CRUD 与列表 ──────────────────────────────────


def create_request(
    db: Session,
    table: DataTable,
    user: User,
    *,
    title: str | None,
    description: str,
    items: list[dict[str, Any]],
) -> ChangeRequest:
    """创建修改申请（POST 端点用，支持多 item）.

    payload 的 base_values 不采信，一律服务端快照（update/delete 需目标行存在）。
    """
    engine = db.get_bind()
    prepared: list[tuple[str, int | None, dict[str, Any], dict[str, Any]]] = []
    for raw in items:
        op = raw["op"]
        if op not in CHANGE_OPS:
            raise HTTPException(status_code=400, detail=f"非法操作类型: {op}")
        row_id = raw.get("row_id")
        values: dict[str, Any] = dict(raw.get("values") or {})
        if op == CHANGE_OP_CREATE:
            if row_id is not None:
                raise HTTPException(status_code=400, detail="create 项不应携带 row_id")
            prepared.append((op, None, {}, values))
            continue
        if row_id is None:
            raise HTTPException(status_code=400, detail=f"{op} 项必须携带 row_id")
        row = rec.get_row(engine, table, row_id, db=db)
        if row is None:
            raise HTTPException(status_code=400, detail=f"行 #{row_id} 不存在")
        if op == CHANGE_OP_UPDATE:
            base = {f: row.get(f) for f in values}
        else:
            base = _snapshot_row_fields(table, row)
            values = {}
        prepared.append((op, row_id, base, values))

    if not title:
        title = _auto_title(prepared)
    return _persist_request(db, table, user, title=title, items=prepared, description=description)


def list_requests(db: Session, table_id: int, *, scope: str, user: User) -> list[dict[str, Any]]:
    """申请列表（scope=open/all/mine），每项附 conflicts_count（与其他 open 申请共享的行数）."""
    q = db.query(ChangeRequest).filter(ChangeRequest.table_id == table_id)
    if scope == "open":
        q = q.filter(ChangeRequest.status == CR_STATUS_OPEN)
    elif scope == "mine":
        q = q.filter(ChangeRequest.submitted_by_id == user.id)
    requests = q.order_by(ChangeRequest.id.desc()).all()
    conflicts = _conflict_row_counts(db, table_id)
    return [serialize_request(r, conflicts_count=conflicts.get(r.id, 0)) for r in requests]


def get_request_or_404(db: Session, table: DataTable, request_id: int) -> ChangeRequest:
    """按 id 取申请并校验归属（表/工作区不匹配一律 404）."""
    cr = db.get(ChangeRequest, request_id)
    if cr is None or cr.table_id != table.id or cr.workspace_id != table.workspace_id:
        raise HTTPException(status_code=404, detail="修改申请不存在")
    return cr


def get_request_detail(db: Session, cr: ChangeRequest, table: DataTable) -> dict[str, Any]:
    """申请详情：items（含字段级 diff 与 field_conflicts）+ 动作流水."""
    engine = db.get_bind()
    items_out: list[dict[str, Any]] = []
    for item in db.query(ChangeItem).filter(ChangeItem.request_id == cr.id).order_by(ChangeItem.id.asc()).all():
        current: dict[str, Any] | None = None
        field_conflicts: list[str] = []
        if item.row_id is not None:
            current = rec.get_row(engine, table, item.row_id, db=db)
        if item.op == CHANGE_OP_UPDATE and current is not None:
            for f, base in (item.base_values or {}).items():
                if f in current and current[f] != base:
                    field_conflicts.append(f)
        items_out.append(
            {
                "id": item.id,
                "op": item.op,
                "row_id": item.row_id,
                "base_values": item.base_values,
                "values": item.values,
                "current_values": current,
                "field_conflicts": field_conflicts,
            }
        )
    actions = (
        db.query(ChangeRequestAction)
        .filter(ChangeRequestAction.request_id == cr.id)
        .order_by(ChangeRequestAction.id.asc())
        .all()
    )
    data = serialize_request(cr)
    data["items"] = items_out
    data["actions"] = [
        {
            "id": a.id,
            "action": a.action,
            "comment": a.comment,
            "acted_by_id": a.acted_by_id,
            "created_at": _iso(a.created_at),
        }
        for a in actions
    ]
    return data


def add_comment(db: Session, cr: ChangeRequest, user: User, content: str) -> dict[str, Any]:
    """添加评论（写动作流水）."""
    action = ChangeRequestAction(request_id=cr.id, action=CR_ACTION_COMMENT, comment=content, acted_by_id=user.id)
    db.add(action)
    db.commit()
    db.refresh(action)
    return {
        "id": action.id,
        "action": action.action,
        "comment": action.comment,
        "acted_by_id": action.acted_by_id,
        "created_at": _iso(action.created_at),
    }


# ── 状态流转 ──────────────────────────────────────────


def merge_request(
    db: Session,
    cr: ChangeRequest,
    table: DataTable,
    user: User,
    decisions: Mapping[int, str],
    comment: str,
) -> dict[str, Any]:
    """逐项决策合并（仅 owner/editor）.

    - update 项 apply：行存在则落库 values；行不存在自动 skip；
      落库前预校验（_normalize_values），任一失败整体 409 保持 open；
    - delete 项 apply：行存在软删，否则自动 skip；create 项直接落库；
    - 全部处理完置 status=merged 并写 merge 动作流水；
    - 其余 open 申请引用本申请 apply 过的行 → 置 stale。
    """
    _require_reviewer(db, cr, user)
    if cr.status != CR_STATUS_OPEN:
        raise HTTPException(status_code=409, detail=f"当前状态 {cr.status} 不允许合并")

    engine = db.get_bind()
    items = db.query(ChangeItem).filter(ChangeItem.request_id == cr.id).all()

    # 预校验：保证任一项非法时整体不落库（保持 open，409 语义）
    for item in items:
        if decisions.get(item.id, "skip") != "apply":
            continue
        if item.op in (CHANGE_OP_CREATE, CHANGE_OP_UPDATE):
            try:
                rec._normalize_values(table, item.values, for_update=item.op == CHANGE_OP_UPDATE)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=f"变更项 #{item.id} 校验失败: {exc}") from exc

    applied = 0
    skipped = 0
    applied_row_ids: set[int] = set()
    try:
        for item in items:
            if decisions.get(item.id, "skip") != "apply":
                skipped += 1
                continue
            row_id = item.row_id
            if item.op == CHANGE_OP_CREATE:
                rec.create_row(engine, table, item.values, db=db)
                applied += 1
            elif item.op == CHANGE_OP_UPDATE:
                if row_id is None or rec.get_row(engine, table, row_id, db=db) is None:
                    skipped += 1
                    continue
                rec.update_row(engine, table, row_id, item.values, db=db)
                applied += 1
                applied_row_ids.add(row_id)
            else:  # delete
                if row_id is None or rec.get_row(engine, table, row_id, db=db) is None:
                    skipped += 1  # 行已不存在，自动失效
                    continue
                rec.trash_row(engine, table, row_id, db=db)
                applied += 1
                applied_row_ids.add(row_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"合并失败，申请保持打开: {exc}") from exc

    cr.status = CR_STATUS_MERGED
    cr.stale = False
    cr.reviewed_by_id = user.id
    cr.reviewed_at = dt.datetime.now(dt.UTC)
    cr.review_comment = comment
    db.add(ChangeRequestAction(request_id=cr.id, action=CR_ACTION_MERGE, comment=comment, acted_by_id=user.id))
    _mark_others_stale(db, cr, applied_row_ids)
    db.commit()
    db.refresh(cr)
    return {"applied": applied, "skipped": skipped, "request": serialize_request(cr)}


def close_request(db: Session, cr: ChangeRequest, user: User, role: WorkspaceRole | None) -> ChangeRequest:
    """关闭申请：owner/editor，或提交人本人（已关闭 409）."""
    if not (role in (WorkspaceRole.OWNER, WorkspaceRole.EDITOR) or cr.submitted_by_id == user.id):
        raise HTTPException(status_code=403, detail="仅 owner/editor 或提交人可关闭")
    if cr.status != CR_STATUS_OPEN:
        raise HTTPException(status_code=409, detail=f"当前状态 {cr.status} 不允许关闭")
    cr.status = CR_STATUS_CLOSED
    cr.reviewed_by_id = user.id
    cr.reviewed_at = dt.datetime.now(dt.UTC)
    db.add(ChangeRequestAction(request_id=cr.id, action=CR_ACTION_CLOSE, acted_by_id=user.id))
    db.commit()
    db.refresh(cr)
    return cr


def reopen_request(db: Session, cr: ChangeRequest, user: User) -> ChangeRequest:
    """重开申请：仅 owner/editor（closed 可重开，merged 不可）."""
    if cr.status != CR_STATUS_CLOSED:
        raise HTTPException(status_code=409, detail=f"当前状态 {cr.status} 不允许重开")
    cr.status = CR_STATUS_OPEN
    db.add(ChangeRequestAction(request_id=cr.id, action=CR_ACTION_REOPEN, acted_by_id=user.id))
    db.commit()
    db.refresh(cr)
    return cr


def update_base(db: Session, cr: ChangeRequest, table: DataTable, user: User) -> ChangeRequest:
    """刷新基准：仅提交人；stale 时重新快照 base_values（保留 values），复位 stale."""
    if cr.submitted_by_id != user.id:
        raise HTTPException(status_code=403, detail="仅提交人可刷新基准")
    if cr.status != CR_STATUS_OPEN:
        raise HTTPException(status_code=409, detail=f"当前状态 {cr.status} 不允许刷新基准")
    engine = db.get_bind()
    refreshed = False
    for item in db.query(ChangeItem).filter(ChangeItem.request_id == cr.id).all():
        if item.op == CHANGE_OP_CREATE:
            continue
        if item.row_id is None:  # pragma: no cover - update/delete 项必有 row_id
            continue
        row = rec.get_row(engine, table, item.row_id, db=db)
        if row is None:
            raise HTTPException(status_code=409, detail=f"行 #{item.row_id} 已不存在，无法刷新基准")
        item.base_values = {f: row.get(f) for f in (item.base_values or {})}
        refreshed = True
    if not refreshed:
        raise HTTPException(status_code=400, detail="申请中没有可刷新基准的 update/delete 变更项")
    cr.stale = False
    db.add(ChangeRequestAction(request_id=cr.id, action=CR_ACTION_UPDATE_BASE, acted_by_id=user.id))
    db.commit()
    db.refresh(cr)
    return cr


def require_reviewer_role(db: Session, table: DataTable, user: User) -> WorkspaceRole | None:
    """取当前用户在表所属工作区的角色（供路由层权限判定）."""
    ws = db.get(Workspace, table.workspace_id)
    if ws is None:  # pragma: no cover
        return None
    return get_member_role(user, ws, db)


def _require_reviewer(db: Session, cr: ChangeRequest, user: User) -> None:
    """merge 仅 owner/editor 可操作."""
    ws = db.get(Workspace, cr.workspace_id)
    role = get_member_role(user, ws, db) if ws else None
    if role not in (WorkspaceRole.OWNER, WorkspaceRole.EDITOR):
        raise HTTPException(status_code=403, detail="仅 owner/editor 可合并修改申请")


# ── 内部工具 ──────────────────────────────────────────


def _persist_request(
    db: Session,
    table: DataTable,
    user: User,
    *,
    title: str,
    items: list[tuple[str, int | None, dict[str, Any], dict[str, Any]]],
    description: str = "",
) -> ChangeRequest:
    """落库申请 + items（服务端快照后统一入口）."""
    cr = ChangeRequest(
        workspace_id=table.workspace_id,
        table_id=table.id,
        title=title,
        description=description,
        status=CR_STATUS_OPEN,
        submitted_by_id=user.id,
    )
    db.add(cr)
    db.flush()
    for op, row_id, base_values, values in items:
        db.add(
            ChangeItem(
                request_id=cr.id,
                op=op,
                row_id=row_id,
                base_values=base_values,
                values=values,
            )
        )
    db.commit()
    db.refresh(cr)
    return cr


def _snapshot_row_fields(table: DataTable, row: dict[str, Any]) -> dict[str, Any]:
    """整行字段快照：只取物理字段名，排除 id/link/lookup 附加键."""
    return {f.name: row.get(f.name) for f in table.fields if f.name in row}


def _auto_title(items: list[tuple[str, int | None, dict[str, Any], dict[str, Any]]]) -> str:
    """未传标题时自动生成：单项按操作命名，多项汇总计数."""
    if len(items) == 1:
        op, row_id, _base, _values = items[0]
        if op == CHANGE_OP_CREATE:
            return "新增行"
        if op == CHANGE_OP_UPDATE:
            return f"修改行 #{row_id}"
        return f"删除行 #{row_id}"
    return f"修改申请（{len(items)} 项变更）"


def _conflict_row_counts(db: Session, table_id: int) -> dict[int, int]:
    """统计每个 open 申请与其他 open 申请共享的行数（去重行数）."""
    rows = (
        db.query(ChangeItem.row_id, ChangeItem.request_id)
        .join(ChangeRequest, ChangeItem.request_id == ChangeRequest.id)
        .filter(
            ChangeRequest.table_id == table_id,
            ChangeRequest.status == CR_STATUS_OPEN,
            ChangeItem.row_id.isnot(None),
        )
        .all()
    )
    row_requests: dict[int, set[int]] = defaultdict(set)
    for rid, req_id in rows:
        row_requests[rid].add(req_id)
    shared_per_request: dict[int, set[int]] = defaultdict(set)
    for rid, req_id in rows:
        if len(row_requests[rid]) > 1:
            shared_per_request[req_id].add(rid)
    return {req_id: len(rows_) for req_id, rows_ in shared_per_request.items()}


def _mark_others_stale(db: Session, cr: ChangeRequest, row_ids: set[int]) -> None:
    """merge 落库后，其余 open 申请中引用相同行的置 stale=True."""
    if not row_ids:
        return
    others = (
        db.query(ChangeRequest)
        .join(ChangeItem, ChangeItem.request_id == ChangeRequest.id)
        .filter(
            ChangeRequest.table_id == cr.table_id,
            ChangeRequest.id != cr.id,
            ChangeRequest.status == CR_STATUS_OPEN,
            ChangeItem.row_id.in_(row_ids),
        )
        .distinct()
        .all()
    )
    for other in others:
        other.stale = True


def serialize_request(cr: ChangeRequest, *, conflicts_count: int | None = None) -> dict[str, Any]:
    """申请序列化（列表/详情/分派响应共用）."""
    data: dict[str, Any] = {
        "id": cr.id,
        "workspace_id": cr.workspace_id,
        "table_id": cr.table_id,
        "title": cr.title,
        "description": cr.description,
        "status": cr.status,
        "stale": cr.stale,
        "submitted_by_id": cr.submitted_by_id,
        "reviewed_by_id": cr.reviewed_by_id,
        "reviewed_at": _iso(cr.reviewed_at),
        "review_comment": cr.review_comment,
        "created_at": _iso(cr.created_at),
        "updated_at": _iso(cr.updated_at),
    }
    if conflicts_count is not None:
        data["conflicts_count"] = conflicts_count
    return data


def _iso(value: Any) -> str | None:
    """datetime 统一转 ISO 字符串."""
    return value.isoformat() if value is not None else None


__all__ = [
    "add_comment",
    "can_write_directly",
    "close_request",
    "create_batch_delete_request",
    "create_dispatch_request",
    "create_request",
    "get_request_detail",
    "get_request_or_404",
    "list_requests",
    "merge_request",
    "reopen_request",
    "require_reviewer_role",
    "serialize_request",
    "update_base",
]
