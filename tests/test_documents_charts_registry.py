"""图表模板注册表（ADR 0048）单测.

覆盖：两级注册表结构、指纹、normalize_config 宽松归一（I6：缺键回默认 /
坏值回退 / 未知键忽略 / 永不抛错）、validate_config 严格校验（结构错误列表）、
require_valid_config（400 入口，成功返回归一 config）。
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


class TestRegistry:
    def test_two_level_structure(self):
        """一级 × 二级分类与模板：模板类别键都指向已登记的二级分类."""
        assert {c.key for c in CHART_CATEGORIES} == {
            "composition",
            "comparison",
            "comparison-bar",
            "comparison-bar-h",
        }
        assert set(CHART_TEMPLATES) == set(TPL_KEYS)
        for key in TPL_KEYS:
            tpl = CHART_TEMPLATES[key]
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
        assert fp == "bar-line-dual-axis@9+r1"
        # 未知模板给占位指纹（实例仍可 ETag 缓存降级图）
        assert template_fingerprint("gone") == "gone@0+r1"

    def test_templates_payload_shape(self):
        payload = templates_payload()
        # 一级分类层级化（ADR 0058）：composition 无模板不输出，comparison 含两个二级 children
        cats = payload["categories"]
        assert [c["key"] for c in cats] == ["comparison"]
        children = cats[0]["children"]
        assert [(c["key"], c["name"], c["parent"]) for c in children] == [
            ("comparison-bar", "对比-柱形", "comparison"),
            ("comparison-bar-h", "对比-条形", "comparison"),
        ]
        assert {t["key"] for t in payload["templates"]} == set(TPL_KEYS)
        tpl = next(t for t in payload["templates"] if t["key"] == "bar-line-dual-axis")
        assert tpl["name"] == "双轴柱线组合图"
        assert tpl["category"] == "comparison-bar"
        assert tpl["row_min"] == 2 and tpl["row_max"] == 24
        assert tpl["default_config"]["data"]["rows"]  # 清单带默认配置供设计器起稿


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
