"""tables 插件单元测试（field_types + models 工具函数）."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.models.base import Base
from cndb.plugins.tables.field_types import (
    BooleanFieldType,
    DateFieldType,
    FieldTypeRegistry,
    FloatFieldType,
    LongTextFieldType,
    MultiSelectFieldType,
    NumberFieldType,
    SelectFieldType,
    TextFieldType,
    build_default_registry,
    default_registry,
)
from cndb.plugins.tables.models import (
    DataField,
    DataTable,
    _link_table_name,
    _trash_table_name,
    generate_db_column_name,
    generate_db_table_name,
)

# ── field_types 测试 ──────────────────────────────────


class TestDefaultRegistry:
    def test_all_builtin_types_registered(self):
        names = sorted(ft.name for ft in default_registry.all())
        assert names == sorted(
            [
                "text",
                "longtext",
                "number",
                "float",
                "boolean",
                "date",
                "datetime",
                "select",
                "link",
                "multiselect",
            ]
        )

    def test_get_existing(self):
        ft = default_registry.get("text")
        assert ft is not None
        assert ft.name == "text"
        assert ft.label == "单行文本"

    def test_get_missing(self):
        assert default_registry.get("nonexistent") is None

    def test_choices(self):
        choices = default_registry.choices()
        assert ("text", "单行文本") in choices


class TestFieldTypeRegistry:
    def test_register_invalid(self):
        reg = FieldTypeRegistry()
        ft = TextFieldType()
        ft.name = ""
        with pytest.raises(ValueError, match="必须定义 name"):
            reg.register(ft)

    def test_build_default(self):
        reg = build_default_registry()
        assert len(reg.all()) == 10


class TestTextFieldType:
    def test_make_column(self):
        ft = TextFieldType()
        col = ft.make_column("field_abc123")
        assert col.name == "field_abc123"
        assert col.nullable is True

    def test_validate_passthrough(self):
        ft = TextFieldType()
        assert ft.validate_value("hello", {}) == "hello"
        assert ft.validate_value(None, {}) is None


class TestNumberFieldType:
    def test_validate_ok(self):
        ft = NumberFieldType()
        assert ft.validate_value(42, {}) == 42

    def test_validate_bounds(self):
        ft = NumberFieldType()
        cfg = {"min": 0, "max": 100}
        assert ft.validate_value(50, cfg) == 50
        with pytest.raises(ValueError, match="小于最小值"):
            ft.validate_value(-1, cfg)
        with pytest.raises(ValueError, match="大于最大值"):
            ft.validate_value(101, cfg)

    def test_validate_coerce(self):
        ft = NumberFieldType()
        assert ft.validate_value("7", {}) == 7


class TestFloatFieldType:
    def test_rounding(self):
        ft = FloatFieldType()
        assert ft.validate_value(3.14159, {"decimals": 2}) == 3.14


class TestBooleanFieldType:
    def test_various_inputs(self):
        ft = BooleanFieldType()
        assert ft.validate_value(True, {}) is True
        assert ft.validate_value(False, {}) is False
        assert ft.validate_value(1, {}) is True
        assert ft.validate_value(0, {}) is False
        assert ft.validate_value("yes", {}) is True
        assert ft.validate_value("no", {}) is False
        assert ft.validate_value(None, {}) is None

    def test_invalid_input(self):
        ft = BooleanFieldType()
        with pytest.raises(ValueError):
            ft.validate_value([1, 2], {})

    def test_default_false(self):
        ft = BooleanFieldType()
        assert ft.default_value({}) is False


class TestSelectFieldType:
    def test_validate_ok(self):
        ft = SelectFieldType()
        assert ft.validate_value("a", {"options": ["a", "b", "c"]}) == "a"

    def test_validate_invalid(self):
        ft = SelectFieldType()
        with pytest.raises(ValueError, match="不在可选值"):
            ft.validate_value("x", {"options": ["a", "b"]})


class TestMultiSelectFieldType:
    def test_validate_list(self):
        ft = MultiSelectFieldType()
        result = ft.validate_value(["a", "b"], {"options": ["a", "b", "c"]})
        assert result == "a,b"

    def test_validate_single(self):
        ft = MultiSelectFieldType()
        assert ft.validate_value("a", {"options": ["a", "b"]}) == "a"


class TestDateFieldType:
    def test_make_column(self):
        ft = DateFieldType()
        col = ft.make_column("field_date")
        assert col.name == "field_date"


class TestLongTextFieldType:
    def test_no_length(self):
        ft = LongTextFieldType()
        assert ft.sqlalchemy_length is None


# ── tables/models 工具函数测试 ────────────────────────


class TestIdentifierGeneration:
    def test_generate_db_table_name(self):
        name = generate_db_table_name()
        assert name.startswith("table_")
        assert len(name) == 6 + 12  # "table_" + 12 hex

    def test_generate_db_column_name(self):
        name = generate_db_column_name()
        assert name.startswith("field_")
        assert len(name) == 6 + 12

    def test_uniqueness(self):
        """多次调用应产生不同的名称（概率极低的碰撞）."""
        names = {generate_db_table_name() for _ in range(100)}
        assert len(names) == 100

    def test_trash_table_name(self):
        assert _trash_table_name("table_abc123def456") == "trash_abc123def456"

    def test_link_table_name(self):
        assert _link_table_name("field_abc123def456") == "link_abc123def456"


class TestDataTableHelpers:
    @pytest.fixture
    def db_session(self, tmp_path):
        engine = create_engine(
            f"sqlite:///{tmp_path}/test.db",
            connect_args={"check_same_thread": False},
        )
        import cndb.plugins.accounts.models
        import cndb.plugins.workspaces.models  # noqa: F401

        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()
            Base.metadata.drop_all(engine)

    def test_ensure_db_name_first_time(self, db_session):
        dt = DataTable(
            workspace_id=1,
            name="测试表",
            db_table_name="",
        )
        dt.ensure_db_name()
        assert dt.db_table_name.startswith("table_")

    def test_ensure_db_name_preserves_existing(self, db_session):
        dt = DataTable(
            workspace_id=1,
            name="测试表",
            db_table_name="table_custom123456",
        )
        dt.ensure_db_name()
        assert dt.db_table_name == "table_custom123456"

    def test_active_fields_filters_trashed(self, db_session):
        dt = DataTable(
            workspace_id=1,
            name="t",
            db_table_name="table_000000000001",
        )
        dt.fields = [
            DataField(name="a", field_type="text", db_column_name="field_000000000001", order=1, trashed=False),
            DataField(name="b", field_type="text", db_column_name="field_000000000002", order=2, trashed=True),
            DataField(name="c", field_type="text", db_column_name="field_000000000003", order=3, trashed=False),
        ]
        active = dt.active_fields()
        assert [f.name for f in active] == ["a", "c"]

    def test_trashed_property(self, db_session):
        dt = DataTable(db_table_name="table_000000000002", workspace_id=1, name="t")
        dt.trashed = True
        dt.trashed_at = dt.datetime.now(dt.UTC) if False else None
        assert dt.trash_table_name == "trash_000000000002"


class TestDataFieldHelpers:
    def test_ensure_db_name(self):
        f = DataField(name="col", field_type="text", db_column_name="")
        f.ensure_db_name()
        assert f.db_column_name.startswith("field_")

    def test_ensure_db_name_preserves(self):
        f = DataField(name="col", field_type="text", db_column_name="field_aaaabbbbcccc")
        f.ensure_db_name()
        assert f.db_column_name == "field_aaaabbbbcccc"

    def test_link_table_name(self):
        f = DataField(name="col", field_type="text", db_column_name="field_abc123def456")
        assert f.link_table_name == "link_abc123def456"
