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
    INPUT_JSON,
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

# 动作域前缀 → 工作区模块名（ADR 0080 D4：目录按模块过滤、保存期拒绝禁用域）
_DOMAIN_BY_PREFIX: dict[str, str] = {
    "table": "tables",
    "document": "documents",
    "design": "design",
}

#: 合法检查域短名（与 ``uses:`` 前缀一致，供 ``domain`` 查询参数校验）
CHECK_DOMAINS: tuple[str, ...] = tuple(_DOMAIN_BY_PREFIX)


def domain_of(uses: str) -> str:
    """检查动作名 → 所属工作区模块（``table/null-rate`` → ``tables``）.

    Raises:
        CheckError: 域前缀不在映射表（未注册的动先经编译期报错）。
    """
    domain = _DOMAIN_BY_PREFIX.get(uses.split("/", 1)[0])
    if domain is None:
        raise CheckError(f"未知检查动作域：{uses}")
    return domain


def prefix_of(uses: str) -> str:
    """检查动作名 → 域短名（``table/null-rate`` → ``table``）."""
    return uses.split("/", 1)[0]


def module_of_domain(domain: str) -> str | None:
    """域短名 → 所属工作区模块（未知域返回 None）."""
    return _DOMAIN_BY_PREFIX.get(domain)


def workflow_domains(compiled: dict[str, Any] | None) -> set[str]:
    """从编译产物提取流水线涉及的动作域集合（跨域编排返回多个）.

    ``compiled`` 来自 DSL 编译快照，结构异常（历史脏数据）时跳过该条目。
    """
    domains: set[str] = set()
    if not compiled:
        return domains
    for job in compiled.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if isinstance(uses, str) and "/" in uses:
                domains.add(prefix_of(uses))
    return domains


def assert_steps_in_enabled_modules(ir: Any, modules: list[str]) -> None:
    """保存 / 校验期断言：IR 中所有步骤的动作域均已启用（ADR 0080 C4）.

    Raises:
        CheckError: 存在属于未启用模块的动作。
    """
    enabled = set(modules)
    for job in ir.jobs:
        for step in job.steps:
            domain = domain_of(step.uses)
            if domain not in enabled:
                raise CheckError(f"检查动作 {step.uses} 属于未启用的功能模块（{domain}），无法保存")


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
        sensitive,
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
    elif input_type == INPUT_JSON:
        ok = _is_json_value(value)
    else:  # pragma: no cover - 注册表只会登记白名单类型
        ok = False
    if not ok:
        raise CheckError(f"{uses} 参数 {name} 类型不匹配（期望 {input_type}）")


def _is_json_value(value: Any) -> bool:
    """值能否原样写进 ``compiled`` JSON 列（拒绝 YAML 日期等非 JSON 类型）."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False


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
    if input_type == INPUT_JSON:
        if _is_json_value(value):
            return value
        raise CheckError(f"{uses} 参数 {name} 不是合法 JSON 值")
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
    "CHECK_DOMAINS",
    "CheckRunner",
    "assert_steps_in_enabled_modules",
    "coerce_params",
    "domain_of",
    "get_check",
    "iter_check_names",
    "iter_check_specs",
    "load_builtins",
    "module_of_domain",
    "prefix_of",
    "register_check",
    "require_check",
    "validate_static_params",
    "workflow_domains",
]
