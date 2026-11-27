"""数据字典中间模型与构建（ADR 0188 I1：所有格式的唯一真相源）.

一份 :class:`FieldDictionary` 描述「这张表有哪些字段、每个字段是什么意思」；
md / xlsx / json / docx / pdf 全部由它渲染，禁止某个格式自己再拼一遍字段信息。

口径：

- **只读、不含行数据**（I2）：这里不碰物理表，只读 `DataField` 元数据；
- **可见性同源**（I3）：字段集合恒等于调用方传进来的 `visible_fields`（由
  `get_hidden_field_names` 裁剪后的结果），本模块不另写裁剪；
- **缺内容显式占位**（I4）：所有缺失走 `labels.MISSING`，不省略列 / 节；
- 业务口径文本按 `sensitivity` + `include_internal` 决定是否脱敏（D8）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from cndb.plugins.tables.models import DataField, DataTable, FieldSensitivity
from cndb.plugins.tables.services.dictionary import labels
from cndb.plugins.tables.services.dictionary.spec import COMPLETENESS_NOTE, FIELD_DESIGN_SPEC

#: 契约标识与版本（JSON 输出用）
DICTIONARY_KIND = "cndb-table-dictionary"
DICTIONARY_VERSION = 1

#: 变更记录最多取多少条
CHANGE_LOG_LIMIT = 20


@dataclass(frozen=True)
class FieldEntry:
    """单个字段的字典条目（渲染层唯一输入）."""

    name: str
    type_label: str
    type_name: str
    type_category: str
    business_meaning: str
    unit: str
    required: bool
    unique: bool
    default_value: str
    value_range: str
    validation: list[str]
    options: list[dict[str, str]]
    relation: str
    visibility: str
    example_value: str
    sensitivity: str
    sensitivity_label: str
    owner: str
    standard_ref: str
    order: int
    #: 内部实现细节（仅 include_internal 时输出）
    db_column_name: str = ""
    field_id: int = 0
    redacted: bool = False


@dataclass(frozen=True)
class TableDictionary:
    """一张表的数据字典（含渲染所需的表级信息）."""

    table_id: int
    table_name: str
    description: str
    group_name: str
    owner: str
    db_table_name: str
    fields: list[FieldEntry] = field(default_factory=list)
    views: list[dict[str, Any]] = field(default_factory=list)
    row_rules_active: bool = False
    change_log: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class DictionaryDocument:
    """整份文档（单表或工作区合订）."""

    workspace_name: str
    workspace_id: int
    generated_at: str
    schema_hash: str
    include_internal: bool
    tables: list[TableDictionary] = field(default_factory=list)
    #: 表间引用索引：[{source_table, target_table, field_name, multiple}]
    references: list[dict[str, str]] = field(default_factory=list)

    @property
    def title(self) -> str:
        """文档标题：单表用表名，多表用工作区名 + 数据字典."""
        if len(self.tables) == 1:
            return f"{self.tables[0].table_name} 数据字典"
        return f"{self.workspace_name} 数据字典"

    @property
    def field_count(self) -> int:
        """字段总数（审计与统计用）."""
        return sum(len(t.fields) for t in self.tables)


# ── 结构指纹 ──────────────────────────────────────────


def compute_schema_hash(tables: list[DataTable], fields_by_table: dict[int, list[DataField]]) -> str:
    """计算结构指纹（C7）：只覆盖结构，不含业务口径文本.

    为什么排除口径 / 示例 / 责任人：改文案不该让用户看到「结构已变更」告警，
    只有「字段增删、类型 / 约束 / 配置 / 顺序变了」才值得提示重新导出。
    """
    payload: list[dict[str, Any]] = []
    for table in sorted(tables, key=lambda t: t.id):
        entries = []
        for f in sorted(fields_by_table.get(table.id, []), key=lambda x: (x.order, x.id)):
            entries.append(
                {
                    "name": f.name,
                    "field_type": f.field_type,
                    "required": bool(f.required),
                    "is_unique": bool(f.is_unique),
                    "default_value": f.default_value,
                    "config": f.config or {},
                    "order": f.order,
                    "hidden": bool(f.hidden),
                }
            )
        payload.append({"id": table.id, "name": table.name, "fields": entries})
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


# ── 构建 ──────────────────────────────────────────────


def _redact(text: str | None, *, confidential: bool, include_internal: bool) -> str:
    """按敏感级脱敏业务文本（D8）：机密 + 默认口径 → 「（受限）」."""
    if confidential and not include_internal:
        return labels.REDACTED
    if text is None or not str(text).strip():
        return labels.MISSING
    return str(text).strip()


def build_field_entry(
    f: DataField,
    *,
    table_names: dict[int, str],
    field_names: dict[int, str],
    hidden_roles: list[str],
    include_internal: bool,
    owner_name: str | None = None,
) -> FieldEntry:
    """把一个 DataField 翻译成字典条目."""
    config: dict[str, Any] = f.config or {}
    sensitivity = FieldSensitivity.normalize(f.sensitivity)
    confidential = sensitivity is FieldSensitivity.CONFIDENTIAL
    return FieldEntry(
        name=f.name,
        type_label=labels.field_type_label(f.field_type),
        type_name=f.field_type,
        type_category=labels.field_type_category(f.field_type),
        business_meaning=_redact(f.business_meaning, confidential=confidential, include_internal=include_internal),
        unit=_redact(f.unit, confidential=confidential, include_internal=include_internal),
        required=bool(f.required),
        unique=bool(f.is_unique),
        default_value=labels.format_default_value(f),
        value_range=labels.format_value_range(f),
        validation=labels.format_validation(f),
        options=labels.format_options(config.get("options")),
        relation=labels.format_relation(f, table_names, field_names),
        visibility=labels.format_hidden_for(hidden_roles),
        example_value=_redact(f.example_value, confidential=confidential, include_internal=include_internal),
        sensitivity=sensitivity.value,
        sensitivity_label=labels.sensitivity_label(f.sensitivity),
        owner=owner_name or labels.UNASSIGNED,
        standard_ref=_redact(f.standard_ref, confidential=False, include_internal=True),
        order=f.order,
        db_column_name=f.db_column_name if include_internal else "",
        field_id=f.id,
        redacted=confidential and not include_internal,
    )


def build_table_dictionary(
    table: DataTable,
    fields: list[DataField],
    *,
    table_names: dict[int, str],
    field_names: dict[int, str],
    hidden_by_field: dict[str, list[str]],
    include_internal: bool,
    group_name: str = "",
    owner_name: str | None = None,
    views: list[dict[str, Any]] | None = None,
    row_rules_active: bool = False,
    change_log: list[dict[str, str]] | None = None,
) -> TableDictionary:
    """构建一张表的数据字典.

    Args:
        fields: **已经按可见性裁剪过**的字段列表（I3：本模块不裁剪）。
        hidden_by_field: 字段名 → 对其隐藏的角色列表（仅用于渲染「可见性」列）。
    """
    entries = [
        build_field_entry(
            f,
            table_names=table_names,
            field_names=field_names,
            hidden_roles=hidden_by_field.get(f.name, []),
            include_internal=include_internal,
            owner_name=getattr(getattr(f, "owner", None), "username", None),
        )
        for f in sorted(fields, key=lambda x: (x.order, x.id))
    ]
    return TableDictionary(
        table_id=table.id,
        table_name=table.name,
        description=(table.description or "").strip() or labels.MISSING,
        group_name=group_name or labels.MISSING,
        owner=owner_name or labels.UNASSIGNED,
        db_table_name=table.db_table_name if include_internal else "",
        fields=entries,
        views=views or [],
        row_rules_active=row_rules_active,
        change_log=change_log or [],
    )


def build_references(tables: list[TableDictionary]) -> list[dict[str, str]]:
    """表间引用索引：link 字段的目标表 → 反向引用表（合订文档末尾用）."""
    refs: list[dict[str, str]] = []
    for table in tables:
        for entry in table.fields:
            if entry.type_name != "link":
                continue
            refs.append(
                {
                    "source_table": table.table_name,
                    "field_name": entry.name,
                    "target": entry.relation,
                }
            )
    return refs


def build_document(
    *,
    workspace_id: int,
    workspace_name: str,
    generated_at: str,
    schema_hash: str,
    include_internal: bool,
    tables: list[TableDictionary],
) -> DictionaryDocument:
    """组装整份文档（含引用索引）."""
    return DictionaryDocument(
        workspace_name=workspace_name,
        workspace_id=workspace_id,
        generated_at=generated_at,
        schema_hash=schema_hash,
        include_internal=include_internal,
        tables=tables,
        references=build_references(tables),
    )


def document_to_dict(document: DictionaryDocument) -> dict[str, Any]:
    """文档 → JSON 契约（C7：`kind` + `version` + `schema_hash`）."""
    return {
        "kind": DICTIONARY_KIND,
        "version": DICTIONARY_VERSION,
        "generated_at": document.generated_at,
        "schema_hash": document.schema_hash,
        "include_internal": document.include_internal,
        "workspace": {"id": document.workspace_id, "name": document.workspace_name},
        "spec": [{"title": title, "text": text} for title, text in FIELD_DESIGN_SPEC],
        "completeness_note": COMPLETENESS_NOTE,
        "tables": [
            {
                "id": table.table_id,
                "name": table.table_name,
                "description": table.description,
                "group": table.group_name,
                "owner": table.owner,
                **({"db_table_name": table.db_table_name} if document.include_internal else {}),
                "row_rules_active": table.row_rules_active,
                "views": table.views,
                "change_log": table.change_log,
                "fields": [
                    {
                        "id": entry.field_id,
                        "name": entry.name,
                        "type": entry.type_name,
                        "type_label": entry.type_label,
                        "type_category": entry.type_category,
                        "business_meaning": entry.business_meaning,
                        "unit": entry.unit,
                        "required": entry.required,
                        "unique": entry.unique,
                        "default_value": entry.default_value,
                        "value_range": entry.value_range,
                        "validation": entry.validation,
                        "options": entry.options,
                        "relation": entry.relation,
                        "visibility": entry.visibility,
                        "example_value": entry.example_value,
                        "sensitivity": entry.sensitivity,
                        "sensitivity_label": entry.sensitivity_label,
                        "owner": entry.owner,
                        "standard_ref": entry.standard_ref,
                        "order": entry.order,
                        "redacted": entry.redacted,
                        **({"db_column_name": entry.db_column_name} if document.include_internal else {}),
                    }
                    for entry in table.fields
                ],
            }
            for table in document.tables
        ],
        "references": document.references,
    }


__all__ = [
    "CHANGE_LOG_LIMIT",
    "DICTIONARY_KIND",
    "DICTIONARY_VERSION",
    "DictionaryDocument",
    "FieldEntry",
    "TableDictionary",
    "build_document",
    "build_field_entry",
    "build_references",
    "build_table_dictionary",
    "compute_schema_hash",
    "document_to_dict",
]
