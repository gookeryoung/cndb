"""core.plugin_registry 测试."""

from __future__ import annotations

from pathlib import Path
from typing import override
from unittest.mock import patch

from fastapi import APIRouter, FastAPI

from pyweb_template.core.plugin_registry import PluginRegistry
from pyweb_template.plugins.base import AppItem, NavItem, PluginBase


def test_empty_registry() -> None:
    """初始状态应无插件."""
    r = PluginRegistry()
    assert len(r) == 0
    assert r.get_plugin_info_list() == []
    assert r.get_all_navigation() == []
    assert r.get_all_apps() == []


def test_register_and_get() -> None:
    """注册后应能通过 name 获取."""

    class FakePlugin(PluginBase):
        name = "fake"
        description = "test"

        @override
        def register_routes(self, router: APIRouter) -> None:
            pass

    r = PluginRegistry()
    r.register(FakePlugin())
    assert r.get_plugin("fake") is not None
    assert len(r) == 1
    info = r.get_plugin_info_list()[0]
    assert info["name"] == "fake"
    assert info["description"] == "test"


def test_duplicate_register_skipped() -> None:
    """同名插件重复注册应被跳过."""

    class FakePlugin(PluginBase):
        name = "dup"

        @override
        def register_routes(self, router: APIRouter) -> None:
            pass

    r = PluginRegistry()
    r.register(FakePlugin())
    r.register(FakePlugin())  # 同名
    assert len(r) == 1


def test_discover_loads_builtin_plugins() -> None:
    """discover_and_load 应能找到 health."""
    from pyweb_template.core.plugin_registry import PluginRegistry as _PR

    r = _PR()
    r.discover_and_load()
    names = {p["name"] for p in r.get_plugin_info_list()}
    assert "health" in names
    assert r.get_all_apps() == []


def test_discover_plugins_dir_not_exists_returns_early(tmp_path: Path) -> None:
    """plugins 目录不存在时 discover_and_load 应安全返回."""
    r = PluginRegistry()
    target = tmp_path / "nonexistent"
    real_path = Path(__file__).resolve()

    def fake_truediv(other: object) -> Path:
        if str(other) == "plugins":
            return target
        return real_path / other  # type: ignore[operator]

    with patch("pyweb_template.core.plugin_registry.Path") as MockPath:
        MockPath.return_value = real_path
        with patch.object(Path, "__truediv__", side_effect=fake_truediv):
            r.discover_and_load()
    assert len(r) == 0


def test_mount_routes_is_idempotent() -> None:
    """mount_routes 应幂等，不重复挂载."""

    class FakePlugin(PluginBase):
        name = "idempotent-test"

        @override
        def register_routes(self, router: APIRouter) -> None:
            @router.get("/ping")
            def ping() -> str:
                return "ok"

    r = PluginRegistry()
    r.register(FakePlugin())

    app = FastAPI()
    r.mount_routes(app)
    n_first = len(app.routes)
    r.mount_routes(app)  # 再调一次
    n_second = len(app.routes)
    assert n_first == n_second


def test_get_all_navigation_collects() -> None:
    """应能从插件收集导航项."""

    class NavPlugin(PluginBase):
        name = "nav-test"

        @override
        def register_routes(self, router: APIRouter) -> None:
            pass

        @override
        def register_navigation(self) -> list[NavItem]:
            return [NavItem(key="a", label="A", path="/a")]

    r = PluginRegistry()
    r.register(NavPlugin())
    nav = r.get_all_navigation()
    assert len(nav) == 1
    assert nav[0]["key"] == "a"
    assert nav[0]["path"] == "/a"


def test_get_all_apps_collects() -> None:
    """应能从插件收集 APP 入口."""

    class AppPlugin(PluginBase):
        name = "app-test"

        @override
        def register_routes(self, router: APIRouter) -> None:
            pass

        @override
        def register_apps(self) -> list[AppItem]:
            return [AppItem(key="x", label="X", path="/x")]

    r = PluginRegistry()
    r.register(AppPlugin())
    apps = r.get_all_apps()
    assert len(apps) == 1
    assert apps[0]["key"] == "x"


def test_get_all_navigation_skips_non_navitem() -> None:
    """register_navigation 返回非 NavItem 实例应被跳过."""

    class BadNavPlugin(PluginBase):
        name = "bad-nav-test"

        @override
        def register_routes(self, router: APIRouter) -> None:
            pass

        @override
        def register_navigation(self) -> list[NavItem]:  # type: ignore[override]
            return ["not-a-navitem"]  # type: ignore[return-value]

    r = PluginRegistry()
    r.register(BadNavPlugin())
    assert r.get_all_navigation() == []


def test_get_all_apps_no_items_returns_empty() -> None:
    """没有插件注册 app 时应返回空列表."""
    r = PluginRegistry()
    assert r.get_all_apps() == []


def test_discover_handles_import_error_gracefully(tmp_path: Path) -> None:
    """某个插件的 plugin.py 导入失败应被跳过."""
    import importlib

    r = PluginRegistry()

    # 创建一个临时插件目录结构
    plugin_dir = tmp_path / "broken_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text("")
    (plugin_dir / "plugin.py").write_text("raise ImportError('broken')")

    with patch("pyweb_template.core.plugin_registry.Path") as MockPath:
        # Mock Path(__file__).resolve().parent.parent → 指向 tmp_path
        MockPath.return_value = tmp_path
        with patch.object(importlib, "import_module", side_effect=ImportError("broken")):
            r.discover_and_load()

    assert len(r) == 0
