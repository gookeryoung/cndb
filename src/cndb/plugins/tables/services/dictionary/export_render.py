"""数据字典的 docx / pdf 渲染入口（ADR 0188 D10）.

本模块只做一件事：把「Markdown → 文件」的能力从注册表取出来用。
渲染实现由 `documents` 插件注册（它拥有 docx / pdf 与图表内联、数据表引用能力），
`tables` 插件不 import `documents`，因此插件方向保持单向（H69）。

未注册时抛 503 并给出可操作文案：数据字典的 md / xlsx / json 三种格式不依赖
该渲染器，用户仍可导出；只是 Word / PDF 需要启用文档模块。
"""

from __future__ import annotations

from fastapi import HTTPException

from cndb.render.markdown_export import (
    RenderUnavailableError,
    available_formats,
)
from cndb.render.markdown_export import (
    render_markdown as _render_registered,
)


def render_office(markdown_text: str, fmt: str, *, title: str = "", template: str | None = None) -> bytes:
    """把字典 Markdown 渲染为 docx / pdf.

    Raises:
        HTTPException: 503（渲染器未注册）。用 503 而非 500 —— 这是「能力暂时不可用」
            而不是程序错误，前端可据此提示「请改用 Markdown / Excel 导出」。
    """
    try:
        return _render_registered(markdown_text, fmt, title=title, template=template)
    except RenderUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"当前实例没有 {fmt} 渲染能力（已注册: {', '.join(available_formats()) or '无'}）；"
                "请改用 md / xlsx / json 格式导出，或启用文档模块后重试"
            ),
        ) from exc


__all__ = ["render_office"]
