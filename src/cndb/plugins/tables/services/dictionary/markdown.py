"""数据字典 → Markdown（ADR 0188 C2 / I4）.

章节骨架固定、顺序不可变（`SECTION_ORDER`），缺内容写占位而不是省略本节 ——
省略会让缺口不可见，而缺口正是数据治理要解决的对象。

Markdown 同时是 docx / pdf 的输入（`cndb/render/markdown_export`），
所以这里不写任何 docx / pdf 专属逻辑，只用标准 Markdown 语法。
"""

from __future__ import annotations

from cndb.plugins.tables.services.dictionary.build import DictionaryDocument, FieldEntry, TableDictionary
from cndb.plugins.tables.services.dictionary.spec import COMPLETENESS_NOTE, FIELD_DESIGN_SPEC

#: 章节顺序（唯一真相源；增删节必须同步这里与测试）
SECTION_ORDER: tuple[str, ...] = (
    "表基本信息",
    "字段清单",
    "枚举字典",
    "校验与规则",
    "关联与派生",
    "可见性",
    "变更记录",
    "设计规范附录",
)

#: 字段清单列头（顺序固定；「业务说明」紧邻字段名，读者第一眼就能看到口径）
FIELD_TABLE_HEADER: tuple[str, ...] = (
    "序号",
    "字段名",
    "类型",
    "业务说明",
    "必填",
    "唯一",
    "默认值",
    "取值范围与校验",
    "枚举",
    "关联与公式",
    "可见性",
    "示例值",
    "敏感级",
    "责任人",
)

#: 内部列（仅 include_internal 时追加）
INTERNAL_HEADER: tuple[str, ...] = ("物理列名",)


def _cell(value: str) -> str:
    """单元格转义：`|` 破坏表格结构，换行破坏行结构."""
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip() or "—"


def _flag(value: bool) -> str:
    return "是" if value else "否"


def _options_text(entry: FieldEntry) -> str:
    if not entry.options:
        return "—"
    return "、".join(o["label"] or o["value"] for o in entry.options)


def _rules_text(entry: FieldEntry) -> str:
    parts = [entry.value_range] if entry.value_range not in ("", "未填写") else []
    parts.extend(entry.validation)
    return "；".join(parts) if parts else "—"


def render_table(table: TableDictionary, *, include_internal: bool) -> list[str]:
    """渲染单表章节（`## 表名` 起头）."""
    lines: list[str] = [f"## {table.table_name}", ""]

    # ── 1. 表基本信息 ──
    lines.extend(["### 表基本信息", "", "| 项目 | 内容 |", "| --- | --- |"])
    lines.append(f"| 表名 | {_cell(table.table_name)} |")
    lines.append(f"| 说明 | {_cell(table.description)} |")
    lines.append(f"| 分组 | {_cell(table.group_name)} |")
    lines.append(f"| 负责人 | {_cell(table.owner)} |")
    lines.append(f"| 字段数 | {len(table.fields)} |")
    lines.append(f"| 行级权限 | {'已启用（按行过滤）' if table.row_rules_active else '未启用'} |")
    if include_internal and table.db_table_name:
        lines.append(f"| 物理表名 | {_cell(table.db_table_name)} |")
    lines.append("")

    # ── 2. 字段清单 ──
    lines.extend(["### 字段清单", ""])
    if not table.fields:
        lines.extend(["该表暂无字段。", ""])
    else:
        header = list(FIELD_TABLE_HEADER) + (list(INTERNAL_HEADER) if include_internal else [])
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for index, entry in enumerate(table.fields, start=1):
            row = [
                str(index),
                entry.name,
                entry.type_label,
                entry.business_meaning,
                _flag(entry.required),
                _flag(entry.unique),
                entry.default_value,
                _rules_text(entry),
                _options_text(entry),
                entry.relation if entry.relation != "未填写" else "—",
                entry.visibility,
                entry.example_value,
                entry.sensitivity_label,
                entry.owner,
            ]
            if include_internal:
                row.append(entry.db_column_name or "—")
            lines.append("| " + " | ".join(_cell(c) for c in row) + " |")
        lines.append("")

    # ── 3. 枚举字典 ──
    lines.extend(["### 枚举字典", ""])
    enum_fields = [e for e in table.fields if e.options]
    if not enum_fields:
        lines.extend(["本表没有单选 / 多选字段。", ""])
    else:
        for entry in enum_fields:
            lines.extend(
                [f"**{entry.name}**（{entry.type_label}）", "", "| 选项值 | 显示名 | 业务含义 |", "| --- | --- | --- |"]
            )
            for option in entry.options:
                lines.append(f"| {_cell(option['value'])} | {_cell(option['label'])} | {_cell(option['meaning'])} |")
            lines.append("")

    # ── 4. 校验与规则 ──
    lines.extend(["### 校验与规则", ""])
    rule_lines: list[str] = []
    for entry in table.fields:
        for rule in entry.validation:
            rule_lines.append(f"- **{entry.name}**：{rule}")
        if entry.required:
            rule_lines.append(f"- **{entry.name}**：必填")
        if entry.unique:
            rule_lines.append(f"- **{entry.name}**：值唯一")
    lines.extend(rule_lines or ["本表未配置额外校验规则（仅默认类型校验）。"])
    lines.append("")

    # ── 5. 关联与派生 ──
    lines.extend(["### 关联与派生", ""])
    relation_lines = [
        f"- **{entry.name}**（{entry.type_label}）：{entry.relation}"
        for entry in table.fields
        if entry.relation != "未填写"
    ]
    lines.extend(relation_lines or ["本表没有关联 / 引用 / 派生字段。"])
    lines.append("")

    # ── 6. 可见性 ──
    lines.extend(["### 可见性", ""])
    restricted = [e for e in table.fields if e.visibility != "全部角色可见"]
    if not restricted:
        lines.extend(["所有字段对全部角色可见。", ""])
    else:
        lines.append("| 字段 | 可见性 | 敏感级 |")
        lines.append("| --- | --- | --- |")
        for entry in restricted:
            lines.append(f"| {_cell(entry.name)} | {_cell(entry.visibility)} | {_cell(entry.sensitivity_label)} |")
        lines.append("")

    # ── 7. 变更记录 ──
    lines.extend(["### 变更记录", ""])
    if not table.change_log:
        lines.extend(["暂无字段级变更记录。", ""])
    else:
        lines.append("| 时间 | 动作 | 操作人 | 说明 |")
        lines.append("| --- | --- | --- | --- |")
        for item in table.change_log:
            lines.append(
                f"| {_cell(item.get('at', '—'))} | {_cell(item.get('action', '—'))} "
                f"| {_cell(item.get('actor', '—'))} | {_cell(item.get('detail', '—'))} |"
            )
        lines.append("")

    # ── 8. 设计规范附录（每表都出，作为对照基线） ──
    lines.extend(["### 设计规范附录", ""])
    for title, text in FIELD_DESIGN_SPEC:
        lines.extend([f"- **{title}**：{text}"])
    lines.append("")
    return lines


def render_markdown(document: DictionaryDocument) -> str:
    """整份文档 → Markdown（标题 + 每表章节 + 引用索引 + 尾注）."""
    lines: list[str] = [f"# {document.title}", ""]
    lines.append(
        f"> 工作区：{document.workspace_name}　生成时间：{document.generated_at}　结构指纹：`{document.schema_hash}`"
    )
    lines.append(">")
    lines.append(
        "> 本文档由系统按当前字段配置自动生成，只描述**字段结构**，不含任何行数据。"
        "重新导出前请勿手工修改；需要修改请改字段配置后重新导出。"
    )
    lines.append("")
    if len(document.tables) > 1:
        lines.extend(["## 目录", ""])
        for index, table in enumerate(document.tables, start=1):
            lines.append(f"{index}. {table.table_name}（{len(table.fields)} 个字段）")
        lines.append("")

    for table in document.tables:
        lines.extend(render_table(table, include_internal=document.include_internal))

    # ── 表间引用索引（仅合订时） ──
    if len(document.tables) > 1:
        lines.extend(["## 表间引用索引", ""])
        if not document.references:
            lines.extend(["各表之间没有关联字段。", ""])
        else:
            lines.append("| 来源表 | 字段 | 引用目标 |")
            lines.append("| --- | --- | --- |")
            for ref in document.references:
                lines.append(f"| {_cell(ref['source_table'])} | {_cell(ref['field_name'])} | {_cell(ref['target'])} |")
            lines.append("")

    lines.extend(["## 附注", "", f"- {COMPLETENESS_NOTE}", ""])
    return "\n".join(lines)


__all__ = ["FIELD_TABLE_HEADER", "INTERNAL_HEADER", "SECTION_ORDER", "render_markdown", "render_table"]
