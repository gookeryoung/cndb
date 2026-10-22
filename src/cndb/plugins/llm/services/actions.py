"""AI 动作注册表（ADR 0020 P0）.

领域插件在自己的 ``services/ai.py`` 模块 import 时调用 :func:`register` 注册原子 AI 能力；
平台**不反向 import** 任何领域插件。注册表只用于「能力目录」（前端据此显隐入口）与
领域路由查找 ``ActionSpec``，**不提供通用执行端点** —— 领域数据的权限校验与输入裁剪
必须留在领域路由（ADR 0020 D5/D6）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from cndb.plugins.llm.services.prompts import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
)


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """一个原子 AI 能力的声明.

    Attributes:
        name: 动作名（``域.动作``，如 ``document.polish``）。
        label: 前端展示名。
        scope: 归属范围（document / table / import / analytics / personal）。
        output_schema: 结构化动作的 Pydantic 输出模型；``None`` 表示自由文本。
        system_prompt: 动作级系统提示词（空 = 平台内置默认）。
        max_tokens / temperature / json_mode: 模型参数。
        max_input_chars: 单次输入上限，超限直接拒绝（不做自动长文分片）。
    """

    name: str
    label: str
    scope: str = "personal"
    output_schema: type[BaseModel] | None = None
    system_prompt: str = ""
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    json_mode: bool = False
    max_input_chars: int = 12000


_REGISTRY: dict[str, ActionSpec] = {}


def register(spec: ActionSpec) -> ActionSpec:
    """注册动作（同 id 覆盖，便于测试 / 热重载幂等）."""
    _REGISTRY[spec.name] = spec
    return spec


def get(name: str) -> ActionSpec | None:
    """按名称取动作（不存在返回 ``None``，由领域路由决定 404 语义）."""
    return _REGISTRY.get(name)


def list_actions() -> list[ActionSpec]:
    """已注册动作（按名称排序，目录稳定）."""
    return [_REGISTRY[name] for name in sorted(_REGISTRY)]


def catalog() -> list[dict[str, Any]]:
    """能力目录（只读元数据，供前端显隐入口）."""
    return [{"name": spec.name, "label": spec.label, "scope": spec.scope} for spec in list_actions()]


def reset_registry() -> None:
    """清空注册表（测试用）."""
    _REGISTRY.clear()


__all__ = [
    "ActionSpec",
    "catalog",
    "get",
    "list_actions",
    "register",
    "reset_registry",
]
