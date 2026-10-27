"""Markdown 源文件转换：front-matter 标题提取 + 首个一级标题剥离.

返回 ``(title, body, warnings)``；正文的空白规整由 ``reader.convert_file`` 统一施加，
本模块只做「标题识别 + 正文剥离」（对应需求 C6，决策 D3）。
"""

from __future__ import annotations

import re
from pathlib import Path

from cndb.plugins.documents.services.charts.inline import (
    iter_inline_chart_blocks,
    validate_document_blocks,
)
from cndb.plugins.documents.services.obsidian import parse_vault_front_matter

from .normalize import decode_text

#: 一级标题行（``# 标题``，恰好一个 ``#``）
_H1_LINE_RE = re.compile(r"#\s+(.*)$")


def strip_paired_chart_images(body: str) -> str:
    """移除导出时追加的配对静态图（``![…](assets/chart-<指纹>.svg)``）.

    只剥离「紧随图表块之后且指纹完全匹配」的那一行，避免误删用户自己的图片；
    未带定义的静态图（外部导入的 Markdown）原样保留。
    """
    for block in iter_inline_chart_blocks(body):
        if not block.fingerprint:
            continue
        pattern = re.compile(
            re.escape(block.source)
            + r"\n\n!\[[^\]\n]*\]\((?:\./)?assets/chart-"
            + re.escape(block.fingerprint)
            + r"\.svg\)"
        )
        source = block.source
        body = pattern.sub(lambda _m, source=source: source, body, count=1)
    return body


def _strip_first_h1(body: str) -> tuple[str, str]:
    """若正文首个非空行是一级标题，剥离该行并返回 ``(新正文, 标题文本)``."""
    lines = body.split("\n")
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        match = _H1_LINE_RE.match(line.strip())
        if match is not None:
            return "\n".join(lines[:index] + lines[index + 1 :]), match.group(1).strip()
        return body, ""
    return body, ""


def convert_markdown(data: bytes, path: str) -> tuple[str, str, list[str]]:
    """把 ``.md`` / ``.markdown`` 源转换为 ``(标题, 正文 Markdown, 告警)``.

    标题优先级：front-matter ``title`` → 正文首个一级标题 → 文件名；
    命中一级标题时该行从正文剥离，避免标题重复。
    """
    warnings: list[str] = []
    text = decode_text(data)
    meta, body = parse_vault_front_matter(text)

    title = ""
    raw_title = meta.get("title")
    if isinstance(raw_title, str) and raw_title.strip():
        title = raw_title.strip()
    if not title:
        body, heading = _strip_first_h1(body)
        if heading:
            title = heading
            warnings.append("标题取自正文首个一级标题，已从正文剥离")
    if not title:
        title = Path(path).stem
        warnings.append("标题取自文件名")
    body = strip_paired_chart_images(body)
    warnings.extend(validate_document_blocks(body))
    return title, body, warnings


__all__ = ["convert_markdown"]
