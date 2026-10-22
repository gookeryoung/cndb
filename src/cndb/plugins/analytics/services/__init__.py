"""analytics 插件服务层：公式校验、求值、描述统计、模板持久化、智能推荐."""

from __future__ import annotations

from cndb.plugins.analytics.services import ai, compute, formula, recommend, templates

__all__ = ["ai", "compute", "formula", "recommend", "templates"]
