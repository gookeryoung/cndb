"""plugins.base 测试."""

from __future__ import annotations

from typing import override

import pytest
from fastapi import APIRouter

from pyweb_template.plugins.base import AppItem, NavItem, PluginBase


def test_navitem_to_dict_basic() -> None:
    item = NavItem(key="k", label="L", icon="i", path="/p")
    d = item.to_dict()
    assert d["key"] == "k"
    assert d["label"] == "L"
    assert d["icon"] == "i"
    assert d["path"] == "/p"
    assert "children" not in d


def test_navitem_to_dict_with_children() -> None:
    child = NavItem(key="c", label="C")
    parent = NavItem(key="p", label="P", children=[child])
    d = parent.to_dict()
    assert len(d["children"]) == 1
    assert d["children"][0]["key"] == "c"


def test_appitem_to_dict_defaults() -> None:
    item = AppItem(key="k", label="L")
    d = item.to_dict()
    assert d["key"] == "k"
    assert d["category"] == "tool"
    assert d["icon"] == "AppstoreOutlined"


def test_pluginbase_is_abstract() -> None:
    """PluginBase 直接实例化应抛 TypeError."""
    with pytest.raises(TypeError):
        PluginBase()  # type: ignore[misc]


def test_pluginbase_get_info_defaults() -> None:
    """get_info 应返回类属性."""

    class Concrete(PluginBase):
        name = "test"
        version = "1.0"
        description = "desc"

        @override
        def register_routes(self, router: APIRouter) -> None:
            pass

    info = Concrete().get_info()
    assert info["name"] == "test"
    assert info["version"] == "1.0"
    assert info["description"] == "desc"
