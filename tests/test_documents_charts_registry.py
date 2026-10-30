"""图表模板注册表（ADR 0048 / 需求卡片 0070）单测.

覆盖：两级注册表结构、指纹、normalize_config 宽松归一（I6：缺键回默认 /
坏值回退 / 未知键忽略 / 永不抛错）、validate_config 严格校验（结构错误列表）、
require_valid_config（400 入口，成功返回归一 config）；标准类型预设库
（0070 C1/C2/C4：10 类 × 3 预设、row_kind 归一 / 校验、兼容性）。
"""

from __future__ import annotations

import copy

import pytest

from cndb.core.errors import BadRequestError
from cndb.plugins.documents.services.charts.registry import (
    CHART_CATEGORIES,
    CHART_TEMPLATES,
    get_category,
    get_template,
    normalize_config,
    require_valid_config,
    template_fingerprint,
    templates_payload,
    validate_config,
)

TPL_KEYS = ("bar-line-dual-axis", "stacked-bar-horizontal", "grouped-bar-horizontal")

#: 标准类型（需求卡片 0070 C1）：10 类图表 × 每类 3 套预设（C2）
STANDARD_TYPES = {
    "line": ("trend-line", "series"),
    "area": ("trend-area", "series"),
    "bar": ("comparison-bar", "series"),
    "pie": ("composition-pie", "value"),
    "scatter": ("distribution-scatter", "xy"),
    "radar": ("evaluation-radar", "series"),
    "funnel": ("composition-funnel", "value"),
    "gauge": ("evaluation-gauge", "value"),
    "treemap": ("composition-treemap", "value"),
    "heatmap": ("distribution-heatmap", "series"),
}
#: 每类预设后缀（bar 用 stacked 避开既有 bar-line-dual-axis 前缀）
STANDARD_SUFFIXES = {
    "line": ("business", "classic", "vivid"),
    "area": ("business", "classic", "stacked"),
    "bar": ("business", "classic", "stacked"),
    "pie": ("business", "classic", "donut"),
    "scatter": ("business", "classic", "trend"),
    "radar": ("business", "classic", "fill"),
    "funnel": ("business", "classic", "vivid"),
    "gauge": ("business", "classic", "vivid"),
    "treemap": ("business", "classic", "vivid"),
    "heatmap": ("business", "classic", "vivid"),
}
STANDARD_KEYS = [f"{t}-{s}" for t, suffixes in STANDARD_SUFFIXES.items() for s in suffixes]


class TestRegistry:
    def test_two_level_structure(self):
        """一级 × 二级分类与模板：模板类别键都指向已登记的二级分类."""
        assert {c.key for c in CHART_CATEGORIES} >= {
            "composition",
            "comparison",
            "comparison-bar",
            "comparison-bar-h",
            # 标准类型分类（0070 C1）
            "trend",
            "distribution",
            "evaluation",
        }
        assert set(CHART_TEMPLATES) >= set(TPL_KEYS) | set(STANDARD_KEYS)
        for _key, tpl in CHART_TEMPLATES.items():
            cat = get_category(tpl.category)
            assert cat is not None and cat.parent is not None  # 模板必属二级
            assert get_category(cat.parent) is not None  # 二级 parent 指向已登记一级
            assert tpl.row_min >= 1 and tpl.row_max >= tpl.row_min
            assert tpl.default_config  # 每个模板必须带默认配置

    def test_category_assignment(self):
        """ADR 0058 C1/C4：双轴更名并归对比-柱形，堆叠 / 分组归对比-条形."""
        dual = CHART_TEMPLATES["bar-line-dual-axis"]
        assert dual.name == "双轴柱线组合图"
        assert dual.category == "comparison-bar"
        assert CHART_TEMPLATES["stacked-bar-horizontal"].category == "comparison-bar-h"
        assert CHART_TEMPLATES["grouped-bar-horizontal"].category == "comparison-bar-h"

    def test_get_template_unknown_is_none(self):
        assert get_template("no-such-template") is None
        assert get_category("no-such-category") is None

    def test_fingerprint_contains_version_and_renderer(self):
        fp = template_fingerprint("bar-line-dual-axis")
        assert fp == "bar-line-dual-axis@9+r2"
        # 未知模板给占位指纹（实例仍可 ETag 缓存降级图）
        assert template_fingerprint("gone") == "gone@0+r2"

    def test_templates_payload_shape(self):
        payload = templates_payload()
        # 一级分类层级化（ADR 0058 + 0070）：空分类不输出，五个一级均含二级 children
        cats = payload["categories"]
        assert [c["key"] for c in cats] == ["composition", "comparison", "trend", "distribution", "evaluation"]
        comparison_children = next(c for c in cats if c["key"] == "comparison")["children"]
        assert [(c["key"], c["name"], c["parent"]) for c in comparison_children] == [
            ("comparison-bar", "对比-柱形", "comparison"),
            ("comparison-bar-h", "对比-条形", "comparison"),
        ]
        assert {t["key"] for t in payload["templates"]} == set(CHART_TEMPLATES)
        tpl = next(t for t in payload["templates"] if t["key"] == "bar-line-dual-axis")
        assert tpl["name"] == "双轴柱线组合图"
        assert tpl["category"] == "comparison-bar"
        assert tpl["row_min"] == 2 and tpl["row_max"] == 24
        assert tpl["default_config"]["data"]["rows"]  # 清单带默认配置供设计器起稿
        # 增量 schema 字段（0070）：row_kind / style_fields 供设计器分派
        assert tpl["row_kind"] == "dual-axis" and tpl["style_fields"] == []
        line = next(t for t in payload["templates"] if t["key"] == "line-vivid")
        assert line["row_kind"] == "series"
        assert [f["key"] for f in line["style_fields"]] == ["showMarkers", "showValues"]


class TestStandardTypePresets:
    """需求卡片 0070 C1/C2/C4：标准类型预设库结构与兼容性."""

    def test_ten_types_with_three_presets_each(self):
        """C1/C2：10 类图表齐全，每类 ≥3 套预设，key 唯一且类别 / 行结构正确."""
        for type_key, (category, row_kind) in STANDARD_TYPES.items():
            presets = [f"{type_key}-{s}" for s in STANDARD_SUFFIXES[type_key]]
            for key in presets:
                assert key in CHART_TEMPLATES, key
                tpl = CHART_TEMPLATES[key]
                assert tpl.category == category, key
                assert tpl.row_kind == row_kind, key
                assert tpl.labels_from_default is True, key
                assert tpl.version == 1
                # 预设差异落在 default_config（C2：配色 / 纸底 / 样式 / 数据展示风格）
                assert tpl.default_config["theme"]["palette"]
                assert tpl.default_config["theme"]["paper"].startswith("#")

    def test_preset_configs_differ(self):
        """C2：同类型三套预设的默认配置互不相同（不同配色方案 / 布局风格）."""
        for type_key in STANDARD_TYPES:
            keys = [f"{type_key}-{s}" for s in STANDARD_SUFFIXES[type_key]]
            configs = [CHART_TEMPLATES[k].default_config for k in keys]
            palettes = {tuple(c["theme"]["palette"]) for c in configs}
            assert len(palettes) == 3, f"{type_key} 预设调色板未全部区分"
            # 商务 / 经典 / 明快三套纸底与配色成对差异
            assert len({c["theme"]["paper"] for c in configs}) >= 2

    def test_default_configs_render_valid(self):
        """C5 前置：全部预设默认配置通过严格校验."""
        for key in STANDARD_KEYS:
            assert validate_config(key, CHART_TEMPLATES[key].default_config) == [], key

    def test_style_fields_match_default_style(self):
        """C3：style_fields 声明与 default_config.style 键一致."""
        for key in STANDARD_KEYS:
            tpl = CHART_TEMPLATES[key]
            declared = {f["key"] for f in tpl.style_fields}
            style = tpl.default_config.get("style", {})
            assert declared == set(style), key
            assert all(isinstance(v, bool) for v in style.values()), key

    def test_legacy_templates_unchanged(self):
        """C4：既有三模板 schema / 版本 / 默认配置不受扩展影响."""
        assert CHART_TEMPLATES["bar-line-dual-axis"].version == 9
        assert CHART_TEMPLATES["bar-line-dual-axis"].row_kind == "dual-axis"
        assert CHART_TEMPLATES["stacked-bar-horizontal"].row_kind == "series"
        assert CHART_TEMPLATES["stacked-bar-horizontal"].labels_from_default is False
        assert CHART_TEMPLATES["grouped-bar-horizontal"].row_kind == "series"
        # 旧模板无 style 声明：归一输出不含 style 节（输出形状不变）
        for key in TPL_KEYS:
            cfg = normalize_config(key, copy.deepcopy(CHART_TEMPLATES[key].default_config))
            assert "style" not in cfg, key


class TestNormalizeConfig:
    def test_default_config_roundtrip_stable(self):
        """默认配置归一后保持稳定（设计器初稿 = 渲染初稿）."""
        for key in TPL_KEYS:
            once = normalize_config(key, copy.deepcopy(CHART_TEMPLATES[key].default_config))
            twice = normalize_config(key, once)
            assert once == twice

    def test_missing_keys_fall_back_to_defaults(self):
        cfg = normalize_config("bar-line-dual-axis", {})
        assert cfg["caption"]["title"] == "未命名图表"
        assert cfg["labels"]["legendActual"] == "主值（实际）"
        assert cfg["theme"]["palette"] == ["#8E2318", "#5C7283", "#5F6B4E"]
        assert cfg["data"]["rows"] == []  # 数据不造假，空行由渲染层回退默认

    def test_garbage_input_never_raises(self):
        """I6：任意垃圾输入不抛错（渲染路径永不因 config 崩）."""
        for bad in (None, "str", 42, [1, 2], {"caption": "x", "data": "y"}):
            for key in TPL_KEYS:
                cfg = normalize_config(key, bad)
                assert set(cfg) == {"caption", "labels", "theme", "data"}

    def test_unknown_keys_ignored_and_bad_values_coerced(self):
        cfg = normalize_config(
            "bar-line-dual-axis",
            {
                "bogus": 1,
                "caption": {"title": 123, "extra": "x"},
                "theme": {"palette": ["#8E2318", "red", "#XYZXYZ"], "paper": "white"},
                "data": {
                    "actualCount": "6",
                    "rows": [{"label": "2020", "value": "132", "growth": "abc"}, "junk"],
                },
            },
        )
        assert "bogus" not in cfg and cfg["caption"]["title"] == "123"
        assert cfg["theme"]["palette"] == ["#8E2318"]  # 非法项丢弃，不全回默认
        assert cfg["theme"]["paper"] == "#FBFAF5"
        # actualCount 会被钳制到有效行数（junk 行被丢弃后仅剩 1 行）
        assert cfg["data"]["actualCount"] == 1
        assert cfg["data"]["rows"] == [{"label": "2020", "value": 132.0, "growth": None}]

    def test_series_rows_padded_and_truncated(self):
        """堆叠 / 分组模板：values 截断或补齐到首行系列数，超上限截断."""
        cfg = normalize_config(
            "stacked-bar-horizontal",
            {"data": {"rows": [{"label": "A", "values": [1, 2, 3, 4]}, {"label": "B", "values": [5]}]}},
        )
        series_count = len(cfg["data"]["rows"][0]["values"])
        assert series_count == 4  # 4 在 stacked 上限(6)内，按首行长度为准
        assert all(len(r["values"]) == series_count for r in cfg["data"]["rows"])
        assert cfg["data"]["rows"][1]["values"] == [5.0, None, None, None]  # 短行补 None

        seven = normalize_config("stacked-bar-horizontal", {"data": {"rows": [{"label": "A", "values": [1] * 7}]}})
        assert len(seven["data"]["rows"][0]["values"]) == 6  # 超 series_max 截断

    def test_standard_default_roundtrip_stable(self):
        """0070：标准类型默认配置归一幂等（含 style 节）."""
        for key in STANDARD_KEYS:
            once = normalize_config(key, copy.deepcopy(CHART_TEMPLATES[key].default_config))
            twice = normalize_config(key, once)
            assert once == twice, key

    def test_standard_series_count_from_labels(self):
        """0070：标准系列模板系列数以 labels.series 为准，行 values 同步扩缩."""
        cfg = normalize_config(
            "line-vivid",
            {
                "labels": {"series": ["甲", "乙"], "unitY": "万元"},
                "data": {"rows": [{"label": "Q1", "values": [1, 2, 3]}, {"label": "Q2", "values": [4]}]},
            },
        )
        assert cfg["labels"]["series"] == ["甲", "乙"]
        assert cfg["labels"]["unitY"] == "万元"
        assert cfg["data"]["rows"][0]["values"] == [1.0, 2.0]  # 截断到系列数
        assert cfg["data"]["rows"][1]["values"] == [4.0, None]  # 短行补空

    def test_value_and_xy_rows_normalized(self):
        """0070：value / xy 行结构归一（非对象行丢弃，缺键补空）."""
        cfg = normalize_config("pie-business", {"data": {"rows": [{"label": "A", "value": "12"}, {"junk": 1}, "bad"]}})
        assert cfg["data"]["rows"] == [{"label": "A", "value": 12.0}, {"label": "", "value": None}]
        xy = normalize_config("scatter-trend", {"data": {"rows": [{"x": "1.5", "y": 2}, "bad"]}})
        assert xy["data"]["rows"] == [{"x": 1.5, "y": 2.0}]

    def test_style_normalized_with_defaults(self):
        """0070 C3：style 缺键回默认、坏值回退、未知键忽略."""
        cfg = normalize_config("pie-business", {"style": {"donut": "yes", "bogus": 1}})
        assert cfg["style"] == {"donut": False, "showPercent": True}  # 缺 showPercent 回默认
        # 完全缺 style 节也回默认
        cfg2 = normalize_config("pie-donut", {})
        assert cfg2["style"] == {"donut": True, "showPercent": True}
        # 无样式模板（gauge）无 style 节
        assert "style" not in normalize_config("gauge-business", {})

    def test_standard_garbage_input_never_raises(self):
        """0070 C5：标准类型任意垃圾输入不抛错."""
        for bad in (None, "str", 42, [1, 2], {"caption": "x", "data": "y", "style": "z"}):
            for key in ("line-vivid", "pie-donut", "scatter-trend", "gauge-classic", "heatmap-vivid"):
                cfg = normalize_config(key, bad)
                assert set(cfg) <= {"caption", "labels", "theme", "style", "data"}


class TestValidateConfig:
    def test_default_configs_all_pass(self):
        for key in TPL_KEYS:
            assert validate_config(key, CHART_TEMPLATES[key].default_config) == []

    def test_dual_axis_default_growth_all_empty(self):
        """ADR 0056 C1：双轴模板默认次值全部留空."""
        rows = CHART_TEMPLATES["bar-line-dual-axis"].default_config["data"]["rows"]
        assert all(row["growth"] is None for row in rows)
        assert CHART_TEMPLATES["bar-line-dual-axis"].version == 9

    def test_first_row_growth_rejected(self):
        """ADR 0056 C2：第 1 行次值禁填（无上年基数），第 2 行起仍允许."""
        tpl = CHART_TEMPLATES["bar-line-dual-axis"]
        rows = copy.deepcopy(tpl.default_config["data"]["rows"])
        rows[0]["growth"] = 12.5
        errors = validate_config("bar-line-dual-axis", {"data": {"rows": rows}})
        assert any("第 1 行次值不能填写" in e for e in errors)
        # 第 2 行起填写合法
        ok = copy.deepcopy(tpl.default_config["data"]["rows"])
        ok[1]["growth"] = 19.7
        assert validate_config("bar-line-dual-axis", {"data": {"rows": ok}}) == []

    def test_unknown_template_and_non_dict(self):
        assert validate_config("gone", {}) == ["模板 gone 不存在或已下线"]
        assert validate_config("bar-line-dual-axis", "nope") == ["config 必须是对象"]

    def test_structural_errors(self):
        tpl = CHART_TEMPLATES["bar-line-dual-axis"]
        rows = tpl.default_config["data"]["rows"]

        # 行数越界
        assert any("行数须在" in e for e in validate_config("bar-line-dual-axis", {"data": {"rows": rows[:1]}}))
        # 缺标签 / 非数字主值 / 非数字次值
        bad = [{"label": "", "value": "x", "growth": "y"}]
        errors = validate_config("bar-line-dual-axis", {"data": {"rows": bad}})
        assert any("缺少行标签" in e for e in errors)
        assert any("主值必须是数字" in e for e in errors)
        assert any("次值必须是数字" in e for e in errors)
        # actualCount 越界
        bad_count = {"data": {"rows": rows, "actualCount": 99}}
        assert any("actualCount" in e for e in validate_config("bar-line-dual-axis", bad_count))
        # 空行数组
        assert validate_config("bar-line-dual-axis", {"data": {"rows": []}}) == ["data.rows 必须是非空数组"]

    def test_series_rules(self):
        stacked = CHART_TEMPLATES["stacked-bar-horizontal"].default_config
        # 系列数不一致
        rows = [
            {"label": "A", "values": [1, 2, 3]},
            {"label": "B", "values": [1, 2]},
        ]
        assert any("不一致" in e for e in validate_config("stacked-bar-horizontal", {"data": {"rows": rows}}))
        # 系列数越界（stacked 上限 6）
        seven = [{"label": "A", "values": [1] * 7}]
        assert any("系列数须在" in e for e in validate_config("stacked-bar-horizontal", {"data": {"rows": seven}}))
        # grouped 恰好两系列
        one = [{"label": "A", "values": [1]}]
        assert any("系列数须在 2–2" in e for e in validate_config("grouped-bar-horizontal", {"data": {"rows": one}}))
        # 缺系列值
        empty = [{"label": "A", "values": []}]
        assert any("非空数组" in e for e in validate_config("stacked-bar-horizontal", {"data": {"rows": empty}}))
        assert stacked  # 默认配置本身通过（已在前一条覆盖）

    def test_require_valid_config_raises_400_and_normalizes(self):
        with pytest.raises(BadRequestError) as exc_info:
            require_valid_config("stacked-bar-horizontal", {"data": {"rows": []}})
        assert exc_info.value.code == "chart_config_invalid"

        normalized = require_valid_config(
            "stacked-bar-horizontal",
            {"data": {"rows": [{"label": "A", "values": [1, "2", 3.5]}]}, "extra": 1},
        )
        assert normalized["data"]["rows"] == [{"label": "A", "values": [1.0, 2.0, 3.5]}]
        assert "extra" not in normalized

    def test_value_row_validation(self):
        """0070：value 行结构（饼图 / 漏斗 / 仪表盘 / 树状图）逐行校验."""
        bad = [{"label": "", "value": "x"}, {"label": "B", "value": 2}]
        errors = validate_config("pie-business", {"data": {"rows": bad}})
        assert any("缺少行标签" in e for e in errors)
        assert any("数值必须是数字" in e for e in errors)
        # 仪表盘只允许 1 行
        two = [{"label": "A", "value": 1}, {"label": "B", "value": 2}]
        assert any("行数须在 1–1" in e for e in validate_config("gauge-business", {"data": {"rows": two}}))

    def test_xy_row_validation(self):
        """0070：xy 行结构（散点）逐行校验."""
        bad = [{"x": "a", "y": 1}, {"x": 2, "y": "b"}]
        errors = validate_config("scatter-trend", {"data": {"rows": bad}})
        assert any("第 1 行横轴值必须是数字" in e for e in errors)
        assert any("第 2 行纵轴值必须是数字" in e for e in errors)

    def test_standard_series_validation(self):
        """0070：标准系列模板沿用系列一致性 / 上下限规则."""
        rows = [
            {"label": "A", "values": [1, 2, 3]},
            {"label": "B", "values": [1, 2]},
        ]
        assert any("不一致" in e for e in validate_config("line-vivid", {"data": {"rows": rows}}))
        single = [{"label": "A", "values": [1]}, {"label": "B", "values": [2]}]
        assert validate_config("line-vivid", {"data": {"rows": single}}) == []
