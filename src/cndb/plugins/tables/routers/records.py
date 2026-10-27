"""行数据路由."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
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
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.schemas import (
    AutoIncrementPreviewResponse,
    RecordCreate,
    RecordListRequest,
    RecordListResponse,
    RecordUpdate,
)
from cndb.plugins.tables.services.core.access import TableAction, check_action, get_table_or_404
from cndb.plugins.tables.services.core.ddl import ensure_sort_index
from cndb.plugins.tables.services.core.records import (
    _get_sa_table,
    count_rows,
    create_row,
    delete_row,
    get_row,
    list_rows,
    preview_auto_increment_values,
    restore_row,
    trash_row,
    update_row,
)
from cndb.plugins.tables.services.core.row_access import can_edit_row, can_view_row
from cndb.plugins.workspaces.permissions import raise_permission_denied

logger = logging.getLogger(__name__)
# 记录列表缓存 TTL（秒）：短 TTL + 事件驱动失效（record.* 事件提交后清该工作区记录缓存）
RECORD_LIST_TTL_SECONDS = 5.0

# 深分页偏移上限（ADR 0046 D8）：OFFSET 线性扫描，超过该值改为提示用户收窄筛选。
# 10 万偏移 = 每页 100 行时第 1000 页，覆盖正常浏览；更深的跳页在大表上必卡。
MAX_RECORD_OFFSET = 100_000


router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/records", tags=["records"])


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
    include_trashed: bool,
    total: int | None = None,
) -> RecordListResponse:
    """调用 list_rows 并统一错误映射（ValueError→400，其余→500），GET/POST 列表端点共用.

    ``total`` 非空时跳过内部 COUNT（ADR 0046 D3 计数缓存命中路径）.
    """
    try:
        rows, total = list_rows(
            db.get_bind(),
            dt,
            filters=filters,
            filter_logic=filter_logic,
            sorts=sorts,
            limit=limit,
            offset=offset,
            include_trashed=include_trashed,
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
    include_trashed: bool,
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

    ck = cache_key("records", workspace_id, table_id, user.id, include_trashed, cache_sig, engine_id)
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
            include_trashed,
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
                    include_trashed=include_trashed,
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
        include_trashed=include_trashed,
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
) -> dict[str, object] | JSONResponse:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    if not _dispatch_or_403(db, dt, current_user):
        return _cr_response(db, dt, current_user, op=CHANGE_OP_CREATE, row_id=None, values=payload.values)

    try:
        row = create_row(db.get_bind(), dt, payload.values, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.exception("create_row 运行时异常")
        raise HTTPException(status_code=500, detail="服务内部错误") from exc

    if row is None:
        raise HTTPException(status_code=500, detail="创建失败")
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
        include_trashed=include_trashed,
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
) -> RecordListResponse:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    # 记录列表是表格页最热的读路径：按（工作区/表/用户/查询体）缓存 5s。
    # 必须带 user_id —— 行级权限（tables_tablepermission）是按人过滤的，不能跨用户复用。
    # 失效：记录写入会写入 record.* 统一事件，事件钩子统一清该工作区的记录缓存。
    # 批量导入 / 数据源同步不写 audit，由 records._invalidate_search_cache 兜底清理。
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
        include_trashed=include_trashed,
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
) -> dict[str, object] | JSONResponse:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    decision = _row_write_decision(db, dt, current_user, record_id)
    if decision == ROW_WRITE_NOT_FOUND:
        raise HTTPException(status_code=404, detail="行不存在")
    if decision == ROW_WRITE_DENIED:
        raise_permission_denied(db, dt.workspace, current_user, scope="表级")
    if decision == ROW_WRITE_CHANGE_REQUEST:
        return _cr_response(db, dt, current_user, op=CHANGE_OP_UPDATE, row_id=record_id, values=payload.values)

    try:
        row = update_row(db.get_bind(), dt, record_id, payload.values, db=db, user=current_user, enforce_row_rules=True)
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
