"""字段级操作入口（兼容外观）.

实现已按职责拆到同包的 field_import / select_options：
- field_import：字段引入（解析 / 冲突校验 / 落库 / 跨表克隆 / lookup 引入）
- select_options：select·multiselect 选项预填充、同步、检测与存量数据重写

本模块只做转发，保证既有 `from ...fields.field_ops import X` 与
`monkeypatch.setattr(field_ops, "X", ...)` 两种用法继续生效。
"""

from __future__ import annotations

from cndb.plugins.tables.services.core import ddl as _ddl
from cndb.plugins.tables.services.fields.field_import import (
    clone_fields_between_tables,
    execute_field_import,
    generate_column_name,
    import_fields_as_lookup,
    plan_field_import,
    rename_trashed_field_aside,
    resolve_source_fields,
    validate_field_import_conflicts,
    validate_link_targets_exist,
)
from cndb.plugins.tables.services.fields.select_options import (
    _extract_values_from_rows,
    _merge_new_options,
    detect_options_from_field_data,
    diff_select_options,
    prefill_select_options_from_rows,
    sync_select_data_on_options_change,
    sync_select_options_from_table,
)

__all__ = [
    "_ddl",
    "_extract_values_from_rows",
    "_merge_new_options",
    "clone_fields_between_tables",
    "detect_options_from_field_data",
    "diff_select_options",
    "execute_field_import",
    "generate_column_name",
    "import_fields_as_lookup",
    "plan_field_import",
    "prefill_select_options_from_rows",
    "rename_trashed_field_aside",
    "resolve_source_fields",
    "sync_select_data_on_options_change",
    "sync_select_options_from_table",
    "validate_field_import_conflicts",
    "validate_link_targets_exist",
]
