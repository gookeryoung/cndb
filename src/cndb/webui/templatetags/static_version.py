"""带版本号的静态资源标签：按文件 mtime 附加 v 参数，静态文件更新即自动破浏览器缓存."""

from __future__ import annotations

from pathlib import Path

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static as django_static

register = template.Library()


@register.simple_tag
def static_v(path: str) -> str:
    """返回静态资源 URL 并附加 ?v=<mtime>，经 staticfiles finder 定位源文件，找不到则原样返回."""
    url = django_static(path)  # type: ignore[bad-assignment]
    found = finders.find(path)
    if not found:
        return str(url)
    try:
        version = int(Path(found).stat().st_mtime)  # type: ignore[bad-argument-type]
    except OSError:
        return str(url)
    return f"{url}?v={version}"
