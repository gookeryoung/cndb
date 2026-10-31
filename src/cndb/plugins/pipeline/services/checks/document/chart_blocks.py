"""``document/chart-blocks`` —— 内嵌图表块规范检查（ADR 0076 C5）.

复用 ``charts/inline.py`` 的解析与校验口径（坏块错误码 / 单块 32KB / 单篇 50 块），
允许 ``with`` 覆盖两个上限（按工作区自定义策略）。发现物只带块序号与错误码，
不携带块内配置（D7）。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from cndb.plugins.documents.services.charts.inline import (
    MAX_BLOCK_BYTES,
    MAX_BLOCKS_PER_DOC,
    block_error_message,
    iter_inline_chart_blocks,
)
from cndb.plugins.pipeline.services.checks.base import (
    INPUT_INTEGER,
    CheckContext,
    CheckInput,
    CheckSpec,
    FindingDraft,
)
from cndb.plugins.pipeline.services.checks.registry import register_check

SPEC = CheckSpec(
    uses="document/chart-blocks",
    title="内嵌图表块检查",
    category="document",
    inputs=(
        CheckInput("max_blocks", INPUT_INTEGER, description="单篇图表块上限", default=MAX_BLOCKS_PER_DOC),
        CheckInput("max_block_bytes", INPUT_INTEGER, description="单块字节上限", default=MAX_BLOCK_BYTES),
    ),
    default_severity="warn",
    target_types=("document",),
)


def run(ctx: CheckContext, params: dict[str, Any]) -> Iterable[FindingDraft]:
    """逐文档检查块数量、单块体积与坏块."""
    max_blocks = int(params.get("max_blocks", MAX_BLOCKS_PER_DOC))
    max_block_bytes = int(params.get("max_block_bytes", MAX_BLOCK_BYTES))
    findings: list[FindingDraft] = []
    for doc, content in ctx.iter_documents():
        blocks = list(iter_inline_chart_blocks(content))
        if len(blocks) > max_blocks:
            findings.append(
                FindingDraft(
                    message=f"图表块数量 {len(blocks)} 超过单篇上限 {max_blocks}",
                    target_type="document",
                    target_id=doc.id,
                    locator={},
                    detail={"count": len(blocks), "limit": max_blocks},
                )
            )
        for index, block in enumerate(blocks):
            size = len(block.source.encode("utf-8"))
            if size > max_block_bytes:
                findings.append(
                    FindingDraft(
                        message=f"第 {index + 1} 个图表块 {size} 字节超过单块上限 {max_block_bytes}",
                        target_type="document",
                        target_id=doc.id,
                        locator={"block_index": index},
                        detail={"size": size, "limit": max_block_bytes},
                    )
                )
            if block.error:
                findings.append(
                    FindingDraft(
                        message=f"第 {index + 1} 个图表块{block_error_message(block.error)}",
                        target_type="document",
                        target_id=doc.id,
                        locator={"block_index": index, "error": block.error},
                    )
                )
    return findings


register_check(SPEC, run)

__all__ = ["SPEC", "run"]
