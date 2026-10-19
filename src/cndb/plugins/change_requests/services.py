"""change_requests 插件服务层：修改申请业务逻辑（设计 3.3/3.4 节）.

核心语义：
- 创建：base_values 由服务端快照（update 取涉及字段当前值，delete 取整行字段快照）；
- merge：逐项 apply/skip，落库任一校验失败整体 409 保持 open；
- merge 成功后其余引用相同行的 open 申请置 stale；
- update-base：仅提交人，重新快照 base_values 保留 values，复位 stale。
"""

from __future__ import annotations

import datetime as dt
import json
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

# 写模式三态：与写路径双轨分派（records._dispatch_or_403）语义一一对应
WRITE_MODE_DIRECT = "direct"  # 原地修改直存
WRITE_MODE_CHANGE_REQUEST = "change_request"  # 写路径自动转为修改申请（202）
WRITE_MODE_DENIED = "denied"  # 有直编资格但表级 EDIT_RECORDS 受限（写操作 403）


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


def resolve_write_mode(db: Session, table: DataTable, user: User) -> str:
    """判定当前用户对该表的写模式，供前端权限标注与提示适配.

    与写路径双轨分派（records._dispatch_or_403）同源，避免标注与实际行为脱节：
    - direct：可直编且表级 EDIT_RECORDS 通过 → 编辑直接落库，不会生成修改申请；
    - change_request：无直编资格（viewer / 工作区关闭直编的 editor）→ 写路径自动生成申请；
    - denied：有直编资格但表级 EDIT_RECORDS 受限 → 写操作将返回 403。
    """
    from cndb.plugins.tables.services.core.access import TableAction, check_action

    if not can_write_directly(db, table, user):
        return WRITE_MODE_CHANGE_REQUEST
    if check_action(db, table, user, TableAction.EDIT_RECORDS):
        return WRITE_MODE_DIRECT
    return WRITE_MODE_DENIED


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


def list_requests(
    db: Session,
    table_id: int,
    *,
    scope: str,
    user: User,
    group_by: str | None = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    """申请列表.

    - 缺省：扁平列表，每项附 conflicts_count（与其他 open 申请共享的行数）与 items 元信息；
    - group_by="row"：按目标行聚合为行组（含冲突/漂移标记），create-only 申请归 ungrouped。

    排序：created_at desc, id desc（时间倒序；同秒提交用 id 兜底稳定序）。
    """
    q = db.query(ChangeRequest).filter(ChangeRequest.table_id == table_id)
    if scope == "open":
        q = q.filter(ChangeRequest.status == CR_STATUS_OPEN)
    elif scope == "merged":
        q = q.filter(ChangeRequest.status == CR_STATUS_MERGED)
    elif scope == "mine":
        q = q.filter(ChangeRequest.submitted_by_id == user.id)
    requests = q.order_by(ChangeRequest.created_at.desc(), ChangeRequest.id.desc()).all()
    conflicts = _conflict_row_counts(db, table_id)
    meta = _request_item_meta(db, table_id)
    if group_by == "row":
        return _group_requests_by_row(db, table_id, requests, conflicts, meta)
    return [
        serialize_request(r, conflicts_count=conflicts.get(r.id, 0), **(meta.get(r.id) or _EMPTY_ITEM_META))
        for r in requests
    ]


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
        row_missing = False
        if item.row_id is not None:
            current = rec.get_row(engine, table, item.row_id, db=db)
            if current is None:
                row_missing = True
        if item.op == CHANGE_OP_UPDATE and current is not None:
            for f, base in (item.base_values or {}).items():
                if f in current and current[f] != base:
                    field_conflicts.append(f)
        # 后端契约：current_values 始终返回 dict（类型定义 Record<string, unknown>），
        # 行已被删除或无权限查看时降级为空 dict，前端可据此展示「基准行已失效」。
        safe_current: dict[str, Any] = current if current is not None else {}
        items_out.append(
            {
                "id": item.id,
                "op": item.op,
                "row_id": item.row_id,
                "base_values": item.base_values,
                "values": item.values,
                "current_values": safe_current,
                "field_conflicts": field_conflicts,
                "row_missing": row_missing,
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
                rec.update_row(engine, table, row_id, item.values, db=db, user=user)
                applied += 1
                applied_row_ids.add(row_id)
            else:  # delete
                if row_id is None or rec.get_row(engine, table, row_id, db=db) is None:
                    skipped += 1  # 行已不存在，自动失效
                    continue
                rec.trash_row(engine, table, row_id, db=db, user=user)
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
    _mark_others_stale(db, cr.table_id, exclude_ids={cr.id}, row_ids=applied_row_ids)
    db.commit()
    db.refresh(cr)
    # 返回完整详情（含 items/actions）：前端以响应覆盖详情缓存，
    # 只回本体缺 items 会导致详情页渲染 undefined.length 崩溃
    return {"applied": applied, "skipped": skipped, "request": get_request_detail(db, cr, table)}


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


def _mark_others_stale(
    db: Session,
    table_id: int,
    *,
    exclude_ids: set[int],
    row_ids: set[int],
) -> None:
    """merge 落库后，其余 open 申请中引用相同行的置 stale=True（exclude_ids 内的申请不处理）."""
    if not row_ids:
        return
    q = (
        db.query(ChangeRequest)
        .join(ChangeItem, ChangeItem.request_id == ChangeRequest.id)
        .filter(
            ChangeRequest.table_id == table_id,
            ChangeRequest.status == CR_STATUS_OPEN,
            ChangeItem.row_id.in_(row_ids),
        )
        .distinct()
    )
    if exclude_ids:
        q = q.filter(ChangeRequest.id.notin_(exclude_ids))
    for other in q.all():
        other.stale = True


# ── items 元信息 / 行组聚合 / 冲突检测 ────────────────

_EMPTY_ITEM_META: dict[str, Any] = {"row_ids": [], "fields": [], "item_count": 0}


def _request_item_meta(db: Session, table_id: int) -> dict[int, dict[str, Any]]:
    """每个申请的 items 元信息：去重 row_ids / 涉及字段（create/update 的 values 键）/ item 数."""
    rows = (
        db.query(ChangeItem, ChangeRequest)
        .join(ChangeRequest, ChangeItem.request_id == ChangeRequest.id)
        .filter(ChangeRequest.table_id == table_id)
        .all()
    )
    acc: dict[int, dict[str, Any]] = {}
    for item, _cr in rows:
        m = acc.setdefault(item.request_id, {"row_id_set": set(), "fields": set(), "item_count": 0})
        m["item_count"] += 1
        if item.row_id is not None:
            m["row_id_set"].add(item.row_id)
        if item.op in (CHANGE_OP_CREATE, CHANGE_OP_UPDATE):
            m["fields"].update((item.values or {}).keys())
    return {
        rid: {
            "row_ids": sorted(m["row_id_set"]),
            "fields": sorted(m["fields"]),
            "item_count": m["item_count"],
        }
        for rid, m in acc.items()
    }


def _open_row_items(db: Session, table_id: int) -> dict[int, list[dict[str, Any]]]:
    """该表全部 open 申请中按 row_id 归集的变更项（create 无 row_id，排除）."""
    rows = (
        db.query(ChangeItem)
        .join(ChangeRequest, ChangeItem.request_id == ChangeRequest.id)
        .filter(
            ChangeRequest.table_id == table_id,
            ChangeRequest.status == CR_STATUS_OPEN,
            ChangeItem.row_id.isnot(None),
        )
        .all()
    )
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for it in rows:
        out[it.row_id].append(_item_row(it))  # type: ignore[index]
    return out


def _item_row(item: ChangeItem) -> dict[str, Any]:
    """ORM item → 行级冲突检测所需的最小投影."""
    return {
        "id": item.id,
        "request_id": item.request_id,
        "op": item.op,
        "row_id": item.row_id,
        "base_values": item.base_values or {},
        "values": item.values or {},
    }


def _hashable(value: Any) -> str:
    """JSON 值的可比较签名（用于判断多个写者是否写入同一值）."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def detect_row_conflicts(items: list[dict[str, Any]], current: dict[str, Any] | None) -> dict[str, Any]:
    """给定同一行的一组 open items 与当前行值，计算冲突与漂移.

    - conflict_fields：同一字段被 ≥2 个写者写入且值不等（交汇冲突）；
    - row_op_conflict：存在 delete 且同行还有其他 item（行级互斥）；
    - drift_fields：字段当前值 != 提交时基准快照（基准漂移）；
    - row_missing：目标行已不存在。
    """
    writers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    has_delete = False
    for it in items:
        if it["op"] == CHANGE_OP_DELETE:
            has_delete = True
            continue
        for f, v in (it["values"] or {}).items():
            writers[f].append({"request_id": it["request_id"], "item_id": it["id"], "value": v})

    conflict_fields = sorted(f for f, ws in writers.items() if len({_hashable(w["value"]) for w in ws}) > 1)

    drift: set[str] = set()
    if current is not None:
        for it in items:
            for f, base in (it.get("base_values") or {}).items():
                if f in current and current[f] != base:
                    drift.add(f)

    drift_fields = sorted(drift)
    row_op_conflict = has_delete and len(items) > 1
    return {
        "conflict_fields": conflict_fields,
        "drift_fields": drift_fields,
        "has_conflict": bool(conflict_fields) or row_op_conflict,
        "has_drift": bool(drift_fields),
        "row_missing": current is None,
        "row_op_conflict": row_op_conflict,
        "field_writers": {f: writers[f] for f in writers},
    }


def _group_requests_by_row(
    db: Session,
    table_id: int,
    requests: list[ChangeRequest],
    conflicts: dict[int, int],
    meta: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """按 row_id 聚合申请为行组；create-only 归 ungrouped；组间/组内均按时间倒序."""
    engine = db.get_bind()
    table = db.get(DataTable, table_id)
    open_items = _open_row_items(db, table_id)

    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    ungrouped: list[dict[str, Any]] = []
    for r in requests:
        item = serialize_request(r, conflicts_count=conflicts.get(r.id, 0), **(meta.get(r.id) or _EMPTY_ITEM_META))
        row_ids = item["row_ids"]
        if not row_ids:
            ungrouped.append(item)
            continue
        # 一个申请可引用多行：分别纳入各行的行组
        for rid in row_ids:
            groups[rid].append(item)

    out_groups: list[dict[str, Any]] = []
    for rid, reqs in groups.items():
        current = rec.get_row(engine, table, rid, db=db) if table is not None else None
        det = detect_row_conflicts(open_items.get(rid, []), current)
        reqs.sort(key=lambda x: (x.get("created_at") or "", x["id"]), reverse=True)
        latest = reqs[0]
        out_groups.append(
            {
                "row_id": rid,
                "row_values": current or {},
                "row_missing": det["row_missing"],
                "requests": reqs,
                "conflict_fields": det["conflict_fields"],
                "drift_fields": det["drift_fields"],
                "has_conflict": det["has_conflict"],
                "has_drift": det["has_drift"],
                "latest_created_at": latest.get("created_at"),
                "_sort": (latest.get("created_at") or "", latest["id"]),
            }
        )
    out_groups.sort(key=lambda g: g["_sort"], reverse=True)
    for g in out_groups:
        g.pop("_sort", None)
    return {"groups": out_groups, "ungrouped": ungrouped, "total": len(requests)}


def merge_row_requests(
    db: Session,
    table: DataTable,
    row_id: int,
    user: User,
    request_ids: list[int],
    resolutions: Mapping[str, Any],
    row_action: str | None,
    comment: str,
) -> dict[str, Any]:
    """行组批量合并：一次审批同一行的多份 open 申请（仅 owner/editor）.

    - 每份申请的变更项须全部属于该行且不含 create，否则 400；
    - 冲突字段（多申请写同值不等）必须由 resolutions 显式裁决，未裁决 409；
    - 存在 delete 与修改互斥时须由 row_action 裁决（keep/delete），否则 409；
    - 落库前 _normalize_values 预校验，失败整体 409 回滚，全部保持 open；
    - 成功后各申请置 merged 并写 merge 流水，同行其余 open 申请置 stale。
    """
    role = require_reviewer_role(db, table, user)
    if role not in (WorkspaceRole.OWNER, WorkspaceRole.EDITOR):
        raise HTTPException(status_code=403, detail="仅 owner/editor 可合并修改申请")

    engine = db.get_bind()
    crs: list[ChangeRequest] = []
    items: list[dict[str, Any]] = []
    for rid in request_ids:
        cr = get_request_or_404(db, table, rid)
        if cr.status != CR_STATUS_OPEN:
            raise HTTPException(status_code=409, detail=f"申请 #{rid} 当前状态 {cr.status} 不允许合并")
        crs.append(cr)
        for item in db.query(ChangeItem).filter(ChangeItem.request_id == cr.id).all():
            if item.op == CHANGE_OP_CREATE:
                raise HTTPException(status_code=400, detail=f"申请 #{cr.id} 含新增行变更项，无法按行批量合并")
            if item.row_id != row_id:
                raise HTTPException(status_code=400, detail=f"申请 #{cr.id} 含其他行的变更项，请到该申请详情单独处理")
            items.append(_item_row(item))

    current = rec.get_row(engine, table, row_id, db=db)
    det = detect_row_conflicts(items, current)

    # 冲突裁决校验：冲突字段必须显式裁决；delete 互斥须指定 row_action
    if det["row_op_conflict"] and row_action not in ("keep", "delete"):
        raise HTTPException(status_code=409, detail="该行存在删除与修改互斥，请先选择保留或删除")
    for f in det["conflict_fields"]:
        res = resolutions.get(f)
        strategy = getattr(res, "strategy", None)
        if strategy is None:
            raise HTTPException(status_code=409, detail=f"字段「{f}」存在冲突，请先裁决")
        if strategy == "item":
            item_id = getattr(res, "item_id", None)
            valid_ids = {w["item_id"] for w in det["field_writers"][f]}
            if item_id not in valid_ids:
                raise HTTPException(status_code=400, detail=f"字段「{f}」的裁决 item_id 非法")

    # 计算最终生效的行写入（delete 分支跳过字段写）
    effective: dict[str, Any] = {}
    applied_row_ids: set[int] = set()
    applied = 0
    skipped = 0
    try:
        if row_action == "delete":
            if current is not None:
                rec.trash_row(engine, table, row_id, db=db, user=user)
                applied_row_ids.add(row_id)
            applied = sum(1 for it in items if it["op"] == CHANGE_OP_DELETE)
            skipped = len(items) - applied
        else:
            for f, ws in det["field_writers"].items():
                if len({_hashable(w["value"]) for w in ws}) == 1:
                    effective[f] = ws[0]["value"]
                    continue
                res = resolutions[f]
                if getattr(res, "strategy", None) == "current":
                    continue
                chosen = next(w for w in ws if w["item_id"] == getattr(res, "item_id", None))
                effective[f] = chosen["value"]
            if effective:
                rec._normalize_values(table, effective, for_update=True)
                if current is not None:
                    rec.update_row(engine, table, row_id, effective, db=db, user=user)
                    applied_row_ids.add(row_id)
            # 应用统计：贡献了生效字段的 update 项计 applied，其余计 skipped
            for it in items:
                if it["op"] == CHANGE_OP_UPDATE and any(f in effective for f in (it["values"] or {})):
                    applied += 1
                else:
                    skipped += 1
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"合并失败，申请保持打开: {exc}") from exc

    now = dt.datetime.now(dt.UTC)
    for cr in crs:
        cr.status = CR_STATUS_MERGED
        cr.stale = False
        cr.reviewed_by_id = user.id
        cr.reviewed_at = now
        cr.review_comment = comment
        db.add(ChangeRequestAction(request_id=cr.id, action=CR_ACTION_MERGE, comment=comment, acted_by_id=user.id))
    _mark_others_stale(db, table.id, exclude_ids=set(request_ids), row_ids=applied_row_ids)
    db.commit()

    return {
        "applied": applied,
        "skipped": skipped,
        "merged_request_ids": list(request_ids),
        "requests": [get_request_detail(db, cr, table) for cr in crs],
    }


def serialize_request(
    cr: ChangeRequest,
    *,
    conflicts_count: int | None = None,
    row_ids: list[int] | None = None,
    fields: list[str] | None = None,
    item_count: int | None = None,
) -> dict[str, Any]:
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
    if row_ids is not None:
        data["row_ids"] = row_ids
    if fields is not None:
        data["fields"] = fields
    if item_count is not None:
        data["item_count"] = item_count
    return data


def _iso(value: Any) -> str | None:
    """datetime 统一转 ISO 字符串."""
    return value.isoformat() if value is not None else None


__all__ = [
    "WRITE_MODE_CHANGE_REQUEST",
    "WRITE_MODE_DENIED",
    "WRITE_MODE_DIRECT",
    "add_comment",
    "can_write_directly",
    "close_request",
    "create_batch_delete_request",
    "create_dispatch_request",
    "create_request",
    "detect_row_conflicts",
    "get_request_detail",
    "get_request_or_404",
    "list_requests",
    "merge_request",
    "merge_row_requests",
    "reopen_request",
    "require_reviewer_role",
    "resolve_write_mode",
    "serialize_request",
    "update_base",
]
