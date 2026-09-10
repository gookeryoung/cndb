"""pyweb_template - FastAPI + SQLAlchemy + Plugin 架构脚手架.

对外门面（facade），仅做 re-export，不承载业务实现。
使用者可直接：

    from pyweb_template import AppFactory, PluginBase, Settings

依赖完整 re-export 清单见 __all__。
"""

from __future__ import annotations

from pyweb_template import core, plugins
from pyweb_template.app import app as _fastapi_app
from pyweb_template.core.config import Settings
from pyweb_template.plugins.base import AppItem, NavItem, PluginBase

__all__ = [
    "AppItem",
    "NavItem",
    "PluginBase",
    "Settings",
    "__version__",
    "app",
    "core",
    "plugins",
]


# 版本号：与 pyproject.toml 保持同步（由 bump-my-version 自动维护）
__version__ = "0.1.2"

# 给调用者一个便捷入口：from pyweb_template import app
app = _fastapi_app
