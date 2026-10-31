"""``document/links`` —— 站内 wikilink 断链检查（ADR 0076 C5）.

复用 ``content.resolve_outgoing_links`` 的解析口径（代码围栏内的 ``[[...]]`` 不计入，
同名文档取最早创建者），仅对 ``broken=true`` 的出链产出发现。发现物只带目标标题、
锚点与原文写法，不携带正文（D7）。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from cndb.plugins.documents.services.content import resolve_outgoing_links
from cndb.plugins.pipeline.services.checks.base import (
    CheckContext,
    CheckSpec,
    FindingDraft,
)
from cndb.plugins.pipeline.services.checks.registry import register_check

SPEC = CheckSpec(
    uses="document/links",
    title="站内链接断链检查",
    category="document",
    inputs=(),
    default_severity="warn",
    target_types=("document",),
)


def run(ctx: CheckContext, _params: dict[str, Any]) -> Iterable[FindingDraft]:
    """逐文档检查 wikilink 是否指向存在的文档."""
    findings: list[FindingDraft] = []
    for doc, _content in ctx.iter_documents():
        for link in resolve_outgoing_links(ctx.db, ctx.workspace_id, doc):
            if not link["broken"]:
                continue
            findings.append(
                FindingDraft(
                    message=f"站内链接指向不存在的文档：{link['title']}",
                    target_type="document",
                    target_id=doc.id,
                    locator={
                        "target": link["title"],
                        "anchor": link["anchor"],
                        "raw": link["raw"],
                    },
                )
            )
    return findings


register_check(SPEC, run)

__all__ = ["SPEC", "run"]
