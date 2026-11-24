"""行数据路由."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.change_requests import services as cr_services
from cndb.plugins.change_requests.models import (
    CHANGE_OP_CREATE,
    CHANGE_OP_DELETE,
    CHANGE_OP_UPDATE,
)
from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.models import AuditLog, DataTable
from cndb.plugins.tables.schemas import (
    AggregateRequest,
    AutoIncrementPreviewResponse,
    BulkRowIds,
    MatrixUpsertRequest,
    RecordCopyRequest,
    RecordCreate,
    RecordListRequest,
    RecordListResponse,
    RecordUpdate,
)
from cndb.plugins.tables.services.core.access import (
    TableAction,
    check_action,
    get_hidden_field_names,
    get_table_or_404,
    row_filters_bypass,
)
from cndb.plugins.tables.services.core.audit import ACTION_TRASH
from cndb.plugins.tables.services.core.ddl import ensure_sort_index
from cndb.plugins.tables.services.core.records import (
    _get_sa_table,
    aggregate_rows,
    bulk_create,
    copy_row_values,
    count_rows,
    create_row,
    delete_row,
    find_month_key_rows,
    get_row,
    list_rows,
    month_bounds,
    parse_if_match,
    preview_auto_increment_values,
    purge_rows,
    restore_row,
    restore_rows,
    trash_row,
    update_row,
)
from cndb.plugins.tables.services.core.row_access import can_edit_row, can_view_row, row_rules_active
from cndb.plugins.workspaces.permissions import raise_permission_denied

logger = logging.getLogger(__name__)
# 记录列表缓存 TTL（秒）：短 TTL + 事件驱动失效（record.* 事件提交后清该工作区记录缓存）
RECORD_LIST_TTL_SECONDS = 5.0

# 深分页偏移上限（ADR 0046 D8）：OFFSET 线性扫描，超过该值改为提示用户收窄筛选。
# 10 万偏移 = 每页 100 行时第 1000 页，覆盖正常浏览；更深的跳页在大表上必卡。
MAX_RECORD_OFFSET = 100_000


router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/records", tags=["records"])


#: 写请求幂等（ADR 0145）：提供该头时同一 key 只执行一次，重复请求回放首个响应
IdempotencyHeader = Annotated[
    str | None, Header(alias="Idempotency-Key", description="可选：写请求幂等键（≤128 字符）")
]


def _idempotency_guard(
    db: Session,
    user: User,
    header: str | None,
    route: str,
    payload: Any,
) -> tuple[str | None, str, JSONResponse | None]:
    """幂等前置检查：返回 (key, 指纹, 需要直接回放的响应或 None)."""
    from cndb.plugins.tables.services.core.idempotency import (
        find_replay,
        normalize_key,
        request_fingerprint,
    )

    if header is None:
        return None, "", None
    key = normalize_key(header)
    if key is None:
        raise HTTPException(status_code=400, detail="Idempotency-Key 必须是非空且 ≤128 字符的字符串")
    fingerprint = request_fingerprint(payload)
    try:
        hit, response, status_code = find_replay(
            db,
            user_id=getattr(user, "id", None),
            key=key,
            route=route,
            fingerprint=fingerprint,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if hit and response is not None:
        return key, fingerprint, JSONResponse(status_code=int(status_code or 200), content=response)
    return key, fingerprint, None


def _idempotency_store(
    db: Session,
    user: User,
    key: str | None,
    route: str,
    fingerprint: str,
    status_code: int,
    response: Any,
) -> None:
    """登记首个成功响应（key 为空时 no-op）."""
    if key is None or not isinstance(response, dict):
        return
    from cndb.plugins.tables.services.core.idempotency import store_replay

    store_replay(
        db,
        user_id=getattr(user, "id", None),
        key=key,
        route=route,
        fingerprint=fingerprint,
        status_code=int(status_code),
        response=response,
    )


#: `trashed` 查询参数取值（ADR 0139 C2）：none = 默认只看活动行；only = 只看回收站；include = 两者都看
TRASHED_MODES = ("none", "only", "include")


def _trash_mode(trashed: str, include_trashed: bool) -> str:
    """归一化回收站过滤模式：`trashed` 显式值优先，`include_trashed` 作为旧参数别名."""
    mode = (trashed or "none").strip().lower()
    if mode not in TRASHED_MODES:
        raise HTTPException(status_code=400, detail=f"trashed 取值非法（可选 none / only / include）: {trashed}")
    if mode == "none" and include_trashed:
        return "include"
    return mode


#: 回收站彻底删除单次上限（ADR 0139 边界 2）
MAX_PURGE_ROWS = 200


def _ensure_all_trashed(db: Session, dt: DataTable, row_ids: list[int], user: User) -> None:
    """purge 前置校验：目标行必须全部在回收站里（ADR 0139 C4 / 边界 2）.

    - 越读范围 / 不存在 → 404（不泄露存在性）；
    - 存在但未软删 → 400（不静默物理删除活动行，整批不做部分成功）。
    """
    ids = [int(i) for i in row_ids]
    if not ids:
        raise HTTPException(status_code=400, detail="row_ids 不能为空")
    if len(ids) > MAX_PURGE_ROWS:
        raise HTTPException(status_code=400, detail=f"一次最多彻底删除 {MAX_PURGE_ROWS} 行")

    from cndb.plugins.tables.services.core.records import _build_row_scope_where

    sa_table = _get_sa_table(db.get_bind(), dt)
    where: list[Any] = [sa_table.c.id.in_(ids)]
    scope = _build_row_scope_where(dt, sa_table, db, user)
    if scope is not None:
        where.append(scope)
    engine: Any = db.get_bind()
    with engine.connect() as conn:
        found = {
            int(row[0]): bool(row[1])
            for row in conn.execute(select(sa_table.c.id, sa_table.c._trashed).where(*where)).all()
        }
    missing = [rid for rid in ids if rid not in found]
    if missing:
        raise HTTPException(status_code=404, detail=f"行不存在: {missing}")
    active = [rid for rid in ids if not found[rid]]
    if active:
        raise HTTPException(status_code=400, detail=f"只能彻底删除回收站中的行（仍活动的行: {active}）")


def revert_changes(db: Session, dt: DataTable, row_id: int, version: int) -> dict[str, Any]:
    """取某版本"撤销时要写回的值"（修改申请轨道复用；版本不存在返回空 dict）."""
    from cndb.plugins.tables.models import RecordRevision
    from cndb.plugins.tables.services.core.row_history import revert_values

    revision = (
        db.query(RecordRevision)
        .filter(
            RecordRevision.table_id == int(dt.id),
            RecordRevision.row_id == int(row_id),
            RecordRevision.version == int(version),
        )
        .first()
    )
    return revert_values(revision) if revision is not None else {}


def _trash_actors(db: Session, table_id: int, row_ids: list[int]) -> dict[int, tuple[int | None, str | None]]:
    """已删行的删除操作人：取该行最近一条 ``action='trash'`` 审计的 actor（ADR 0139 C2 / D3）."""
    if not row_ids:
        return {}
    entries = (
        db.query(AuditLog)
        .filter(
            AuditLog.table_id == table_id,
            AuditLog.action == ACTION_TRASH,
            AuditLog.target_id.in_(row_ids),
        )
        .order_by(AuditLog.id.desc())
        .all()
    )
    latest: dict[int, int | None] = {}
    for entry in entries:
        if entry.target_id is None:
            continue
        latest.setdefault(int(entry.target_id), entry.actor_id)
    actor_ids = {aid for aid in latest.values() if aid is not None}
    names: dict[int, str] = {}
    if actor_ids:
        names = {
            int(uid): str(username)
            for uid, username in db.query(User.id, User.username).filter(User.id.in_(actor_ids)).all()
        }
    return {row_id: (aid, names.get(int(aid)) if aid is not None else None) for row_id, aid in latest.items()}


def _dispatch_or_403(
    db: Session,
    dt: DataTable,
    user: User,
) -> bool:
    """双轨分派判定（设计 3.3 节）：可直编则校验表级 EDIT_RECORDS 权限并返回 True.

    直编条件：工作区角色 owner 恒直编；editor 需 allow_edit 开启；viewer 一律走修改申请。
    直编但表级权限受限时仍按原语义抛 403。
    """
    if not cr_services.can_write_directly(db, dt, user):
        return False
    if not check_action(db, dt, user, TableAction.EDIT_RECORDS):
        raise_permission_denied(db, dt.workspace, user, scope="表级")
    return True


#: 单行写路径按行分派结果（ADR 0004 §4）
ROW_WRITE_DIRECT = "direct"  # 在写范围内且可直编 → 原地落库
ROW_WRITE_CHANGE_REQUEST = "change_request"  # 可看不可改 / 无直编资格 → 生成修改申请（202）
ROW_WRITE_DENIED = "denied"  # 有直编资格但表级 EDIT_RECORDS 受限 → 403（存量语义）
ROW_WRITE_NOT_FOUND = "not_found"  # 读范围外 / 不存在 → 404（不泄露存在性，I6）


def _row_write_decision(db: Session, dt: DataTable, user: User, row_id: int) -> str:
    """单行 update / delete 的按行分派（ADR 0004 §4）.

    顺序：读范围外 → 404；写范围内且可直编 → 直编；其余按双轨制分派（可看不可改 → 202，
    有直编资格但表级阈值受限 → 403）。管理员在行范围判定中豁免（看到全表）。
    """
    sa_table = _get_sa_table(db.get_bind(), dt)
    if not can_view_row(db, dt, sa_table, row_id, user):
        return ROW_WRITE_NOT_FOUND
    direct_capable = cr_services.can_write_directly(db, dt, user)
    if direct_capable and can_edit_row(db, dt, sa_table, row_id, user):
        return ROW_WRITE_DIRECT
    if direct_capable and not check_action(db, dt, user, TableAction.EDIT_RECORDS):
        return ROW_WRITE_DENIED
    return ROW_WRITE_CHANGE_REQUEST


def _cr_response(
    db: Session,
    dt: DataTable,
    user: User,
    *,
    op: str,
    row_id: int | None,
    values: dict[str, Any],
) -> JSONResponse:
    """走修改申请轨道：自动生成申请并返回 202 载荷."""
    cr = cr_services.create_dispatch_request(db, dt, user, op, row_id, values)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"change_request": cr_services.serialize_request(cr)},
    )


def _list_response(
    db: Session,
    dt: DataTable,
    user: User,
    *,
    filters: list[dict[str, Any]] | None,
    filter_logic: str,
    sorts: list[dict[str, Any]] | None,
    limit: int,
    offset: int,
    trashed: str = "none",
    total: int | None = None,
) -> RecordListResponse:
    """调用 list_rows 并统一错误映射（ValueError→400，其余→500），GET/POST 列表端点共用.

    ``total`` 非空时跳过内部 COUNT（ADR 0046 D3 计数缓存命中路径）.
    ``trashed="only"`` 时按 ADR 0139 C2 附带删除时间与操作人.
    """
    only_trashed = trashed == "only"
    try:
        rows, total = list_rows(
            db.get_bind(),
            dt,
            filters=filters,
            filter_logic=filter_logic,
            sorts=sorts,
            limit=limit,
            offset=offset,
            include_trashed=trashed == "include",
            only_trashed=only_trashed,
            db=db,
            user=user,
            total=total,
        )
    except ValueError as exc:
        # 业务语义错误（未知操作符、非法字段等）— 客户端可修正
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # SQLAlchemy / 数据库等运行时错误 — 记录日志，避免把内部结构泄漏给客户端
        logger.exception("list_rows 运行时异常")
        raise HTTPException(status_code=500, detail="服务内部错误") from exc

    if only_trashed and rows:
        actors = _trash_actors(db, int(dt.id), [int(r["id"]) for r in rows if "id" in r])
        for row in rows:
            actor_id, actor_name = actors.get(int(row.get("id", 0)), (None, None))
            row["_trashed_by"] = actor_id
            row["_trashed_by_name"] = actor_name

    return RecordListResponse(rows=rows, total=total, limit=limit, offset=offset)


def _query_sig(
    *,
    filters: list[dict[str, Any]] | None,
    sorts: list[dict[str, Any]] | None,
    filter_logic: str,
    limit: int | None = None,
    offset: int | None = None,
) -> str:
    """查询体签名（缓存键的一段）；不含 limit/offset 时用于计数缓存（翻页不重算）."""
    body: dict[str, Any] = {"filters": filters or [], "sorts": sorts or [], "logic": filter_logic}
    if limit is not None:
        body["limit"] = limit
        body["offset"] = offset
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _cached_list(
    db: Session,
    dt: DataTable,
    user: User,
    *,
    filters: list[dict[str, Any]] | None,
    sorts: list[dict[str, Any]] | None,
    filter_logic: str,
    limit: int,
    offset: int,
    trashed: str = "none",
    cache_sig: str,
) -> RecordListResponse:
    """记录列表的统一读路径（GET/POST 共用）：排序索引 → 计数缓存 → 响应缓存（ADR 0046 D2/D3）."""
    from cndb.core.cache import cache_key, list_cache
    from cndb.plugins.tables.services.core.lookups import lookup_field_names

    # 深分页保护（ADR 0046 D8）：SQLite 的 OFFSET 线性扫描，400 万偏移实测 ~3s。
    # 超过上限直接给出可操作的提示，避免页面「假死」。
    if offset > MAX_RECORD_OFFSET:
        raise HTTPException(
            status_code=400,
            detail=(f"分页偏移过大（最多支持 OFFSET={MAX_RECORD_OFFSET}），请用筛选条件或搜索缩小范围后再翻页"),
        )

    workspace_id = int(dt.workspace_id)
    table_id = int(dt.id)
    engine_id = id(db.bind)

    ck = cache_key("records", workspace_id, table_id, user.id, trashed, cache_sig, engine_id)
    cached = list_cache.get(ck)
    if cached is not None:
        return cached

    # 视图排序索引：首个匹配查询一次性建（幂等），失败只降级为慢查询、不阻断读
    if sorts:
        try:
            ensure_sort_index(db, dt, sorts)
        except Exception:  # pragma: no cover - DDL 失败降级为无索引查询
            logger.warning("视图排序索引创建失败，降级为无索引查询 table=%s", dt.db_table_name, exc_info=True)

    total: int | None = None
    # 含 lookup 字段的表 total 需 attach 后内存修正，不走计数缓存（保守跳过）
    if db is not None and not lookup_field_names(dt):
        count_ck = cache_key(
            "records",
            workspace_id,
            table_id,
            "count",
            user.id,
            trashed,
            _query_sig(filters=filters, sorts=None, filter_logic=filter_logic),
            engine_id,
        )
        total = list_cache.get(count_ck)
        if total is None:
            try:
                total = count_rows(
                    db.get_bind(),
                    dt,
                    filters=filters,
                    filter_logic=filter_logic,
                    include_trashed=trashed == "include",
                    only_trashed=trashed == "only",
                    db=db,
                    user=user,
                )
            except ValueError as exc:
                # 计数与行数据同一处 WHERE 构建：非法操作符等业务语义错误同样映射 400
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if total is not None:
                list_cache.set(count_ck, total, RECORD_LIST_TTL_SECONDS)

    result = _list_response(
        db,
        dt,
        user,
        filters=filters,
        filter_logic=filter_logic,
        sorts=sorts,
        limit=limit,
        offset=offset,
        trashed=trashed,
        total=total,
    )
    list_cache.set(ck, result, RECORD_LIST_TTL_SECONDS)
    return result


@router.post("", status_code=status.HTTP_201_CREATED, response_model=None)
def create_record(
    workspace_id: int,
    table_id: int,
    payload: RecordCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: IdempotencyHeader = None,
) -> dict[str, object] | JSONResponse:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    route = f"POST /workspaces/{workspace_id}/tables/{table_id}/records"
    key, fingerprint, replay = _idempotency_guard(db, current_user, idempotency_key, route, payload.values)
    if replay is not None:
        return replay

    if not _dispatch_or_403(db, dt, current_user):
        return _cr_response(db, dt, current_user, op=CHANGE_OP_CREATE, row_id=None, values=payload.values)

    try:
        row = create_row(db.get_bind(), dt, payload.values, db=db, user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.exception("create_row 运行时异常")
        raise HTTPException(status_code=500, detail="服务内部错误") from exc

    if row is None:
        raise HTTPException(status_code=500, detail="创建失败")
    _idempotency_store(db, current_user, key, route, fingerprint, status.HTTP_201_CREATED, row)
    return row


@router.get("", response_model=RecordListResponse)
def list_records_get(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=5000),
    filters: str | None = Query(default=None),
    sorts: str | None = Query(default=None),
    filter_logic: str = Query(default="AND", pattern="^(AND|OR)$"),
    include_trashed: bool = Query(default=False),
    trashed: str = Query(default="none", description="none / only（回收站）/ include"),
) -> RecordListResponse:
    """GET /records - 前端友好的列表端点.

    sorts / filters 为 URL 编码的 JSON 字符串. 解析失败时降级为空列表
    而非报错，确保分页等基础功能不被参数格式阻断.
    """
    import json as _json

    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    def _parse(s: str | None, label: str) -> list[dict[str, Any]] | None:
        if not s:
            return None
        try:
            v = _json.loads(s)
        except _json.JSONDecodeError:
            logger.warning("%s JSON 解析失败，降级为空", label)
            return None
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        return None

    parsed_filters = _parse(filters, "filters")
    parsed_sorts = _parse(sorts, "sorts")
    mode = _trash_mode(trashed, include_trashed)
    # GET 与 POST /list 共用同一读路径（缓存 / 计数缓存 / 排序索引）—— 前端网格实际走 GET
    return _cached_list(
        db,
        dt,
        current_user,
        filters=parsed_filters,
        sorts=parsed_sorts,
        filter_logic=filter_logic,
        limit=limit,
        offset=offset,
        trashed=mode,
        cache_sig=_query_sig(
            filters=parsed_filters,
            sorts=parsed_sorts,
            filter_logic=filter_logic,
            limit=limit,
            offset=offset,
        ),
    )


@router.post("/list", response_model=RecordListResponse)
def list_records(
    workspace_id: int,
    table_id: int,
    payload: RecordListRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_trashed: bool = Query(default=False),
    trashed: str = Query(default="none", description="none / only（回收站）/ include"),
) -> RecordListResponse:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    # 记录列表是表格页最热的读路径：按（工作区/表/用户/查询体）缓存 5s。
    # 必须带 user_id —— 行级权限（tables_tablepermission）是按人过滤的，不能跨用户复用。
    # 失效：记录写入会写入 record.* 统一事件，事件钩子统一清该工作区的记录缓存。
    # 批量导入 / 数据同步不写 audit，由 records._invalidate_search_cache 兜底清理。
    body_sig = hashlib.sha256(payload.model_dump_json().encode("utf-8")).hexdigest()[:16]
    return _cached_list(
        db,
        dt,
        current_user,
        filters=payload.filters if payload.filters else None,
        sorts=payload.sorts if payload.sorts else None,
        filter_logic=payload.filter_logic,
        limit=payload.limit,
        offset=payload.offset,
        trashed=_trash_mode(trashed, include_trashed),
        cache_sig=body_sig,
    )


@router.get("/auto-increment-preview", response_model=AutoIncrementPreviewResponse)
def auto_increment_preview(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AutoIncrementPreviewResponse:
    """预览本表所有自动编号字段的下一个值（新增行只读展示；不落库）.

    必须注册在 ``/{record_id}`` 之前 —— 否则会被按 int 解析成 422。
    与建行路径共用 ``next_increment_value``：按库内已有数据（含软删行）取
    max + 1，并受 ``increment_start`` 下限约束，展示值与保存后生成值同口径。
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    return AutoIncrementPreviewResponse(values=preview_auto_increment_values(db.get_bind(), dt))


@router.post("/matrix-upsert", response_model=None)
def matrix_upsert(
    workspace_id: int,
    table_id: int,
    payload: MatrixUpsertRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object] | JSONResponse | Response:
    """评分矩阵单元格 upsert（ADR 0136）.

    - 键 =（单选对象字段, 月份字段所在月）；月份按 [当月1日, 次月1日) 匹配；
    - 0 行 → 新建（月份写当月 1 日）；1 行 → 只更新得分；多行 → 409 不写；
    - 写入复用现有 create / update 双轨分派（修改申请 202 / 403 / 404 口径不变）；
    - 表配置行级权限时禁用（避免看不到已有行而重复建行）。
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    fields = {f.name: f for f in dt.fields if not f.trashed}
    row_def = fields.get(payload.row_field)
    month_def = fields.get(payload.month_field)
    value_def = fields.get(payload.value_field)
    missing = [
        name
        for name, definition in (
            (payload.row_field, row_def),
            (payload.month_field, month_def),
            (payload.value_field, value_def),
        )
        if definition is None
    ]
    if missing:
        raise HTTPException(status_code=400, detail=f"评分矩阵字段不存在: {missing}")
    assert row_def is not None and month_def is not None and value_def is not None
    if len({payload.row_field, payload.month_field, payload.value_field}) != 3:
        raise HTTPException(status_code=400, detail="对象 / 月份 / 得分别必须是不同字段")

    row_ft = default_registry.get(row_def.field_type)
    month_ft = default_registry.get(month_def.field_type)
    value_ft = default_registry.get(value_def.field_type)
    if row_ft is None or row_ft.name != "select":
        raise HTTPException(status_code=400, detail="评分矩阵的对象字段必须是单选类型")
    if month_ft is None or month_ft.name != "date":
        raise HTTPException(status_code=400, detail="评分矩阵的月份字段必须是日期类型")
    if value_ft is None or value_ft.name not in {"number", "float", "percentage"}:
        raise HTTPException(status_code=400, detail="评分矩阵的得分字段必须是数字类型")

    hidden = get_hidden_field_names(db, dt, current_user)
    hidden_hit = hidden & {payload.row_field, payload.month_field, payload.value_field}
    if hidden_hit:
        raise HTTPException(status_code=403, detail=f"评分矩阵字段被权限隐藏: {sorted(hidden_hit)}")
    if row_rules_active(db, dt) and not row_filters_bypass(db, dt, current_user):
        raise HTTPException(status_code=403, detail="该表配置了行级权限，评分矩阵不支持录入")

    try:
        month_start, month_end = month_bounds(payload.month)
        row_value = row_ft.validate_value(payload.row_value, row_def.config or {})
        value = value_ft.validate_value(payload.value, value_def.config or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row_value is None or str(row_value).strip() == "":
        raise HTTPException(status_code=400, detail="评分矩阵的对象值不能为空")

    row_ids = find_month_key_rows(
        db.get_bind(),
        dt,
        payload.row_field,
        str(row_value),
        payload.month_field,
        month_start,
        month_end,
    )
    if len(row_ids) > 1:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": f"该对象在 {payload.month} 存在 {len(row_ids)} 行重复记录，未写入；请先在表格视图清理重复行",
                "row_ids": row_ids,
            },
        )

    if not row_ids:
        if value is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        values = {
            payload.row_field: str(row_value),
            payload.month_field: month_start.isoformat(),
            payload.value_field: value,
        }
        if not _dispatch_or_403(db, dt, current_user):
            return _cr_response(db, dt, current_user, op=CHANGE_OP_CREATE, row_id=None, values=values)
        try:
            row = create_row(db.get_bind(), dt, values, db=db, user=current_user)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            logger.exception("matrix_upsert 新建行失败")
            raise HTTPException(status_code=500, detail="评分单元格保存失败") from exc
        if row is None:
            raise HTTPException(status_code=500, detail="评分单元格保存失败")
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=jsonable_encoder({"action": "created", "row_id": row["id"], "row": row}),
        )

    row_id = row_ids[0]
    decision = _row_write_decision(db, dt, current_user, row_id)
    if decision == ROW_WRITE_NOT_FOUND:
        raise HTTPException(status_code=404, detail="行不存在")
    if decision == ROW_WRITE_DENIED:
        raise_permission_denied(db, dt.workspace, current_user, scope="表级")
    if decision == ROW_WRITE_CHANGE_REQUEST:
        return _cr_response(
            db,
            dt,
            current_user,
            op=CHANGE_OP_UPDATE,
            row_id=row_id,
            values={payload.value_field: value},
        )
    try:
        row = update_row(
            db.get_bind(),
            dt,
            row_id,
            {payload.value_field: value},
            db=db,
            user=current_user,
            enforce_row_rules=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="行不存在")
    return {"action": "updated", "row_id": row_id, "row": row}


@router.post("/aggregate", response_model=None)
def aggregate_records(
    workspace_id: int,
    table_id: int,
    payload: AggregateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """服务端聚合 / 分组（需求 0147）：GROUP BY 下推 SQL，行级权限与软删过滤无条件生效."""
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    try:
        return aggregate_rows(
            db.get_bind(),
            dt,
            group_by=payload.group_by,
            metrics=[metric.model_dump() for metric in payload.metrics],
            filters=payload.filters or None,
            filter_logic=payload.filter_logic,
            order_by=payload.order_by,
            limit=payload.limit,
            db=db,
            user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/copy", status_code=status.HTTP_201_CREATED, response_model=None)
def copy_records(
    workspace_id: int,
    table_id: int,
    payload: RecordCopyRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """复制行（需求 0092）：按源行原值批量创建，不触发自动填充 / 默认值 / 自动编号.

    - 行读范围与 ``GET /{record_id}`` 同源：范围外 / 已删除的行 404；
    - 复制全部物理列原值（含被隐藏的字段，但响应不回显），关联字段按目标 id 复制；
    - 复制属于「新增行」：需要表级 EDIT_RECORDS 权限（与批量建行一致）。
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)
    rows: list[dict[str, Any]] = []
    for row_id in payload.row_ids:
        values = copy_row_values(db.get_bind(), dt, row_id, db=db, user=current_user)
        if values is None:
            raise HTTPException(status_code=404, detail=f"行 {row_id} 不存在或不可见")
        rows.append(values)
    try:
        ids = bulk_create(db.get_bind(), dt, rows, db=db, exact_copy=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"created": len(ids), "ids": ids}


@router.get("/{record_id}")
def get_record(
    workspace_id: int,
    table_id: int,
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    row = get_row(db.get_bind(), dt, record_id, db=db, user=current_user)
    if row is None:
        raise HTTPException(status_code=404, detail="行不存在")
    return row


@router.patch("/{record_id}", response_model=None)
def update_record(
    workspace_id: int,
    table_id: int,
    record_id: int,
    payload: RecordUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, object] | JSONResponse:
    """更新一行（ADR 0140）：带 `If-Match` 时做乐观并发校验，不一致返回 409 record_stale."""
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    try:
        etag = parse_if_match(if_match)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    expected_rev = etag[1] if etag is not None else None

    decision = _row_write_decision(db, dt, current_user, record_id)
    if decision == ROW_WRITE_NOT_FOUND:
        raise HTTPException(status_code=404, detail="行不存在")
    if decision == ROW_WRITE_DENIED:
        raise_permission_denied(db, dt.workspace, current_user, scope="表级")
    if decision == ROW_WRITE_CHANGE_REQUEST:
        return _cr_response(db, dt, current_user, op=CHANGE_OP_UPDATE, row_id=record_id, values=payload.values)

    try:
        row = update_row(
            db.get_bind(),
            dt,
            record_id,
            payload.values,
            db=db,
            user=current_user,
            enforce_row_rules=True,
            expected_rev=expected_rev,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if row is None:
        raise HTTPException(status_code=404, detail="行不存在")
    return row


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_record(
    workspace_id: int,
    table_id: int,
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    soft: bool = Query(default=True, description="软删除 vs 硬删除"),
) -> Response:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    decision = _row_write_decision(db, dt, current_user, record_id)
    if decision == ROW_WRITE_NOT_FOUND:
        raise HTTPException(status_code=404, detail="行不存在")
    if decision == ROW_WRITE_DENIED:
        raise_permission_denied(db, dt.workspace, current_user, scope="表级")
    if decision == ROW_WRITE_CHANGE_REQUEST:
        return _cr_response(db, dt, current_user, op=CHANGE_OP_DELETE, row_id=record_id, values={})

    if soft:
        ok = trash_row(db.get_bind(), dt, record_id, db=db, user=current_user, enforce_row_rules=True)
    else:
        ok = delete_row(db.get_bind(), dt, record_id, db=db, user=current_user, enforce_row_rules=True)

    if not ok:
        raise HTTPException(status_code=404, detail="行不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{record_id}/restore", status_code=status.HTTP_200_OK)
def restore_record(
    workspace_id: int,
    table_id: int,
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)
    ok = restore_row(db.get_bind(), dt, record_id, db=db, user=current_user)
    if not ok:
        raise HTTPException(status_code=404, detail="行不存在或未在回收站中")
    row = get_row(db.get_bind(), dt, record_id, db=db, user=current_user)
    if row is None:  # pragma: no cover - 防御性
        raise HTTPException(status_code=500, detail="恢复后读取失败")
    return row


@router.get("/{record_id}/history", response_model=None)
def get_record_history(
    workspace_id: int,
    table_id: int,
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """行级历史（ADR 0144）：版本倒序，含操作人快照与变化字段.

    可见性口径与行读取一致：调用者必须能看到该行（行级权限范围外 → 404）。
    """
    from cndb.plugins.tables.services.core.row_history import list_revisions

    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    if get_row(db.get_bind(), dt, record_id, db=db, user=current_user) is None:
        raise HTTPException(status_code=404, detail="行不存在")
    revisions = list_revisions(db, dt, record_id, limit=limit)
    return [
        {
            "id": int(item.id),
            "row_id": int(item.row_id),
            "version": int(item.version),
            "op": item.op,
            "actor_id": item.actor_id,
            "actor_name": item.actor_name,
            "diff": dict(item.diff or {}),
            "created_at": item.created_at.isoformat() if item.created_at is not None else None,
        }
        for item in revisions
    ]


@router.post("/{record_id}/revert/{version}", response_model=None)
def revert_record_version(
    workspace_id: int,
    table_id: int,
    record_id: int,
    version: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object] | JSONResponse:
    """把行恢复到指定版本之前的值（生成新版本，不改历史；ADR 0144 D3）."""
    from cndb.plugins.tables.services.core.row_history import revert_revision

    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    decision = _row_write_decision(db, dt, current_user, record_id)
    if decision == ROW_WRITE_NOT_FOUND:
        raise HTTPException(status_code=404, detail="行不存在")
    if decision == ROW_WRITE_DENIED:
        raise_permission_denied(db, dt.workspace, current_user, scope="表级")
    if decision == ROW_WRITE_CHANGE_REQUEST:
        # 撤销同样走修改申请轨道：先算出差量再提交申请
        row = revert_revision(db, dt, record_id, version, user=current_user, enforce_row_rules=False)
        if row is None:
            raise HTTPException(status_code=404, detail="版本不存在")
        return _cr_response(
            db,
            dt,
            current_user,
            op=CHANGE_OP_UPDATE,
            row_id=record_id,
            values=revert_changes(db, dt, record_id, version),
        )

    try:
        row = revert_revision(db, dt, record_id, version, user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    return row


@router.post("/restore", response_model=None)
def restore_records(
    workspace_id: int,
    table_id: int,
    payload: BulkRowIds,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    """批量恢复回收站行（ADR 0139 C3）：只处理当前已删且在读范围内的行."""
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)
    restored = restore_rows(db.get_bind(), dt, payload.row_ids, db=db, user=current_user)
    return {"restored": restored}


@router.post("/purge", response_model=None)
def purge_records(
    workspace_id: int,
    table_id: int,
    payload: BulkRowIds,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    """批量彻底删除回收站行（ADR 0139 C4）：非已删行一律 400，不做部分成功."""
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)
    _ensure_all_trashed(db, dt, payload.row_ids, current_user)
    purged = purge_rows(db.get_bind(), dt, payload.row_ids, db=db, user=current_user)
    return {"purged": purged}


@router.post("/{record_id}/purge", response_model=None)
def purge_record(
    workspace_id: int,
    table_id: int,
    record_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """彻底删除单行（仅限已进回收站的行，ADR 0139 C4）."""
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_RECORDS)
    _ensure_all_trashed(db, dt, [record_id], current_user)
    purged = purge_rows(db.get_bind(), dt, [record_id], db=db, user=current_user)
    if purged == 0:
        raise HTTPException(status_code=404, detail="行不存在或未在回收站中")
    return {"id": record_id, "purged": True}
