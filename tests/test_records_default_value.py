"""records 默认值/自动填充测试 —— DataField.default_value 创建路径填充 + auto_fill 规则."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from cndb.plugins.tables.field_types import DateFieldConfig, DateFieldType, DateTimeFieldType
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.workspaces.models import Workspace


@pytest.fixture
def ws(db):
    """最小工作区（created_by_id 可空，无需用户）."""
    workspace = Workspace(name="DV_WS")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


@pytest.fixture
def dv_table(db, db_engine, ws):
    """带默认值/自动填充字段的表.

    字段清单：
    - 状态 text   default_value="待办"
    - 数量 number default_value="123"（字符串默认值，验证 coerce）
    - 创建日期 date   config={auto_fill: on_create}（无 default_value）
    - 更新时间 datetime config={auto_fill: on_update}
    - 截止日期 date   default_value="2024-01-15" + config={auto_fill: on_create}（默认值优先）
    - 坏默认 number default_value="abc"（非法默认值，验证跳过不阻塞）
    """
    dt = DataTable(workspace_id=ws.id, name="DVTable")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()

    specs: list[dict] = [
        {"name": "状态", "field_type": "text", "order": 0, "default_value": "待办"},
        {"name": "数量", "field_type": "number", "order": 1, "default_value": "123"},
        {"name": "创建日期", "field_type": "date", "order": 2, "config": {"auto_fill": "on_create"}},
        {"name": "更新时间", "field_type": "datetime", "order": 3, "config": {"auto_fill": "on_update"}},
        {
            "name": "截止日期",
            "field_type": "date",
            "order": 4,
            "default_value": "2024-01-15",
            "config": {"auto_fill": "on_create"},
        },
        {"name": "坏默认", "field_type": "number", "order": 5, "default_value": "abc"},
    ]
    fields: list[DataField] = []
    for spec in specs:
        df = DataField(table_id=dt.id, **spec)
        df.ensure_db_name()
        fields.append(df)
    db.add_all(fields)
    db.commit()
    db.refresh(dt)

    ddl.create_table(db_engine, dt)
    return dt, {f.name: f for f in fields}


class TestCreateRowDefaultValue:
    """create_row 的 default_value / auto_fill 填充规则."""

    def test_text_default_value_filled(self, db_engine, dv_table):
        dt, _fields = dv_table
        row = rec.create_row(db_engine, dt, {})
        assert row["状态"] == "待办"

    def test_number_string_default_coerced(self, db_engine, dv_table):
        dt, _fields = dv_table
        row = rec.create_row(db_engine, dt, {})
        assert row["数量"] == 123

    def test_default_value_wins_over_auto_fill(self, db_engine, dv_table):
        """default_value 与 auto_fill 同时配置时，默认值优先于当前日期."""
        dt, _fields = dv_table
        row = rec.create_row(db_engine, dt, {})
        assert row["截止日期"] == date(2024, 1, 15)

    def test_invalid_default_skipped(self, db_engine, dv_table):
        """非法默认值（number + "abc"）跳过且不阻塞建行."""
        dt, _fields = dv_table
        row = rec.create_row(db_engine, dt, {})
        assert row["坏默认"] is None

    def test_explicit_value_not_overridden(self, db_engine, dv_table):
        """用户显式传值时不被默认值覆盖."""
        dt, _fields = dv_table
        row = rec.create_row(db_engine, dt, {"状态": "进行中"})
        assert row["状态"] == "进行中"

    def test_explicit_none_wins(self, db_engine, dv_table):
        """显式传 None（清空意图）同样不被默认值覆盖."""
        dt, _fields = dv_table
        row = rec.create_row(db_engine, dt, {"状态": None})
        assert row["状态"] is None

    def test_update_path_no_default_fill(self, db_engine, dv_table):
        """更新路径不填 default_value（仅创建时生效；auto_fill=on_update 的覆盖不在本断言范围）."""
        dt, _fields = dv_table
        result, _link = rec._normalize_values(dt, {}, for_update=True)
        name_to_col = {f.name: f.db_column_name for f in dt.fields}
        for fname in ("状态", "数量", "截止日期", "坏默认"):
            assert name_to_col[fname] not in result


class TestAutoFillRules:
    """date/datetime auto_fill 自动填充规则."""

    def test_date_on_create_fills_today(self, db_engine, dv_table):
        dt, _fields = dv_table
        row = rec.create_row(db_engine, dt, {})
        assert row["创建日期"] == date.today()

    def test_datetime_on_update_fills(self, db_engine, dv_table):
        dt, _fields = dv_table
        row = rec.create_row(db_engine, dt, {})
        assert isinstance(row["更新时间"], datetime)


class TestDateFieldConfig:
    """DateFieldConfig / FieldType.default_value 单元测试（去 pragma no cover 回归）."""

    def test_should_auto_fill_matrix(self):
        assert DateFieldConfig(auto_fill="").should_auto_fill(for_update=False) is False
        assert DateFieldConfig(auto_fill="").should_auto_fill(for_update=True) is False
        assert DateFieldConfig(auto_fill="on_create").should_auto_fill(for_update=False) is True
        assert DateFieldConfig(auto_fill="on_create").should_auto_fill(for_update=True) is False
        assert DateFieldConfig(auto_fill="on_update").should_auto_fill(for_update=False) is True
        assert DateFieldConfig(auto_fill="on_update").should_auto_fill(for_update=True) is True

    def test_date_default_value_today(self):
        assert DateFieldType().default_value({"auto_fill": "on_create"}) == date.today()
        assert DateFieldType().default_value({"auto_fill": "on_update"}) == date.today()
        assert DateFieldType().default_value({"auto_fill": ""}) is None

    def test_datetime_default_value_now(self):
        # 实现存 UTC naive（与 TimestampMixin 语义一致），窗口边界也用 UTC
        before = datetime.now(UTC).replace(tzinfo=None)
        value = DateTimeFieldType().default_value({"auto_fill": "on_create"})
        after = datetime.now(UTC).replace(tzinfo=None)
        assert value is not None and before <= value <= after
        assert DateTimeFieldType().default_value({"auto_fill": ""}) is None
