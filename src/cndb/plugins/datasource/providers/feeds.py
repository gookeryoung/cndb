"""内置 provider：``rss_atom`` / ``academic`` / ``sitemap``（ADR 0085 P2）.

三者都是「响应不是普通 JSON 对象数组」或「多家接口字段各异」的场景，因此统一
继承 :class:`HttpJsonProvider` 复用请求构造（模板 / 分页 / 时间窗），只覆写
``parse`` 把响应文本转成**统一字段**的行：

- ``rss_atom``：RSS 2.0 / RSS 1.0(RDF) / Atom 三种订阅格式；
- ``academic``：arXiv（Atom）、OpenAlex、Crossref（JSON）三家学术开放 API，
  按内容自动判别格式，字段归一为 ``title/url/summary/published_at/doi/authors``；
- ``sitemap``：``sitemap.xml`` 的 URL 发现（只做发现，正文抓取仍走文档导入）。

统一字段口径是采集策略筛选与去重的前提：``rules/filter`` 按键名匹配、
``rules/dedupe`` 优先用 ``doi`` / ``url`` 作去重键。
"""

from __future__ import annotations

import datetime as dt
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from email.utils import parsedate_to_datetime
from typing import Any, override
from urllib.parse import urlsplit

from cndb.plugins.datasource.providers.base import (
    CursorStrategy,
    ProviderError,
    SyncJobSpec,
)
from cndb.plugins.datasource.providers.http_json import HttpJsonProvider, _resolve_path
from cndb.plugins.datasource.services.normalize import NormalizeResult, apply_field_mapping

#: 统一字段：所有 provider 都把结果归一成这几个键（缺失即不出现）
UNIFIED_FIELDS: tuple[str, ...] = ("title", "url", "summary", "published_at", "doi", "authors")

RSS_ATOM_PARAMS_SCHEMA: dict[str, Any] = {
    "fields": [
        {"name": "url_template", "type": "text", "required": True, "label": "订阅地址（RSS / Atom）"},
        {"name": "encoding", "type": "text", "default": "utf-8"},
    ],
    "placeholders": ["query"],
}

ACADEMIC_PARAMS_SCHEMA: dict[str, Any] = {
    "fields": [
        {"name": "url_template", "type": "text", "required": True, "label": "接口地址"},
        {"name": "params_template", "type": "json", "label": "查询参数模板（含 {query}）"},
        {"name": "data_path", "type": "text", "label": "结果数组路径（arXiv 留空）"},
    ],
    "sources": ["arxiv", "openalex", "crossref"],
    "placeholders": ["query", "start", "end"],
}

SITEMAP_PARAMS_SCHEMA: dict[str, Any] = {
    "fields": [
        {"name": "url_template", "type": "text", "required": True, "label": "sitemap 地址"},
        {"name": "encoding", "type": "text", "default": "utf-8"},
    ],
    "notes": "只支持 <urlset>；指向 <sitemapindex> 会报错并提示改用子 sitemap",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


# ── 通用小工具 ────────────────────────────────────


def local_name(tag: Any) -> str:
    """去掉命名空间后的标签名（Atom / RDF / dc 混用时的统一口径）."""
    text = str(tag or "")
    return text.rsplit("}", 1)[-1].lower() if text else ""


def _strip_html(text: str) -> str:
    """摘要去标签 + 折叠空白（学术接口常把 HTML 塞进 abstract）."""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text or "")).strip()


def _iso_time(raw: str) -> str:
    """pubDate / ISO 时间串 → ISO 8601（解析失败原样返回，不丢信息）."""
    text = str(raw or "").strip()
    if not text:
        return ""
    parsed: dt.datetime | None = None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        candidate = text.replace("Z", "+00:00")
        for fmt in (None, "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = dt.datetime.fromisoformat(candidate) if fmt is None else dt.datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return text
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.UTC)
    return parsed.isoformat()


def _first_text(node: ET.Element, names: Sequence[str]) -> str:
    """按名字优先级取第一个后代元素文本（同名多个时取首个）."""
    for name in names:
        for child in node.iter():
            if local_name(child.tag) == name:
                text = (child.text or "").strip()
                if text:
                    return text
    return ""


def _atom_link(node: ET.Element) -> str:
    """Atom 的链接在 ``<link href>`` 属性上（RSS 在文本节点）."""
    fallback = ""
    for child in node.iter():
        if local_name(child.tag) != "link":
            continue
        href = str(child.get("href") or "").strip()
        if not href:
            continue
        rel = str(child.get("rel") or "alternate")
        if rel in ("alternate", ""):
            return href
        fallback = fallback or href
    return fallback


def _authors(node: ET.Element) -> list[str]:
    names: list[str] = []
    for child in node.iter():
        tag = local_name(child.tag)
        if tag not in {"author", "creator"}:
            continue
        text = (child.text or "").strip()
        if text:
            names.append(text)
            continue
        for sub in child.iter():
            sub_text = (sub.text or "").strip()
            if local_name(sub.tag) == "name" and sub_text:
                names.append(sub_text)
                break
    seen: dict[str, None] = {}
    for name in names:
        seen.setdefault(name, None)
    return list(seen)


def parse_feed(text: str) -> list[dict[str, Any]]:
    """RSS 2.0 / Atom / RDF 文本 → 统一字段行（无条目返回空列表，格式错误抛错）."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ProviderError(f"订阅内容不是合法 XML: {exc}") from exc
    kind = local_name(root.tag)
    item_names = {"rss": "item", "rdf": "item", "feed": "entry"}
    item_tag = item_names.get(kind)
    if item_tag is None:
        raise ProviderError(f"无法识别的订阅格式（根节点 {kind or '未知'}）")

    rows: list[dict[str, Any]] = []
    for node in root.iter():
        if local_name(node.tag) != item_tag:
            continue
        title = _strip_html(_first_text(node, ("title",)))
        url = _atom_link(node) or _first_text(node, ("link", "guid", "id"))
        summary = _strip_html(_first_text(node, ("description", "summary", "content", "encoded")))
        published = _iso_time(_first_text(node, ("pubdate", "published", "updated", "date")))
        row: dict[str, Any] = {"title": title, "url": url, "summary": summary, "published_at": published}
        authors = _authors(node)
        if authors:
            row["authors"] = ", ".join(authors)
        if title or url:
            rows.append(row)
    return rows


# ── rss_atom ────────────────────────────────────


class RssAtomProvider(HttpJsonProvider):
    """RSS / Atom 订阅适配器（XML → 统一字段行）."""

    name = "rss_atom"
    label = "RSS / Atom 订阅"
    params_schema: Mapping[str, Any] = RSS_ATOM_PARAMS_SCHEMA
    default_cursor: CursorStrategy = "none"
    supports_paging = False
    uses_custom_parse = True

    @override
    def parse(self, text: str, job: SyncJobSpec, *, data_path: str | None = None) -> list[dict[str, Any]]:
        """忽略 ``data_path``（XML 不走路径定位）."""
        del job, data_path
        return parse_feed(text)

    @override
    def normalize(self, rows: Sequence[Mapping[str, Any]], job: SyncJobSpec) -> NormalizeResult:
        return apply_field_mapping(rows, job.field_mapping)


# ── academic ────────────────────────────────────


def _pick(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _openalex_row(item: Mapping[str, Any]) -> dict[str, Any]:
    location = item.get("primary_location") or {}
    url = ""
    if isinstance(location, Mapping):
        url = str(location.get("landing_page_url") or location.get("pdf_url") or "")
    authorships = item.get("authorships") or []
    names = [
        str(((entry or {}).get("author") or {}).get("display_name") or "")
        for entry in authorships[:8]
        if isinstance(entry, Mapping)
    ]
    return {
        "title": _strip_html(str(item.get("display_name") or item.get("title") or "")),
        "url": url or str(item.get("id") or ""),
        "summary": "",
        "published_at": _iso_time(str(item.get("publication_date") or item.get("publication_year") or "")),
        "doi": str(item.get("doi") or ""),
        "authors": ", ".join(name for name in names if name),
    }


def _crossref_row(item: Mapping[str, Any]) -> dict[str, Any]:
    titles = item.get("title") or []
    title = str(titles[0]) if isinstance(titles, list) and titles else str(titles or "")
    issued = item.get("issued") or item.get("published") or {}
    parts = (issued or {}).get("date-parts") if isinstance(issued, Mapping) else None
    published = ""
    if isinstance(parts, list) and parts and isinstance(parts[0], list):
        published = "-".join(f"{int(part):02d}" if index else str(int(part)) for index, part in enumerate(parts[0]))
    authors: list[str] = []
    for entry in (item.get("author") or [])[:8]:
        if isinstance(entry, Mapping):
            name = " ".join(part for part in (entry.get("given"), entry.get("family")) if part)
            if name:
                authors.append(str(name))
    return {
        "title": _strip_html(title),
        "url": str(item.get("URL") or ""),
        "summary": _strip_html(str(item.get("abstract") or ""))[:2000],
        "published_at": _iso_time(published),
        "doi": str(item.get("DOI") or ""),
        "authors": ", ".join(authors),
    }


def _generic_row(item: Mapping[str, Any]) -> dict[str, Any]:
    raw_title = _pick(item, "title", "name", "display_name") or ""
    if isinstance(raw_title, list):
        raw_title = raw_title[0] if raw_title else ""
    return {
        "title": _strip_html(str(raw_title)),
        "url": str(_pick(item, "url", "link", "href", "id") or ""),
        "summary": _strip_html(str(_pick(item, "summary", "description", "abstract") or ""))[:2000],
        "published_at": _iso_time(str(_pick(item, "published_at", "published", "pubDate", "date", "updated") or "")),
        "doi": str(_pick(item, "doi", "DOI") or ""),
        "authors": "",
    }


def _as_rows(payload: Any, data_path: str | None) -> list[dict[str, Any]]:
    """在响应里定位结果数组：显式 ``data_path`` 优先，否则按常见键探测."""
    node: Any = _resolve_path(payload, data_path) if data_path else payload
    if node is None and data_path:
        raise ProviderError(f"响应缺少 data_path 指定的节点: {data_path}")
    if isinstance(node, list):
        return [dict(entry) for entry in node if isinstance(entry, Mapping)]
    if isinstance(node, Mapping):
        for key in ("results", "items", "data", "entries", "docs"):
            candidate = node.get(key)
            if isinstance(candidate, list):
                return [dict(entry) for entry in candidate if isinstance(entry, Mapping)]
        message = node.get("message")
        if isinstance(message, Mapping) and isinstance(message.get("items"), list):
            return [dict(entry) for entry in message["items"] if isinstance(entry, Mapping)]
    raise ProviderError("学术接口响应里没有可识别的结果数组")


class AcademicProvider(HttpJsonProvider):
    """学术开放 API 适配器（arXiv Atom / OpenAlex / Crossref JSON 通用）."""

    name = "academic"
    label = "学术开放 API"
    params_schema: Mapping[str, Any] = ACADEMIC_PARAMS_SCHEMA
    default_cursor: CursorStrategy = "none"
    supports_paging = False
    uses_custom_parse = True

    @override
    def parse(self, text: str, job: SyncJobSpec, *, data_path: str | None = None) -> list[dict[str, Any]]:
        """按响应内容判别格式：``<`` 开头走 Atom，否则走 JSON."""
        stripped = text.lstrip()
        if stripped.startswith("<"):
            return parse_feed(text)
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(f"学术接口响应既不是 XML 也不是合法 JSON: {exc}") from exc
        path = data_path if data_path is not None else job.request.data_path
        rows: list[dict[str, Any]] = []
        for item in _as_rows(payload, path):
            if "display_name" in item or "authorships" in item:
                row = _openalex_row(item)
            elif "DOI" in item or "issued" in item:
                row = _crossref_row(item)
            else:
                row = _generic_row(item)
            if row["title"] or row["url"]:
                rows.append(row)
        return rows

    @override
    def normalize(self, rows: Sequence[Mapping[str, Any]], job: SyncJobSpec) -> NormalizeResult:
        return apply_field_mapping(rows, job.field_mapping)


# ── sitemap ────────────────────────────────────


def parse_sitemap(text: str) -> list[dict[str, Any]]:
    """``sitemap.xml`` → URL 发现行（``type`` 区分 url / sitemap）.

    只做发现：不递归抓取子 sitemap，也不抓正文（正文交给文档导入链）。
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ProviderError(f"sitemap 不是合法 XML: {exc}") from exc
    kind = local_name(root.tag)
    if kind == "sitemapindex":
        raise ProviderError("该地址是 sitemap 索引，请改为指向具体的子 sitemap（本期不做递归展开）")
    if kind != "urlset":
        raise ProviderError(f"无法识别的 sitemap 根节点: {kind or '未知'}")

    rows: list[dict[str, Any]] = []
    for node in root.iter():
        if local_name(node.tag) != "url":
            continue
        loc = _first_text(node, ("loc",))
        if not loc:
            continue
        path = urlsplit(loc).path.rstrip("/")
        slug = path.rsplit("/", 1)[-1] if path else ""
        rows.append(
            {
                "title": slug.replace("-", " ").replace("_", " ") or loc,
                "url": loc,
                "published_at": _iso_time(_first_text(node, ("lastmod",))),
                "type": "url",
            }
        )
    return rows


class SitemapProvider(HttpJsonProvider):
    """sitemap URL 发现适配器（只解析 ``<urlset>``）."""

    name = "sitemap"
    label = "站点 sitemap（URL 发现）"
    params_schema: Mapping[str, Any] = SITEMAP_PARAMS_SCHEMA
    default_cursor: CursorStrategy = "none"
    supports_paging = False
    uses_custom_parse = True

    @override
    def parse(self, text: str, job: SyncJobSpec, *, data_path: str | None = None) -> list[dict[str, Any]]:
        del job, data_path
        return parse_sitemap(text)

    @override
    def normalize(self, rows: Sequence[Mapping[str, Any]], job: SyncJobSpec) -> NormalizeResult:
        return apply_field_mapping(rows, job.field_mapping)


__all__ = [
    "ACADEMIC_PARAMS_SCHEMA",
    "RSS_ATOM_PARAMS_SCHEMA",
    "SITEMAP_PARAMS_SCHEMA",
    "UNIFIED_FIELDS",
    "AcademicProvider",
    "RssAtomProvider",
    "SitemapProvider",
    "local_name",
    "parse_feed",
    "parse_sitemap",
]
