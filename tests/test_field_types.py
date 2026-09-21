"""field_types 单元测试."""

import pytest

from cndb.plugins.tables.field_types import default_registry


def _ft(name: str):
    ft = default_registry.get(name)
    assert ft is not None, f"未知字段类型: {name}"
    return ft


def test_number_min_violation():
    ft = _ft("number")
    with pytest.raises(ValueError):
        ft.validate_value(5, {"min": 10})


def test_number_max_violation():
    ft = _ft("number")
    with pytest.raises(ValueError):
        ft.validate_value(100, {"max": 50})


def test_number_none_passthrough():
    ft = _ft("number")
    assert ft.validate_value(None, {}) is None


def test_link_none_passthrough():
    ft = _ft("link")
    # LinkFieldType None → 空列表（空关联集合，语义正确）
    assert ft.validate_value(None, {}) == []


def test_link_invalid_int():
    ft = _ft("link")
    with pytest.raises(ValueError):
        ft.validate_value("not_an_int", {})


def test_select_option_not_in_list():
    ft = _ft("select")
    with pytest.raises(ValueError):
        ft.validate_value("xyz", {"options": ["a", "b"]})


def test_text_none_passthrough():
    ft = _ft("text")
    assert ft.validate_value(None, {}) is None


def test_number_none_passthrough_already():
    """NumberFieldType None passthrough (int 版本)."""
    ft = _ft("number")
    assert ft.validate_value(None, {}) is None


def test_float_none_passthrough():
    ft = _ft("float")
    assert ft.validate_value(None, {}) is None


def test_longtext_none_passthrough():
    ft = _ft("longtext")
    assert ft.validate_value(None, {}) is None


def test_multiselect_none_passthrough():
    ft = _ft("multiselect")
    assert ft.validate_value(None, {}) is None


def test_date_none_passthrough():
    ft = _ft("date")
    assert ft.validate_value(None, {}) is None


def test_datetime_none_passthrough():
    ft = _ft("datetime")
    assert ft.validate_value(None, {}) is None


def test_boolean_none_passthrough():
    ft = _ft("boolean")
    assert ft.validate_value(None, {}) is None


def test_registry_register_class():
    """register 直接传 class（而非实例）应自动实例化."""
    from cndb.plugins.tables.field_types import FieldTypeRegistry, TextFieldType

    reg = FieldTypeRegistry()
    reg.register(TextFieldType)
    assert reg.get("text") is not None


def test_number_int_min_violation():
    """NumberFieldType (int) 的 min 校验."""
    ft = _ft("number")
    with pytest.raises(ValueError):
        ft.validate_value(5, {"min": 10})


# ── 覆盖率补测 ──────────────────────────────────────────


def test_make_column_with_default():
    """FieldType.make_column(default=...) 分支 — L38."""
    ft = _ft("text")
    col = ft.make_column("name", default="hello")
    assert col.default is not None


def test_base_default_value_returns_none():
    """基类 FieldType.default_value 返回 None — L47."""
    ft = _ft("text")
    assert ft.default_value({}) is None


def test_float_min_violation():
    """DecimalFieldType (float) 的 min 校验 — L108."""
    ft = _ft("float")
    with pytest.raises(ValueError) as ei:
        ft.validate_value("0", {"min": 1.0})
    assert "小于最小值" in str(ei.value)


def test_select_field_config_non_empty_ok():
    """SelectFieldConfig 纯字符串输入归一化为 SelectOption — 兼容旧格式."""
    from cndb.plugins.tables.field_types import SelectFieldConfig

    cfg = SelectFieldConfig(options=["a", "b"])
    assert len(cfg.options) == 2
    assert cfg.options[0].label == "a"
    assert cfg.options[0].value == "a"
    assert cfg.options[1].label == "b"


def test_select_field_type_none_passthrough():
    """SelectFieldType.validate_value None passthrough — L182."""
    ft = _ft("select")
    assert ft.validate_value(None, {"options": ["a", "b"]}) is None


# ── SelectFieldConfig 新格式覆盖 ────────────────────────────


def test_select_config_dict_input():
    """options 以字典列表输入 —— label/value 分离."""
    from cndb.plugins.tables.field_types import SelectFieldConfig

    cfg = SelectFieldConfig(options=[{"label": "是", "value": 1, "color": "#ff0000"}])
    assert len(cfg.options) == 1
    assert cfg.options[0].label == "是"
    assert cfg.options[0].value == 1
    assert cfg.options[0].color == "#ff0000"


def test_select_config_auto_fill_colors_on_import():
    """建表/导入场景：options 未带 color 时校验器自动智能配色（导入 → 编辑字段同步）."""
    from cndb.plugins.tables.field_types import SelectFieldConfig
    from cndb.plugins.tables.field_types.smart_color import suggest_colors

    labels = ["紧急", "进行中", "已完成", "玄学词A"]
    cfg = SelectFieldConfig(options=labels)  # 纯字符串列表 —— 文件导入的典型输入
    assert [o.label for o in cfg.options] == labels
    # 每个选项 color 非空，且与 suggest_colors 结果一致
    assert [o.color for o in cfg.options] == suggest_colors(labels)
    # 手动设置的颜色不会被覆盖
    cfg2 = SelectFieldConfig(options=[{"label": "紧急", "value": "紧急", "color": "purple"}])
    assert cfg2.options[0].color == "purple"


def test_select_config_select_option_input():
    """options 以 SelectOption 实例输入."""
    from cndb.plugins.tables.field_types import SelectFieldConfig, SelectOption

    cfg = SelectFieldConfig(options=[SelectOption(label="活跃", value=1)])
    assert cfg.option_values() == ["1"]


def test_select_config_value_label_separation():
    """SelectFieldType 校验 value 用 numberic id 而展示用 label."""
    ft = _ft("select")
    cfg = {"options": [{"label": "男", "value": 1}, {"label": "女", "value": 2}]}
    assert ft.validate_value(1, cfg) == "1"
    assert ft.validate_value("1", cfg) == "1"
    with pytest.raises(ValueError):
        ft.validate_value("男", cfg)  # label 不能直接当 value


def test_multiselect_dict_config():
    """多选 + dict 格式 —— 逗号拼接 value."""
    ft = _ft("multiselect")
    cfg = {"options": [{"label": "A", "value": 1}, {"label": "B", "value": 2}]}
    assert ft.validate_value([1, 2], cfg) == "1,2"


# ── DateFieldConfig auto_fill 覆盖 ──────────────────────────


def test_date_config_auto_fill_on_create():
    """DateFieldConfig.should_auto_fill — on_create."""
    from cndb.plugins.tables.field_types import DateFieldConfig

    cfg = DateFieldConfig(auto_fill="on_create")
    assert cfg.should_auto_fill(for_update=False) is True
    assert cfg.should_auto_fill(for_update=True) is False


def test_date_config_auto_fill_on_update():
    """DateFieldConfig.should_auto_fill — on_update."""
    from cndb.plugins.tables.field_types import DateFieldConfig

    cfg = DateFieldConfig(auto_fill="on_update")
    assert cfg.should_auto_fill(for_update=False) is True
    assert cfg.should_auto_fill(for_update=True) is True


def test_date_config_auto_fill_empty():
    """DateFieldConfig.should_auto_fill — 不自动填充."""
    from cndb.plugins.tables.field_types import DateFieldConfig

    cfg = DateFieldConfig()
    assert cfg.should_auto_fill(for_update=False) is False
    assert cfg.should_auto_fill(for_update=True) is False


def test_date_default_value_auto_fill():
    """DateFieldType default_value — on_create 返回今天."""
    from datetime import date

    ft = _ft("date")
    val = ft.default_value({"auto_fill": "on_create"})
    assert isinstance(val, date)


def test_datetime_default_value_auto_fill():
    """DateTimeFieldType default_value — on_create 返回当前时间."""
    from datetime import datetime

    ft = _ft("datetime")
    val = ft.default_value({"auto_fill": "on_create"})
    assert isinstance(val, datetime)


def test_date_validate_str_input():
    """DateFieldType validate_value — str 输入路径."""
    from datetime import date

    ft = _ft("date")
    assert ft.validate_value("2026-09-12", {}) == date(2026, 9, 12)
    assert ft.validate_value("2026/09/12", {}) == date(2026, 9, 12)


def test_datetime_validate_date_input():
    """DateTimeFieldType validate_value — date 转换为 datetime."""
    from datetime import date, datetime

    ft = _ft("datetime")
    result = ft.validate_value(date(2026, 9, 12), {})
    assert isinstance(result, datetime)
    assert result.date() == date(2026, 9, 12)


# ── 健壮性补充：类型校验边界矩阵 ─────────────────────


def test_boolean_string_unknown_is_false():
    """BooleanFieldType — 未命中真值白名单的字符串静默返回 False（历史行为锁定）."""
    ft = _ft("boolean")
    assert ft.validate_value("maybe", {}) is False
    assert ft.validate_value("否", {}) is False
    assert ft.validate_value("是", {}) is True


def test_boolean_unsupported_type_raises():
    """BooleanFieldType — 非 str/int/float 输入抛 ValueError，消息含原值."""
    ft = _ft("boolean")
    with pytest.raises(ValueError, match="转为布尔值"):
        ft.validate_value(["x"], {})


def test_datetime_numeric_tz_offset_stripped():
    """DateTimeFieldType — 数字时区偏移后缀 "+08:00" 被剥离，按无时区语义存储."""
    from datetime import datetime

    ft = _ft("datetime")
    result = ft.validate_value("2024-01-15T10:30:45+08:00", {})
    assert result == datetime(2024, 1, 15, 10, 30, 45)
    assert result.tzinfo is None


def test_date_invalid_message():
    """DateFieldType — 无效日期字符串报错消息含"日期格式错误"与原值."""
    ft = _ft("date")
    with pytest.raises(ValueError, match=r"日期格式错误: not-a-date"):
        ft.validate_value("not-a-date", {})


def test_float_string_boundary_violation():
    """FloatFieldType — config 边界用字符串形式（"100"）同样生效，"100.5" 报大于最大值."""
    ft = _ft("float")
    # decimals=2 避免默认 0 位小数取整干扰
    assert ft.validate_value("99.5", {"max": "100", "decimals": 2}) == 99.5
    with pytest.raises(ValueError, match="大于最大值"):
        ft.validate_value("100.5", {"max": "100", "decimals": 2})
