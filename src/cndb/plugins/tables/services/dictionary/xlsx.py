"""数据字典 → XLSX（ADR 0188 C1 / I1）.

多 sheet 工作簿，便于数据管理员逐字段维护后回填：

- `概览`     ：表 / 字段统计与结构指纹
- `字段清单` ：每字段一行（与 Markdown 主表同列序）
- `枚举字典` ：每个枚举选项一行
- `校验规则` ：每条规则一行
- `设计规范` ：附录条目

实现复用 `transfer/exporting.py` 的 openpyxl 工具函数（公式注入防护 / 字节串输出），
不另写一份 xlsx 写盘逻辑。
"""

from __future__ import annotations

from typing import Any

from cndb.plugins.tables.services.dictionary.build import DictionaryDocument, FieldEntry
from cndb.plugins.tables.services.dictionary.markdown import FIELD_TABLE_HEADER, INTERNAL_HEADER
from cndb.plugins.tables.services.dictionary.spec import COMPLETENESS_NOTE, FIELD_DESIGN_SPEC


def _write_header(ws: Any, header: list[str]) -> None:
    """写表头并加粗（openpyxl 直接设 font，不引样式依赖）."""
    from openpyxl.styles import Font

    ws.append(header)
    bold = Font(bold=True)
    for cell in ws[ws.max_row]:
        cell.font = bold


def _field_row(index: int, entry: FieldEntry, *, include_internal: bool) -> list[Any]:
    row: list[Any] = [
        index,
        entry.name,
        entry.type_label,
        entry.business_meaning,
        "是" if entry.required else "否",
        "是" if entry.unique else "否",
        entry.default_value,
        "；".join([*([entry.value_range] if entry.value_range != "未填写" else []), *entry.validation]) or "—",
        "、".join(o["label"] or o["value"] for o in entry.options) or "—",
        entry.relation if entry.relation != "未填写" else "—",
        entry.visibility,
        entry.example_value,
        entry.sensitivity_label,
        entry.owner,
    ]
    if include_internal:
        row.append(entry.db_column_name or "—")
    return row


def render_xlsx(document: DictionaryDocument) -> bytes:
    """整份文档 → xlsx 字节串（多 sheet）."""
    from typing import cast

    from openpyxl import Workbook
    from openpyxl.worksheet.worksheet import Worksheet

    from cndb.plugins.tables.services.transfer.exporting import _fix_xlsx_formula_cells, _wb_to_bytes

    wb = Workbook()

    # ── 概览 ──
    overview = cast(Worksheet, wb.active)
    overview.title = "概览"
    _write_header(overview, ["项目", "内容"])
    overview.append(["工作区", document.workspace_name])
    overview.append(["生成时间", document.generated_at])
    overview.append(["结构指纹", document.schema_hash])
    overview.append(["表数量", len(document.tables)])
    overview.append(["字段总数", document.field_count])
    overview.append(["含内部列", "是" if document.include_internal else "否"])
    overview.append(["说明", COMPLETENESS_NOTE])

    # ── 字段清单 ──
    fields_ws = cast(Worksheet, wb.create_sheet("字段清单"))
    header = ["表名", *FIELD_TABLE_HEADER]
    if document.include_internal:
        header.extend(INTERNAL_HEADER)
    _write_header(fields_ws, header)
    for table in document.tables:
        for index, entry in enumerate(table.fields, start=1):
            fields_ws.append([table.table_name, *_field_row(index, entry, include_internal=document.include_internal)])
            _fix_xlsx_formula_cells(fields_ws, fields_ws.max_row)

    # ── 枚举字典 ──
    enum_ws = cast(Worksheet, wb.create_sheet("枚举字典"))
    _write_header(enum_ws, ["表名", "字段", "选项值", "显示名", "业务含义"])
    for table in document.tables:
        for entry in table.fields:
            for option in entry.options:
                enum_ws.append([table.table_name, entry.name, option["value"], option["label"], option["meaning"]])
                _fix_xlsx_formula_cells(enum_ws, enum_ws.max_row)
    if enum_ws.max_row == 1:
        enum_ws.append(["（本工作区没有枚举字段）", "", "", "", ""])

    # ── 校验规则 ──
    rule_ws = cast(Worksheet, wb.create_sheet("校验规则"))
    _write_header(rule_ws, ["表名", "字段", "规则"])
    rule_count = 0
    for table in document.tables:
        for entry in table.fields:
            rules = list(entry.validation)
            if entry.required:
                rules.append("必填")
            if entry.unique:
                rules.append("值唯一")
            for rule in rules:
                rule_ws.append([table.table_name, entry.name, rule])
                rule_count += 1
    if rule_count == 0:
        rule_ws.append(["（本工作区未配置额外校验规则）", "", ""])

    # ── 设计规范 ──
    spec_ws = cast(Worksheet, wb.create_sheet("设计规范"))
    _write_header(spec_ws, ["条目", "内容"])
    for title, text in FIELD_DESIGN_SPEC:
        spec_ws.append([title, text])

    return _wb_to_bytes(wb)


__all__ = ["render_xlsx"]
