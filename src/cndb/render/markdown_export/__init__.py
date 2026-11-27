"""Markdown → 文件渲染器注册表（ADR 0188 D10）.

**为什么是注册表而不是直接 import**：

docx / pdf 渲染实现依赖 `charts`（图表内联）与 `table_refs`（`{{table:…}}` 数据表引用）
这两个**文档插件**的领域能力。把渲染代码物理搬到 `cndb/render/` 会把领域依赖一起带走，
或迫使渲染器拆成「有图表」与「无图表」两份。反过来让 `tables` 直接 import
`documents.services.export` 又违反插件方向（ADR 0130 / H69）。

注册表解掉这个死结：

- `documents` 插件在 `register_routes` 期调用 :func:`register_renderer` 注册实现；
- 任何插件（如 `tables` 的数据字典导出）调用 :func:`render_markdown` 即可，
  不需要知道实现来自哪个插件；
- 未注册时**显式报错**（`RenderUnavailableError`），不做静默降级成 md —— 用户点
  「导出 Word」却拿到 Markdown 是最糟的失败方式。

口径：

- 渲染器签名固定 ``(markdown, fmt, *, title, template) -> bytes``，与 ADR 0152 的
  导出模板 ref 对齐；
- 注册是幂等的（同名覆盖），测试可重复注册 / 清理。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)

#: 渲染器签名：(markdown_text, fmt, title, template) → 文件字节串
Renderer = Callable[..., bytes]


class RenderUnavailableError(RuntimeError):
    """目标格式没有可用渲染器（实现插件未启用 / 未注册）."""


class SupportsRender(Protocol):
    """渲染器协议（仅用于类型标注）."""

    def __call__(self, markdown_text: str, fmt: str, *, title: str = "", template: str | None = None) -> bytes: ...


_registry: dict[str, Renderer] = {}


def register_renderer(fmt: str, renderer: Renderer) -> None:
    """注册某格式的渲染器（幂等：同名覆盖）."""
    if not fmt:
        raise ValueError("register_renderer 需要非空格式名")
    _registry[fmt.lower()] = renderer
    logger.debug("已注册 markdown 渲染器: %s", fmt)


def unregister_renderer(fmt: str) -> None:
    """移除某格式的渲染器（供测试清理 / 插件卸载）."""
    _registry.pop(fmt.lower(), None)


def available_formats() -> tuple[str, ...]:
    """已注册的格式清单（排序后返回，便于文档 / 报错文案稳定）."""
    return tuple(sorted(_registry))


def is_available(fmt: str) -> bool:
    """某格式当前是否可用."""
    return fmt.lower() in _registry


def render_markdown(
    markdown_text: str,
    fmt: str,
    *,
    title: str = "",
    template: str | None = None,
) -> bytes:
    """把 Markdown 渲染为指定格式的文件字节串.

    Raises:
        RenderUnavailableError: 该格式没有注册渲染器.
    """
    renderer = _registry.get((fmt or "").lower())
    if renderer is None:
        raise RenderUnavailableError(f"没有可用的 {fmt} 渲染器（已注册: {', '.join(available_formats()) or '无'}）")
    return renderer(markdown_text, fmt, title=title, template=template)


__all__ = [
    "RenderUnavailableError",
    "Renderer",
    "SupportsRender",
    "available_formats",
    "is_available",
    "register_renderer",
    "render_markdown",
    "unregister_renderer",
]
