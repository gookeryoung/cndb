"""检查动作注册表（ADR 0076 D4）.

- 动作名 ``域/动作``（如 ``table/null-rate``），DSL ``uses:`` 直接引用；
- 每个动作声明输入 schema（``CheckInput``）与默认严重度；
- 目录端点与 DSL 保存期校验都从这里取唯一真相源；
- 内置动作在 :func:`load_builtins` 中惰性导入注册（新格式扩展只需新增模块并在此导入）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from cndb.plugins.pipeline.services.checks.base import (
    INPUT_BOOLEAN,
    INPUT_INTEGER,
    INPUT_NUMBER,
    INPUT_STRING,
    INPUT_STRING_LIST,
    CheckContext,
    CheckSpec,
    FindingDraft,
)
from cndb.plugins.pipeline.services.errors import CheckError

CheckRunner = Callable[[CheckContext, dict[str, Any]], Iterable[FindingDraft]]

_REGISTRY: dict[str, tuple[CheckSpec, CheckRunner]] = {}
_STATE = {"loaded": False}


def register_check(spec: CheckSpec, runner: CheckRunner) -> None:
    """登记一个检查动作（重复登记同名动作会被拒绝，便于插件化排障）."""
    if spec.uses in _REGISTRY:
        raise CheckError(f"检查动作重复登记：{spec.uses}")
    _REGISTRY[spec.uses] = (spec, runner)


def load_builtins() -> None:
    """惰性导入内置检查动作（导入即注册）."""
    if _STATE["loaded"]:
        return
    _STATE["loaded"] = True
    from cndb.plugins.pipeline.services.checks.document import (  # noqa: F401 - 导入即注册
        broken_refs,
        chart_blocks,
        links,
    )
    from cndb.plugins.pipeline.services.checks.table import (  # noqa: F401 - 导入即注册
        duplicates,
        null_rate,
        stale,
        value_range,
    )


def get_check(uses: str) -> tuple[CheckSpec, CheckRunner] | None:
    """按动作名查找（不存在返回 None）."""
    load_builtins()
    return _REGISTRY.get(uses)


def require_check(uses: str) -> tuple[CheckSpec, CheckRunner]:
    """按动作名查找，不存在抛 ``CheckError``（编译期错误信息含可用动作）."""
    found = get_check(uses)
    if found is None:
        raise CheckError(f"未知检查动作：{uses}（可用：{', '.join(iter_check_names())}）")
    return found


def iter_check_names() -> list[str]:
    """全部已注册动作名（按字典序）."""
    load_builtins()
    return sorted(_REGISTRY)


def iter_check_specs() -> list[CheckSpec]:
    """全部动作声明（目录端点 / 前端插入辅助用）."""
    load_builtins()
    return [_REGISTRY[name][0] for name in sorted(_REGISTRY)]


def validate_static_params(spec: CheckSpec, params: dict[str, Any]) -> dict[str, Any]:
    """保存期校验 ``with:`` 参数：未知键 / 缺失必填 / 静态值类型.

    ``${{ ... }}`` 表达式值跳过静态类型校验（运行期求值后再强制转换）。

    Raises:
        CheckError: 参数不合法。
    """
    known = {item.name for item in spec.inputs}
    unknown = sorted(set(params) - known)
    if unknown:
        raise CheckError(f"{spec.uses} 不支持参数：{', '.join(unknown)}")
    for item in spec.inputs:
        if item.required and item.name not in params:
            raise CheckError(f"{spec.uses} 缺少必填参数：{item.name}")
        if item.name in params:
            _validate_static(item.type, params[item.name], spec.uses, item.name)
    return params


def _validate_static(input_type: str, value: Any, uses: str, name: str) -> None:
    # 延迟导入：``dsl`` 包门面会导入 parse，而 parse 又依赖本注册表，模块级导入会成环
    from cndb.plugins.pipeline.services.dsl.expressions import is_expression

    if is_expression(value):
        return
    if input_type == INPUT_STRING:
        ok = isinstance(value, str)
    elif input_type == INPUT_INTEGER:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif input_type == INPUT_NUMBER:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif input_type == INPUT_BOOLEAN:
        ok = isinstance(value, bool)
    elif input_type == INPUT_STRING_LIST:
        ok = isinstance(value, str) or (isinstance(value, list) and all(isinstance(v, str) for v in value))
    else:  # pragma: no cover - 注册表只会登记白名单类型
        ok = False
    if not ok:
        raise CheckError(f"{uses} 参数 {name} 类型不匹配（期望 {input_type}）")


def coerce_params(spec: CheckSpec, params: dict[str, Any]) -> dict[str, Any]:
    """运行期把参数归一为目标类型并补默认值（表达式已在调用前求值）."""
    coerced: dict[str, Any] = {}
    for item in spec.inputs:
        if item.name in params:
            coerced[item.name] = _coerce(item.type, params[item.name], spec.uses, item.name)
        elif item.default is not None:
            coerced[item.name] = item.default
    return coerced


def _coerce(input_type: str, value: Any, uses: str, name: str) -> Any:
    if input_type == INPUT_STRING_LIST:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            return list(value)
        raise CheckError(f"{uses} 参数 {name} 不是字符串列表")
    if input_type == INPUT_STRING:
        if isinstance(value, str):
            return value
        raise CheckError(f"{uses} 参数 {name} 不是字符串")
    if input_type == INPUT_INTEGER:
        if isinstance(value, bool):
            raise CheckError(f"{uses} 参数 {name} 不是整数")
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise CheckError(f"{uses} 参数 {name} 不是整数")
    if input_type == INPUT_NUMBER:
        if isinstance(value, bool):
            raise CheckError(f"{uses} 参数 {name} 不是数值")
        if isinstance(value, (int, float)):
            return float(value)
        raise CheckError(f"{uses} 参数 {name} 不是数值")
    if input_type == INPUT_BOOLEAN:
        if isinstance(value, bool):
            return value
        raise CheckError(f"{uses} 参数 {name} 不是布尔值")
    raise CheckError(f"{uses} 参数 {name} 类型未知: {input_type}")  # pragma: no cover


__all__ = [
    "CheckRunner",
    "coerce_params",
    "get_check",
    "iter_check_names",
    "iter_check_specs",
    "load_builtins",
    "register_check",
    "require_check",
    "validate_static_params",
]
