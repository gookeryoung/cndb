"""对外推送 —— 把工作区数据表的行按批 POST/PUT 到外部接口（需求 0099）.

与抓取共用 ``datasource_sync_job`` / ``datasource_sync_run`` 与调度租约，但方向相反：
- 抓取：外部 → 工作区表（provider + parser + upsert）；
- 推送：工作区表 → 外部接口（读取表行 → 渲染请求 → HTTP 发送）。

``push_spec`` 只描述推送目标与批次，不引入第二套 HTTP 基础设施：SSRF 校验、
超时、重定向与响应上限复用 ``core.http.open_http_client``。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import MetaData, select
from sqlalchemy.orm import Session

from cndb.core.crypto import decrypt_secrets
from cndb.core.http import open_http_client, validate_url
from cndb.plugins.datasource.models import DatasourceSession, DatasourceSyncJob, DatasourceSyncRun
from cndb.plugins.datasource.providers.base import ProviderError
from cndb.plugins.datasource.providers.template import render_text
from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core.ddl import build_sa_table

PUSH_METHODS = ("POST", "PUT", "PATCH")
DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_ROWS = 5000


@dataclass(slots=True)
class PushOutcome:
    """一次推送的结果（与抓取 PipelineOutcome 解耦，供 runner 组装运行记录）."""

    rows_read: int = 0
    pushed: int = 0
    batches: int = 0
    failed_batches: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    cursor_from: str = ""
    cursor_to: str = ""
    # 发送过的 HTTP 状态码（排障留痕，最多保留前 50 条）
    responses: list[dict[str, Any]] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.batches and self.failed_batches >= self.batches:
            return "failed"
        if self.failed_batches:
            return "partial"
        return "success"


def validate_push_spec(
    push_spec: Mapping[str, Any] | None,
    *,
    table_id: int | None,
    db: Session,
    workspace_id: int,
) -> dict[str, Any]:
    """校验并归一推送配置；非法时抛 :class:`ProviderError`（路由层转 400）."""
    if table_id is None:
        raise ProviderError("推送任务必须选择源数据表")
    table = db.get(DataTable, table_id)
    if table is None or table.workspace_id != workspace_id or table.trashed_at is not None:
        raise ProviderError(f"源数据表不存在: {table_id}")
    raw = dict(push_spec or {})
    url_template = str(raw.get("url_template") or "").strip()
    if not url_template.startswith(("http://", "https://")):
        raise ProviderError("push_spec.url_template 必须是 http/https URL")
    method = str(raw.get("method") or "POST").upper()
    if method not in PUSH_METHODS:
        raise ProviderError(f"push_spec.method 只支持 {' / '.join(PUSH_METHODS)}")
    headers = raw.get("headers_template") or {}
    if not isinstance(headers, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()
    ):
        raise ProviderError("push_spec.headers_template 必须是字符串键值对象")
    body = raw.get("body_template")
    if body is not None and not isinstance(body, (dict, list, str)):
        raise ProviderError("push_spec.body_template 必须是对象 / 数组 / 字符串")
    batch_size = raw.get("batch_size", DEFAULT_BATCH_SIZE)
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 1000:
        raise ProviderError("push_spec.batch_size 必须是 1..1000 的整数")
    max_rows = raw.get("max_rows", DEFAULT_MAX_ROWS)
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or not 1 <= max_rows <= 100_000:
        raise ProviderError("push_spec.max_rows 必须是 1..100000 的整数")
    fields = raw.get("fields") or []
    if not isinstance(fields, list) or any(not isinstance(f, str) for f in fields):
        raise ProviderError("push_spec.fields 必须是字段名数组")
    field_names = {f.name for f in table.active_fields()}
    missing = [name for name in fields if name not in field_names]
    if missing:
        raise ProviderError(f"push_spec.fields 引用了不存在的字段: {', '.join(missing)}")
    watermark = str(raw.get("watermark_field") or "").strip()
    if watermark and watermark not in field_names:
        raise ProviderError(f"push_spec.watermark_field 引用了不存在的字段: {watermark}")
    timeout = raw.get("timeout", 30.0)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 1 <= float(timeout) <= 300:
        raise ProviderError("push_spec.timeout 必须是 1..300 秒")
    return {
        "url_template": url_template,
        "method": method,
        "headers_template": headers,
        "body_template": body,
        "batch_size": batch_size,
        "max_rows": max_rows,
        "fields": fields,
        "watermark_field": watermark,
        "timeout": float(timeout),
    }


def _render_body(template: Any, variables: Mapping[str, Any]) -> Any:
    """递归渲染请求体；``{rows}`` / ``{count}`` 等整值占位符保留 JSON 类型."""
    if isinstance(template, dict):
        return {str(k): _render_body(v, variables) for k, v in template.items()}
    if isinstance(template, list):
        return [_render_body(item, variables) for item in template]
    if isinstance(template, str):
        stripped = template.strip()
        if stripped in {"{rows}", "{count}", "{table}", "{job}", "{batch}"}:
            return variables.get(stripped[1:-1])
        return render_text(template, variables)
    return template


def _row_values(row: Any, fields: list[DataField], selected: Sequence[str] | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    selected_set = set(selected or [])
    for field_item in fields:
        if selected_set and field_item.name not in selected_set:
            continue
        value = getattr(row, field_item.db_column_name, None)
        if isinstance(value, (dt.date, dt.datetime)):
            value = value.isoformat()
        values[field_item.name] = value
    return values


def _watermark_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return str(value)


def execute_push(
    db: Session,
    job: DatasourceSyncJob,
    run: DatasourceSyncRun,
    *,
    session: DatasourceSession | None = None,
) -> PushOutcome:
    """执行一次推送：读源表 → 分批渲染 → HTTP 发送 → 返回计数 / 游标."""
    spec = validate_push_spec(job.push_spec, table_id=job.table_id, db=db, workspace_id=job.workspace_id)
    table = db.get(DataTable, job.table_id)
    if table is None:  # pragma: no cover - validate 已兜底
        raise ProviderError("源数据表不存在")
    all_fields = table.active_fields()
    field_by_name = {f.name: f for f in all_fields}
    watermark_field = field_by_name.get(spec["watermark_field"]) if spec["watermark_field"] else None
    metadata = MetaData()
    sa_table = build_sa_table(metadata, table)
    # link / lookup 等无物理列的字段不参与推送（避免发送一串 null）
    fields = [f for f in all_fields if f.db_column_name in sa_table.c]
    selected = spec["fields"] or [f.name for f in fields if not f.hidden]
    columns = [sa_table.c[f.db_column_name] for f in fields]
    stmt = select(*columns)
    if "_trashed" in sa_table.c:
        stmt = stmt.where(sa_table.c._trashed.is_(False))
    cursor_value = str((job.cursor or {}).get("value") or "")
    if watermark_field is not None and cursor_value:
        field_type = default_registry.get(watermark_field.field_type)
        if field_type is None:
            raise ProviderError(f"游标字段类型不支持: {watermark_field.field_type}")
        parsed = field_type.validate_value(cursor_value, watermark_field.config or {})
        col = sa_table.c[watermark_field.db_column_name]
        stmt = stmt.where(col > parsed)
    if watermark_field is not None:
        stmt = stmt.order_by(sa_table.c[watermark_field.db_column_name].asc(), sa_table.c.id.asc())
    else:
        stmt = stmt.order_by(sa_table.c.id.asc())
    stmt = stmt.limit(spec["max_rows"])

    rows = db.execute(stmt).all()
    outcome = PushOutcome(rows_read=len(rows), cursor_from=cursor_value)
    if not rows:
        run.detail = {**(run.detail or {}), "push": {"rows_read": 0, "pushed": 0, "batches": 0}}
        return outcome

    session_secrets = decrypt_secrets(session.secrets) if session is not None else {}
    session_headers = dict(session.headers or {}) if session is not None else {}
    variables = {
        "table": table.name,
        "job": job.name,
        "today": dt.date.today().isoformat(),
        **session_secrets,
    }
    headers = {**session_headers, **{k: render_text(v, variables) for k, v in spec["headers_template"].items()}}
    url = render_text(spec["url_template"], variables)
    validate_url(url)
    batch_size = int(spec["batch_size"])
    last_watermark = ""
    with open_http_client(timeout=spec["timeout"]) as client:
        for start in range(0, len(rows), batch_size):
            batch_rows = rows[start : start + batch_size]
            payload_rows = [_row_values(row, fields, selected) for row in batch_rows]
            batch_vars = {
                **variables,
                "rows": payload_rows,
                "count": len(payload_rows),
                "batch": outcome.batches + 1,
            }
            body = spec["body_template"]
            if body is None:
                body = {"rows": payload_rows}
            else:
                body = _render_body(body, batch_vars)
            outcome.batches += 1
            try:
                response = client.request(spec["method"], url, headers=headers, json=body)
                if response.status_code >= 400:
                    raise ProviderError(f"HTTP {response.status_code}: {response.text[:300]}")
                outcome.pushed += len(payload_rows)
                if len(outcome.responses) < 50:
                    outcome.responses.append({"batch": outcome.batches, "status": response.status_code})
                if watermark_field is not None:
                    value = getattr(batch_rows[-1], watermark_field.db_column_name, None)
                    last_watermark = _watermark_value(value)
            except Exception as exc:
                outcome.failed_batches += 1
                outcome.failures.append({"batch": outcome.batches, "error": str(exc)[:500]})
                if len(outcome.failures) >= 20:
                    break
    outcome.cursor_to = last_watermark or cursor_value
    run.detail = {
        **(run.detail or {}),
        "push": {
            "rows_read": outcome.rows_read,
            "pushed": outcome.pushed,
            "batches": outcome.batches,
            "failed_batches": outcome.failed_batches,
            "url": url,
            "method": spec["method"],
            "responses": outcome.responses,
        },
    }
    return outcome


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_MAX_ROWS",
    "PUSH_METHODS",
    "PushOutcome",
    "execute_push",
    "validate_push_spec",
]
