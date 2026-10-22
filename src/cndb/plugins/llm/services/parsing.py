"""OpenAI 兼容响应的解析helpers（自 ``datasource/providers/llm_prompt.py`` 迁入，ADR 0020 P0）.

行为与迁移前逐字一致：Markdown 围栏剥离、截断识别（``Unterminated string`` / 末尾
``Expecting``）、``{"rows": [...]}`` / 对象 / 数组三种行形态。数据源 provider 复用本模块，
错误由调用方转回 ``ProviderError``。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from cndb.plugins.llm.services.errors import LlmOutputInvalid

# 判断 JSON 解析失败是否更像「输出被 max_tokens 截断」而不是模型返回了别的东西：
# - ``Unterminated string``：字符串没有闭合，说明内容在字符串中途结束；
# - ``Expecting ...``：缺少分隔符 / 值，只有错误位置落在内容末尾附近才按截断处理，
#   模型输出中间语法错误（如漏逗号）仍保留原来的「不是合法 JSON」文案。
_TRUNCATION_MESSAGE_PREFIXES = ("Unterminated string", "Expecting")
_TRUNCATION_TAIL_TOLERANCE = 2


def strip_json_fences(content: str) -> str:
    """去掉模型常见的 ```json ... ``` 代码围栏."""
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def looks_truncated(exc: json.JSONDecodeError, content: str) -> bool:
    """JSON 解析错误是否更像「输出被 max_tokens 截断」."""
    if not exc.msg.startswith(_TRUNCATION_MESSAGE_PREFIXES):
        return False
    if exc.msg.startswith("Unterminated string"):
        return True
    return exc.pos >= max(0, len(content) - _TRUNCATION_TAIL_TOLERANCE)


def content_text(content: Any) -> str:
    """取 ``choices[0].message.content`` 文本（兼容分段 list 形态）."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts).strip()
    return ""


def error_message(error: Any) -> str:
    """取 ``error`` 字段的人类可读信息."""
    if isinstance(error, Mapping):
        return str(error.get("message") or error)
    return str(error)


def response_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    """从响应包提取模型名与 token 用量（失败时为空字段）."""
    metadata: dict[str, Any] = {"model": str(payload.get("model") or "")}
    usage = payload.get("usage")
    if isinstance(usage, Mapping):
        metadata["usage"] = {
            key: int(value)
            for key, value in usage.items()
            if key in ("prompt_tokens", "completion_tokens", "total_tokens") and isinstance(value, int)
        }
    return metadata


def parse_envelope(text: str) -> tuple[str, dict[str, Any]]:
    """解析 OpenAI 兼容响应包，返回 ``choices[0].message.content`` 与元数据.

    Returns:
        ``(content, metadata)``；``metadata`` 含 ``model`` / ``usage``.

    Raises:
        LlmOutputInvalid: 响应不是 JSON 对象 / 缺少 choices / content 为空 / 接口返回 error。
    """
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LlmOutputInvalid(f"模型响应不是合法 JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise LlmOutputInvalid("模型响应必须是 JSON 对象")
    if "choices" not in payload and payload.get("error"):
        raise LlmOutputInvalid(f"模型接口错误: {error_message(payload.get('error'))}")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlmOutputInvalid("模型响应缺少 choices")
    first: Mapping[str, Any] = choices[0] if isinstance(choices[0], Mapping) else {}
    raw_message = first.get("message")
    message: Mapping[str, Any] = raw_message if isinstance(raw_message, Mapping) else {}
    content = content_text(message.get("content"))
    if not content:
        raise LlmOutputInvalid("模型响应 content 为空")
    return content, response_metadata(payload)


def parse_content(text: str) -> Any:
    """把模型返回的 content 解析为 JSON 值（先剥围栏，再识别截断）."""
    text = strip_json_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        if looks_truncated(exc, text):
            from cndb.plugins.llm.services.prompts import DEFAULT_MAX_TOKENS

            raise LlmOutputInvalid(
                f"模型输出可能被截断：请提高 max_tokens（当前默认 {DEFAULT_MAX_TOKENS}）"
                f"或精简提示词输出（本次返回 {len(text)} 字符）；原始错误: {exc}"
            ) from exc
        raise LlmOutputInvalid(f"模型返回内容不是合法 JSON: {exc}") from exc


def rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    """把解析后的 JSON 值规范成行对象数组（对象 / 数组 / ``{"rows": [...]}``）."""
    if isinstance(payload, list):
        return [_as_row(item) for item in payload]
    if isinstance(payload, Mapping):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return [_as_row(item) for item in rows]
        return [dict(payload)]
    raise LlmOutputInvalid("模型返回的 JSON 必须是对象或对象数组")


def parse_chat_response(text: str, metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """完整响应包 → 数据行数组（数据源 ``llm_prompt`` 的解析入口）."""
    content, meta = parse_envelope(text)
    if metadata is not None:
        metadata.update(meta)
    return rows_from_payload(parse_content(content))


def _as_row(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise LlmOutputInvalid("模型返回的数组元素必须是对象")
    return dict(item)


__all__ = [
    "content_text",
    "error_message",
    "looks_truncated",
    "parse_chat_response",
    "parse_content",
    "parse_envelope",
    "response_metadata",
    "rows_from_payload",
    "strip_json_fences",
]
