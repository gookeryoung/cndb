"""运行编排 —— 把一条 job 跑成「抓取 → 归一 → 落表 → 游标推进 → 留痕」.

唯一入口：

- :func:`execute_job`  真正跑一次并写 ``datasource_sync_run``（手动 / 调度 / CLI 共用）
- :func:`preview_job`  只抓不落库，返回行预览与失败明细（向导「抓取预览」用）

失败口径：异常不向外抛（调度器要继续处理下一条），统一落 ``status=failed`` +
``error_message``，并把逐请求失败写进 ``detail``。
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from cndb.core.crypto import decrypt_secrets
from cndb.plugins.datasource.models import (
    DatasourceSession,
    DatasourceSyncJob,
    DatasourceSyncRun,
    RunStatus,
    RunTrigger,
)
from cndb.plugins.datasource.providers.base import (
    FetchFn,
    FieldTransform,
    PagingSpec,
    RequestSpec,
    SyncJobSpec,
    TimeWindowSpec,
)
from cndb.plugins.datasource.services.auto_table import (
    candidate_names,
    ensure_job_table,
    infer_match_keys,
    is_table_empty,
)
from cndb.plugins.datasource.services.cursor import CursorConfig, advance, window_start
from cndb.plugins.datasource.services.pipeline import PipelineOutcome, run_pipeline
from cndb.plugins.datasource.services.write import WriteOutcome, upsert_rows

logger = logging.getLogger(__name__)

# 预览默认返回行数（前端表格一屏足够）
PREVIEW_LIMIT = 50


@dataclass(slots=True)
class JobExecution:
    """一次执行的完整结果（run 已落库）."""

    run: DatasourceSyncRun
    outcome: PipelineOutcome | None = None
    write: WriteOutcome | None = None
    cursor_from: str = ""
    cursor_to: str = ""


@dataclass(slots=True)
class PreviewResult:
    """只读预览结果（不落库、不推进游标）."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    columns: list[str] = field(default_factory=list)
    plans: int = 0
    succeeded: int = 0
    status: str = RunStatus.SUCCESS.value
    failures: list[dict[str, Any]] = field(default_factory=list)
    normalize_failures: list[dict[str, Any]] = field(default_factory=list)
    cursor_from: str = ""
    cursor_to: str = ""
    # 建议的幂等键（ADR 0019；仅 llm_prompt 计算，供前端向导回填 match_keys）
    suggested_match_keys: list[str] = field(default_factory=list)


def execute_job(
    db: Session,
    job: DatasourceSyncJob,
    *,
    trigger: RunTrigger | str = RunTrigger.MANUAL,
    user: Any = None,
    fetch: FetchFn | None = None,
    now: dt.datetime | None = None,
) -> JobExecution:
    """执行一次同步并写入运行记录.

    Args:
        db: 会话（运行记录 / 游标 / last_status 都写这里）。
        job: 任务定义。
        trigger: 触发来源，落库用于区分手动与调度。
        user: 触发用户（行级写范围判定）；定时任务传 ``None``。
        fetch: 注入的抓取函数（测试用假源）。
        now: 注入的当前时刻（测试用）。
    """
    started = now or dt.datetime.now(dt.UTC)
    started_clock = time.perf_counter()
    trigger_value = str(trigger)

    run = DatasourceSyncRun(
        job_id=job.id,
        status=RunStatus.RUNNING.value,
        trigger=trigger_value,
        started_at=started,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # 游标配置解析放在 try 内：坏配置要落成 failed 运行记录，而不是炸掉调度器
    cursor_config = CursorConfig(strategy="none")
    today = _as_utc(started).date().isoformat()
    cursor_from = ""
    cursor_to = ""

    try:
        cursor_config = CursorConfig.from_dict(job.cursor)
        cursor_from = window_start(cursor_config, today=today) or ""
        session = db.get(DatasourceSession, job.session_id) if job.session_id else None
        spec = build_job_spec(
            job,
            cursor_from=cursor_from,
            today=today,
            session=session,
            db=db,
            llm_user_id=getattr(user, "id", None) or job.created_by,
        )
        outcome = run_pipeline(spec, fetch=fetch, rate_limit_ms=max(0, int(job.rate_limit_ms or 0)))

        # ADR 0019：仅 llm_prompt 自动建表 / 补字段 / 推断幂等键，其它 provider 行为不变
        auto_landing = job.provider == "llm_prompt"
        if auto_landing and outcome.rows and job.table_id is None:
            ensure_job_table(db, job)
        write_outcome = _persist_rows(
            db,
            job,
            outcome.rows,
            user=user,
            auto_add_fields=auto_landing,
            auto_match_keys=auto_landing,
        )
        # 推断出幂等键时回填并持久化，后续运行沿用同一组键（重复运行只更新）
        if auto_landing and not [key for key in (job.match_keys or []) if key] and write_outcome.match_keys:
            job.match_keys = list(write_outcome.match_keys)
            db.add(job)
        cursor_to = advance(cursor_config, outcome.rows) or ""
        _finalize(
            run,
            outcome=outcome,
            write=write_outcome,
            cursor_from=cursor_from,
            cursor_to=cursor_to,
            started_clock=started_clock,
            now=started,
            auto_fields=write_outcome.auto_fields if auto_landing else [],
            auto_match_keys=write_outcome.match_keys if auto_landing else [],
        )
        _update_job_state(db, job, status=run.status, run_at=started, cursor=cursor_config, cursor_to=cursor_to)
        _record_event(db, job, run, user=user)
        return JobExecution(run=run, outcome=outcome, write=write_outcome, cursor_from=cursor_from, cursor_to=cursor_to)
    except Exception as exc:  # 运行失败不抛给调度器，落记录后继续
        logger.warning("同步任务 %s 执行失败: %s", job.id, exc, exc_info=True)
        db.rollback()
        run.status = RunStatus.FAILED.value
        run.error_message = str(exc)[:1000]
        run.finished_at = _as_utc(started)
        run.duration_ms = int((time.perf_counter() - started_clock) * 1000)
        run.cursor_from = cursor_from
        db.add(run)
        _update_job_state(db, job, status=RunStatus.FAILED.value, run_at=started, cursor=cursor_config, cursor_to="")
        _record_event(db, job, run, user=user)
        return JobExecution(run=run, cursor_from=cursor_from)


def preview_job(
    job: DatasourceSyncJob,
    *,
    fetch: FetchFn | None = None,
    now: dt.datetime | None = None,
    limit: int = PREVIEW_LIMIT,
    session: DatasourceSession | None = None,
    db: Session | None = None,
    user: Any = None,
) -> PreviewResult:
    """抓一次做预览：不落库、不推进游标、不写运行记录.

    ``db`` 用于读取已有目标表的字段名（推断建议幂等键的候选）与补充 llm_prompt
    个人连接默认值；``user`` 用于解析个人连接（无则回退 ``job.created_by``）。
    缺省时按行 key 推断，其它预览行为与旧接口一致。
    """
    current = now or dt.datetime.now(dt.UTC)
    today = _as_utc(current).date().isoformat()
    cursor_config = CursorConfig.from_dict(job.cursor)
    cursor_from = window_start(cursor_config, today=today) or ""

    spec = build_job_spec(
        job,
        cursor_from=cursor_from,
        today=today,
        session=session,
        db=db,
        llm_user_id=getattr(user, "id", None) or job.created_by,
    )
    outcome = run_pipeline(spec, fetch=fetch, rate_limit_ms=max(0, int(job.rate_limit_ms or 0)))
    normalized = outcome.normalize
    columns: list[str] = []
    if outcome.rows:
        columns = list(outcome.rows[0].keys())
    return PreviewResult(
        rows=outcome.rows[: max(1, limit)],
        total=len(outcome.rows),
        columns=columns,
        plans=outcome.plans,
        succeeded=outcome.succeeded,
        status=outcome.status,
        failures=[_failure_dict(item) for item in outcome.failures],
        normalize_failures=(
            [
                {"row_index": item.row_index, "field": item.field, "reason": item.reason}
                for item in normalized.failures[:50]
            ]
            if normalized is not None
            else []
        ),
        cursor_from=cursor_from,
        cursor_to=advance(cursor_config, outcome.rows) or "",
        suggested_match_keys=_suggested_match_keys(job, outcome.rows, db),
    )


# ── 配置还原 ─────────────────────────────────────


def build_job_spec(
    job: DatasourceSyncJob,
    *,
    cursor_from: str,
    today: str,
    session: DatasourceSession | None = None,
    db: Session | None = None,
    llm_user_id: int | None = None,
) -> SyncJobSpec:
    """把 DB 里的 JSON 声明还原成 ``SyncJobSpec``，注入时间窗口与会话凭证.

    会话（M5）贡献两部分：``headers`` 作为请求头**铺底**（job 自己的同名头优先），
    ``secrets`` 作为模板变量（请求模板里写 ``{api_key}`` 即可）。

    llm_prompt（ADR 0019）额外从**个人**大模型连接补默认值：会话 secrets 的
    ``api_key`` 优先，其次该用户个人连接配置的 Key；``request_spec`` 缺 ``url_template`` /
    ``llm.model`` 时用连接默认值补齐；连接的系统提示词作为
    ``extra_variables["system_prompt_default"]`` 交给 provider 使用。
    """
    payload = dict(job.request_spec or {})
    extra_variables: dict[str, Any] = {}
    if session is not None:
        merged_headers = {**(session.headers or {}), **(payload.get("headers_template") or {})}
        if merged_headers:
            payload["headers_template"] = merged_headers
        # 密钥列在库里是密文（core.crypto）；解密失败直接抛 SecretDecryptError，
        # 由外层 try 落成 failed 运行记录 —— 静默降级成空密钥只会变成难查的 401
        extra_variables = decrypt_secrets(session.secrets)
    if job.provider == "llm_prompt":
        user_id = llm_user_id if llm_user_id is not None else job.created_by
        connection = _load_llm_connection(db, user_id)
        if connection is not None:
            _apply_llm_connection(payload, extra_variables, connection)
    # 内置提示词变量（ADR 0014）：today 由本次运行时钟统一给出，保证重放一致
    extra_variables["today"] = today
    request = request_spec_from_payload(payload, cursor_from=cursor_from, today=today)
    return SyncJobSpec(
        request=request,
        provider=job.provider,
        entrant_param=job.entrant_param,
        entrant_values=tuple(job.entrant_keys or ()),
        match_keys=tuple(job.match_keys or ()),
        field_mapping=field_mapping_from_payload(job.field_mapping),
        parser=job.parser,
        extra_variables=extra_variables,
    )


def _load_llm_connection(db: Session | None, user_id: int | None) -> Any:
    """读取**个人**大模型连接配置（ADR 0019）；未注入 db（旧调用方）时返回 None."""
    if db is None:
        return None
    from cndb.plugins.datasource.services.connection import load_llm_connection

    if user_id is None:
        return None
    return load_llm_connection(db, user_id)


def _apply_llm_connection(
    payload: dict[str, Any],
    extra_variables: dict[str, Any],
    connection: Any,
) -> None:
    """用个人连接配置补齐 llm_prompt 的请求声明与模板变量（原地修改）."""
    api_key = str(getattr(connection, "api_key", "") or "").strip()
    if api_key and not str(extra_variables.get("api_key") or "").strip():
        # 会话 secrets 优先；没有会话 Key 时回退到连接配置
        extra_variables["api_key"] = api_key
    system_prompt = str(getattr(connection, "system_prompt", "") or "").strip()
    if system_prompt:
        extra_variables["system_prompt_default"] = system_prompt
    if not str(payload.get("url_template") or "").strip():
        base_url = str(getattr(connection, "base_url", "") or "").strip()
        if base_url:
            payload["url_template"] = base_url
    llm = dict(payload.get("llm") or {})
    if not str(llm.get("model") or "").strip():
        model = str(getattr(connection, "model", "") or "").strip()
        if model:
            llm["model"] = model
            payload["llm"] = llm


def _suggested_match_keys(
    job: DatasourceSyncJob,
    rows: list[dict[str, Any]],
    db: Session | None,
) -> list[str]:
    """预览阶段建议幂等键（ADR 0019）：仅 llm_prompt 计算，其它 provider 恒为空."""
    if job.provider != "llm_prompt" or not rows:
        return []
    field_names: list[str] = []
    if db is not None and job.table_id is not None:
        from cndb.plugins.tables.models import DataTable

        table = db.get(DataTable, job.table_id)
        if table is not None:
            field_names = [item.name for item in table.active_fields()]
    return infer_match_keys(rows, candidate_names(rows, field_names))


def request_spec_from_payload(
    payload: Mapping[str, Any] | None,
    *,
    cursor_from: str = "",
    today: str = "",
) -> RequestSpec:
    """JSON → ``RequestSpec``（只认白名单键，多余键忽略，避免历史配置阻塞运行）."""
    data = dict(payload or {})
    if not data.get("url_template"):
        raise ValueError("request_spec.url_template 缺失")
    time_window = dict(data.get("time_window") or {})
    if cursor_from and today and time_window.get("mode", "none") != "none":
        time_window["start"] = cursor_from
        time_window["end"] = today
    return RequestSpec(
        url_template=str(data["url_template"]),
        method=str(data.get("method") or "GET"),
        headers_template=dict(data.get("headers_template") or {}),
        params_template=dict(data.get("params_template") or {}),
        body_template=data.get("body_template"),
        data_path=data.get("data_path") or None,
        record_mode="columns" if data.get("record_mode") == "columns" else "rows",
        record_layout=dict(data.get("record_layout") or {}),
        encoding=str(data.get("encoding") or "utf-8"),
        timeout=float(data.get("timeout") or 15.0),
        paging=PagingSpec(**dict(data.get("paging") or {})),
        time_window=TimeWindowSpec(**time_window),
        prompt=dict(data.get("prompt") or {}),
        llm=dict(data.get("llm") or {}),
    )


def field_mapping_from_payload(payload: Mapping[str, Any] | None) -> dict[str, FieldTransform | None]:
    """JSON → ``{源字段: FieldTransform | None}``；null 表示丢弃该字段."""
    mapping: dict[str, FieldTransform | None] = {}
    for source, value in dict(payload or {}).items():
        if value is None:
            mapping[source] = None
            continue
        if isinstance(value, str):
            mapping[source] = FieldTransform(name=value)
            continue
        if isinstance(value, Mapping):
            name = value.get("name") or source
            mapping[source] = FieldTransform(name=str(name), field_type=str(value.get("field_type") or "text"))
            continue
        raise ValueError(f"field_mapping[{source!r}] 必须是对象 / 字符串 / null")
    return mapping


def validate_request_spec(payload: Mapping[str, Any] | None) -> RequestSpec:
    """创建 / 更新时的请求模板校验.

    ``time_window`` 为 ``range`` 时，``start`` / ``end`` 是运行时由游标注入的，
    创建阶段用占位日期通过校验（否则合法配置会被判非法）。
    """
    data = dict(payload or {})
    window = dict(data.get("time_window") or {})
    if window.get("mode") == "range":
        window.setdefault("start", "1970-01-01")
        window.setdefault("end", "1970-01-01")
        data["time_window"] = window
    return request_spec_from_payload(data)


# ── 内部 ─────────────────────────────────────────


def _persist_rows(
    db: Session,
    job: DatasourceSyncJob,
    rows: list[dict[str, Any]],
    *,
    user: Any,
    auto_add_fields: bool = False,
    auto_match_keys: bool = False,
) -> WriteOutcome:
    """写入目标表；未绑定表时跳过（只留抓取结果）.

    ``auto_add_fields`` / ``auto_match_keys`` 仅 llm_prompt 打开（ADR 0019）：
    前者只在目标表为空时生效（空表才允许补字段）。
    """
    if not rows or job.table_id is None:
        return WriteOutcome(fetched=len(rows))
    from cndb.plugins.tables.models import DataTable

    table = db.get(DataTable, job.table_id)
    if table is None:
        raise ValueError(f"目标表不存在: table_id={job.table_id}")
    empty = is_table_empty(db, table) if auto_add_fields else False
    return upsert_rows(
        db.get_bind(),
        db,
        table,
        rows,
        match_keys=job.match_keys or (),
        user=user,
        auto_add_fields=empty,
        auto_match_keys=auto_match_keys,
    )


def _finalize(
    run: DatasourceSyncRun,
    *,
    outcome: PipelineOutcome,
    write: WriteOutcome,
    cursor_from: str,
    cursor_to: str,
    started_clock: float,
    now: dt.datetime,
    auto_fields: list[str] | None = None,
    auto_match_keys: list[str] | None = None,
) -> None:
    normalized = outcome.normalize
    run.status = outcome.status
    run.fetched = write.fetched
    run.inserted = write.inserted
    run.updated = write.updated
    run.skipped = write.skipped
    run.cursor_from = cursor_from
    run.cursor_to = cursor_to
    run.finished_at = _as_utc(now)
    run.duration_ms = int((time.perf_counter() - started_clock) * 1000)
    run.detail = {
        "plans": outcome.plans,
        "succeeded": outcome.succeeded,
        "failures": [_failure_dict(item) for item in outcome.failures],
        "normalize_failures": (
            [
                {"row_index": item.row_index, "field": item.field, "reason": item.reason}
                for item in normalized.failures[:100]
            ]
            if normalized is not None
            else []
        ),
        "dropped_fields": normalized.dropped if normalized is not None else 0,
        "response_metadata": outcome.metadata[:50],
        # ADR 0019 留痕：自动补字段与自动推断出的幂等键（非 llm_prompt 恒为空）
        "auto_fields": list(auto_fields or []),
        "auto_match_keys": list(auto_match_keys or []),
    }
    if outcome.status == RunStatus.FAILED.value and outcome.failures:
        run.error_message = "; ".join(f"{item.label}: {item.error}" for item in outcome.failures[:3])[:1000]


def _update_job_state(
    db: Session,
    job: DatasourceSyncJob,
    *,
    status: str,
    run_at: dt.datetime,
    cursor: CursorConfig,
    cursor_to: str,
) -> None:
    job.last_run_at = _as_utc(run_at)
    job.last_status = status
    if cursor.is_windowed and cursor_to:
        job.cursor = CursorConfig(
            strategy=cursor.strategy,
            field=cursor.field,
            backfill_start=cursor.backfill_start,
            value=cursor_to,
        ).to_dict()
    db.add(job)
    db.commit()
    db.refresh(job)


def _record_event(db: Session, job: DatasourceSyncJob, run: DatasourceSyncRun, *, user: Any) -> None:
    from cndb.core.events import ACTION_DATASOURCE_SYNC, TARGET_DATASOURCE, record_event

    record_event(
        db,
        ACTION_DATASOURCE_SYNC,
        summary=f"数据源同步「{job.name}」{run.status}（新增 {run.inserted} / 更新 {run.updated}）",
        target_type=TARGET_DATASOURCE,
        target_id=job.id,
        workspace_id=job.workspace_id,
        actor_id=getattr(user, "id", None),
        actor_name=getattr(user, "username", None),
        detail={
            "run_id": run.id,
            "trigger": run.trigger,
            "status": run.status,
            "fetched": run.fetched,
            "inserted": run.inserted,
            "updated": run.updated,
            "skipped": run.skipped,
            "cursor_from": run.cursor_from,
            "cursor_to": run.cursor_to,
        },
    )


def _failure_dict(item: Any) -> dict[str, Any]:
    return {
        "label": item.label,
        "entrant": item.entrant,
        "page": item.page,
        "error": item.error,
    }


def _as_utc(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


__all__ = [
    "PREVIEW_LIMIT",
    "JobExecution",
    "PreviewResult",
    "build_job_spec",
    "execute_job",
    "field_mapping_from_payload",
    "preview_job",
    "request_spec_from_payload",
    "validate_request_spec",
]
