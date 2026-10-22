"""cndb sync 子命令 —— 数据源同步的运维入口（生产建议配系统 cron）。

子命令：
- ``list``         列出同步任务（名称 / 来源 / 目标表 / 调度 / 上次状态）
- ``run``          立即执行（``--job-id`` 指定一条，或 ``--all`` 跑全部启用的）
- ``tick``         到期扫描（cron 每分钟调一次；``--job-id`` 只看某条）
- ``preview``      只抓不落库，打印前 N 行与失败明细
- ``batch-kline``  按批创建 / 更新 K 线同步任务（全市场分片，每批 ≤100 只，错峰调度）

示例：
    cndb sync tick                       # 系统 cron：* * * * * cndb sync tick
    cndb sync run --job-id 3 --dry-run   # 演练：只抓不写
    cndb sync list --json
    cndb sync batch-kline --workspace 数据源示例 --market A --batch-size 100
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

# ── batch-kline：全市场分片同步 ─────────────────────

# 单 job 标的数上限：东方财富按 secid 逐个请求，批次过大既拖长单次运行
# 也会让单个 job 的失败面覆盖整轮（ADR 0011 D5）
MAX_BATCH_SIZE = 100

# K 线序列 → 请求参数与目标列（与示例 datasource.json 的 5 个 job 同口径）
KLINE_SERIES: dict[str, dict[str, str]] = {
    "day_qfq": {"klt": "101", "fqt": "1", "label": "日线前复权", "field": "日线前复权"},
    "day_hfq": {"klt": "101", "fqt": "2", "label": "日线后复权", "field": "日线后复权"},
    "day_none": {"klt": "101", "fqt": "0", "label": "日线不复权", "field": "日线不复权"},
    "week_qfq": {"klt": "102", "fqt": "1", "label": "周线前复权", "field": "周线前复权"},
    "month_qfq": {"klt": "103", "fqt": "1", "label": "月线前复权", "field": "月线前复权"},
}

# 市场 → 任务名可读标签
_MARKET_LABELS = {"A": "A股", "HK": "港股", "US": "美股", "ALL": "全市场"}

_EASTMONEY_KLINE_BASE = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}"
    "&fields1=f1,f2,f3,f4,f5,f6"
    "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
)


def _kline_url(klt: str, fqt: str) -> str:
    """拼出带周期 / 复权参数的 K 线 URL 模板（``{secid}`` 由 provider 注入）."""
    return f"{_EASTMONEY_KLINE_BASE}&klt={klt}&fqt={fqt}&beg=0&end=20500101&lmt=100000"


def _series_mapping(series_key: str) -> dict[str, dict[str, str]]:
    """单个序列的字段映射；日线前复权额外写最新行情快照列."""
    target = KLINE_SERIES[series_key]["field"]
    mapping: dict[str, dict[str, str]] = {
        "symbol": {"name": "股票代码", "field_type": "text"},
        "kline": {"name": target, "field_type": "json"},
    }
    if series_key == "day_qfq":
        mapping.update(
            {
                "name": {"name": "股票名称", "field_type": "text"},
                "latest_date": {"name": "最新交易日", "field_type": "date"},
                "latest_close": {"name": "最新价", "field_type": "float"},
                "latest_pct_change": {"name": "涨跌幅", "field_type": "float"},
                "latest_volume": {"name": "成交量", "field_type": "float"},
                "latest_amount": {"name": "成交额", "field_type": "float"},
            }
        )
    return mapping


def _parse_series(text: str) -> list[str]:
    """``--series`` → 去重保序的序列列表；未知值直接报错."""
    keys: list[str] = []
    for part in str(text or "").split(","):
        key = part.strip()
        if key and key not in keys:
            keys.append(key)
    unknown = [key for key in keys if key not in KLINE_SERIES]
    if not keys or unknown:
        raise SystemExit(f"[error] --series 含未知序列 {unknown or keys}，可选: {', '.join(KLINE_SERIES)}")
    return keys


def _staggered_at(base: str, offset_minutes: int) -> str:
    """把 ``HH:MM`` 后移 N 分钟（按 24h 环绕），用于批次错峰."""
    hour_text, _, minute_text = str(base or "").partition(":")
    try:
        hour, minute = int(hour_text), int(minute_text)
    except ValueError as exc:
        raise SystemExit(f"[error] --at 必须是 HH:MM: {base!r}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise SystemExit(f"[error] --at 超出范围: {base!r}")
    total = (hour * 60 + minute + max(0, offset_minutes)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _get_session() -> Session:
    """按当前 settings.DATABASE_URL 打开 session（与 cndb docs / users 同口径）."""
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker

    import cndb.plugins.datasource.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401
    from cndb.core.config import settings
    from cndb.core.database import register_sqlite_pragmas
    from cndb.models.base import Base

    connect_args: dict[str, Any] = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, echo=settings.DEBUG)
    if "sqlite" in settings.DATABASE_URL:
        register_sqlite_pragmas(engine)
    inspector = inspect(engine)
    if not (inspector.has_table("datasource_sync_job") and inspector.has_table("datasource_session")):
        Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def cmd_list(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.datasource.models import DatasourceSyncJob

    db = _get_session()
    try:
        stmt = select(DatasourceSyncJob).order_by(DatasourceSyncJob.id)
        workspace_id = getattr(args, "workspace_id", None)
        if workspace_id is not None:
            stmt = stmt.where(DatasourceSyncJob.workspace_id == workspace_id)
        jobs = list(db.execute(stmt).scalars())
        return {
            "total": len(jobs),
            "jobs": [
                {
                    "id": job.id,
                    "workspace_id": job.workspace_id,
                    "name": job.name,
                    "provider": job.provider,
                    "table_id": job.table_id,
                    "enabled": job.enabled,
                    "schedule": job.schedule,
                    "last_run_at": job.last_run_at.isoformat() if job.last_run_at else None,
                    "last_status": job.last_status,
                    "cursor": job.cursor,
                }
                for job in jobs
            ],
        }
    finally:
        db.close()


def cmd_run(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.datasource.models import DatasourceSession, DatasourceSyncJob, RunStatus, RunTrigger
    from cndb.plugins.datasource.services.runner import execute_job, preview_job
    from cndb.plugins.datasource.services.scheduler import (
        LEASE_TTL_SECONDS,
        acquire_lease,
        default_owner,
        release_lease,
    )

    db = _get_session()
    owner = default_owner()
    try:
        if getattr(args, "job_id", None):
            job = db.get(DatasourceSyncJob, int(args.job_id))
            if job is None:
                raise SystemExit(f"[error] 同步任务不存在: {args.job_id}")
            jobs = [job]
        else:
            jobs = list(db.execute(select(DatasourceSyncJob).where(DatasourceSyncJob.enabled.is_(True))).scalars())

        results: list[dict[str, Any]] = []
        for job in jobs:
            if getattr(args, "dry_run", False):
                session = db.get(DatasourceSession, job.session_id) if job.session_id else None
                preview = preview_job(job, limit=int(getattr(args, "limit", 20) or 20), session=session, db=db)
                results.append(
                    {
                        "job_id": job.id,
                        "name": job.name,
                        "dry_run": True,
                        "status": preview.status,
                        "total": preview.total,
                        "columns": preview.columns,
                        "failures": preview.failures,
                        "rows": preview.rows,
                        # ADR 0019：llm_prompt 预览会给出自动识别的幂等键
                        "suggested_match_keys": preview.suggested_match_keys,
                    }
                )
                continue

            if not acquire_lease(db, job.id, owner, now=_now(), ttl_seconds=LEASE_TTL_SECONDS):
                results.append({"job_id": job.id, "name": job.name, "skipped": "租约已被占用"})
                continue
            try:
                execution = execute_job(db, job, trigger=RunTrigger.CLI)
                run = execution.run
                results.append(
                    {
                        "job_id": job.id,
                        "name": job.name,
                        "run_id": run.id,
                        "status": run.status,
                        "fetched": run.fetched,
                        "inserted": run.inserted,
                        "updated": run.updated,
                        "skipped_rows": run.skipped,
                        "cursor_from": execution.cursor_from,
                        "cursor_to": execution.cursor_to,
                        "error": run.error_message,
                    }
                )
            finally:
                release_lease(db, job.id, owner)
        failed = [item for item in results if item.get("status") == RunStatus.FAILED.value]
        return {"total": len(results), "failed": len(failed), "results": results}
    finally:
        db.close()


def cmd_tick(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.datasource.services.scheduler import tick

    db = _get_session()
    try:
        report = tick(
            db,
            now=_now(),
            limit=int(getattr(args, "limit", 20) or 20),
            job_id=int(args.job_id) if getattr(args, "job_id", None) else None,
            workspace_id=int(args.workspace_id) if getattr(args, "workspace_id", None) else None,
        )
        return report.to_dict()
    finally:
        db.close()


def cmd_preview(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.datasource.models import DatasourceSession, DatasourceSyncJob
    from cndb.plugins.datasource.services.runner import preview_job

    db = _get_session()
    try:
        job = db.get(DatasourceSyncJob, int(args.job_id))
        if job is None:
            raise SystemExit(f"[error] 同步任务不存在: {args.job_id}")
        session = db.get(DatasourceSession, job.session_id) if job.session_id else None
        preview = preview_job(job, limit=int(getattr(args, "limit", 20) or 20), session=session, db=db)
        return {
            "job_id": job.id,
            "name": job.name,
            "status": preview.status,
            "plans": preview.plans,
            "succeeded": preview.succeeded,
            "total": preview.total,
            "columns": preview.columns,
            "cursor_from": preview.cursor_from,
            "cursor_to": preview.cursor_to,
            "failures": preview.failures,
            "normalize_failures": preview.normalize_failures,
            # ADR 0019：llm_prompt 预览会给出自动识别的幂等键
            "suggested_match_keys": preview.suggested_match_keys,
            "rows": preview.rows,
        }
    finally:
        db.close()


def _resolve_workspace(db: Session, ref: str) -> Any:
    """解析 ``--workspace``：纯数字按 id，否则按名称（重名报错）."""
    from cndb.plugins.workspaces.models import Workspace

    text = str(ref).strip()
    if text.isdigit():
        ws = db.get(Workspace, int(text))
        if ws is None:
            raise SystemExit(f"[error] 工作区 id={text} 不存在")
        return ws
    matches = db.query(Workspace).filter(Workspace.name == text).all()
    if not matches:
        raise SystemExit(f"[error] 工作区名称 {text!r} 不存在")
    if len(matches) > 1:
        ids = ", ".join(str(w.id) for w in matches)
        raise SystemExit(f"[error] 工作区名称 {text!r} 不唯一（id: {ids}），请改用 id")
    return matches[0]


def _resolve_table(db: Session, workspace_id: int, ref: str) -> Any:
    """解析 ``--table``：纯数字按 id，否则按名称（限该工作区内，重名报错）."""
    from cndb.plugins.tables.models import DataTable

    text = str(ref).strip()
    if text.isdigit():
        dt = db.query(DataTable).filter(DataTable.id == int(text), DataTable.workspace_id == workspace_id).first()
        if dt is None:
            raise SystemExit(f"[error] 该工作区下不存在数据表 id={text}")
        return dt
    matches = db.query(DataTable).filter(DataTable.name == text, DataTable.workspace_id == workspace_id).all()
    if not matches:
        raise SystemExit(f"[error] 该工作区下不存在数据表名称 {text!r}")
    if len(matches) > 1:
        ids = ", ".join(str(t.id) for t in matches)
        raise SystemExit(f"[error] 数据表名称 {text!r} 不唯一（id: {ids}），请改用 id")
    return matches[0]


def _load_symbols(
    db: Session,
    table: Any,
    *,
    code_field: str,
    name_field: str,
    market_field: str,
    selected_field: str,
    only_selected: bool,
    market_key: str,
) -> list[dict[str, str]]:
    """从标的表读取代码 / 名称 / 市场（只取小列，不加载 K 线 JSON）.

    市场过滤按代码前缀判定（``sh``/``sz`` → A 股，``hk`` → 港股，``us`` → 美股），
    避免表内 ``市场`` 列为空时漏项；同一代码只保留首次出现。
    """
    from cndb.plugins.datasource.providers.eastmoney_symbols import MARKET_PREFIXES
    from cndb.plugins.tables.services.core.ddl import get_reflected_table

    field_by_name = {f.name: f for f in table.fields if not f.trashed}
    required = [code_field] + ([selected_field] if only_selected else [])
    missing = [name for name in required if name not in field_by_name]
    if missing:
        raise SystemExit(f"[error] 数据表 {table.name!r} 缺少字段: {', '.join(missing)}")

    engine = db.get_bind().engine
    sa_table = get_reflected_table(
        engine,
        table.db_table_name,
        missing_message=f"物理表 {table.db_table_name} 不存在，请先建表",
    )

    columns: dict[str, Any] = {"code": sa_table.c[field_by_name[code_field].db_column_name].label("code")}
    for label, alias in ((name_field, "name"), (market_field, "market")):
        field = field_by_name.get(label)
        if field is not None:
            columns[alias] = sa_table.c[field.db_column_name].label(alias)

    stmt = select(*columns.values())
    if only_selected:
        stmt = stmt.where(sa_table.c[field_by_name[selected_field].db_column_name].is_(True))

    prefixes = MARKET_PREFIXES[market_key]
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    with engine.connect() as conn:
        for row in conn.execute(stmt.order_by(columns["code"])).mappings():
            code = str(row.get("code") or "").strip()
            if not code or code in seen:
                continue
            if not code.lower().startswith(prefixes):
                continue
            seen.add(code)
            rows.append(
                {
                    "code": code,
                    "name": str(row.get("name") or "").strip(),
                    "market": str(row.get("market") or "").strip(),
                }
            )
    return rows


def _batch_plans(
    symbols: list[dict[str, str]],
    *,
    table_id: int,
    prefix: str,
    market_key: str,
    series_keys: list[str],
    batch_size: int,
    schedule_mode: str,
    at: str,
    stagger_minutes: int,
    rate_limit_ms: int,
) -> list[dict[str, Any]]:
    """把标的按批切片并展开为任务声明（每个序列 × 每个批次一条 job）."""
    chunks = [symbols[i : i + batch_size] for i in range(0, len(symbols), batch_size)]
    plans: list[dict[str, Any]] = []
    index = 0
    for series_key in series_keys:
        info = KLINE_SERIES[series_key]
        for batch_no, chunk in enumerate(chunks, start=1):
            name = f"{prefix}-{_MARKET_LABELS[market_key]}-{info['label']}-{batch_no:03d}"
            if schedule_mode == "manual":
                schedule: dict[str, Any] = {"mode": "manual"}
            else:
                schedule = {
                    "mode": "daily",
                    "at": _staggered_at(at, index * stagger_minutes),
                    "tz_offset_minutes": 480,
                }
            plans.append(
                {
                    "name": name,
                    "series": series_key,
                    "symbols": [item["code"] for item in chunk],
                    "schedule": schedule,
                    "fields": {
                        "provider": "eastmoney_kline",
                        "table_id": table_id,
                        "request_spec": {"url_template": _kline_url(info["klt"], info["fqt"])},
                        "parser": "json",
                        "entrant_param": "symbol",
                        "entrant_keys": [item["code"] for item in chunk],
                        "match_keys": ["股票代码"],
                        "field_mapping": _series_mapping(series_key),
                        "rate_limit_ms": rate_limit_ms,
                        "cursor": {"strategy": "none"},
                        "schedule": schedule,
                        "enabled": True,
                    },
                }
            )
            index += 1
    return plans


def cmd_batch_kline(args: argparse.Namespace) -> dict[str, Any]:
    """按批创建 / 更新 K 线同步任务（幂等：同名任务原地更新）."""
    from cndb.plugins.datasource.models import DatasourceSyncJob
    from cndb.plugins.datasource.providers.eastmoney_symbols import normalize_market

    series_keys = _parse_series(getattr(args, "series", "day_qfq"))
    market_key = normalize_market(getattr(args, "market", "ALL"))
    batch_size = int(getattr(args, "batch_size", MAX_BATCH_SIZE) or MAX_BATCH_SIZE)
    if batch_size < 1:
        raise SystemExit("[error] --batch-size 必须 >= 1")
    if batch_size > MAX_BATCH_SIZE:
        print(
            f"[sync batch-kline] --batch-size {batch_size} 超过上限，已收敛为 {MAX_BATCH_SIZE}",
            file=sys.stderr,
        )
        batch_size = MAX_BATCH_SIZE

    db = _get_session()
    try:
        ws = _resolve_workspace(db, args.workspace)
        table = _resolve_table(db, int(ws.id), getattr(args, "table", None) or "自选股")
        symbols = _load_symbols(
            db,
            table,
            code_field=str(getattr(args, "code_field", "股票代码")),
            name_field=str(getattr(args, "name_field", "股票名称")),
            market_field=str(getattr(args, "market_field", "市场")),
            selected_field=str(getattr(args, "selected_field", "是否自选")),
            only_selected=not getattr(args, "include_unselected", False),
            market_key=market_key,
        )

        # 目标列必须存在，否则写入阶段才报错（先在这里一次性抬断）
        valid_fields = {f.name for f in table.fields if not f.trashed}
        missing = sorted(
            {
                target["name"]
                for series_key in series_keys
                for target in _series_mapping(series_key).values()
                if target["name"] not in valid_fields
            }
        )
        if missing:
            raise SystemExit(f"[error] 数据表 {table.name!r} 缺少 K 线目标列: {', '.join(missing)}")

        plans = _batch_plans(
            symbols,
            table_id=int(table.id),
            prefix=str(getattr(args, "prefix", None) or "自选股K线"),
            market_key=market_key,
            series_keys=series_keys,
            batch_size=batch_size,
            schedule_mode=str(getattr(args, "schedule", "daily")),
            at=str(getattr(args, "at", "17:30") or "17:30"),
            stagger_minutes=int(getattr(args, "stagger_minutes", 2) or 0),
            rate_limit_ms=max(0, int(getattr(args, "rate_limit_ms", 400) or 0)),
        )

        dry_run = bool(getattr(args, "dry_run", False))
        existing = {
            str(job.name): job
            for job in db.execute(
                select(DatasourceSyncJob).where(
                    DatasourceSyncJob.workspace_id == int(ws.id),
                    DatasourceSyncJob.provider == "eastmoney_kline",
                    DatasourceSyncJob.table_id == int(table.id),
                    DatasourceSyncJob.name.startswith(f"{getattr(args, 'prefix', None) or '自选股K线'}-"),
                )
            ).scalars()
        }

        created = 0
        updated = 0
        jobs_report: list[dict[str, Any]] = []
        planned: set[str] = set()
        for plan in plans:
            planned.add(plan["name"])
            job = existing.get(plan["name"])
            action = "updated" if job is not None else "created"
            if not dry_run:
                if job is None:
                    job = DatasourceSyncJob(workspace_id=int(ws.id), created_by=None, name=plan["name"])
                    db.add(job)
                    created += 1
                else:
                    updated += 1
                for key, value in plan["fields"].items():
                    setattr(job, key, value)
            jobs_report.append(
                {
                    "name": plan["name"],
                    "series": plan["series"],
                    "symbols": len(plan["symbols"]),
                    "at": plan["schedule"].get("at", ""),
                    "action": "planned" if dry_run else action,
                }
            )

        leftovers: list[str] = sorted(set(existing) - planned)
        pruned: list[str] = []
        if getattr(args, "prune", False) and not dry_run:
            for name in leftovers:
                db.delete(existing[name])
                pruned.append(name)
            leftovers.clear()
        if not dry_run:
            db.commit()

        return {
            "workspace": {"id": int(ws.id), "name": str(ws.name)},
            "table": {"id": int(table.id), "name": str(table.name)},
            "market": market_key,
            "series": series_keys,
            "only_selected": not getattr(args, "include_unselected", False),
            "total_symbols": len(symbols),
            "batch_size": batch_size,
            "batches": len(plans) // max(1, len(series_keys)),
            "jobs": jobs_report,
            "created": 0 if dry_run else created,
            "updated": 0 if dry_run else updated,
            "pruned": pruned,
            "leftovers": leftovers,
            "dry_run": dry_run,
        }
    finally:
        db.close()


def _print_list(payload: dict[str, Any]) -> None:
    print(f"[sync] 共 {payload['total']} 个任务")
    for job in payload["jobs"]:
        state = "启用" if job["enabled"] else "停用"
        schedule = job["schedule"].get("mode", "manual") if isinstance(job["schedule"], dict) else "manual"
        print(
            f"  #{job['id']} {job['name']} [{state}] provider={job['provider']} "
            f"table={job['table_id']} schedule={schedule} "
            f"last={job['last_status'] or '-'}@{job['last_run_at'] or '-'}"
        )


def _print_run(payload: dict[str, Any]) -> None:
    for item in payload["results"]:
        if "skipped" in item:
            print(f"  #{item['job_id']} {item['name']} 跳过：{item['skipped']}")
            continue
        if item.get("dry_run"):
            print(
                f"  #{item['job_id']} {item['name']} [dry-run] status={item['status']} "
                f"rows={item['total']} columns={','.join(item['columns']) or '-'}"
            )
            for failure in item["failures"]:
                print(f"    ! {failure['label']}: {failure['error']}")
            continue
        print(
            f"  #{item['job_id']} {item['name']} run#{item['run_id']} status={item['status']} "
            f"fetched={item['fetched']} inserted={item['inserted']} updated={item['updated']} "
            f"cursor={item['cursor_from'] or '-'}→{item['cursor_to'] or '-'}"
        )
        if item.get("error"):
            print(f"    ! {item['error']}")
    print(f"[sync] 共 {payload['total']} 条，失败 {payload['failed']} 条")


def _print_tick(payload: dict[str, Any]) -> None:
    print(
        f"[sync tick] 到期 {payload['examined']}，执行 {payload['executed']}"
        f"（成功 {payload['succeeded']} / 失败 {payload['failed']}），"
        f"租约占用跳过 {payload['skipped_leased']}"
    )
    if payload["job_ids"]:
        print(f"  执行任务: {', '.join(f'#{job_id}' for job_id in payload['job_ids'])}")


def _print_preview(payload: dict[str, Any]) -> None:
    print(
        f"[sync preview] #{payload['job_id']} {payload['name']} status={payload['status']} "
        f"plans={payload['plans']} rows={payload['total']} "
        f"cursor={payload['cursor_from'] or '-'}→{payload['cursor_to'] or '-'}"
    )
    print(f"  列: {', '.join(payload['columns']) or '-'}")
    for failure in payload["failures"]:
        print(f"  ! {failure['label']}: {failure['error']}")
    for row in payload["rows"]:
        print(f"  {json.dumps(row, ensure_ascii=False, default=str)}")


def _print_batch_kline(payload: dict[str, Any]) -> None:
    ws = payload["workspace"]
    table = payload["table"]
    print(
        f"[sync batch-kline] 工作区 {ws['name']}(id={ws['id']}) / 表 {table['name']}(id={table['id']})"
        f" — market={payload['market']} series={','.join(payload['series'])}"
        f" 仅自选={payload['only_selected']}"
    )
    print(
        f"[sync batch-kline] 标的 {payload['total_symbols']} 只 → {payload['batches']} 批"
        f" × 每批 ≤{payload['batch_size']}，共 {len(payload['jobs'])} 个任务"
    )
    for job in payload["jobs"]:
        at = f" at={job['at']}" if job["at"] else ""
        print(f"  {job['action']:<7} {job['name']} symbols={job['symbols']}{at}")
    if payload["dry_run"]:
        print("[sync batch-kline] dry-run：未写库")
        return
    print(
        f"[sync batch-kline] 新建 {payload['created']}，更新 {payload['updated']}，删除 {len(payload['pruned'])} 个旧批次"
    )
    if payload["leftovers"]:
        print(f"[sync batch-kline] 另有 {len(payload['leftovers'])} 个同前缀旧任务不在本次分批内（加 --prune 可删除）")


def sync_command(args: argparse.Namespace) -> None:
    """分发 ``cndb sync <sub>``."""
    cmd = getattr(args, "sync_cmd", None)
    if cmd is None:
        print("[error] 缺少 sync 子命令，可用: list / run / tick / preview / batch-kline", file=sys.stderr)
        sys.exit(2)
    handlers = {
        "list": cmd_list,
        "run": cmd_run,
        "tick": cmd_tick,
        "preview": cmd_preview,
        "batch-kline": cmd_batch_kline,
    }
    printers = {
        "list": _print_list,
        "run": _print_run,
        "tick": _print_tick,
        "preview": _print_preview,
        "batch-kline": _print_batch_kline,
    }
    handler = handlers.get(cmd)
    if handler is None:  # pragma: no cover - argparse 已收窄
        print(f"[error] 未知 sync 子命令: {cmd}", file=sys.stderr)
        sys.exit(2)
    payload = handler(args)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        printers[cmd](payload)
    if cmd in ("run", "tick") and payload.get("failed"):
        sys.exit(1)


def register_sync_subparser(sub: Any) -> None:
    """向顶层 ArgumentParser 注册 `cndb sync` 子命令组."""
    p_sync = sub.add_parser("sync", help="数据源同步（list / run / tick / preview / batch-kline）")
    sync_sub = p_sync.add_subparsers(dest="sync_cmd")

    p_list = sync_sub.add_parser("list", help="列出同步任务")
    p_list.add_argument("--workspace-id", type=int, help="只看某个工作区")
    p_list.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_run = sync_sub.add_parser("run", help="立即执行（--job-id 指定一条，缺省跑全部启用的）")
    p_run.add_argument("--job-id", type=int, help="任务 id")
    p_run.add_argument("--dry-run", action="store_true", help="只抓不落库")
    p_run.add_argument("--limit", type=int, default=20, help="dry-run 打印行数上限")
    p_run.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_tick = sync_sub.add_parser("tick", help="到期扫描并执行（生产 cron 每分钟调用）")
    p_tick.add_argument("--job-id", type=int, help="只处理指定任务")
    p_tick.add_argument("--workspace-id", type=int, help="只处理指定工作区")
    p_tick.add_argument("--limit", type=int, default=20, help="单次最多处理任务数")
    p_tick.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_preview = sync_sub.add_parser("preview", help="只抓不落库，打印预览行")
    p_preview.add_argument("--job-id", type=int, required=True, help="任务 id")
    p_preview.add_argument("--limit", type=int, default=20, help="打印行数上限")
    p_preview.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_batch = sync_sub.add_parser(
        "batch-kline",
        help="按批创建/更新 K 线同步任务（全市场分片，每批 ≤100 只，默认错峰每日调度）",
    )
    p_batch.add_argument("--workspace", required=True, help="工作区 id 或名称（名称需唯一）")
    p_batch.add_argument("--table", default="自选股", help="标的表（id 或名称，默认 自选股）")
    p_batch.add_argument("--market", default="ALL", help="市场过滤：A/HK/US/ALL（也接受 A股/港股/美股）")
    p_batch.add_argument("--batch-size", type=int, default=MAX_BATCH_SIZE, help="每批标的数（上限 100）")
    p_batch.add_argument(
        "--series",
        default="day_qfq",
        help="K 线序列，逗号分隔：day_qfq,day_hfq,day_none,week_qfq,month_qfq",
    )
    p_batch.add_argument(
        "--include-unselected",
        action="store_true",
        help="不按「是否自选」过滤（全市场分批；默认只取 是否自选=true）",
    )
    p_batch.add_argument("--prefix", default="自选股K线", help="任务名前缀（同名任务原地更新）")
    p_batch.add_argument("--schedule", choices=["daily", "manual"], default="daily", help="新任务调度模式")
    p_batch.add_argument("--at", default="17:30", help="daily 调度的起始时刻 HH:MM")
    p_batch.add_argument("--stagger-minutes", type=int, default=2, help="相邻批次错峰分钟数")
    p_batch.add_argument("--rate-limit-ms", type=int, default=400, help="同一批内相邻请求间隔（毫秒）")
    p_batch.add_argument("--prune", action="store_true", help="删除同一前缀下多余的旧批次任务（默认保留并提示）")
    p_batch.add_argument("--dry-run", action="store_true", help="只打印分批计划，不写库")
    p_batch.add_argument("--json", action="store_true", help="以 JSON 输出")


__all__ = [
    "KLINE_SERIES",
    "MAX_BATCH_SIZE",
    "cmd_batch_kline",
    "cmd_list",
    "cmd_preview",
    "cmd_run",
    "cmd_tick",
    "register_sync_subparser",
    "sync_command",
]
