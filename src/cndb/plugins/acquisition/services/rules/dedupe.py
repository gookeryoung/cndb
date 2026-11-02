"""去重键：同一来源多轮 / 多渠道只入一次（ADR 0085 §2 / D4）.

优先级（依次回落，前缀标识来源维度）：

1. ``doi:``    DOI 归一（小写、去 ``https://doi.org/`` 前缀）；
2. ``url:``    归一 URL（去锚点 / 去追踪参数 / 去尾斜杠 / 小写主机）；
3. ``sha1:``   正文指纹（标题 + 摘要去空白后取 sha1，源站无 doi / url 时）；
4. ``title:``  归一标题 + 发布日前 10 位（最后的兜底）。

前缀让台账可读，也让「同一 DOI 换了 URL」仍然命中同一条记录。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__all__ = ["content_digest", "dedupe_key", "normalize_doi", "normalize_url"]

_TRACKING_PREFIXES = ("utm_", "spm", "from", "share_", "ref_")
_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "doi:", "https://dx.doi.org/")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_doi(value: Any) -> str:
    """DOI 归一：去协议 / 前缀，统一小写."""
    text = str(value or "").strip().lower()
    for prefix in _DOI_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text.strip().rstrip(".")


def normalize_url(value: Any) -> str:
    """URL 归一：去锚点 / 追踪参数，路径与主机小写，去尾斜杠."""
    text = str(value or "").strip()
    if not text:
        return ""
    parts = urlsplit(text)
    query = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, urlencode(query), ""))


def content_digest(*parts: Any) -> str:
    """正文指纹：多段文本去空白后取 sha1 前 40 位（台账 payload_digest 同口径）."""
    joined = " ".join(_WHITESPACE_RE.sub(" ", str(part or "")).strip() for part in parts).strip()
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def dedupe_key(item: Mapping[str, Any], channel: str = "", identity: Sequence[str] = ()) -> str:
    """去重键：``identity``（表落点的 match_keys）优先，其次 doi → url → 正文指纹 → 标题+日期.

    表落点的业务身份就是 ``match_keys``：用内容指纹会让「同一行换了数值」变成新条目，
    台账与去重都失真（D4）。
    """
    fields = [str(field) for field in identity if str(field).strip()]
    if fields and all(str(item.get(field) or "").strip() for field in fields):
        return "row:" + content_digest(*[str(item.get(field)) for field in fields])
    doi = normalize_doi(item.get("doi"))
    if doi:
        return f"doi:{doi}"
    url = normalize_url(item.get("url") or item.get("source_url") or item.get("fulltext_url"))
    if url:
        return f"url:{url}"
    title = str(item.get("title") or "").strip()
    summary = str(item.get("summary") or item.get("content") or "")
    if title:
        published = str(item.get("published_at") or "")[:10]
        return f"title:{content_digest(title)}:{published}"
    if summary:
        return f"sha1:{content_digest(summary)}"
    return f"sha1:{content_digest(channel, repr(sorted((str(k), str(v)) for k, v in item.items())))}"
