"""内置 provider：``rss_atom`` —— RSS 2.0 / Atom 订阅源.

RSS 2.0::

    <rss><channel><title>源名</title>
      <item><title>…</title><link>…</link><description>…</description><pubDate>…</pubDate></item>
    </channel></rss>

Atom::

    <feed><title>源名</title>
      <entry><title>…</title><link href="…"/><summary>…</summary><updated>…</updated></entry>
    </feed>

统一输出 ``title / link / summary / published_at / source``（``published_at`` 归一为
``YYYY-MM-DD HH:MM:SS``，读不到就留空）。RSS 的 ``pubDate`` 是 RFC 822，Atom 的是 ISO 8601，
两者都吃。

继承 ``http_json`` 复用请求模板与归一；只覆写 ``parse``（XML 而非 JSON）。
默认游标用 ``datetime``（按发布时间增量），幂等键通常取 ``link``。
"""

from __future__ import annotations

import email.utils
import xml.etree.ElementTree as ET  # nosec B405 - 仅解析远端订阅源，ElementTree 不做外部实体展开
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, override

from cndb.plugins.datasource.providers.base import ProviderError, SourceProvider, SyncJobSpec
from cndb.plugins.datasource.providers.http_json import HttpJsonProvider
from cndb.plugins.datasource.services.normalize import coerce_value

RSS_ATOM_PARAMS_SCHEMA: dict[str, Any] = {
    "fields": [
        {"name": "url_template", "type": "text", "required": True, "label": "订阅源 URL（http/https）"},
        {
            "name": "headers_template",
            "type": "json",
            "label": "请求头模板",
            "placeholder": '{"User-Agent": "cndb-sync/1.0"}',
        },
    ],
    "placeholders": [],
    "notes": "输出列：title / link / summary / published_at / source；幂等键建议用 link。",
}

_ENTRY_TAGS = frozenset({"item", "entry"})


class RssAtomProvider(HttpJsonProvider):
    """RSS / Atom 订阅源：XML → 统一新闻行."""

    name = "rss_atom"
    label = "RSS / Atom 订阅"
    params_schema: Mapping[str, Any] = RSS_ATOM_PARAMS_SCHEMA
    default_cursor = "datetime"
    supports_paging = False
    uses_custom_parse = True

    @override
    def parse(self, text: str, job: SyncJobSpec) -> list[dict[str, Any]]:
        try:
            root = ET.fromstring(text)  # nosec B314 - 输入是远端订阅源，仅取文本节点
        except ET.ParseError as exc:
            raise ProviderError(f"响应不是合法 XML: {exc}") from exc
        source = _feed_title(root)
        rows: list[dict[str, Any]] = []
        for element in root.iter():
            if _local(element.tag) not in _ENTRY_TAGS:
                continue
            rows.append(_row_from_entry(element, source))
        return rows


def _row_from_entry(element: ET.Element, source: str) -> dict[str, Any]:
    title = _child_text(element, "title")
    link = _child_text(element, "link") or _link_href(element)
    summary = _child_text(element, "description") or _child_text(element, "summary") or _child_text(element, "content")
    published = (
        _child_text(element, "pubDate")
        or _child_text(element, "published")
        or _child_text(element, "updated")
        or _child_text(element, "date")
    )
    return {
        "title": title,
        "link": link,
        "summary": summary,
        "published_at": _normalize_time(published),
        "source": source,
    }


def _feed_title(root: ET.Element) -> str:
    for child in root:
        if _local(child.tag) in ("channel", "feed"):
            return _child_text(child, "title")
    return _child_text(root, "title")


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local(child.tag) == name:
            text = (child.text or "").strip()
            if text:
                return text
    return ""


def _link_href(element: ET.Element) -> str:
    """Atom 的 link 是空元素 + href 属性（alternate 优先）."""
    fallback = ""
    for child in element:
        if _local(child.tag) != "link":
            continue
        href = (child.get("href") or "").strip()
        if not href:
            continue
        if child.get("rel") in (None, "", "alternate"):
            return href
        fallback = fallback or href
    return fallback


def _normalize_time(raw: str) -> str:
    """RFC 822（RSS）或 ISO 8601（Atom）→ ``YYYY-MM-DD HH:MM:SS``；解析失败留空."""
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        parsed = None
    if parsed is not None:
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    value, reason = coerce_value(text, "datetime")
    return str(value) if reason is None and value is not None else ""


def _local(tag: str) -> str:
    """去掉 ``{namespace}`` 前缀（RSS 无 namespace，Atom 一定有）."""
    return tag.rsplit("}", 1)[-1]


__all__ = ["RSS_ATOM_PARAMS_SCHEMA", "RssAtomProvider"]

if TYPE_CHECKING:
    _contract: SourceProvider = RssAtomProvider()
