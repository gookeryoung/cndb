"""标题 / 题注序号的显式检出（ADR 0186 I1 / I2 / I4）.

编号的权威只有一处：导出模板的 ``NumberingConfig``。正文（含内容模板骨架）若已
自带序号，模板编号必须**让位**，否则会出现「（一） 一、项目基本信息」这类叠加。
本模块是这条判定的唯一入口，docx 与 pdf 渲染器共用：

- :func:`has_explicit_heading_numbers` —— 只看标题块，全篇 all-or-nothing（I2）；
- :func:`has_explicit_caption_number` —— 题注文本自带「图 N」「表 N-M」则不叠加；
- :func:`resolve_heading_numbering` —— 把 ``mode``（auto / force / off）折成实际方案。

保守原则（I4）：认不出就当「没有显式序号」，最多少编号一次，绝不误判成手写而
丢掉用户期望的模板编号。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from cndb.plugins.documents.services.export.markdown_blocks import HeadingBlock, plain_text

#: 标题文本**开头**的显式序号（第一章 / 一、/ （一）/ 3.1 / 1. / 1、）
EXPLICIT_HEADING_PREFIX_RE = re.compile(
    r"""^[\s　]*(?:
        第[\s　]*[一二三四五六七八九十百千零〇两\d]+[\s　]*[章节篇部]      # 第一章 / 第 1 节
      | [（(][\s　]*[一二三四五六七八九十百千零〇]+[\s　]*[）)]            # （一）
      | [一二三四五六七八九十百千零〇]+[\s　]*[、.．]                      # 一、 / 十二.
      | \d+(?:[.．]\d+)+(?:[\s　]*[、.．)）]?)?                            # 3.1 / 1.1.
      | \d+[\s　]*[、.．)）]                                              # 1. / 1、 / 1)
    )""",
    re.VERBOSE,
)

#: 题注文本**开头**的显式编号（图 1 / 图 1-1 / 表 2 …）
EXPLICIT_CAPTION_PREFIX_RE = re.compile(r"""^[\s　]*[图表][\s　]*[0-9０-９]+(?:[\s　]*[-－—.．][\s　]*[0-9０-９]+)*""")


def has_explicit_heading_numbers(blocks: Sequence[object]) -> bool:
    """正文标题里是否已含显式序号（I2：只看标题块，任一级命中即整篇让位）.

    列表项自带的 ``1.`` 是列表序号而非标题编号，代码块里的示例文本也不参与判定 ——
    两者都不是 :class:`HeadingBlock`，天然被跳过。
    """
    for block in blocks:
        if not isinstance(block, HeadingBlock):
            continue
        if EXPLICIT_HEADING_PREFIX_RE.match(plain_text(block.spans).strip()):
            return True
    return False


def has_explicit_caption_number(text: str) -> bool:
    """题注文本是否自带编号（``图 1 架构`` / ``表 2-1 指标``）."""
    return EXPLICIT_CAPTION_PREFIX_RE.match(text.strip()) is not None


def heading_level_offset(blocks: Sequence[object]) -> int:
    """编号层级基准：正文最高一级标题视为「第 1 级」（ADR 0186 C2 / D11）.

    文档标题由文件名 / ``core_properties.title`` 承担，正文从 ``##`` 开始是常态
    （内置内容模板全部如此）。若直接按 Markdown 层级编号，``##`` 会生成 ``0.1``。
    返回 ``min(level) - 1``（无标题时为 0），渲染器用它平移计数器。
    """
    levels = [block.level for block in blocks if isinstance(block, HeadingBlock)]
    return max(min(levels) - 1, 0) if levels else 0


def resolve_heading_numbering(mode: str, heading: str, blocks: Sequence[object]) -> str:
    """把 ``mode`` 折成实际生效的编号方案（渲染器的唯一判定入口）.

    - ``off``：永不生成编号；
    - ``force``：始终用 ``heading``（升级前的旧行为，供显式选择）；
    - 其它（含未知值，按 ``auto``）：正文有显式序号则 ``none``，否则用 ``heading``。
    """
    if mode == "off":
        return "none"
    if mode == "force":
        return heading
    return "none" if has_explicit_heading_numbers(blocks) else heading


__all__ = [
    "EXPLICIT_CAPTION_PREFIX_RE",
    "EXPLICIT_HEADING_PREFIX_RE",
    "has_explicit_caption_number",
    "has_explicit_heading_numbers",
    "heading_level_offset",
    "resolve_heading_numbering",
]
