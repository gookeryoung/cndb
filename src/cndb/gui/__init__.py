"""cndb GUI 包入口.

本包为纯 facade，不 eager import main_window（避免 runpy.run_module
在加载 ``cndb.gui.main_window`` 时触发 RuntimeWarning：模块已在
``sys.modules`` 中但尚未被 runpy 执行）。

入口配置见 pyproject.toml：
    cndbw = "cndb.gui.main_window:main"
"""

from __future__ import annotations

__all__ = ["main"]


def __getattr__(name: str):
    """模块级延迟加载：仅在访问 ``main`` 时才 import main_window."""
    if name == "main":
        from cndb.gui.main_window import main

        return main
    raise AttributeError(f"module 'cndb.gui' has no attribute {name!r}")
