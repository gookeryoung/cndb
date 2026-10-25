"""帮助图示构建器（ADR 0030 §1）.

**每张图的数据都来自代码里的真相源**，而不是手抄的说明文字：

| 图示 | 真相源 |
|---|---|
| 字段类型一览 | `tables.field_types.default_registry` |
| 权限与角色 | `workspaces.models.WorkspaceRole` / `ViewVisibility` |
| 数据源同步 | `datasource.models.ScheduleMode` / `RunStatus` |
| 示例数据预览 | `examples/datasets` 下**真实 CSV** 的表头与前 4 行 |
| 结构 / 流程类 | 本模块的编排代码（改了代码，指纹就变，图随之重建） |

因此「代码更新后图示过期」在结构上不会发生：要么数据源变了重建，
要么编排代码变了重建（指纹见 `registry.py`）。
"""

from __future__ import annotations

import csv
from pathlib import Path

from cndb.plugins.help.services.figures.svg import (
    BORDER,
    BRAND,
    MUTED,
    SUBTLE,
    SURFACE,
    TEXT,
    Svg,
    text_width,
    truncate,
)
from cndb.plugins.tables.field_types import FieldTypeCategory, default_registry

_CATEGORY_LABELS: dict[FieldTypeCategory, str] = {
    FieldTypeCategory.BASIC: "基础",
    FieldTypeCategory.NUMERIC: "数值",
    FieldTypeCategory.DATE: "日期",
    FieldTypeCategory.SELECT: "选择",
    FieldTypeCategory.LINK: "关联",
    FieldTypeCategory.ADVANCED: "高级",
}

_ROLE_LABELS = {"owner": "所有者 owner", "editor": "编辑者 editor", "viewer": "阅读者 viewer"}

_ROLE_DUTIES: dict[str, tuple[str, ...]] = {
    "owner": ("管理成员与角色", "工作区设置与删除", "全部数据的增删改查"),
    "editor": ("建表、建视图、导入导出", "编辑数据与视图配置", "不能管理成员"),
    "viewer": ("只读浏览数据表与视图", "不能编辑数据", "不能管理成员"),
}

_VISIBILITY_LABELS = {
    "table": "继承表权限",
    "shared": "指定成员可见",
    "private": "仅创建者可见",
}

_SCHEDULE_LABELS = {
    "manual": "手动触发",
    "daily": "每天固定时刻",
    "interval": "固定间隔秒数",
    "cron": "5 段 cron",
}


# ── 公共小工具 ────────────────────────────────────────────


def _tree_root_to_children(
    svg: Svg, root_x: float, root_bottom: float, child_centers: list[float], child_top: float
) -> None:
    """从根节点底部画「一横多竖」的连接线."""
    mid_y = root_bottom + (child_top - root_bottom) / 2
    svg.line(root_x, root_bottom, root_x, mid_y, color=BORDER)
    svg.line(min(child_centers), mid_y, max(child_centers), mid_y, color=BORDER)
    for cx in child_centers:
        svg.line(cx, mid_y, cx, child_top, color=BORDER)


def _step_number(svg: Svg, cx: float, cy: float, number: int) -> None:
    svg.raw(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="14" fill="{SUBTLE}" stroke="{BRAND}" stroke-width="1.2"/>')
    svg.text(cx, cy + 4.5, str(number), size=13, fill=BRAND, weight=600, anchor="middle")


# ── 结构 / 流程类 ────────────────────────────────────────


def build_quick_start_flow() -> str:
    """五步上手：创建工作区 → 导入数据 → 录入整理 → 切换视图 → 协作授权."""
    steps = (
        ("创建工作区", "数据与文档的容器"),
        ("导入数据", "CSV / Excel / JSON"),
        ("录入整理", "补字段、改类型"),
        ("切换视图", "表格 / 看板 / 图表"),
        ("协作授权", "成员角色与权限"),
    )
    svg = Svg(132)
    slot = svg.width / len(steps)
    centers = [slot * (index + 0.5) for index in range(len(steps))]
    svg.line(centers[0], 40, centers[-1], 40, color=BORDER, width=1.2)
    for index, ((title, note), cx) in enumerate(zip(steps, centers, strict=True)):
        _step_number(svg, cx, 40, index + 1)
        svg.text(cx, 76, title, size=13, weight=600, anchor="middle")
        svg.text(cx, 96, note, size=11, fill=MUTED, anchor="middle")
    return svg.render(title="五步上手流程", desc="创建并协作一个工作区的最小路径")


def build_workspace_structure() -> str:
    """工作区结构：数据表 / 文档 / 成员三层承载关系."""
    svg = Svg(196)
    root_w, root_h = 168, 40
    root_x = (svg.width - root_w) / 2
    svg.rect(root_x, 12, root_w, root_h)
    svg.text(svg.width / 2, 37, "工作区", size=14, weight=600, anchor="middle")

    columns = (
        ("数据表", ("字段", "视图", "权限")),
        ("文档", ("正文", "附件", "分享链接")),
        ("成员", ("角色", "邀请", "可见性")),
    )
    box_w, box_h, gap = 184, 46, 22
    total = len(columns) * box_w + (len(columns) - 1) * gap
    start_x = (svg.width - total) / 2
    child_top, chip_y = 92, 148
    centers = [start_x + index * (box_w + gap) + box_w / 2 for index in range(len(columns))]
    _tree_root_to_children(svg, svg.width / 2, 52, centers, child_top)

    for (title, chips), cx in zip(columns, centers, strict=True):
        left = cx - box_w / 2
        svg.rect(left, child_top, box_w, box_h)
        svg.text(cx, child_top + 28, title, size=13, weight=600, anchor="middle")
        chip_widths = [text_width(chip, 11) + 16 for chip in chips]
        chip_total = sum(chip_widths) + 6 * (len(chips) - 1)
        chip_x = cx - chip_total / 2
        for chip, width in zip(chips, chip_widths, strict=True):
            svg.rect(chip_x, chip_y, width, 24, rx=12, fill=SUBTLE)
            svg.text(chip_x + width / 2, chip_y + 16, chip, size=11, fill=MUTED, anchor="middle")
            chip_x += width + 6
    return svg.render(title="工作区结构", desc="工作区下的数据表、文档与成员")


def build_import_flow() -> str:
    """导入链路：选文件 → 识别表头 → 推断类型 → 预览确认 → 落表."""
    steps = (
        ("选择文件", "CSV / Excel / JSON，可批量"),
        ("识别表头", "自动跳过顶部标题行，可手动改"),
        ("推断字段类型", "文本 / 数字 / 日期 / 单选…"),
        ("预览确认", "改类型、改字段名、设去重键"),
        ("写入数据表", "进度可见，失败可重试"),
    )
    row_h = 44
    svg = Svg(16 + row_h * len(steps))
    for index, (title, note) in enumerate(steps):
        cy = 16 + row_h * index + row_h / 2
        _step_number(svg, 30, cy, index + 1)
        if index < len(steps) - 1:
            svg.line(30, cy + 14, 30, cy + row_h - 14, color=BORDER)
        svg.text(58, cy - 2, title, size=13, weight=600)
        svg.text(58, cy + 16, note, size=11, fill=MUTED)
    return svg.render(title="导入流程", desc="从选择文件到写入数据表的五个步骤")


# ── 数据驱动类 ────────────────────────────────────────────


def build_field_types() -> str:
    """字段类型一览：直接读 `default_registry`，新增类型自动出现在图里."""
    grouped: dict[FieldTypeCategory, list[str]] = {}
    for field_type in default_registry.all():
        label = field_type.label or field_type.name
        grouped.setdefault(field_type.category, []).append(label)
    if not grouped:
        grouped = {FieldTypeCategory.BASIC: ["（暂无注册的字段类型）"]}

    label_w, chip_gap, line_h, pad = 92, 8, 26, 10
    svg = Svg(1)
    y = 14.0
    for category, labels in grouped.items():
        svg.text(16, y + 18, _CATEGORY_LABELS.get(category, str(category)), size=12, weight=600, fill=MUTED)
        x = 16 + label_w
        for label in labels:
            width = text_width(label, 12) + pad * 2
            if x + width > svg.width - 16:
                x = 16 + label_w
                y += line_h + chip_gap
            svg.chip(x, y, label, size=12)
            x += width + chip_gap
        y += line_h + chip_gap + 4
    svg.height = int(y + 10)
    return svg.render(title="字段类型一览", desc="按分类列出的全部可用字段类型")


def build_permission_model() -> str:
    """权限模型：工作区三角色 + 视图三档可见性（读真实枚举）."""
    from cndb.plugins.tables.models import ViewVisibility
    from cndb.plugins.workspaces.models import WorkspaceRole

    svg = Svg(212)
    svg.text(16, 20, "工作区角色（权限从高到低）", size=12, weight=600, fill=MUTED)

    roles = [role.value for role in WorkspaceRole]
    box_w, gap, top = 200, 12, 32
    total = len(roles) * box_w + (len(roles) - 1) * gap
    start_x = (svg.width - total) / 2
    for index, role in enumerate(roles):
        left = start_x + index * (box_w + gap)
        svg.rect(left, top, box_w, 112)
        svg.rect(left, top, box_w, 4, rx=2, fill=BRAND)
        svg.text(left + 14, top + 30, _ROLE_LABELS.get(role, role), size=13, weight=600)
        for line_index, duty in enumerate(_ROLE_DUTIES.get(role, ())):
            svg.text(left + 14, top + 56 + line_index * 20, f"· {duty}", size=11, fill=MUTED)
        if index < len(roles) - 1:
            svg.arrow(left + box_w + 1, top + 56, left + box_w + gap - 1, top + 56, color=BORDER)

    svg.text(16, 176, "视图可见性", size=12, weight=600, fill=MUTED)
    x = 96.0
    for visibility in ViewVisibility:
        width = svg.chip(x, 160, _VISIBILITY_LABELS.get(visibility.value, visibility.value), size=11, height=24) + 8
        x += width
    svg.text(16, 204, "生效权限 = min(视图授权, 表权限)：视图授权永不放行表外的人，也不提升改权。", size=11, fill=MUTED)
    return svg.render(title="权限与角色", desc="工作区三角色与视图三档可见性")


def build_datasource_sync() -> str:
    """数据源同步：四种调度模式 + 固定执行链路（读真实枚举）."""
    from cndb.plugins.datasource.models import ScheduleMode

    svg = Svg(168)
    svg.text(16, 20, "调度模式", size=12, weight=600, fill=MUTED)
    modes = [mode.value for mode in ScheduleMode if mode.value in _SCHEDULE_LABELS]
    x = 16.0
    for mode in modes:
        width = svg.chip(x, 30, _SCHEDULE_LABELS[mode], size=11, height=24) + 6
        x += width
    svg.text(
        16,
        74,
        "按需手动触发用 manual；每天固定时刻用 daily；高频源用 interval；要精确到分钟用 5 段 cron。",
        size=11,
        fill=MUTED,
    )

    nodes = (
        ("同步任务", "配置来源与字段映射"),
        ("抓取数据", "分页拉取外部接口"),
        ("去重合并", "按去重键跳过重复"),
        ("写入数据表", "失败行单独记录"),
        ("运行记录", "成功 / 部分成功 / 失败"),
    )
    node_w, gap, top = 112, 12, 92
    total = len(nodes) * node_w + (len(nodes) - 1) * gap
    start_x = (svg.width - total) / 2
    for index, (title, note) in enumerate(nodes):
        left = start_x + index * (node_w + gap)
        svg.rect(left, top, node_w, 60)
        svg.text(left + node_w / 2, top + 26, title, size=12, weight=600, anchor="middle")
        svg.text(left + node_w / 2, top + 46, note, size=10, fill=MUTED, anchor="middle")
        if index < len(nodes) - 1:
            svg.arrow(left + node_w + 1, top + 30, left + node_w + gap - 1, top + 30, color=BORDER)
    return svg.render(title="数据源同步链路", desc="调度模式与从抓取到落表的执行链路")


# ── 示例数据预览（真实 CSV）────────────────────────────────


def _read_csv_sample(path: Path, *, max_rows: int = 4, max_cols: int = 5) -> tuple[list[str], list[list[str]], int]:
    """读取表头 + 前 N 行 + 总行数（`utf-8-sig` 兼容 Excel 导出的 BOM）."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        rows: list[list[str]] = []
        total = 0
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            total += 1
            if len(rows) < max_rows:
                rows.append(row)
    return header[:max_cols], [row[:max_cols] for row in rows], total


def build_example_preview(scenario: str, filename: str) -> str:
    """示例数据预览：直接读真实 CSV 的表头与前 4 行，文件改了图就变."""
    from cndb.plugins.help.services.assets import resolve_example_file

    path = resolve_example_file(scenario, filename)
    svg = Svg(120)
    if path is None:
        svg.text(16, 40, "示例文件暂不可用", size=13, fill=MUTED)
        return svg.render(title=f"{filename} 预览", desc="示例文件缺失")

    header, rows, total = _read_csv_sample(path)
    columns = max(len(header), 1)
    label = f"{filename} · 共 {total} 行 · 展示前 {len(rows)} 行 / {columns} 列"
    svg.text(16, 20, label, size=11, fill=MUTED)

    size = 12
    pad = 12
    widths: list[float] = []
    for index in range(columns):
        cells = [header[index] if index < len(header) else ""]
        cells += [row[index] if index < len(row) else "" for row in rows]
        widths.append(max(max(text_width(cell, size) for cell in cells) + pad * 2, 68))

    table_w = svg.width - 32
    scale = table_w / sum(widths)
    widths = [width * scale for width in widths]

    top, row_h, header_h = 32, 28, 30
    left = 16.0
    svg.rect(left, top, sum(widths), header_h + row_h * max(len(rows), 1), rx=6, fill=SURFACE)
    svg.rect(left, top, sum(widths), header_h, rx=6, fill=SUBTLE)
    svg.rect(left, top + header_h - 6, sum(widths), 6, rx=0, fill=SUBTLE)

    def cell(x: float, y: float, content: str, width: float, *, fill: str, weight: int = 400) -> None:
        svg.text(x + pad, y, truncate(content, size, width - pad * 2), size=size, fill=fill, weight=weight)

    x = left
    for width, name in zip(widths, [header[i] if i < len(header) else "" for i in range(columns)], strict=True):
        cell(x, top + 20, name, width, fill=TEXT, weight=600)
        x += width

    for row_index, row in enumerate(rows or [[""] * columns]):
        y = top + header_h + row_index * row_h
        svg.line(left, y, left + sum(widths), y, color=BORDER)
        x = left
        for width, value in zip(widths, row, strict=True):
            cell(x, y + 19, value, width, fill=TEXT)
            x += width
    svg.height = int(top + header_h + row_h * max(len(rows), 1) + 12)
    return svg.render(title=f"{filename} 数据预览", desc=f"{filename} 表头与首批数据行")


__all__ = [
    "build_datasource_sync",
    "build_example_preview",
    "build_field_types",
    "build_import_flow",
    "build_permission_model",
    "build_quick_start_flow",
    "build_workspace_structure",
]
