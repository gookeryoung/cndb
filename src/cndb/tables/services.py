"""表结构服务：所有结构变更走本模块，保证元数据与物理表在同一事务内一致."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from cndb.tables import ddl
from cndb.tables.field_types import get_field_type
from cndb.tables.models import DataField, DataTable
from cndb.workspaces.models import Workspace


@dataclass
class FieldChanges:
    """字段变更集合：None 表示该项保持不变."""

    name: str | None = None
    field_type: str | None = None
    config: Mapping[str, Any] | None = None
    required: bool | None = None
    trashed: bool | None = None


def create_table(*, workspace: Workspace, name: str, field_defs: list[dict[str, Any]]) -> DataTable:
    """创建数据表：先写元数据（生成物理名），再建物理表，任一步失败整体回滚."""
    with transaction.atomic():  # type: ignore[bad-context-manager]
        table = DataTable.objects.create(workspace=workspace, name=name)
        for field_def in field_defs:
            DataField.objects.create(table=table, **field_def)
        ddl.create_physical_table(table)
        return table


def add_field(table: DataTable, field_def: dict[str, Any]) -> DataField:
    """新增字段：元数据与物理列同事务写入."""
    with transaction.atomic():  # type: ignore[bad-context-manager]
        field = DataField.objects.create(table=table, **field_def)
        ddl.add_physical_column(field)
        return field


def _column_type_of(field: DataField) -> str:
    """计算字段当前的 DDL 列类型字符串（用于判断结构是否变化）."""
    return get_field_type(str(field.field_type)).db_column_type(field.config)  # type: ignore[bad-argument-type]


def update_field(field: DataField, changes: FieldChanges) -> None:
    """更新字段：按变更内容同步物理列（改名不动 DDL，类型/配置变化才重建）."""
    old_column_type, old_trashed = _column_type_of(field), bool(field.trashed)
    if changes.name is not None:
        field.name = changes.name  # type: ignore[bad-assignment]
    if changes.field_type is not None:
        field.field_type = changes.field_type  # type: ignore[bad-assignment]
    if changes.config is not None:
        field.config = dict(changes.config)  # type: ignore[bad-assignment]
    if changes.required is not None:
        field.required = changes.required  # type: ignore[bad-assignment]
    if changes.trashed is not None:
        field.trashed = changes.trashed  # type: ignore[bad-assignment]
    with transaction.atomic():  # type: ignore[bad-context-manager]
        field.save()
        if changes.trashed and not old_trashed:
            # 进入回收站即移除物理列；恢复时重新加列（历史数据不再保留）
            ddl.drop_physical_column(field)
        elif changes.trashed is False and old_trashed:
            ddl.add_physical_column(field)
        elif old_column_type != _column_type_of(field):
            ddl.alter_physical_column_type(field)


def delete_field(field: DataField) -> None:
    """删除字段：先删物理列再删元数据，同事务回滚."""
    with transaction.atomic():  # type: ignore[bad-context-manager]
        if not field.trashed:
            ddl.drop_physical_column(field)
        field.delete()


def delete_table(table: DataTable) -> None:
    """删除数据表：物理表与元数据（级联字段）同事务删除."""
    with transaction.atomic():  # type: ignore[bad-context-manager]
        ddl.drop_physical_table(table)
        table.delete()
