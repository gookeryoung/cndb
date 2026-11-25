"""文档导出模板：可配置排版（ADR 0152）.

一份 :class:`ExportTemplateConfig` 同时供电 ``docx`` 与 ``pdf`` 两个渲染器
（I3）：Word 侧完整生效，PDF 侧按自身能力映射（字体族最佳匹配、域类特性跳过）。

三件事只在这里做：

1. **配置模型与校验**：``validate_config`` 是唯一入口，越界 / 未知字段一律
   ``ValueError``（路由层转 400），不做静默夹取，避免「保存成功但效果不对」。
2. **内置预设**：代码常量（不入库），``standard`` 与历史 ``DEFAULT_THEME`` 视觉
   等价，保证未指定模板时导出行为逐项不变（I2）。
3. **解析链**：``resolve_export_template`` = 显式 ref → 工作区默认 → 内置 standard。
   导出器与路由都只调它（I1）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cndb.plugins.documents.services.export.theme import DEFAULT_THEME

# ── 取值域 ──

PAPER_SIZES: tuple[str, ...] = ("A4", "A3", "Letter")
ALIGNS: tuple[str, ...] = ("left", "center", "right", "justify")
LINE_SPACING_RULES: tuple[str, ...] = ("multiple", "fixed")
PAGE_NUMBER_MODES: tuple[str, ...] = ("none", "plain", "page", "page_of_total")
HEADING_NUMBERING: tuple[str, ...] = ("none", "arabic_multilevel", "chapter_chinese", "cn_ordinal")
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
    """标题自动编号方案."""

    model_config = ConfigDict(extra="forbid")

    heading: Literal["none", "arabic_multilevel", "chapter_chinese", "cn_ordinal"] = "none"


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


def _standard_config() -> ExportTemplateConfig:
    """标准预设：与历史 ``DEFAULT_THEME`` 视觉等价（I2）."""
    return ExportTemplateConfig(
        body=BodyConfig(
            latin_font=DEFAULT_THEME.body_font,
            east_asia_font=DEFAULT_THEME.body_font,
            size=DEFAULT_THEME.body_size,
        ),
        headings=_headings(
            latin=DEFAULT_THEME.heading_font,
            east_asia=DEFAULT_THEME.heading_font,
            sizes=(18.0, 15.0, 13.0, 12.0, 11.0, 10.5),
            before=(12.0, 10.0, 8.0, 6.0, 6.0, 6.0),
            after=(6.0, 5.0, 4.0, 3.0, 3.0, 3.0),
        ),
        table=TableConfig(
            header_bg=DEFAULT_THEME.table_header_bg,
            header_color=DEFAULT_THEME.table_header_color,
            latin_font=DEFAULT_THEME.table_body_font,
            east_asia_font=DEFAULT_THEME.table_body_font,
        ),
        code=CodeConfig(
            latin_font=DEFAULT_THEME.code_font,
            east_asia_font=DEFAULT_THEME.code_font,
        ),
    )


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
    """研究报告：宋体 12pt / 1.5 倍行距 / 首行缩进 2 字符 / 三线表."""
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
    """技术报告：宋体 11pt / 1.5 倍行距 / 黑体标题 / 浅蓝表头."""
    return ExportTemplateConfig(
        header_footer=HeaderFooterConfig(page_number="page", font_size=9.0),
        body=BodyConfig(
            latin_font="Calibri",
            east_asia_font="宋体",
            size=11.0,
            align="justify",
            line_spacing=1.5,
            space_before=0.0,
            space_after=0.0,
            first_line_indent_chars=2.0,
        ),
        headings=_headings(
            latin="Calibri",
            east_asia="黑体",
            sizes=(18.0, 15.0, 13.0, 12.0, 11.0, 11.0),
            before=(18.0, 14.0, 10.0, 8.0, 8.0, 8.0),
            after=(10.0, 8.0, 6.0, 4.0, 4.0, 4.0),
            align=("center", "left", "left", "left", "left", "left"),
        ),
        numbering=NumberingConfig(heading="arabic_multilevel"),
        table=TableConfig(
            header_bg="#E6EEF5",
            header_color="#1A5276",
            east_asia_font="宋体",
            latin_font="Calibri",
            size=10.5,
            cell_valign="center",
        ),
    )


def _trend_config() -> ExportTemplateConfig:
    """趋势分析：左对齐多级编号，图表题注在下."""
    return ExportTemplateConfig(
        header_footer=HeaderFooterConfig(page_number="plain", font_size=9.0),
        body=BodyConfig(
            latin_font="Calibri",
            east_asia_font="宋体",
            size=11.0,
            line_spacing=1.5,
            space_before=0.0,
            space_after=0.0,
            first_line_indent_chars=2.0,
        ),
        headings=_headings(
            latin="Calibri",
            east_asia="黑体",
            sizes=(16.0, 14.0, 12.0, 11.0, 11.0, 11.0),
            before=(14.0, 12.0, 10.0, 8.0, 8.0, 8.0),
            after=(8.0, 6.0, 4.0, 3.0, 3.0, 3.0),
        ),
        numbering=NumberingConfig(heading="arabic_multilevel"),
        table=TableConfig(
            header_bg="#EAF2FB",
            header_color="#1F3864",
            east_asia_font="宋体",
            latin_font="Calibri",
            size=10.0,
            zebra=True,
        ),
        captions=CaptionsConfig(
            figure=CaptionStyleConfig(enabled=True, position="below", numbering="n", align="center"),
            table=CaptionStyleConfig(enabled=True, position="above", numbering="n", align="center"),
        ),
    )


def _official_config() -> ExportTemplateConfig:
    """公文函件：仿宋三号 / 固定行距 28pt / 一、编号 / 页脚「第 X 页 共 Y 页」."""
    return ExportTemplateConfig(
        page=PageConfig(margin_top=3.7, margin_bottom=3.5, margin_left=2.8, margin_right=2.6),
        header_footer=HeaderFooterConfig(page_number="page_of_total", first_page_different=True, font_size=9.0),
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
        headings=_headings(
            latin="Times New Roman",
            east_asia="黑体",
            sizes=(22.0, 16.0, 16.0, 16.0, 16.0, 16.0),
            before=(18.0, 12.0, 10.0, 8.0, 8.0, 8.0),
            after=(14.0, 8.0, 6.0, 4.0, 4.0, 4.0),
            align=("center", "left", "left", "left", "left", "left"),
        ),
        numbering=NumberingConfig(heading="cn_ordinal"),
        table=TableConfig(
            header_bg="#FFFFFF",
            header_color="#000000",
            east_asia_font="仿宋",
            latin_font="Times New Roman",
            size=14.0,
            border_color="#000000",
            cell_valign="center",
        ),
    )


def _weekly_config() -> ExportTemplateConfig:
    """周报：紧凑列表 + 斑马纹表格，便于快速扫读."""
    return ExportTemplateConfig(
        header_footer=HeaderFooterConfig(page_number="plain"),
        body=BodyConfig(
            latin_font="Calibri",
            east_asia_font="宋体",
            size=11.0,
            line_spacing=1.5,
            space_before=0.0,
            space_after=2.0,
        ),
        headings=_headings(
            latin="Calibri",
            east_asia="黑体",
            sizes=(15.0, 13.0, 12.0, 11.0, 11.0, 11.0),
            before=(12.0, 10.0, 8.0, 6.0, 6.0, 6.0),
            after=(6.0, 5.0, 4.0, 3.0, 3.0, 3.0),
        ),
        table=TableConfig(
            header_bg="#EFF3F8",
            header_color="#1F3864",
            east_asia_font="宋体",
            latin_font="Calibri",
            size=10.0,
            zebra=True,
            cell_valign="center",
        ),
    )


def _press_config() -> ExportTemplateConfig:
    """宣传报道：无首行缩进、1.75 倍行距，正文更松散易读."""
    return ExportTemplateConfig(
        header_footer=HeaderFooterConfig(page_number="none"),
        body=BodyConfig(
            latin_font="Calibri",
            east_asia_font="宋体",
            size=12.0,
            line_spacing=1.75,
            space_before=0.0,
            space_after=4.0,
        ),
        headings=_headings(
            latin="Calibri",
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
            latin_font="Calibri",
            size=10.5,
        ),
    )


BUILTIN_TEMPLATES: dict[str, BuiltinTemplate] = {
    "standard": BuiltinTemplate(
        key="standard",
        name="标准",
        description="系统历史默认视觉：Calibri 10.5pt、单倍行距、无首行缩进",
        config=_standard_config(),
    ),
    "research": BuiltinTemplate(
        key="research",
        name="研究报告",
        description="宋体 12pt、1.5 倍行距、首行缩进 2 字符、三线表、图表题注、多级标题编号",
        config=_research_config(),
    ),
    "techreport": BuiltinTemplate(
        key="techreport",
        name="技术报告",
        description="宋体 11pt、1.5 倍行距、黑体标题分级、浅蓝表头、页脚页码",
        config=_techreport_config(),
    ),
    "trend": BuiltinTemplate(
        key="trend",
        name="趋势分析",
        description="宋体 11pt、左对齐多级编号、斑马纹表格、图表题注在下",
        config=_trend_config(),
    ),
    "thesis": BuiltinTemplate(
        key="thesis",
        name="论文",
        description="宋体 12pt、1.5 倍行距、居中一级标题（第一章）、三线表、图表题注",
        config=_thesis_config(),
    ),
    "official": BuiltinTemplate(
        key="official",
        name="公文",
        description="仿宋三号、固定行距 28pt、一、二级编号、页脚「第 X 页 共 Y 页」",
        config=_official_config(),
    ),
    "weekly": BuiltinTemplate(
        key="weekly",
        name="周报",
        description="宋体 11pt、紧凑段落、斑马纹表格，适合快速扫读",
        config=_weekly_config(),
    ),
    "press": BuiltinTemplate(
        key="press",
        name="宣传报道",
        description="宋体 12pt、1.75 倍行距、无首行缩进、标题居中",
        config=_press_config(),
    ),
}

DEFAULT_TEMPLATE_KEY = "standard"
DEFAULT_TEMPLATE_REF = f"{_BUILTIN_PREFIX}{DEFAULT_TEMPLATE_KEY}"


def validate_config(raw: Mapping[str, Any] | None) -> ExportTemplateConfig:
    """把外部提交的 config 校验成 :class:`ExportTemplateConfig`.

    Raises:
        ValueError: 缺字段以外的一切非法（越界 / 未知字段 / 未知枚举）都报错，
            文案里带字段路径，路由层直接转 400。
    """
    if raw is None:
        return _standard_config()
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


def resolve_export_template(db: Any, workspace_id: int, ref: str | None = None) -> ResolvedTemplate:
    """唯一解析入口：显式 ref → 工作区默认 → 内置 standard（I1）.

    Raises:
        ValueError: ref 格式非法。
        NotFoundError: ref 指向的模板不存在 / 不属于该工作区（统一 404）。
    """
    from cndb.core.errors import NotFoundError
    from cndb.plugins.documents.models import ExportTemplate

    normalized = normalize_ref(ref)
    if normalized is not None:
        builtin = resolve_builtin(normalized)
        if builtin is not None:
            return builtin
        if normalized.startswith(_BUILTIN_PREFIX):
            raise NotFoundError("模板不存在")
        row = db.get(ExportTemplate, int(normalized))
        if row is None or row.workspace_id != workspace_id:
            raise NotFoundError("模板不存在")
        return _resolved_from_row(row)

    row = (
        db.query(ExportTemplate)
        .filter(ExportTemplate.workspace_id == workspace_id, ExportTemplate.is_default.is_(True))
        .order_by(ExportTemplate.id)
        .first()
    )
    if row is not None:
        return _resolved_from_row(row)
    return default_template()


def _resolved_from_row(row: Any) -> ResolvedTemplate:
    return ResolvedTemplate(
        ref=str(row.id),
        name=row.name,
        source="custom",
        config=validate_config(row.config or {}),
    )


def heading_prefix(scheme: str, level: int, counters: list[int]) -> str:
    """按编号方案生成标题前缀文本（不含尾部分隔，调用方决定空白）.

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
    # cn_ordinal：一级「一、」 二级「（一）」 三级起阿拉伯数字
    if level == 1:
        return f"{_chinese_number(numbers[0])}、"
    if level == 2:
        return f"（{_chinese_number(numbers[1])}）"
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
]
