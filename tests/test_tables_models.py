"""tables 模型测试：元数据生成、校验与约束."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from cndb.accounts.models import User
from cndb.tables.field_types import UnknownFieldTypeError
from cndb.tables.models import DataField, DataTable, generate_db_table_name
from cndb.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def table(user: User) -> DataTable:
    """挂在工作区下的空数据表."""
    workspace = Workspace.objects.create(name="ws", created_by=user)
    return DataTable.objects.create(workspace=workspace, name="客户表")


def test_generate_db_table_name_format() -> None:
    """物理表名：table_ 前缀 + 12 位十六进制."""
    name = generate_db_table_name()
    assert name.startswith("table_")
    assert len(name) == len("table_") + 12


def test_data_table_generates_db_table_name(table: DataTable) -> None:
    """首次保存自动生成物理表名."""
    assert table.db_table_name.startswith("table_")


def test_data_field_config_normalized_on_save(table: DataTable) -> None:
    """保存时 config 经字段类型系统归一化：填充默认精度与标度."""
    field = DataField.objects.create(table=table, name="数量", field_type="number", config={})
    assert field.config == {"precision": 10, "scale": 2}


def test_data_field_invalid_config_rejected(table: DataTable) -> None:
    """非法 config（精度越界）：保存被拒绝."""
    from cndb.tables.field_types import InvalidFieldConfigError

    with pytest.raises(InvalidFieldConfigError):
        DataField.objects.create(table=table, name="数量", field_type="number", config={"precision": 99})


def test_data_field_unknown_type_rejected(table: DataTable) -> None:
    """未注册字段类型：保存被拒绝."""
    with pytest.raises(UnknownFieldTypeError, match="未注册"):
        DataField.objects.create(table=table, name="神秘", field_type="nope")


def test_data_field_duplicate_name_rejected(table: DataTable) -> None:
    """同表字段重名：IntegrityError."""
    DataField.objects.create(table=table, name="名称", field_type="text")
    with pytest.raises(IntegrityError):
        DataField.objects.create(table=table, name="名称", field_type="long_text")


def test_str_methods(table: DataTable) -> None:
    """模型 __str__ 展示."""
    field = DataField.objects.create(table=table, name="名称", field_type="text")
    assert "客户表" in str(table)
    assert str(field) == "名称: text"
