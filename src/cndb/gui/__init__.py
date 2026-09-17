"""cndb GUI 入口（cndbw）.

标准库 tkinter 实现，提供 CLI 全部功能的图形化界面：
serve / backup / restore / users / seed / info。

入口：
    cndbw = "cndb.gui:main"
"""

from __future__ import annotations

from cndb.gui.main_window import main

__all__ = ["main"]
