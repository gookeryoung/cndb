"""插件包.

插件架构允许业务模块以"即插即用"方式扩展：
1. 在 pyweb_template/plugins/<name>/ 下创建 plugin.py
2. 继承 PluginBase，实现 register_routes() 抽象方法
3. 可选覆写 register_models() / register_navigation() / register_apps()
4. PluginRegistry.discover_and_load() 启动时自动发现并挂载
"""

from __future__ import annotations

from pyweb_template.plugins.base import AppItem, NavItem, PluginBase

__all__ = ["AppItem", "NavItem", "PluginBase"]
