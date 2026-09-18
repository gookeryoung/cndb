"""cndb - FastAPI + SQLAlchemy + Plugin 架构脚手架.

对外门面（facade），仅做 re-export，不承载业务实现。
使用者可直接：

    from cndb import AppFactory, PluginBase, Settings
    from cndb import app

依赖完整 re-export 清单见 __all__。

冷启动优化（GUI 场景，尤其 fspack/Nuitka 打包）：
- 历史上 ``import cndb`` 会在导入期 eager 构建整个 FastAPI app
  （``cndb.app`` → 加载 fastapi/sqlalchemy/alembic 与全部插件路由），
  GUI 入口 ``cndb.gui.main_window`` 因此每次启动都被拖慢约数秒。
- 现改为 PEP 562 惰性门面：``import cndb`` 只返回 O(0)。
  重符号（app/core/plugins/Settings/PluginBase/...）在**首次访问**时才
  import 对应子模块并缓存。GUI 启动只需 tkinter + 本包，接近瞬时。
- ``__version__`` 为纯常量，无需惰性。
"""

from __future__ import annotations

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
__version__ = "0.1.11"

# 惰性导出映射：公开符号 → 其所属子模块。
# 仅在访问 ``cndb.<符号>`` 时触发子模块加载，避免冷启动串起整个后端依赖图。
_LAZY_EXPORTS: dict[str, str] = {
    "app": "cndb.app",
    "core": "cndb.core",
    "plugins": "cndb.plugins",
    "Settings": "cndb.core.config",
    "PluginBase": "cndb.plugins.base",
    "AppItem": "cndb.plugins.base",
    "NavItem": "cndb.plugins.base",
}


def __getattr__(name: str):
    """PEP 562 惰性门面：按需 import 子模块并缓存已解析符号."""
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module 'cndb' has no attribute {name!r}")

    import importlib

    module = importlib.import_module(module_path)
    value = getattr(module, name)
    globals()[name] = value
    return value
