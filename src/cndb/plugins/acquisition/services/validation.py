"""策略声明校验：保存期就把错误暴露（ADR 0085 §7）.

校验项（任一不合法抛 :class:`RuleError`，路由层转 400）：

- ``scope.channels`` 非空且每条引用可解析（``job:<id>`` / 内联 provider 声明）；
- ``scope.query`` 占位符可渲染（用样例上下文，未知占位符直接报错）；
- ``filter_rule`` 布尔式可解析、日期可解析、数值项合法；
- ``targets``：``kind`` 白名单 + 必填字段（``table`` 要 ``table_id``；``document`` 的 ``parent_id`` 可空）；
- ``iteration``：``max_rounds`` / 预算数值范围（防跑飞，I8）；
- ``schedule``：与数据同步同语义（``manual`` / ``daily`` / ``interval`` / ``cron``），
  非法表达式在保存期就报错（P2 接入调度后必须前置校验）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cndb.plugins.acquisition.services.channels import parse_channel_ref
from cndb.plugins.acquisition.services.rules.expr import RuleError, render_query
from cndb.plugins.acquisition.services.rules.filter import FilterRule
from cndb.plugins.datasource.services.schedule import ScheduleConfig

__all__ = ["MAX_CHANNELS", "MAX_REQUESTS_LIMIT", "MAX_ROUNDS_LIMIT", "validate_strategy_payload"]

MAX_CHANNELS = 8
MAX_ROUNDS_LIMIT = 5
MAX_REQUESTS_LIMIT = 1000
#: 校验期用于渲染检索式的样例上下文（真实值运行期注入）
_SAMPLE_CONTEXT = {"today": "2020-01-01", "topic": "示例主题"}


def _validate_channels(channels: Sequence[Any]) -> None:
    if not channels:
        raise RuleError("scope.channels 不能为空，至少选择一个渠道")
    if len(channels) > MAX_CHANNELS:
        raise RuleError(f"渠道数量上限 {MAX_CHANNELS}")
    for ref in channels:
        parse_channel_ref(ref)


def _validate_targets(targets: Sequence[Any]) -> None:
    if not targets:
        raise RuleError("targets 不能为空，至少声明一个落点")
    for target in targets:
        if not isinstance(target, Mapping):
            raise RuleError(f"落点声明必须是对象: {target!r}")
        kind = str(target.get("kind") or "")
        if kind == "table":
            table_id = target.get("table_id")
            if not isinstance(table_id, int) or table_id <= 0:
                raise RuleError("table 落点缺少合法的 table_id")
            continue
        if kind == "document":
            parent_id = target.get("parent_id")
            if parent_id is not None and (not isinstance(parent_id, int) or parent_id <= 0):
                raise RuleError("document 落点的 parent_id 必须是正整数或 null")
            continue
        raise RuleError(f"未知落点类型: {kind!r}")


def _positive_int(value: Any, *, field: str, default: int, ceiling: int | None = None) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise RuleError(f"{field} 必须是整数") from exc
    if number <= 0:
        raise RuleError(f"{field} 必须大于 0")
    if ceiling is not None and number > ceiling:
        raise RuleError(f"{field} 上限 {ceiling}")
    return number


def _validate_iteration(iteration: Mapping[str, Any]) -> None:
    if not iteration:
        return
    _positive_int(iteration.get("max_rounds"), field="iteration.max_rounds", default=1, ceiling=MAX_ROUNDS_LIMIT)
    budget = iteration.get("budget")
    if isinstance(budget, Mapping):
        _positive_int(
            budget.get("max_requests"),
            field="iteration.budget.max_requests",
            default=MAX_REQUESTS_LIMIT,
            ceiling=MAX_REQUESTS_LIMIT,
        )
        for key in ("max_rows", "max_llm_calls", "max_llm_tokens"):
            if budget.get(key) not in (None, ""):
                _positive_int(budget.get(key), field=f"iteration.budget.{key}", default=1)
    expand = iteration.get("expand")
    if isinstance(expand, Mapping):
        review = str(expand.get("review") or "auto")
        if review not in ("auto", "llm", "manual"):
            raise RuleError(f"iteration.expand.review 非法: {review!r}")


def _validate_schedule(schedule: Mapping[str, Any] | None) -> None:
    """调度声明：复用数据同步的 ``ScheduleConfig``（含 cron 表达式与时区）."""
    if not schedule:
        return
    try:
        ScheduleConfig.from_dict(dict(schedule))
    except Exception as exc:  # ProviderError / ValueError / TypeError 统一转规则错误
        raise RuleError(f"schedule 非法: {exc}") from exc


def validate_strategy_payload(
    *,
    scope: Mapping[str, Any] | None,
    filter_rule: Mapping[str, Any] | None,
    targets: Sequence[Any] | None,
    iteration: Mapping[str, Any] | None,
    schedule: Mapping[str, Any] | None = None,
) -> None:
    """逐段校验策略声明；不合法抛 :class:`RuleError`."""
    payload = dict(scope or {})
    _validate_channels(list(payload.get("channels") or []))
    render_query(str(payload.get("query") or ""), dict(_SAMPLE_CONTEXT))

    rule = FilterRule.from_dict(filter_rule)
    rule.validate()

    _validate_targets(list(targets or []))

    _validate_iteration(dict(iteration or {}))
    _validate_schedule(schedule)
    max_items = payload.get("max_results_per_channel")
    if max_items not in (None, ""):
        _positive_int(max_items, field="scope.max_results_per_channel", default=200, ceiling=200)
