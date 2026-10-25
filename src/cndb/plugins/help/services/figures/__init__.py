"""帮助图示子包（ADR 0030）.

对外只暴露四件事：清单（`FIGURE_SPECS`）、构建器、快照仓库、后台刷新线程。
"""

from __future__ import annotations

from cndb.plugins.help.services.figures.registry import FIGURE_SPECS, FigureSpec, find_spec
from cndb.plugins.help.services.figures.store import (
    FigureRefresher,
    FigureStore,
    RenderedFigure,
    get_figure_refresher,
    get_figure_store,
    start_figure_refresher,
    stop_figure_refresher,
)

__all__ = [
    "FIGURE_SPECS",
    "FigureRefresher",
    "FigureSpec",
    "FigureStore",
    "RenderedFigure",
    "find_spec",
    "get_figure_refresher",
    "get_figure_store",
    "start_figure_refresher",
    "stop_figure_refresher",
]
