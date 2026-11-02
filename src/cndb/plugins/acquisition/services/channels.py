"""渠道展开：策略声明的渠道 → 可执行的内存 ``SyncJobSpec``（ADR 0085 §2 / D2）.

渠道引用形态（``scope.channels`` 数组元素）：

- ``"job:12"`` / ``{"job": 12}``：引用同工作区的既有同步任务，复用其请求模板 / 凭证会话 / 分页；
  运行期读一次构造内存声明，**不复制、不回写** job 行，存量任务零迁移；
- ``"rss:https://example.com/feed.xml"``：订阅渠道（``rss_atom`` provider）；
- ``"sitemap:https://example.com/sitemap.xml"``：站点 URL 发现（只解析 ``<urlset>``）；
- ``"arxiv:"`` / ``"openalex:固态电池"`` / ``"crossref:"``：学术开放 API；冒号后留空表示用本轮
  迭代检索式 ``{query}``，填了则固定该检索词（P2）；
- ``{"provider": "http_json", "request_spec": {...}, "parser": "json"}``：内联声明（不落 job 表、
  可用任意已注册 provider）。

策略层只做「取声明 + 注入本轮检索式变量 ``{query}``」，抓取仍由 datasource 管线执行。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.acquisition.services.rules.expr import RuleError
from cndb.plugins.datasource.models import DatasourceSession, DatasourceSyncJob
from cndb.plugins.datasource.providers.base import SyncJobSpec
from cndb.plugins.datasource.services.runner import build_job_spec, request_spec_from_payload

__all__ = [
    "ChannelSpec",
    "build_channel_specs",
    "channel_label",
    "parse_channel_ref",
    "preset_request",
]

_DEFAULT_MAX_ITEMS = 200
#: 学术接口单次返回上限（各家都接受 50，过大容易触发限流）
_ACADEMIC_PAGE_SIZE = 50

#: 渠道简写 → 内联声明模板；``{q}`` 在运行期替换成本轮检索式
_PRESETS: dict[str, dict[str, Any]] = {
    "rss": {"provider": "rss_atom", "parser": "rss"},
    "sitemap": {"provider": "sitemap", "parser": "sitemap"},
    "arxiv": {
        "provider": "academic",
        "parser": "academic",
        "url_template": "https://export.arxiv.org/api/query",
        "params_template": {"search_query": "all:{q}", "max_results": _ACADEMIC_PAGE_SIZE},
    },
    "openalex": {
        "provider": "academic",
        "parser": "academic",
        "url_template": "https://api.openalex.org/works",
        "params_template": {"search": "{q}", "per-page": _ACADEMIC_PAGE_SIZE},
        "data_path": "results",
    },
    "crossref": {
        "provider": "academic",
        "parser": "academic",
        "url_template": "https://api.crossref.org/works",
        "params_template": {"query": "{q}", "rows": _ACADEMIC_PAGE_SIZE},
        "data_path": "message.items",
    },
}


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    """一个可执行渠道：标签 + 声明 + 本轮条数上限."""

    channel: str
    provider: str
    spec: SyncJobSpec
    rate_limit_ms: int = 0
    max_items: int = _DEFAULT_MAX_ITEMS


def channel_label(ref: Any, index: int) -> str:
    """渠道展示名：``job:12`` 原样、字典取 job / provider、非法值给序号."""
    if isinstance(ref, str) and ref.strip():
        return ref.strip()
    if isinstance(ref, Mapping):
        if ref.get("job") is not None:
            return f"job:{ref['job']}"
        provider = str(ref.get("provider") or "").strip()
        if provider:
            return provider
    return f"channel-{index}"


def parse_channel_ref(ref: Any) -> tuple[str, Any]:
    """解析单个渠道引用，返回 ``(kind, payload)``；非法抛 :class:`RuleError`."""
    if isinstance(ref, str):
        text = ref.strip()
        if text.startswith("job:"):
            job_id = text[4:].strip()
            if not job_id.isdigit():
                raise RuleError(f"渠道引用非法（job 编号必须是整数）: {ref!r}")
            return "job", int(job_id)
        prefix, _, rest = text.partition(":")
        if prefix in _PRESETS:
            return "preset", (prefix, rest.strip())
        raise RuleError(
            f"渠道引用非法（支持 job:<id> / rss:<url> / sitemap:<url> / arxiv: / openalex: / crossref: / 内联 provider 声明）: {ref!r}"
        )
    if isinstance(ref, Mapping):
        if ref.get("job") is not None:
            try:
                return "job", int(ref["job"])
            except (TypeError, ValueError) as exc:
                raise RuleError(f"渠道 job 编号非法: {ref['job']!r}") from exc
        if ref.get("request_spec") or ref.get("provider"):
            return "inline", dict(ref)
        raise RuleError(f"渠道声明缺少 job 或 provider: {ref!r}")
    raise RuleError(f"渠道声明类型非法: {ref!r}")


def preset_request(kind: str, rest: str, query: str) -> dict[str, Any]:
    """渠道简写 → 内联声明；``rss`` / ``sitemap`` 必须给 http(s) 地址（P2）."""
    preset = _PRESETS.get(kind)
    if preset is None:
        raise RuleError(f"未知渠道简写: {kind!r}")
    term = rest or query
    request_spec: dict[str, Any] = {}
    if kind in ("rss", "sitemap"):
        if not rest.startswith(("http://", "https://")):
            raise RuleError(f"{kind}: 后必须是一个 http/https 地址: {rest!r}")
        request_spec = {"url_template": rest}
    else:
        request_spec = {
            "url_template": preset["url_template"],
            "params_template": {
                key: str(value).replace("{q}", term) for key, value in dict(preset["params_template"]).items()
            },
        }
        if preset.get("data_path"):
            request_spec["data_path"] = preset["data_path"]
    payload: dict[str, Any] = {
        "provider": preset["provider"],
        "parser": preset["parser"],
        "request_spec": request_spec,
    }
    return payload


def _with_query(spec: SyncJobSpec, query: str) -> SyncJobSpec:
    """把本轮检索式注入模板变量 ``{query}``（模板未使用时无副作用）."""
    if not query:
        return spec
    variables = {**dict(spec.extra_variables), "query": query}
    return replace(spec, extra_variables=variables)


def build_channel_specs(
    db: Session,
    *,
    workspace_id: int,
    scope: Mapping[str, Any],
    query: str,
    today: str,
    user_id: int | None = None,
) -> tuple[list[ChannelSpec], list[dict[str, str]]]:
    """把 ``scope.channels`` 展开成可执行渠道；单个渠道失败不影响其它渠道.

    Returns:
        ``(specs, errors)``：``errors`` 为 ``[{"channel","error"}]``，进运行明细。
    """
    raw_channels: Sequence[Any] = list(scope.get("channels") or [])
    max_items = int(scope.get("max_results_per_channel") or _DEFAULT_MAX_ITEMS)
    specs: list[ChannelSpec] = []
    errors: list[dict[str, str]] = []

    for index, ref in enumerate(raw_channels, start=1):
        label = channel_label(ref, index)
        try:
            kind, payload = parse_channel_ref(ref)
            if kind == "preset":
                payload = preset_request(str(payload[0]), str(payload[1]), query)
                kind = "inline"
            if kind == "job":
                job = db.get(DatasourceSyncJob, int(payload))
                if job is None:
                    raise RuleError(f"同步任务不存在: {payload}")
                if job.workspace_id != workspace_id:
                    raise RuleError(f"同步任务 {payload} 不属于当前工作区")
                session = db.get(DatasourceSession, job.session_id) if job.session_id else None
                spec = build_job_spec(
                    job,
                    cursor_from="",
                    today=today,
                    session=session,
                    db=db,
                    llm_user_id=user_id if user_id is not None else job.created_by,
                )
                specs.append(
                    ChannelSpec(
                        channel=label,
                        provider=job.provider,
                        spec=_with_query(spec, query),
                        rate_limit_ms=max(0, job.rate_limit_ms or 0),
                        max_items=max_items,
                    )
                )
                continue

            request_payload = dict(payload.get("request_spec") or {})
            provider = str(payload.get("provider") or "http_json")
            request = request_spec_from_payload(request_payload)
            spec = SyncJobSpec(
                request=request,
                provider=provider,
                parser=str(payload.get("parser") or "json"),
                match_keys=tuple(payload.get("match_keys") or ()),
                extra_variables={"query": query} if query else {},
            )
            rate_limit_ms = int(payload.get("rate_limit_ms") or 0)
            specs.append(
                ChannelSpec(
                    channel=label,
                    provider=provider,
                    spec=spec,
                    rate_limit_ms=max(0, rate_limit_ms),
                    max_items=int(payload.get("max_items") or max_items),
                )
            )
        except (RuleError, ValueError) as exc:
            errors.append({"channel": label, "error": str(exc)[:300]})

    return specs, errors
