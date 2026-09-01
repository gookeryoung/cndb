"""DDL 引擎与服务层测试：物理表结构变更与事务一致性."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import connection

from cndb.tables import services
from cndb.tables.field_types import UnknownFieldTypeError
from cndb.tables.models import DataField, DataTable
from cndb.workspaces.models import Workspace


@pytest.fixture
def workspace(db: object) -> Workspace:
    """测试用工作区（无成员，仅作挂载点）."""
    return Workspace.objects.create(name="测试工作区")


def _table_columns(table_name: object) -> list[str]:
    """返回物理表的列名列表（含 id 与时间戳列）."""
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, str(table_name))
    return [column.name for column in description]


def _table_exists(table_name: object) -> bool:
    """判断物理表是否存在."""
    with connection.cursor() as cursor:
        return str(table_name) in connection.introspection.table_names(cursor)


def _insert_row(table: DataTable, values: dict[str, Any]) -> None:
    """向物理表插入一行业务数据（参数化防注入）."""
    columns = ", ".join(f'"{name}"' for name in values)
    placeholders = ", ".join(["%s"] * len(values))
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO "{table.db_table_name}" ({columns}) VALUES ({placeholders})',
            list(values.values()),
        )


def _fetch_rows(table: DataTable) -> list[tuple[Any, ...]]:
    """读取物理表全部行（按 id 排序）."""
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT * FROM "{table.db_table_name}" ORDER BY "id"')
        return list(cursor.fetchall())


def _make_table(workspace: Workspace) -> DataTable:
    """建一张含文本与数值两字段的表."""
    return services.create_table(
        workspace=workspace,
        name="项目表",
        field_defs=[
            {"name": "名称", "field_type": "text", "config": {"max_length": 255}, "required": True, "order": 0},
            {
                "name": "金额",
                "field_type": "number",
                "config": {"precision": 10, "scale": 2},
                "required": False,
                "order": 1,
            },
        ],
    )


class TestCreateDropTable:
    """建表与删表."""

    def test_create_table_builds_physical_columns(self, workspace: Workspace) -> None:
        """建表后物理表包含 id/时间戳列与全部业务列."""
        table = _make_table(workspace)
        assert _table_exists(table.db_table_name)
        columns = _table_columns(table.db_table_name)
        for expected in ("id", "created_on", "updated_on"):
            assert expected in columns
        for field in table.fields.all():
            assert field.db_column_name in columns
        # 物理名与用户输入无关
        assert table.db_table_name.startswith("table_")
        assert all(f.db_column_name.startswith("field_") for f in table.fields.all())

    def test_create_table_with_no_fields(self, workspace: Workspace) -> None:
        """空字段列表允许建表，物理表仅含系统列."""
        table = services.create_table(workspace=workspace, name="空表", field_defs=[])
        assert _table_exists(table.db_table_name)
        assert len(_table_columns(table.db_table_name)) == 3

    def test_create_table_invalid_type_rolls_back_metadata(self, workspace: Workspace) -> None:
        """字段类型未注册时建表失败，元数据整体回滚."""
        with pytest.raises(UnknownFieldTypeError, match="未注册的字段类型"):
            services.create_table(
                workspace=workspace,
                name="坏表",
                field_defs=[{"name": "坏字段", "field_type": "no_such_type"}],
            )
        assert not DataTable.objects.filter(name="坏表").exists()

    def test_delete_table_drops_physical(self, workspace: Workspace) -> None:
        """删表后物理表消失，元数据级联删除."""
        table = _make_table(workspace)
        services.delete_table(table)
        assert not _table_exists(table.db_table_name)
        assert not DataTable.objects.filter(pk=table.pk).exists()
        assert not DataField.objects.filter(table_id=table.pk).exists()


class TestColumnChanges:
    """加列/删列/改列/回收站."""

    def test_add_field_adds_column(self, workspace: Workspace) -> None:
        """加字段后物理表出现对应列."""
        table = _make_table(workspace)
        field = services.add_field(table, {"name": "备注", "field_type": "long_text"})
        assert field.db_column_name in _table_columns(table.db_table_name)

    def test_delete_field_drops_column(self, workspace: Workspace) -> None:
        """删字段后物理列消失，元数据删除."""
        table = _make_table(workspace)
        field = table.fields.get(name="金额")
        services.delete_field(field)
        assert field.db_column_name not in _table_columns(table.db_table_name)
        assert not DataField.objects.filter(pk=field.pk).exists()

    def test_rename_field_keeps_physical_column(self, workspace: Workspace) -> None:
        """仅改字段名不动 DDL，物理列保持不变."""
        table = _make_table(workspace)
        field = table.fields.get(name="名称")
        services.update_field(field, services.FieldChanges(name="项目名称"))
        field.refresh_from_db()
        assert field.name == "项目名称"
        assert field.db_column_name in _table_columns(table.db_table_name)

    def test_trash_field_drops_and_restore_adds_column(self, workspace: Workspace) -> None:
        """字段进回收站移除物理列，恢复后重新加列."""
        table = _make_table(workspace)
        field = table.fields.get(name="金额")
        services.update_field(field, services.FieldChanges(trashed=True))
        assert field.db_column_name not in _table_columns(table.db_table_name)
        services.update_field(field, services.FieldChanges(trashed=False))
        assert field.db_column_name in _table_columns(table.db_table_name)

    def test_trash_already_trashed_field_is_noop(self, workspace: Workspace) -> None:
        """对已在回收站的字段重复置回收站不报错."""
        table = _make_table(workspace)
        field = table.fields.get(name="金额")
        services.update_field(field, services.FieldChanges(trashed=True))
        services.update_field(field, services.FieldChanges(trashed=True))
        assert field.trashed


class TestAlterColumn:
    """改列类型（重建表）."""

    def test_alter_number_scale_preserves_data(self, workspace: Workspace) -> None:
        """扩大数值精度后旧数据保留，且可继续插入（主键序列不回退）."""
        table = _make_table(workspace)
        text_field = table.fields.get(name="名称")
        number_field = table.fields.get(name="金额")
        _insert_row(table, {text_field.db_column_name: "项目甲", number_field.db_column_name: 12.34})
        services.update_field(number_field, services.FieldChanges(config={"precision": 12, "scale": 4}))
        field = DataField.objects.get(pk=number_field.pk)
        rows = _fetch_rows(table)
        assert len(rows) == 1
        _insert_row(table, {text_field.db_column_name: "项目乙", field.db_column_name: 56.78})
        rows = _fetch_rows(table)
        assert len(rows) == 2
        assert rows[0][0] != rows[1][0]

    def test_alter_text_to_long_text_preserves_data(self, workspace: Workspace) -> None:
        """text 改 long_text 走重建，文本数据保留."""
        table = _make_table(workspace)
        field = table.fields.get(name="名称")
        _insert_row(table, {field.db_column_name: "保留我"})
        services.update_field(field, services.FieldChanges(field_type="long_text"))
        field = DataField.objects.get(pk=field.pk)
        index = _table_columns(table.db_table_name).index(field.db_column_name)
        assert _fetch_rows(table)[0][index] == "保留我"

    def test_alter_jsonb_column_works_on_sqlite(self, workspace: Workspace) -> None:
        """multi_select 的 jsonb 列在 SQLite 上映射为 text，建表与改类型均可用."""
        table = services.create_table(
            workspace=workspace,
            name="选项表",
            field_defs=[
                {"name": "标签", "field_type": "multi_select", "config": {"choices": ["红", "绿"]}},
            ],
        )
        field = table.fields.get(name="标签")
        services.update_field(field, services.FieldChanges(field_type="text"))
        assert field.db_column_name in _table_columns(table.db_table_name)
