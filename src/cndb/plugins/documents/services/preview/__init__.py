"""原件族在线预览（ADR 0087）：Office（xlsx / docx）原件 → 自包含 HTML.

MHTML 预览仍由 ``importers.mhtml.build_preview_html`` 承担（需求 0064），本包只覆盖 Office；
路由按 ``content_type`` 在两者间分派。
"""

from __future__ import annotations

from .office import (
    LEGACY_MIMES,
    MAX_HTML_CHARS,
    UnsupportedPreview,
    build_document_html,
    build_office_preview,
    build_spreadsheet_html,
)

__all__ = [
    "LEGACY_MIMES",
    "MAX_HTML_CHARS",
    "UnsupportedPreview",
    "build_document_html",
    "build_office_preview",
    "build_spreadsheet_html",
]
