"""插件注册中心 - 自动发现、加载和管理插件.

插件目录约定：pyweb_template/plugins/<name>/plugin.py 中定义 PluginBase 子类。
PluginRegistry.discover_and_load() 会扫描 plugins 包的每个子包，
导入其 plugin.py 模块并注册发现到的插件实例。
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI

from pyweb_template.core.config import settings
from pyweb_template.plugins.base import NavItem, PluginBase

logger = logging.getLogger(__name__)


class PluginRegistry:
    """插件注册中心.

    生命周期：
    1. discover_and_load() — 扫描 plugins 包，发现并实例化所有插件
    2. mount_routes(app)   — 将每个插件的 router 挂到 FastAPI app 上（幂等）
    3. get_all_navigation() / get_all_apps() — 供前端动态构建菜单

    幂等机制：mount_routes 内部用 _mounted_app_ids 追踪已挂载过的 app，
    避免 TestClient 多次触发 lifespan 或测试重复调用导致路由累积。
    """

    def __init__(self) -> None:
        self._plugins: dict[str, PluginBase] = {}
        self._mounted_app_ids: set[int] = set()

    # ── 注册 ─────────────────────────────────────────────

    def register(self, plugin: PluginBase) -> None:
        """注册一个插件实例.

        重复注册同名插件会被跳过（不覆盖），便于开发时热插拔重试。
        """
        if plugin.name in self._plugins:
            logger.warning("插件 %s 已存在，跳过重复注册", plugin.name)
            return
        self._plugins[plugin.name] = plugin
        plugin.register_models()
        logger.info("插件已注册: %s v%s", plugin.name, plugin.version)

    def discover_and_load(self) -> None:
        """自动发现并加载 plugins 包下的所有插件.

        扫描规则：
        - 跳过以 "_" 开头的子包（私有/测试包）
        - 导入 `<package>.plugins.<name>.plugin` 模块
        - 查找其中的 PluginBase 非抽象子类并实例化
        """
        plugins_dir = Path(__file__).resolve().parent.parent / "plugins"

        if not plugins_dir.is_dir():
            logger.debug("plugins 目录不存在，跳过插件发现: %s", plugins_dir)
            return

        for item in sorted(plugins_dir.iterdir()):
            if not item.is_dir() or item.name.startswith("_"):
                continue

            plugin_module_path = f"pyweb_template.plugins.{item.name}"
            try:
                module = importlib.import_module(f"{plugin_module_path}.plugin")
            except ImportError as exc:
                logger.debug("跳过 %s: %s", item.name, exc)
                continue
            except Exception as exc:
                logger.error("加载插件 %s 失败: %s", item.name, exc)
                continue

            # 查找 PluginBase 非抽象子类
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, PluginBase) and attr is not PluginBase:
                    self.register(attr())
                    break

    # ── 路由挂载 ──────────────────────────────────────────

    def mount_routes(self, app: FastAPI) -> None:
        """挂载所有插件路由（在插件加载后调用，幂等）.

        幂等：同一 app 实例只挂一次，多次调用不累积路由。
        """
        app_id = id(app)
        if app_id in self._mounted_app_ids:
            logger.debug("app 已挂载过插件路由，跳过: id=%s", app_id)
            return

        for name, plugin in self._plugins.items():
            router = APIRouter()
            plugin.register_routes(router)
            prefix = f"{settings.API_V1_PREFIX}/{name}"
            app.include_router(router, prefix=prefix, tags=[plugin.name])
            logger.info("插件路由已挂载: %s -> %s", name, prefix)

        self._mounted_app_ids.add(app_id)

    def get_plugin_info_list(self) -> list[dict[str, str]]:
        """获取所有已注册插件的元信息."""
        return [p.get_info() for p in self._plugins.values()]

    def get_plugin(self, name: str) -> PluginBase | None:
        """按名称获取插件实例（调试/手动调用插件方法用）."""
        return self._plugins.get(name)

    def get_all_navigation(self) -> list[dict[str, Any]]:
        """汇总所有插件返回的侧边栏导航项."""
        result: list[dict[str, Any]] = []
        for plugin in self._plugins.values():
            for item in plugin.register_navigation():
                if isinstance(item, NavItem):
                    result.append(item.to_dict())
        return result

    def get_all_apps(self) -> list[dict[str, Any]]:
        """汇总所有插件返回的 APP 入口（通过应用中心访问）."""
        result: list[dict[str, Any]] = []
        for plugin in self._plugins.values():
            for item in plugin.register_apps():
                result.append(item.to_dict())
        return result

    def __len__(self) -> int:  # pragma: no cover - 简单代理
        return len(self._plugins)


# 全局单例（应用生命周期内唯一）
plugin_registry = PluginRegistry()
