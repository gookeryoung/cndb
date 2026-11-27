"""数据字典服务包（ADR 0188）.

对外只暴露构建 / 渲染 / 评分三个入口；路由层只做权限、可见性裁剪与响应封装。

- `build`    ：中间模型（唯一真相源）+ 结构指纹 + JSON 契约
- `labels`   ：字段配置 → 人话
- `markdown` ：中间模型 → Markdown（同时是 docx / pdf 的输入）
- `xlsx`     ：中间模型 → 多 sheet 工作簿
- `score`    ：标准符合度指标
- `spec`     ：字段设计规范附录（只读常量）
"""

from __future__ import annotations

from cndb.plugins.tables.services.dictionary.build import (
    DICTIONARY_KIND,
    DICTIONARY_VERSION,
    DictionaryDocument,
    FieldEntry,
    TableDictionary,
    build_document,
    build_field_entry,
    build_table_dictionary,
    compute_schema_hash,
    document_to_dict,
)
from cndb.plugins.tables.services.dictionary.labels import (
    MISSING,
    REDACTED,
    UNASSIGNED,
    field_type_label,
    format_hidden_for,
    format_options,
    format_relation,
    format_validation,
    format_value_range,
    sensitivity_label,
)
from cndb.plugins.tables.services.dictionary.markdown import SECTION_ORDER, render_markdown
from cndb.plugins.tables.services.dictionary.score import METRIC_LABELS, compute_score
from cndb.plugins.tables.services.dictionary.spec import COMPLETENESS_NOTE, FIELD_DESIGN_SPEC
from cndb.plugins.tables.services.dictionary.xlsx import render_xlsx

__all__ = [
    "COMPLETENESS_NOTE",
    "DICTIONARY_KIND",
    "DICTIONARY_VERSION",
    "FIELD_DESIGN_SPEC",
    "METRIC_LABELS",
    "MISSING",
    "REDACTED",
    "SECTION_ORDER",
    "UNASSIGNED",
    "DictionaryDocument",
    "FieldEntry",
    "TableDictionary",
    "build_document",
    "build_field_entry",
    "build_table_dictionary",
    "compute_schema_hash",
    "compute_score",
    "document_to_dict",
    "field_type_label",
    "format_hidden_for",
    "format_options",
    "format_relation",
    "format_validation",
    "format_value_range",
    "render_markdown",
    "render_xlsx",
    "sensitivity_label",
]
