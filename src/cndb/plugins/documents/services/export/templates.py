"""文档导出模板：可配置排版（ADR 0152）.

一份 :class:`ExportTemplateConfig` 同时供电 ``docx`` 与 ``pdf`` 两个渲染器
（I3）：Word 侧完整生效，PDF 侧按自身能力映射（字体族最佳匹配、域类特性跳过）。

三件事只在这里做：

1. **配置模型与校验**：``validate_config`` 是唯一入口，越界 / 未知字段一律
   ``ValueError``（路由层转 400），不做静默夹取，避免「保存成功但效果不对」。
2. **内置预设**：代码常量（不入库），共 6 套（研究报告 / 技术报告 / 趋势分析 / 论文 /
   公文 / 宣传报道）；未指定模板时用 ``research``（研究报告，企业报告规范的通用基线）。
3. **解析链**：``resolve_export_template`` = 显式 ref → 工作区默认 → 内置 ``research``。
   导出器与路由都只调它（I1）。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_logger = logging.getLogger(__name__)

# ── 取值域 ──

PAPER_SIZES: tuple[str, ...] = ("A4", "A3", "Letter")
ALIGNS: tuple[str, ...] = ("left", "center", "right", "justify")
LINE_SPACING_RULES: tuple[str, ...] = ("multiple", "fixed")
PAGE_NUMBER_MODES: tuple[str, ...] = ("none", "plain", "page", "page_of_total")
HEADING_NUMBERING: tuple[str, ...] = ("none", "arabic_multilevel", "chapter_chinese", "cn_ordinal")
HEADING_NUMBERING_MODES: tuple[str, ...] = ("auto", "force", "off")
TABLE_STYLES: tuple[str, ...] = ("single", "three_line")
LIST_MARKERS: tuple[str, ...] = ("bullet", "dash", "dot")
CAPTION_POSITIONS: tuple[str, ...] = ("above", "below")
CAPTION_NUMBERING: tuple[str, ...] = ("n", "n-n")

_HEX_COLOR = r"^#[0-9a-fA-F]{6}$"
_FONT_NAME = r"^[\w \-.（）()]{1,64}$"

#: 模板引用：``builtin:<key>`` 或十进制行 id
_BUILTIN_PREFIX = "builtin:"

#: 表格题注的显式写法：表格前紧邻段落须为「表：说明」/「表: 说明」
TABLE_CAPTION_RE = re.compile(r"^表\s*[：:]\s*(?P<text>.+)$")


class PageConfig(BaseModel):
    """纸张与页边距（cm）."""

    model_config = ConfigDict(extra="forbid")

    paper: Literal["A4", "A3", "Letter"] = "A4"
    margin_top: float = Field(default=2.54, ge=0.5, le=5.0)
    margin_bottom: float = Field(default=2.54, ge=0.5, le=5.0)
    margin_left: float = Field(default=2.54, ge=0.5, le=5.0)
    margin_right: float = Field(default=2.54, ge=0.5, le=5.0)


class HeaderFooterConfig(BaseModel):
    """页眉文字与页脚页码（标准预设默认关闭，保持历史导出不变）."""

    model_config = ConfigDict(extra="forbid")

    header_text: str = Field(default="", max_length=120)
    page_number: Literal["none", "plain", "page", "page_of_total"] = "none"
    first_page_different: bool = False
    font_size: float = Field(default=8.0, ge=6.0, le=14.0)


class BodyConfig(BaseModel):
    """正文段落：字体 / 字号 / 对齐 / 行距 / 间距 / 缩进."""

    model_config = ConfigDict(extra="forbid")

    latin_font: str = Field(default="Calibri", pattern=_FONT_NAME)
    east_asia_font: str = Field(default="Calibri", pattern=_FONT_NAME)
    size: float = Field(default=10.5, ge=8.0, le=72.0)
    bold: bool = False
    color: str = Field(default="#000000", pattern=_HEX_COLOR)
    align: Literal["left", "center", "right", "justify"] = "left"
    line_spacing_rule: Literal["multiple", "fixed"] = "multiple"
    line_spacing: float = Field(default=1.08, ge=1.0, le=3.0)
    line_spacing_pt: float = Field(default=15.0, ge=10.0, le=60.0)
    space_before: float = Field(default=0.0, ge=0.0, le=36.0)
    space_after: float = Field(default=8.0, ge=0.0, le=36.0)
    first_line_indent_chars: float = Field(default=0.0, ge=0.0, le=8.0)
    char_spacing: float = Field(default=0.0, ge=-2.0, le=10.0)
    widow_control: bool = True
    keep_with_next: bool = False


class HeadingConfig(BaseModel):
    """单级标题排版（H1..H6 各一份）."""

    model_config = ConfigDict(extra="forbid")

    latin_font: str = Field(default="Calibri", pattern=_FONT_NAME)
    east_asia_font: str = Field(default="Calibri", pattern=_FONT_NAME)
    size: float = Field(default=18.0, ge=8.0, le=72.0)
    bold: bool = True
    color: str = Field(default="#000000", pattern=_HEX_COLOR)
    align: Literal["left", "center", "right", "justify"] = "left"
    space_before: float = Field(default=12.0, ge=0.0, le=36.0)
    space_after: float = Field(default=6.0, ge=0.0, le=36.0)
    first_line_indent_chars: float = Field(default=0.0, ge=0.0, le=8.0)
    keep_with_next: bool = True


class NumberingConfig(BaseModel):
    """标题自动编号方案 + 叠加时机（ADR 0186）.

    ``mode`` 决定模板编号何时生效（编号权威只有模板一处，正文自带序号时让位）：

    - ``auto``（默认）：正文标题已含显式序号（``一、`` / ``3.1`` / ``第一章``）时本次
      导出不叠加，否则按 ``heading`` 生成；
    - ``force``：始终按 ``heading`` 生成（升级前行为，可能产生重复编号）；
    - ``off``：从不生成编号（语义是「这篇不要编号」，与 ``heading="none"`` 区分）。
    """

    model_config = ConfigDict(extra="forbid")

    heading: Literal["none", "arabic_multilevel", "chapter_chinese", "cn_ordinal"] = "none"
    mode: Literal["auto", "force", "off"] = "auto"


class TableConfig(BaseModel):
    """表格：样式 / 表头配色 / 字体 / 边框 / 跨页与斑马纹."""

    model_config = ConfigDict(extra="forbid")

    style: Literal["single", "three_line"] = "single"
    header_bg: str = Field(default="#E6EEF5", pattern=_HEX_COLOR)
    header_color: str = Field(default="#1A5276", pattern=_HEX_COLOR)
    header_bold: bool = True
    latin_font: str = Field(default="Calibri", pattern=_FONT_NAME)
    east_asia_font: str = Field(default="Calibri", pattern=_FONT_NAME)
    size: float = Field(default=10.5, ge=6.0, le=24.0)
    border_color: str = Field(default="#000000", pattern=_HEX_COLOR)
    header_repeat: bool = True
    zebra: bool = False
    cell_valign: Literal["top", "center"] = "top"


class CaptionStyleConfig(BaseModel):
    """题注（图 / 表）排版."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    position: Literal["above", "below"] = "below"
    numbering: Literal["n", "n-n"] = "n"
    size: float = Field(default=9.0, ge=6.0, le=24.0)
    align: Literal["left", "center", "right"] = "center"


class CaptionsConfig(BaseModel):
    """图 / 表题注配置."""

    model_config = ConfigDict(extra="forbid")

    figure: CaptionStyleConfig = Field(
        default_factory=lambda: CaptionStyleConfig(enabled=False, position="below", numbering="n")
    )
    table: CaptionStyleConfig = Field(
        default_factory=lambda: CaptionStyleConfig(enabled=False, position="above", numbering="n")
    )


class ListConfig(BaseModel):
    """列表缩进 / 段后 / 项目符号."""

    model_config = ConfigDict(extra="forbid")

    indent_pt: float = Field(default=16.0, ge=8.0, le=40.0)
    hanging_pt: float = Field(default=14.0, ge=4.0, le=30.0)
    space_after: float = Field(default=2.0, ge=0.0, le=12.0)
    marker: Literal["bullet", "dash", "dot"] = "bullet"


class CodeConfig(BaseModel):
    """代码块排版."""

    model_config = ConfigDict(extra="forbid")

    latin_font: str = Field(default="Courier New", pattern=_FONT_NAME)
    east_asia_font: str = Field(default="Courier New", pattern=_FONT_NAME)
    size: float = Field(default=9.0, ge=6.0, le=24.0)
    bg: str = Field(default="#F6F8FA", pattern=_HEX_COLOR)
    border: str = Field(default="#E5E7EB", pattern=_HEX_COLOR)
    left_bar: bool = False


class ExportTemplateConfig(BaseModel):
    """一份导出模板的完整排版（ADR 0152 C3 五组）."""

    model_config = ConfigDict(extra="forbid")

    page: PageConfig = Field(default_factory=PageConfig)
    header_footer: HeaderFooterConfig = Field(default_factory=HeaderFooterConfig)
    body: BodyConfig = Field(default_factory=BodyConfig)
    headings: list[HeadingConfig] = Field(default_factory=list)
    numbering: NumberingConfig = Field(default_factory=NumberingConfig)
    table: TableConfig = Field(default_factory=TableConfig)
    captions: CaptionsConfig = Field(default_factory=CaptionsConfig)
    lists: ListConfig = Field(default_factory=ListConfig)
    code: CodeConfig = Field(default_factory=CodeConfig)

    def heading(self, level: int) -> HeadingConfig:
        """取第 ``level``（1..6）级标题配置；配置不足时沿用最后一级."""
        index = min(max(level, 1), 6) - 1
        if not self.headings:
            return HeadingConfig()
        return self.headings[min(index, len(self.headings) - 1)]


@dataclass(frozen=True)
class ResolvedTemplate:
    """解析后的模板：``ref`` 指回来源，``config`` 是渲染唯一输入."""

    ref: str
    name: str
    source: str  # builtin / custom
    config: ExportTemplateConfig

    @property
    def description(self) -> str:
        return self.name


@dataclass(frozen=True)
class BuiltinTemplate:
    """内置预设（代码常量，不入库，只能被引用或另存为）."""

    key: str
    name: str
    description: str
    config: ExportTemplateConfig

    @property
    def ref(self) -> str:
        return f"{_BUILTIN_PREFIX}{self.key}"


def _headings(
    *,
    latin: str,
    east_asia: str,
    sizes: tuple[float, ...],
    before: tuple[float, ...],
    after: tuple[float, ...],
    align: tuple[str, ...] | None = None,
) -> list[HeadingConfig]:
    """按 6 级生成标题配置（sizes / before / after 至少 3 项，末位向后沿用）."""
    aligns = align or ("left",) * 6
    return [
        HeadingConfig(
            latin_font=latin,
            east_asia_font=east_asia,
            size=_pick(sizes, level),
            align=aligns[level - 1],  # type: ignore[arg-type]
            space_before=_pick(before, level),
            space_after=_pick(after, level),
        )
        for level in range(1, 7)
    ]


def _pick(values: tuple[float, ...], level: int) -> float:
    return values[min(level, len(values)) - 1] if level <= len(values) else values[-1]


def _thesis_config() -> ExportTemplateConfig:
    """学术论文：宋体 12pt / 1.5 倍行距 / 首行缩进 2 字符 / 三线表 + 题注."""
    return ExportTemplateConfig(
        header_footer=HeaderFooterConfig(page_number="plain"),
        body=BodyConfig(
            latin_font="Times New Roman",
            east_asia_font="宋体",
            size=12.0,
            align="justify",
            line_spacing=1.5,
            space_before=0.0,
            space_after=0.0,
            first_line_indent_chars=2.0,
        ),
        headings=_headings(
            latin="Times New Roman",
            east_asia="黑体",
            sizes=(18.0, 15.0, 13.0, 12.0, 12.0, 12.0),
            before=(18.0, 12.0, 10.0, 8.0, 8.0, 8.0),
            after=(12.0, 8.0, 6.0, 4.0, 4.0, 4.0),
            align=("center", "left", "left", "left", "left", "left"),
        ),
        numbering=NumberingConfig(heading="chapter_chinese"),
        table=TableConfig(
            style="three_line",
            header_bg="#FFFFFF",
            header_color="#000000",
            latin_font="Times New Roman",
            east_asia_font="宋体",
            size=10.5,
            border_color="#000000",
            cell_valign="center",
        ),
        captions=CaptionsConfig(
            figure=CaptionStyleConfig(enabled=True, position="below", numbering="n-n", align="center"),
            table=CaptionStyleConfig(enabled=True, position="above", numbering="n-n", align="center"),
        ),
    )


def _research_config() -> ExportTemplateConfig:
    """研究报告（企业通用规范）：A4 + 2.54cm 边距 / 宋体小四 12pt / 1.5 倍行距 /
    首行缩进 2 字符 / 黑体标题 16·14·12 / 三线表 / 图表题注 / 1·1.1·1.1.1 编号."""
    return ExportTemplateConfig(
        header_footer=HeaderFooterConfig(header_text="研究报告", page_number="page", font_size=9.0),
        body=BodyConfig(
            latin_font="Times New Roman",
            east_asia_font="宋体",
            size=12.0,
            align="justify",
            line_spacing=1.5,
            space_before=0.0,
            space_after=0.0,
            first_line_indent_chars=2.0,
        ),
        headings=_headings(
            latin="Times New Roman",
            east_asia="黑体",
            sizes=(16.0, 14.0, 12.0, 12.0, 12.0, 12.0),
            before=(16.0, 12.0, 10.0, 8.0, 8.0, 8.0),
            after=(10.0, 8.0, 6.0, 4.0, 4.0, 4.0),
            align=("center", "left", "left", "left", "left", "left"),
        ),
        numbering=NumberingConfig(heading="arabic_multilevel"),
        table=TableConfig(
            style="three_line",
            header_color="#000000",
            header_bg="#FFFFFF",
            latin_font="Times New Roman",
            east_asia_font="宋体",
            size=10.5,
            cell_valign="center",
        ),
        captions=CaptionsConfig(
            figure=CaptionStyleConfig(enabled=True, position="below", numbering="n", align="center"),
            table=CaptionStyleConfig(enabled=True, position="above", numbering="n", align="center"),
        ),
    )


def _techreport_config() -> ExportTemplateConfig:
    """技术报告（研发交付）：正文宋体小四 12pt / 1.5 倍行距 / 首行缩进 2 字符；
    标题黑体三号→四号→小四；浅蓝表头 + 表头跨页重复；图表题注「图 1-1」；页脚页码."""
    return ExportTemplateConfig(
        header_footer=HeaderFooterConfig(page_number="page", font_size=9.0),
        body=BodyConfig(
            latin_font="Times New Roman",
            east_asia_font="宋体",
            size=12.0,
            align="justify",
            line_spacing=1.5,
            space_before=0.0,
            space_after=0.0,
            first_line_indent_chars=2.0,
        ),
        headings=_headings(
            latin="Times New Roman",
            east_asia="黑体",
            sizes=(16.0, 14.0, 12.0, 12.0, 12.0, 12.0),
            before=(18.0, 14.0, 10.0, 8.0, 8.0, 8.0),
            after=(10.0, 8.0, 6.0, 4.0, 4.0, 4.0),
            align=("center", "left", "left", "left", "left", "left"),
        ),
        numbering=NumberingConfig(heading="arabic_multilevel"),
        table=TableConfig(
            header_bg="#E6EEF5",
            header_color="#1A5276",
            east_asia_font="宋体",
            latin_font="Times New Roman",
            size=10.5,
            cell_valign="center",
        ),
        captions=CaptionsConfig(
            figure=CaptionStyleConfig(enabled=True, position="below", numbering="n-n", align="center"),
            table=CaptionStyleConfig(enabled=True, position="above", numbering="n-n", align="center"),
        ),
    )


def _trend_config() -> ExportTemplateConfig:
    """趋势分析（数据简报）：正文宋体小四 12pt / 1.5 倍行距 / 首行缩进 2 字符；
    左对齐多级编号 + 斑马纹表格便于扫读；图表题注在下."""
    return ExportTemplateConfig(
        header_footer=HeaderFooterConfig(page_number="plain", font_size=9.0),
        body=BodyConfig(
            latin_font="Times New Roman",
            east_asia_font="宋体",
            size=12.0,
            line_spacing=1.5,
            space_before=0.0,
            space_after=0.0,
            first_line_indent_chars=2.0,
        ),
        headings=_headings(
            latin="Times New Roman",
            east_asia="黑体",
            sizes=(16.0, 14.0, 12.0, 12.0, 12.0, 12.0),
            before=(14.0, 12.0, 10.0, 8.0, 8.0, 8.0),
            after=(8.0, 6.0, 4.0, 3.0, 3.0, 3.0),
        ),
        numbering=NumberingConfig(heading="arabic_multilevel"),
        table=TableConfig(
            header_bg="#EAF2FB",
            header_color="#1F3864",
            east_asia_font="宋体",
            latin_font="Times New Roman",
            size=10.5,
            zebra=True,
        ),
        captions=CaptionsConfig(
            figure=CaptionStyleConfig(enabled=True, position="below", numbering="n", align="center"),
            table=CaptionStyleConfig(enabled=True, position="above", numbering="n", align="center"),
        ),
    )


def _thesis_config() -> ExportTemplateConfig:
    """论文（学位论文编写规则 GB/T 7713 系列通行口径）：A4 / 上 2.5 下 2.5 左 3.0（装订侧）右 2.5；
    正文宋体小四 12pt / 1.5 倍行距 / 首行缩进 2 字符；一级标题黑体三号居中（第一章）/
    二级黑体四号 / 三级黑体小四；三线表 + 「图 1-1」题注."""
    return ExportTemplateConfig(
        page=PageConfig(margin_top=2.5, margin_bottom=2.5, margin_left=3.0, margin_right=2.5),
        header_footer=HeaderFooterConfig(page_number="plain"),
        body=BodyConfig(
            latin_font="Times New Roman",
            east_asia_font="宋体",
            size=12.0,
            align="justify",
            line_spacing=1.5,
            space_before=0.0,
            space_after=0.0,
            first_line_indent_chars=2.0,
        ),
        headings=_headings(
            latin="Times New Roman",
            east_asia="黑体",
            sizes=(16.0, 14.0, 12.0, 12.0, 12.0, 12.0),
            before=(18.0, 12.0, 10.0, 8.0, 8.0, 8.0),
            after=(12.0, 8.0, 6.0, 4.0, 4.0, 4.0),
            align=("center", "left", "left", "left", "left", "left"),
        ),
        numbering=NumberingConfig(heading="chapter_chinese"),
        table=TableConfig(
            style="three_line",
            header_bg="#FFFFFF",
            header_color="#000000",
            latin_font="Times New Roman",
            east_asia_font="宋体",
            size=10.5,
            border_color="#000000",
            cell_valign="center",
        ),
        captions=CaptionsConfig(
            figure=CaptionStyleConfig(enabled=True, position="below", numbering="n-n", align="center"),
            table=CaptionStyleConfig(enabled=True, position="above", numbering="n-n", align="center"),
        ),
    )


def _official_config() -> ExportTemplateConfig:
    """公文（GB/T 9704-2012 党政机关公文格式）：
    页边距 上 37mm / 下 35mm / 左 28mm / 右 26mm；正文三号仿宋（16pt）固定行距 28pt、首行缩进 2 字；
    标题 2 号小标宋（22pt）居中；一级「一、」黑体三号、二级「（一）」楷体三号、三级「1.」仿宋三号加粗；
    页码 4 号宋体数字（公文不写「第 X 页 共 Y 页」）."""
    return ExportTemplateConfig(
        page=PageConfig(margin_top=3.7, margin_bottom=3.5, margin_left=2.8, margin_right=2.6),
        header_footer=HeaderFooterConfig(page_number="plain", first_page_different=True, font_size=14.0),
        body=BodyConfig(
            latin_font="Times New Roman",
            east_asia_font="仿宋",
            size=16.0,
            line_spacing_rule="fixed",
            line_spacing_pt=28.0,
            space_before=0.0,
            space_after=0.0,
            first_line_indent_chars=2.0,
        ),
        headings=[
            HeadingConfig(
                latin_font="Times New Roman",
                east_asia_font="方正小标宋简体",
                size=22.0,
                bold=False,
                align="center",
                space_before=18.0,
                space_after=14.0,
            ),
            HeadingConfig(
                latin_font="Times New Roman",
                east_asia_font="黑体",
                size=16.0,
                bold=False,
                space_before=12.0,
                space_after=8.0,
            ),
            HeadingConfig(
                latin_font="Times New Roman",
                east_asia_font="楷体",
                size=16.0,
                bold=False,
                space_before=10.0,
                space_after=6.0,
            ),
            HeadingConfig(
                latin_font="Times New Roman",
                east_asia_font="仿宋",
                size=16.0,
                bold=True,
                space_before=8.0,
                space_after=4.0,
            ),
            HeadingConfig(
                latin_font="Times New Roman",
                east_asia_font="仿宋",
                size=16.0,
                bold=False,
                space_before=8.0,
                space_after=4.0,
            ),
            HeadingConfig(
                latin_font="Times New Roman",
                east_asia_font="仿宋",
                size=16.0,
                bold=False,
                space_before=8.0,
                space_after=4.0,
            ),
        ],
        numbering=NumberingConfig(heading="cn_ordinal"),
        table=TableConfig(
            header_bg="#FFFFFF",
            header_color="#000000",
            east_asia_font="仿宋",
            latin_font="Times New Roman",
            size=12.0,
            border_color="#000000",
            cell_valign="center",
        ),
    )


def _press_config() -> ExportTemplateConfig:
    """宣传报道：正文宋体小四 12pt / 1.5 倍行距 / 不缩进（网媒阅读习惯）；
    标题黑体号数递减、一级居中；浅暖色表头."""
    return ExportTemplateConfig(
        header_footer=HeaderFooterConfig(page_number="none"),
        body=BodyConfig(
            latin_font="Times New Roman",
            east_asia_font="宋体",
            size=12.0,
            line_spacing=1.5,
            space_before=0.0,
            space_after=4.0,
        ),
        headings=_headings(
            latin="Times New Roman",
            east_asia="黑体",
            sizes=(18.0, 15.0, 13.0, 12.0, 12.0, 12.0),
            before=(18.0, 14.0, 10.0, 8.0, 8.0, 8.0),
            after=(10.0, 8.0, 6.0, 4.0, 4.0, 4.0),
            align=("center", "left", "left", "left", "left", "left"),
        ),
        table=TableConfig(
            header_bg="#FDF1EC",
            header_color="#8A3B12",
            east_asia_font="宋体",
            latin_font="Times New Roman",
            size=10.5,
        ),
    )


BUILTIN_TEMPLATES: dict[str, BuiltinTemplate] = {
    "research": BuiltinTemplate(
        key="research",
        name="研究报告",
        description="企业通用规范：宋体小四 12pt、1.5 倍行距、首行缩进 2 字符、三线表、图表题注、1·1.1·1.1.1 编号",
        config=_research_config(),
    ),
    "techreport": BuiltinTemplate(
        key="techreport",
        name="技术报告",
        description="研发交付：宋体小四 12pt、黑体标题三号→四号→小四、浅蓝表头、图 1-1 题注、页脚页码",
        config=_techreport_config(),
    ),
    "trend": BuiltinTemplate(
        key="trend",
        name="趋势分析",
        description="数据简报：宋体小四 12pt、1·1.1·1.1.1 编号、斑马纹表格、图表题注、页脚页码",
        config=_trend_config(),
    ),
    "thesis": BuiltinTemplate(
        key="thesis",
        name="论文",
        description="学位论文通行口径（GB/T 7713 系列）：宋体小四 12pt、左侧装订边 3cm、第一章编号、三线表、图 1-1 题注",
        config=_thesis_config(),
    ),
    "official": BuiltinTemplate(
        key="official",
        name="公文",
        description="GB/T 9704-2012：仿宋三号、固定行距 28pt、页边距 37/35/28/26mm、小标宋标题、一、/（一）/1./（1）层次序数、4 号页码",
        config=_official_config(),
    ),
    "press": BuiltinTemplate(
        key="press",
        name="宣传报道",
        description="网媒稿件：宋体小四 12pt、1.5 倍行距、不缩进、标题黑体居中",
        config=_press_config(),
    ),
}

DEFAULT_TEMPLATE_KEY = "research"
DEFAULT_TEMPLATE_REF = f"{_BUILTIN_PREFIX}{DEFAULT_TEMPLATE_KEY}"


def validate_config(raw: Mapping[str, Any] | None) -> ExportTemplateConfig:
    """把外部提交的 config 校验成 :class:`ExportTemplateConfig`.

    Raises:
        ValueError: 缺字段以外的一切非法（越界 / 未知字段 / 未知枚举）都报错，
            文案里带字段路径，路由层直接转 400。
    """
    if raw is None:
        return BUILTIN_TEMPLATES[DEFAULT_TEMPLATE_KEY].config
    try:
        config = ExportTemplateConfig.model_validate(dict(raw))
    except ValidationError as exc:
        first: dict[str, Any] = dict(exc.errors()[0]) if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ()))
        message = first.get("msg", "配置不合法")
        raise ValueError(f"模板配置不合法（{location or 'config'}）：{message}") from exc
    return _normalize_headings(config)


def _normalize_headings(config: ExportTemplateConfig) -> ExportTemplateConfig:
    """把不足 6 级的标题配置补齐到 6 级（缺省沿用末位），保证渲染恒定可预期."""
    if len(config.headings) == 6:
        return config
    if not config.headings:
        config.headings = _headings(
            latin=config.body.latin_font,
            east_asia=config.body.east_asia_font,
            sizes=(18.0, 15.0, 13.0, 12.0, 11.0, 10.5),
            before=(12.0, 10.0, 8.0, 6.0, 6.0, 6.0),
            after=(6.0, 5.0, 4.0, 3.0, 3.0, 3.0),
        )
        return config
    last = config.headings[-1]
    while len(config.headings) < 6:
        config.headings.append(last.model_copy())
    return config


def config_to_dict(config: ExportTemplateConfig) -> dict[str, Any]:
    """落库 / 备份用的规范化 dict（JSON 列与备份载荷共用一份口径）."""
    return config.model_dump(mode="json")


def normalize_ref(ref: str | None) -> str | None:
    """把模板引用规范化为 ``builtin:<key>`` / 数字字符串 / None.

    Raises:
        ValueError: ref 既不是内置 key 也不是正整数 id。
    """
    if ref is None:
        return None
    text = str(ref).strip()
    if not text:
        return None
    if text.startswith(_BUILTIN_PREFIX):
        key = text[len(_BUILTIN_PREFIX) :].strip()
        return f"{_BUILTIN_PREFIX}{key}"
    if re.fullmatch(r"\d+", text):
        return text
    raise ValueError(f"不支持的模板引用: {text}")


def builtin_template(key: str) -> BuiltinTemplate | None:
    return BUILTIN_TEMPLATES.get(key)


def resolve_builtin(ref: str | None) -> ResolvedTemplate | None:
    """只解析内置引用（无库依赖）；非内置或未知 key 返回 None."""
    if not ref or not ref.startswith(_BUILTIN_PREFIX):
        return None
    template = BUILTIN_TEMPLATES.get(ref[len(_BUILTIN_PREFIX) :])
    if template is None:
        return None
    return ResolvedTemplate(ref=template.ref, name=template.name, source="builtin", config=template.config)


def default_template() -> ResolvedTemplate:
    template = BUILTIN_TEMPLATES[DEFAULT_TEMPLATE_KEY]
    return ResolvedTemplate(ref=template.ref, name=template.name, source="builtin", config=template.config)


def validate_export_template_ref(db: Any, workspace_id: int, ref: str | None) -> str | None:
    """写入口校验（ADR 0177 D9）：规范化引用并检查存在性与工作区归属.

    Returns:
        规范化后的 ``builtin:<key>`` / 数字字符串，或 ``None``（未绑定）。

    Raises:
        ValueError: 格式非法、内置 key 未知或模板不属于该工作区（路由转 400）。
    """
    normalized = normalize_ref(ref)
    if normalized is None:
        return None
    from cndb.core.errors import NotFoundError

    try:
        _resolve_normalized(db, workspace_id, normalized)
    except NotFoundError as exc:
        raise ValueError("模板不存在或不属于当前工作区") from exc
    return normalized


def resolve_export_template(
    db: Any, workspace_id: int, ref: str | None = None, *, document_ref: str | None = None
) -> ResolvedTemplate:
    """唯一解析入口：显式 ref → 文档绑定 → 工作区默认 → 内置 ``research``（I1 / D9）.

    ``document_ref`` 是文档 / 内容模板上的绑定：失败（格式非法 / 已删 / 跨工作区）
    **记 warning 后静默跳过**，不阻断导出，也不向调用方泄露模板是否存在（I3）。

    Raises:
        ValueError: 显式 ref 格式非法。
        NotFoundError: 显式 ref 指向的模板不存在 / 不属于该工作区（统一 404）。
    """
    from cndb.core.errors import NotFoundError
    from cndb.plugins.documents.models import ExportTemplate

    normalized = normalize_ref(ref)
    if normalized is not None:
        return _resolve_normalized(db, workspace_id, normalized)

    if document_ref is not None:
        try:
            bound = normalize_ref(document_ref)
            if bound is not None:
                return _resolve_normalized(db, workspace_id, bound)
        except (ValueError, NotFoundError):
            _logger.warning(
                "文档绑定的排版模板不可用，已回落工作区默认: ref=%r workspace=%s",
                document_ref,
                workspace_id,
            )

    row = (
        db.query(ExportTemplate)
        .filter(ExportTemplate.workspace_id == workspace_id, ExportTemplate.is_default.is_(True))
        .order_by(ExportTemplate.id)
        .first()
    )
    if row is not None:
        return _resolved_from_row(row)
    return default_template()


def _resolve_normalized(db: Any, workspace_id: int, normalized: str) -> ResolvedTemplate:
    """规范化引用 → 解析结果；未知内置 key / 跨区 / 已删统一 ``NotFoundError``."""
    from cndb.core.errors import NotFoundError
    from cndb.plugins.documents.models import ExportTemplate

    builtin = resolve_builtin(normalized)
    if builtin is not None:
        return builtin
    if normalized.startswith(_BUILTIN_PREFIX):
        raise NotFoundError("模板不存在")
    row = db.get(ExportTemplate, int(normalized))
    if row is None or row.workspace_id != workspace_id:
        raise NotFoundError("模板不存在")
    return _resolved_from_row(row)


def _resolved_from_row(row: Any) -> ResolvedTemplate:
    """库里的自定义模板 → 可渲染的解析结果.

    **损坏的配置不阻断导出**：历史数据 / 手工改库 / 旧版本字段可能让 ``config`` 校验失败，
    这时记一条告警并回落到内置默认模板（研究报告），保证「导出」这个主流程永远能出文件；
    用户在模板面板里仍能看到该模板并自行修正或删除（面板加载走 `list_templates`，不经过这里）。
    """
    import logging

    try:
        config = validate_config(row.config or {})
    except ValueError:
        logging.getLogger(__name__).warning(
            "导出模板配置非法，已回落默认模板: id=%s name=%r", getattr(row, "id", None), getattr(row, "name", None)
        )
        return default_template()
    return ResolvedTemplate(
        ref=str(row.id),
        name=row.name,
        source="custom",
        config=config,
    )


def heading_prefix(scheme: str, level: int, counters: list[int]) -> str:
    """按编号方案生成标题前缀文本（不含尾部分隔，调用方决定空白）.

    方案与推荐文体一一对应（前端下拉同样标注，避免用户凭感觉选错）：
    - ``arabic_multilevel``：``1`` / ``1.1`` / ``1.1.1`` —— 研究报告 / 技术报告 / 趋势分析 / 周报；
    - ``chapter_chinese``：``第一章`` / ``1.1`` / ``1.1.1`` —— 论文 / 专著；
    - ``cn_ordinal``：``一、`` / ``（一）`` / ``1.`` / ``（1）`` —— 公文 / 函件（GB/T 9704 层次序数）。

    ``counters`` 为长度 6 的层级计数器（调用方负责自增 / 清零）。
    """
    if scheme == "none":
        return ""
    level = min(max(level, 1), 6)
    numbers = counters[:level]
    if scheme == "arabic_multilevel":
        return ".".join(str(n) for n in numbers)
    if scheme == "chapter_chinese":
        if level == 1:
            return f"第{_chinese_number(numbers[0])}章"
        return ".".join(str(n) for n in numbers)
    # cn_ordinal（党政机关公文 / GB/T 9704 层次序数）：一、→（一）→ 1. →（1）
    if level == 1:
        return f"{_chinese_number(numbers[0])}、"
    if level == 2:
        return f"（{_chinese_number(numbers[1])}）"
    if level == 3:
        return f"{numbers[2]}."
    if level == 4:
        return f"（{numbers[3]}）"
    return ".".join(str(n) for n in numbers)


_CN_DIGITS = "零一二三四五六七八九"


def _chinese_number(value: int) -> str:
    """1..99 的中文数字（标题编号只需这个范围，超出原样返回）."""
    if value <= 0 or value >= 100:
        return str(value)
    if value < 10:
        return _CN_DIGITS[value]
    tens, ones = divmod(value, 10)
    prefix = "十" if tens == 1 else f"{_CN_DIGITS[tens]}十"
    return prefix if ones == 0 else f"{prefix}{_CN_DIGITS[ones]}"


def advance_counters(counters: list[int], level: int) -> list[int]:
    """标题计数器推进：本级 +1，更深层清零."""
    level = min(max(level, 1), len(counters))
    counters[level - 1] += 1
    for index in range(level, len(counters)):
        counters[index] = 0
    return counters


def sample_markdown() -> str:
    """模板预览用的示例正文（覆盖标题 / 正文 / 列表 / 表格 / 代码 / 引用）."""
    return (
        "# 第一章 概述\n\n"
        "这是一段示例正文，用于查看字体、字号、行距、段前段后与首行缩进的实际效果。"
        "中文与 English mixed text 都会按当前模板排版。\n\n"
        "## 1.1 背景\n\n"
        "- 第一个要点\n"
        "- 第二个要点\n\n"
        "### 1.1.1 细节\n\n"
        "| 指标 | 说明 | 数量 |\n| --- | --- | ---: |\n"
        "| 覆盖率 | 单位测试行覆盖 | 95.2 |\n"
        "| 用例数 | 自动化用例 | 7201 |\n\n"
        "> 引用块示例：模板只决定排版，不改变正文语义。\n\n"
        "```python\nprint('hello template')\n```\n"
    )


def render_sample(fmt: str, config: ExportTemplateConfig) -> bytes:
    """用示例正文渲染一份导入模板的示例文件（preview 端点用）."""
    from cndb.plugins.documents.services.export.docx import _render_docx
    from cndb.plugins.documents.services.export.pdf import _render_pdf

    resolved = ResolvedTemplate(ref="preview", name="示例预览", source="custom", config=config)
    text = sample_markdown()
    if fmt == "pdf":
        return _render_pdf(text, title="模板示例", template=resolved)
    return _render_docx(text, title="模板示例", template=resolved)


__all__ = [
    "ALIGNS",
    "BUILTIN_TEMPLATES",
    "CAPTION_NUMBERING",
    "CAPTION_POSITIONS",
    "DEFAULT_TEMPLATE_KEY",
    "DEFAULT_TEMPLATE_REF",
    "HEADING_NUMBERING",
    "HEADING_NUMBERING_MODES",
    "LINE_SPACING_RULES",
    "LIST_MARKERS",
    "PAGE_NUMBER_MODES",
    "PAPER_SIZES",
    "TABLE_CAPTION_RE",
    "TABLE_STYLES",
    "BodyConfig",
    "BuiltinTemplate",
    "CaptionStyleConfig",
    "CaptionsConfig",
    "CodeConfig",
    "ExportTemplateConfig",
    "HeaderFooterConfig",
    "HeadingConfig",
    "ListConfig",
    "NumberingConfig",
    "PageConfig",
    "ResolvedTemplate",
    "TableConfig",
    "advance_counters",
    "builtin_template",
    "config_to_dict",
    "default_template",
    "heading_prefix",
    "normalize_ref",
    "render_sample",
    "resolve_builtin",
    "resolve_export_template",
    "sample_markdown",
    "validate_config",
    "validate_export_template_ref",
]
