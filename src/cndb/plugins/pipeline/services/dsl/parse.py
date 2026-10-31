"""流水线 DSL 编译：YAML 子集 → 校验过的 IR（ADR 0076 D2）.

保存期一次性完成结构校验（未知键 / DAG 环 / 未知动作 / ``with`` schema / 表达式语法），
因此运行期只可能出现业务数据层面的发现，不会出现语法 / 结构错误（I2）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

from cndb.plugins.pipeline.models import SEVERITIES
from cndb.plugins.pipeline.services.checks.registry import (
    require_check,
    validate_static_params,
)
from cndb.plugins.pipeline.services.dsl.expressions import (
    is_expression,
    parse_expression,
)
from cndb.plugins.pipeline.services.errors import DslError

#: 定义名上限（与 ``pipeline_workflow.name`` 列宽一致）
MAX_NAME_LENGTH = 120

_TOP_KEYS = {"name", "on", "vars", "jobs"}
_ON_KEYS = {"manual", "events", "schedule"}
_JOB_KEYS = {"needs", "if", "steps"}
_STEP_KEYS = {"uses", "with", "severity", "continue-on-error"}


@dataclass(frozen=True)
class StepIR:
    """编译后的一个 step."""

    uses: str
    params: dict[str, Any] = field(default_factory=dict)
    severity: str = "warn"
    continue_on_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 友好字典（落 ``compiled`` 列）."""
        return {
            "uses": self.uses,
            "with": dict(self.params),
            "severity": self.severity,
            "continue_on_error": self.continue_on_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepIR:
        """从 ``compiled`` 快照还原."""
        return cls(
            uses=str(data["uses"]),
            params=dict(data.get("with") or {}),
            severity=str(data.get("severity") or "warn"),
            continue_on_error=bool(data.get("continue_on_error")),
        )


@dataclass(frozen=True)
class JobIR:
    """编译后的一个 job（DAG 节点）."""

    job_id: str
    needs: tuple[str, ...] = ()
    condition: str | None = None
    steps: tuple[StepIR, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 友好字典."""
        return {
            "id": self.job_id,
            "needs": list(self.needs),
            "if": self.condition,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobIR:
        """从 ``compiled`` 快照还原."""
        return cls(
            job_id=str(data["id"]),
            needs=tuple(str(n) for n in data.get("needs") or ()),
            condition=str(data["if"]) if data.get("if") else None,
            steps=tuple(StepIR.from_dict(step) for step in data.get("steps") or ()),
        )


@dataclass(frozen=True)
class WorkflowIR:
    """流水线编译产物（``compiled`` 列的载荷）."""

    name: str
    triggers: dict[str, Any] = field(default_factory=dict)
    vars: dict[str, Any] = field(default_factory=dict)
    jobs: tuple[JobIR, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 友好字典."""
        return {
            "name": self.name,
            "on": dict(self.triggers),
            "vars": dict(self.vars),
            "jobs": [job.to_dict() for job in self.jobs],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowIR:
        """从 ``compiled`` 快照还原（运行期入口）."""
        return cls(
            name=str(data.get("name") or ""),
            triggers=dict(data.get("on") or {}),
            vars=dict(data.get("vars") or {}),
            jobs=tuple(JobIR.from_dict(job) for job in data.get("jobs") or ()),
        )


def compile_workflow(content: str, *, fallback_name: str = "") -> WorkflowIR:
    """把 YAML 原文编译为校验过的 IR.

    Args:
        content: DSL 原文（YAML）。
        fallback_name: DSL 未写 ``name`` 时使用的名称（通常取定义记录名）。

    Raises:
        DslError: YAML 解析失败或任意结构 / 参数 / 表达式不合法。
    """
    if not content or not content.strip():
        raise DslError("DSL 内容不能为空")
    try:
        data: Any = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise DslError(f"YAML 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise DslError("DSL 顶层必须是映射（name / on / vars / jobs）")
    # YAML 1.1 把裸键 ``on`` 解析为布尔 True（GitHub Actions 同款坑）；这里归一回字符串键
    if True in data:
        if "on" not in data:
            data["on"] = data.pop(True)
        else:
            data.pop(True)
    _reject_unknown_keys(data, _TOP_KEYS, "顶层")

    name = _optional_str(data.get("name"), "name") or fallback_name
    if not name:
        raise DslError("DSL 缺少 name（或在定义记录上填写名称）")
    if len(name) > MAX_NAME_LENGTH:
        raise DslError(f"name 超过 {MAX_NAME_LENGTH} 字符上限")

    triggers = _compile_triggers(data.get("on"))
    variables = _compile_vars(data.get("vars"))
    jobs = _compile_jobs(data.get("jobs"))
    return WorkflowIR(name=name, triggers=triggers, vars=variables, jobs=tuple(jobs))


def _reject_unknown_keys(mapping: dict[str, Any], allowed: set[str], what: str) -> None:
    unknown = sorted(str(key) for key in set(mapping) - allowed)
    if unknown:
        raise DslError(f"{what}存在未知键：{', '.join(unknown)}（允许：{', '.join(sorted(allowed))}）")


def _optional_str(value: Any, what: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DslError(f"{what} 必须是字符串")
    return value.strip()


def _compile_triggers(raw: Any) -> dict[str, Any]:
    """校验 ``on``：手动 / 事件 / 定时（P0 只消费手动，其余仅存快照）."""
    if raw is None:
        return {"manual": True}
    if not isinstance(raw, dict):
        raise DslError("on 必须是映射（manual / events / schedule）")
    _reject_unknown_keys(raw, _ON_KEYS, "on ")
    manual = raw.get("manual", True)
    if not isinstance(manual, bool):
        raise DslError("on.manual 必须是布尔值")
    events_raw = raw.get("events")
    events: list[str] = []
    if events_raw is not None:
        if not isinstance(events_raw, list) or not all(isinstance(e, str) and e for e in events_raw):
            raise DslError("on.events 必须是事件名列表")
        events = [str(e) for e in events_raw]
    schedule = _optional_str(raw.get("schedule"), "on.schedule")
    if schedule and len(schedule.split()) != 5:
        raise DslError("on.schedule 必须是 5 段 cron 表达式")
    triggers: dict[str, Any] = {"manual": manual}
    if events:
        triggers["events"] = events
    if schedule:
        triggers["schedule"] = schedule
    return triggers


def _compile_vars(raw: Any) -> dict[str, Any]:
    """校验 ``vars``：键为标识符，值为标量或 ``${{ }}`` 表达式."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DslError("vars 必须是映射")
    variables: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.isidentifier():
            raise DslError(f"vars 键必须是标识符：{key!r}")
        if isinstance(value, (dict, list)):
            raise DslError(f"vars.{key} 只能是标量或表达式")
        if is_expression(value):
            parse_expression(str(value))
        variables[key] = value
    return variables


def _compile_jobs(raw: Any) -> list[JobIR]:
    """校验 ``jobs`` 结构、DAG 依赖与 step 参数."""
    if not isinstance(raw, dict) or not raw:
        raise DslError("jobs 必须是非空映射")
    jobs: list[JobIR] = []
    for job_id, job_raw in raw.items():
        if not isinstance(job_id, str) or not job_id.strip():
            raise DslError("job 标识必须是非空字符串")
        if not isinstance(job_raw, dict):
            raise DslError(f"jobs.{job_id} 必须是映射")
        _reject_unknown_keys(job_raw, _JOB_KEYS, f"jobs.{job_id} ")
        needs = _compile_needs(job_raw.get("needs"))
        condition = _compile_condition(job_raw.get("if"), job_id)
        steps = _compile_steps(job_raw.get("steps"), job_id)
        jobs.append(JobIR(job_id=job_id, needs=needs, condition=condition, steps=steps))

    job_ids = {job.job_id for job in jobs}
    for job in jobs:
        missing = [need for need in job.needs if need not in job_ids]
        if missing:
            raise DslError(f"jobs.{job.job_id} 依赖不存在的 job：{', '.join(missing)}")
        if job.job_id in job.needs:
            raise DslError(f"jobs.{job.job_id} 不能依赖自身")
    _detect_cycles(jobs)
    return jobs


def _compile_needs(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list) and all(isinstance(item, str) and item for item in raw):
        return tuple(str(item) for item in raw)
    raise DslError("jobs.<id>.needs 必须是 job 名或其列表")


def _compile_condition(raw: Any, job_id: str) -> str | None:
    if raw is None:
        return None
    if not is_expression(raw):
        raise DslError(f"jobs.{job_id}.if 必须写成 ${{{{ ... }}}} 表达式")
    condition = str(raw)
    parse_expression(condition)
    return condition


def _compile_steps(raw: Any, job_id: str) -> tuple[StepIR, ...]:
    if not isinstance(raw, list) or not raw:
        raise DslError(f"jobs.{job_id}.steps 必须是非空列表")
    steps: list[StepIR] = []
    for index, step_raw in enumerate(raw):
        what = f"jobs.{job_id}.steps[{index}]"
        if not isinstance(step_raw, dict):
            raise DslError(f"{what} 必须是映射")
        _reject_unknown_keys(step_raw, _STEP_KEYS, f"{what} ")
        uses = step_raw.get("uses")
        if not isinstance(uses, str) or not uses:
            raise DslError(f"{what}.uses 必须是非空字符串")
        spec, _ = require_check(uses)
        params_raw: Any = step_raw.get("with")
        if params_raw is None:
            params_raw = dict[str, Any]()
        if not isinstance(params_raw, dict):
            raise DslError(f"{what}.with 必须是映射")
        params: dict[str, Any] = params_raw
        _validate_expression_values(params, f"{what}.with")
        validate_static_params(spec, params)
        severity = step_raw.get("severity", spec.default_severity)
        if severity not in SEVERITIES:
            raise DslError(f"{what}.severity 必须是 {' / '.join(SEVERITIES)}")
        continue_on_error = step_raw.get("continue-on-error", False)
        if not isinstance(continue_on_error, bool):
            raise DslError(f"{what}.continue-on-error 必须是布尔值")
        steps.append(
            StepIR(
                uses=uses,
                params=dict(params),
                severity=str(severity),
                continue_on_error=continue_on_error,
            )
        )
    return tuple(steps)


def _validate_expression_values(params: dict[str, Any], what: str) -> None:
    """``with`` 静态值中的表达式逐个做语法校验."""
    for key, value in params.items():
        if is_expression(value):
            parse_expression(str(value))
        elif isinstance(value, list):
            for item in value:
                if is_expression(item):
                    parse_expression(str(item))
        elif isinstance(value, (dict,)):
            raise DslError(f"{what}.{key} 不支持嵌套对象")
        elif not isinstance(value, (str, int, float, bool)) and value is not None:
            raise DslError(f"{what}.{key} 类型不受支持")


def _detect_cycles(jobs: list[JobIR]) -> None:
    """DFS 检测 ``needs`` 环路（存在则抛 ``DslError``）."""
    graph = {job.job_id: job.needs for job in jobs}
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str) -> None:
        if node in done:
            return
        if node in visiting:
            raise DslError(f"jobs 依赖存在环：{node}")
        visiting.add(node)
        for need in graph.get(node, ()):
            visit(need)
        visiting.discard(node)
        done.add(node)

    for job_id in graph:
        visit(job_id)


def topological_jobs(jobs: tuple[JobIR, ...]) -> list[JobIR]:
    """按 ``needs`` 拓扑排序（同层保持 YAML 声明顺序）."""
    ordered: list[JobIR] = []
    placed: set[str] = set()
    while len(ordered) < len(jobs):
        progressed = False
        for job in jobs:
            if job.job_id in placed:
                continue
            if all(need in placed for need in job.needs):
                ordered.append(job)
                placed.add(job.job_id)
                progressed = True
        if not progressed:  # pragma: no cover - 编译期已排除环
            raise DslError("jobs 依赖无法排序")
    return ordered


__all__ = [
    "MAX_NAME_LENGTH",
    "JobIR",
    "StepIR",
    "WorkflowIR",
    "compile_workflow",
    "topological_jobs",
]
