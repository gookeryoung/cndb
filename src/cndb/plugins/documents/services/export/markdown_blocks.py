"""导出器共用的 Markdown 块级 / 行内解析（PDF、DOCX 同一套规则）.

预览由前端 ``react-markdown`` + ``remark-gfm`` 渲染；导出端没有 HTML 中间层，
如果 PDF 与 DOCX 各自逐行扫文本，两套规则必然漂移（历史上列表、代码围栏、
表格分隔行与换行都因此表现不一致）。本模块把正文切成块，两个渲染器只负责
把块映射到各自的排版对象。

支持的块：标题、段落、有序 / 无序列表（层级、编号延续、任务框）、GFM 表格
（对齐、转义竖线）、围栏代码块、引用、分隔线、换页标记、站内图片、数据表引用。
不支持：缩进式代码块、HTML 块、脚注 —— 编辑器不会产出，预览与导出一致忽略。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cndb.plugins.documents.services.export.images import IMAGE_LINE_RE

#: 行内片段类型
INLINE_TEXT = "text"
INLINE_BOLD = "bold"
INLINE_ITALIC = "italic"
INLINE_CODE = "code"
INLINE_STRIKE = "strike"
INLINE_LINK = "link"
INLINE_BREAK = "break"


@dataclass(frozen=True)
class InlineSpan:
    """行内片段；``break`` 表示显式换行（``<br>``），``href`` 仅链接使用."""

    kind: str
    text: str
    href: str = ""


@dataclass(frozen=True)
class HeadingBlock:
    level: int
    spans: tuple[InlineSpan, ...]


@dataclass(frozen=True)
class ParagraphBlock:
    spans: tuple[InlineSpan, ...]


@dataclass(frozen=True)
class ListItemBlock:
    level: int
    marker: str
    ordered: bool
    checked: bool | None
    spans: tuple[InlineSpan, ...]


@dataclass(frozen=True)
class ListBlock:
    items: tuple[ListItemBlock, ...]


@dataclass(frozen=True)
class TableBlock:
    header: tuple[tuple[InlineSpan, ...], ...]
    rows: tuple[tuple[tuple[InlineSpan, ...], ...], ...]
    aligns: tuple[str, ...]


@dataclass(frozen=True)
class CodeBlock:
    language: str
    code: str


@dataclass(frozen=True)
class QuoteBlock:
    lines: tuple[tuple[InlineSpan, ...], ...]


@dataclass(frozen=True)
class RuleBlock:
    pass


@dataclass(frozen=True)
class PageBreakBlock:
    pass


@dataclass(frozen=True)
class ImageBlock:
    alt: str
    key: str


@dataclass(frozen=True)
class TableRefBlock:
    """``{{table:…}}`` 原始行；由渲染器在拿到解析器后再解析，保持本模块无 DB 依赖."""

    raw: str


Block = (
    HeadingBlock
    | ParagraphBlock
    | ListBlock
    | TableBlock
    | CodeBlock
    | QuoteBlock
    | RuleBlock
    | PageBreakBlock
    | ImageBlock
    | TableRefBlock
)

_FENCE_RE = re.compile(r"^\s{0,3}(?P<fence>`{3,}|~{3,})\s*(?P<info>[^\s`~]*)\s*$")
_HEADING_RE = re.compile(r"^\s{0,3}(?P<marks>#{1,6})\s+(?P<text>.*?)\s*#*\s*$")
_LIST_RE = re.compile(r"^(?P<indent>[ \t]*)(?:(?P<bullet>[-+*])|(?P<number>\d{1,9})[.)])\s+(?P<text>.*)$")
_TASK_RE = re.compile(r"^\[(?P<flag>[ xX])\]\s+(?P<text>.*)$")
_QUOTE_RE = re.compile(r"^\s{0,3}>\s?(?P<text>.*)$")
_RULE_RE = re.compile(r"^\s{0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$")
_TABLE_REF_LINE_RE = re.compile(r"^\s*\{\{table:\d+[^}]*\}\}\s*$")

_INLINE_RE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<image>!\[(?P<image_alt>[^\]]*)\]\((?P<image_src>[^)\s]+)\))"
    r"|(?P<link>\[(?P<link_text>[^\]]+)\]\((?P<link_href>[^)\s]+)\))"
    r"|(?P<wikilink>\[\[(?P<wiki_text>[^\]]+)\]\])"
    r"|(?P<bold>\*\*(?P<bold_text>.+?)\*\*)"
    r"|(?P<strike>~~(?P<strike_text>.+?)~~)"
    r"|(?P<italic>(?<!\*)\*(?!\*)(?P<star_text>[^*\n]+)\*(?!\*)|(?<!_)_(?!_)(?P<underscore_text>[^_\n]+)_(?!_))"
    r"|(?P<br><br\s*/?>)"
)

#: 列表最大层级（更深缩进并入最后一层，避免导出缩进跑到页边距外）
MAX_LIST_LEVEL = 7


def _plain_inline(text: str) -> str:
    """把行内标记还原为纯文本（用于链接文字、宽度估算等）."""
    out: list[str] = []
    pos = 0
    for match in _INLINE_RE.finditer(text):
        out.append(text[pos : match.start()])
        if match.group("code"):
            out.append(match.group("code")[1:-1])
        elif match.group("image"):
            out.append(match.group("image_alt"))
        elif match.group("link"):
            out.append(_plain_inline(match.group("link_text")))
        elif match.group("wikilink"):
            out.append(match.group("wiki_text"))
        elif match.group("bold"):
            out.append(_plain_inline(match.group("bold_text")))
        elif match.group("strike"):
            out.append(_plain_inline(match.group("strike_text")))
        elif match.group("italic"):
            out.append(_plain_inline(match.group("star_text") or match.group("underscore_text") or ""))
        elif match.group("br"):
            out.append(" ")
        pos = match.end()
    out.append(text[pos:])
    return "".join(out)


def parse_inline(text: str) -> tuple[InlineSpan, ...]:
    """把一行 Markdown 拆成行内片段.

    嵌套格式（如 ``**a `b`**``）按最外层标记折叠为纯文本，保证导出文字不丢字符；
    导出物不追求逐层套用样式，只保证与预览的可见文字一致。
    """
    spans: list[InlineSpan] = []
    pos = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > pos:
            spans.append(InlineSpan(INLINE_TEXT, text[pos : match.start()]))
        if match.group("code"):
            spans.append(InlineSpan(INLINE_CODE, match.group("code")[1:-1]))
        elif match.group("image"):
            spans.append(InlineSpan(INLINE_TEXT, match.group("image_alt") or "图片"))
        elif match.group("link"):
            label = _plain_inline(match.group("link_text"))
            spans.append(InlineSpan(INLINE_LINK, label, match.group("link_href")))
        elif match.group("wikilink"):
            spans.append(InlineSpan(INLINE_TEXT, match.group("wiki_text")))
        elif match.group("bold"):
            spans.append(InlineSpan(INLINE_BOLD, _plain_inline(match.group("bold_text"))))
        elif match.group("strike"):
            spans.append(InlineSpan(INLINE_STRIKE, _plain_inline(match.group("strike_text"))))
        elif match.group("italic"):
            body = match.group("star_text") or match.group("underscore_text") or ""
            spans.append(InlineSpan(INLINE_ITALIC, _plain_inline(body)))
        elif match.group("br"):
            spans.append(InlineSpan(INLINE_BREAK, ""))
        pos = match.end()
    if pos < len(text):
        spans.append(InlineSpan(INLINE_TEXT, text[pos:]))
    return tuple(spans)


def plain_text(spans: tuple[InlineSpan, ...] | list[InlineSpan]) -> str:
    """行内片段 → 纯文本（换行按空格计）."""
    parts: list[str] = []
    for span in spans:
        parts.append(" " if span.kind == INLINE_BREAK else span.text)
    return "".join(parts)


def display_width(text: str) -> int:
    """估算显示宽度：CJK / 全角字符按 2，其余按 1."""
    width = 0
    for ch in text:
        width += 2 if ord(ch) > 0x2E7F else 1
    return width


def fit_column_widths(
    weights: list[float],
    total: float,
    *,
    min_ratio: float = 0.08,
    max_ratio: float = 0.55,
) -> list[float]:
    """按内容权重分配列宽，并把每列收敛到 ``[min_ratio, max_ratio]``.

    最后一列取剩余值，保证 ``sum(widths) == total``（浮点误差只落在末列）。
    越界列固定后重新分配剩余宽度，最多迭代列数次即可收敛。
    """
    count = len(weights)
    if count == 0:
        return []
    sanitized = [max(1.0, float(w)) for w in weights]
    low, high = total * min_ratio, total * max_ratio
    widths = [0.0] * count
    clamped: dict[int, float] = {}
    for _ in range(count + 1):
        free = [i for i in range(count) if i not in clamped]
        if not free:
            break
        remaining = total - sum(clamped.values())
        free_weight = sum(sanitized[i] for i in free)
        for i in free:
            widths[i] = remaining * sanitized[i] / free_weight if free_weight else remaining / len(free)
        newly_clamped = False
        for i in free:
            if widths[i] < low:
                clamped[i] = low
                widths[i] = low
                newly_clamped = True
            elif widths[i] > high:
                clamped[i] = high
                widths[i] = high
                newly_clamped = True
        if not newly_clamped:
            break
    # 末列吸收浮点余量，保证总宽精确等于 total
    widths[-1] = total - sum(widths[:-1])
    return widths


def _split_table_cells(line: str) -> list[str]:
    """按未转义的 ``|`` 拆单元格，并去掉首尾空单元（外层竖线）."""
    stripped = line.strip()
    cells: list[str] = []
    buf: list[str] = []
    escaped = False
    for ch in stripped:
        if escaped:
            if ch != "|":
                buf.append("\\")
            buf.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "|":
            cells.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if escaped:
        buf.append("\\")
    cells.append("".join(buf))
    if cells and not cells[0].strip():
        cells = cells[1:]
    if cells and not cells[-1].strip():
        cells = cells[:-1]
    return [c.strip() for c in cells]


def _is_separator_row(line: str) -> bool:
    cells = _split_table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-+:?", c) for c in cells)


def _aligns_from_separator(line: str) -> tuple[str, ...]:
    aligns: list[str] = []
    for cell in _split_table_cells(line):
        left, right = cell.startswith(":"), cell.endswith(":")
        if left and right:
            aligns.append("center")
        elif right:
            aligns.append("right")
        else:
            aligns.append("left")
    return tuple(aligns)


def _indent_width(text: str) -> int:
    return len(text.expandtabs(4))


def _parse_list(lines: list[str], start: int) -> tuple[ListBlock, int]:
    """从 ``start`` 起解析连续列表；返回块与下一行下标."""
    items: list[ListItemBlock] = []
    indent_stack: list[int] = []
    counters: dict[int, int] = {}
    level_kinds: dict[int, bool] = {}
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            # 松散列表：空行后仍是列表项则继续，否则列表结束
            probe = index + 1
            while probe < len(lines) and not lines[probe].strip():
                probe += 1
            if probe < len(lines) and _LIST_RE.match(lines[probe]):
                index = probe
                continue
            break
        match = _LIST_RE.match(line)
        if match is None:
            # 列表项续行：缩进且不是新块 → 并入上一项
            if items and line[:1] in (" ", "\t") and not _starts_block(lines, index):
                previous = items[-1]
                text = f"{plain_text(previous.spans)} {line.strip()}"
                items[-1] = ListItemBlock(
                    previous.level,
                    previous.marker,
                    previous.ordered,
                    previous.checked,
                    parse_inline(text),
                )
                index += 1
                continue
            break

        indent = _indent_width(match.group("indent"))
        while indent_stack and indent < indent_stack[-1]:
            indent_stack.pop()
        if not indent_stack or indent > indent_stack[-1]:
            indent_stack.append(indent)
        level = min(len(indent_stack) - 1, MAX_LIST_LEVEL)

        for deeper in [key for key in counters if key > level]:
            counters.pop(deeper, None)
        for deeper in [key for key in level_kinds if key > level]:
            level_kinds.pop(deeper, None)

        ordered = match.group("number") is not None
        if ordered:
            number = int(match.group("number"))
            if level_kinds.get(level) is not True:
                counters[level] = number - 1
            counters[level] = counters.get(level, number - 1) + 1
            marker = f"{counters[level]}."
        else:
            marker = "•"
            counters.pop(level, None)
        level_kinds[level] = ordered

        text = match.group("text")
        checked: bool | None = None
        task_match = _TASK_RE.match(text)
        if task_match:
            checked = task_match.group("flag").lower() == "x"
            marker = "☑" if checked else "☐"
            text = task_match.group("text")
        items.append(ListItemBlock(level, marker, ordered, checked, parse_inline(text)))
        index += 1
    return ListBlock(tuple(items)), index


def _parse_table(lines: list[str], start: int) -> tuple[TableBlock, int]:
    header = _split_table_cells(lines[start])
    aligns = _aligns_from_separator(lines[start + 1])
    columns = len(header)
    if len(aligns) < columns:
        aligns = [*aligns, *(["left"] * (columns - len(aligns)))]
    rows: list[tuple[tuple[InlineSpan, ...], ...]] = []
    index = start + 2
    while index < len(lines):
        line = lines[index]
        if not line.strip() or "|" not in line:
            break
        cells = _split_table_cells(line)
        if not cells:
            break
        cells = (cells + [""] * columns)[:columns]
        rows.append(tuple(parse_inline(cell) for cell in cells))
        index += 1
    return (
        TableBlock(
            header=tuple(parse_inline(cell) for cell in header),
            rows=tuple(rows),
            aligns=tuple(aligns[:columns]),
        ),
        index,
    )


def _table_starts_at(lines: list[str], index: int) -> bool:
    """``index`` 行是否开启 GFM 表格（需下一行为同列数的分隔行）."""
    line = lines[index]
    if "|" not in line or index + 1 >= len(lines):
        return False
    separator = lines[index + 1]
    if not _is_separator_row(separator):
        return False
    return len(_split_table_cells(line)) == len(_split_table_cells(separator))


def _starts_block(lines: list[str], index: int) -> bool:
    """``index`` 行是否开启一个独立块（用于段落 / 列表续行的边界判定）."""
    line = lines[index]
    if not line.strip() or line.strip() == "---PAGE---":
        return True
    if _FENCE_RE.match(line) or _HEADING_RE.match(line) or _RULE_RE.match(line):
        return True
    if _QUOTE_RE.match(line) or _LIST_RE.match(line):
        return True
    if IMAGE_LINE_RE.match(line) or _TABLE_REF_LINE_RE.match(line):
        return True
    return _table_starts_at(lines, index)


def parse_blocks(markdown_text: str) -> list[Block]:
    """把 Markdown 正文解析为块序列（空行不产生块，间距由渲染样式负责）."""
    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        if stripped == "---PAGE---":
            blocks.append(PageBreakBlock())
            index += 1
            continue

        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group("fence")
            fence_char, fence_len = marker[0], len(marker)
            body: list[str] = []
            index += 1
            while index < len(lines):
                candidate = lines[index]
                closing = re.match(rf"^\s{{0,3}}{re.escape(fence_char)}{{{fence_len},}}\s*$", candidate)
                if closing:
                    index += 1
                    break
                body.append(candidate)
                index += 1
            blocks.append(CodeBlock(fence.group("info"), "\n".join(body)))
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            blocks.append(HeadingBlock(len(heading.group("marks")), parse_inline(heading.group("text"))))
            index += 1
            continue

        image = IMAGE_LINE_RE.match(line)
        if image:
            blocks.append(ImageBlock(image.group("alt") or "图片", image.group("key")))
            index += 1
            continue

        if _TABLE_REF_LINE_RE.match(line):
            blocks.append(TableRefBlock(stripped))
            index += 1
            continue

        if _table_starts_at(lines, index):
            table, index = _parse_table(lines, index)
            blocks.append(table)
            continue

        if _RULE_RE.match(line):
            blocks.append(RuleBlock())
            index += 1
            continue

        if _LIST_RE.match(line):
            list_block, index = _parse_list(lines, index)
            blocks.append(list_block)
            continue

        if _QUOTE_RE.match(line):
            quote_lines: list[tuple[InlineSpan, ...]] = []
            while index < len(lines):
                quote = _QUOTE_RE.match(lines[index])
                if quote is None:
                    break
                quote_lines.append(parse_inline(quote.group("text")))
                index += 1
            blocks.append(QuoteBlock(tuple(quote_lines)))
            continue

        # 普通段落：连续非空、非块起点的行按软换行合并（与预览一致）
        paragraph: list[str] = [stripped]
        index += 1
        while index < len(lines) and not _starts_block(lines, index):
            paragraph.append(lines[index].strip())
            index += 1
        blocks.append(ParagraphBlock(parse_inline(" ".join(paragraph))))
    return blocks


__all__ = [
    "MAX_LIST_LEVEL",
    "Block",
    "CodeBlock",
    "HeadingBlock",
    "ImageBlock",
    "InlineSpan",
    "ListBlock",
    "ListItemBlock",
    "PageBreakBlock",
    "ParagraphBlock",
    "QuoteBlock",
    "RuleBlock",
    "TableBlock",
    "TableRefBlock",
    "display_width",
    "fit_column_widths",
    "parse_blocks",
    "parse_inline",
    "plain_text",
]
