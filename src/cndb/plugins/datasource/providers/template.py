"""请求模板求值 —— 只做字面占位符替换，不求值任何表达式.

语法：
- ``{name}``   占位符，由 variables 取值后 ``str()`` 注入；缺失即报错（不静默留空）
- ``{{`` / ``}}``  转义为字面量花括号（API 里常见于 JSON body 模板）

安全口径（ADR 0006「风险与缓解」）：模板不引入求值器，占位符只做字面替换，
URL 的合法性最终仍由 ``api_fetch.validate_url`` 的 SSRF 防护把关。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cndb.plugins.datasource.providers.base import ProviderError


def render_text(text: str, variables: Mapping[str, Any]) -> str:
    """把 ``{name}`` 占位符替换为 variables 中的值.

    Raises:
        ProviderError: 占位符未闭合、出现未转义的 ``}`` 或变量缺失.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "{":
            if text.startswith("{{", index):
                out.append("{")
                index += 2
                continue
            close = text.find("}", index + 1)
            if close < 0:
                raise ProviderError(f"模板占位符未闭合: {text[index : index + 40]!r}")
            name = text[index + 1 : close].strip()
            if not name:
                raise ProviderError(f"模板出现空占位符: {text[index : index + 40]!r}")
            if name not in variables:
                raise ProviderError(f"模板变量缺失: {{{name}}}（可用: {sorted(variables)}）")
            out.append(_as_text(variables[name]))
            index = close + 1
            continue
        if char == "}":
            if text.startswith("}}", index):
                out.append("}")
                index += 2
                continue
            raise ProviderError(f"模板出现未转义的 '}}': {text[index : index + 40]!r}")
        out.append(char)
        index += 1
    return "".join(out)


def render_value(value: Any, variables: Mapping[str, Any]) -> Any:
    """递归求值 dict / list / tuple / str；其它标量原样返回."""
    if isinstance(value, str):
        return render_text(value, variables)
    if isinstance(value, Mapping):
        return {str(key): render_value(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [render_value(item, variables) for item in value]
    if isinstance(value, tuple):
        return tuple(render_value(item, variables) for item in value)
    return value


def _as_text(value: Any) -> str:
    """占位符取值转文本：None 视为空串（而非 "None"，避免把空参写进 URL）."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


__all__ = ["render_text", "render_value"]
