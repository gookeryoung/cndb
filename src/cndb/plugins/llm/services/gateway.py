"""调用网关：唯一的大模型调用入口 + 留痕（ADR 0020 P0/C7）.

领域插件调用 :func:`invoke` 之前必须自己完成权限校验与输入裁剪（平台不承担领域权限）。
网关负责：连接解析 → 调客户端 → 输出 schema 校验 → 写 ``llm_run`` + ``core_event``。
"""

from __future__ import annotations

import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from cndb.core.events import record_event
from cndb.plugins.accounts.models import User
from cndb.plugins.llm.models import LlmRun
from cndb.plugins.llm.services import client
from cndb.plugins.llm.services.actions import ActionSpec
from cndb.plugins.llm.services.connection import LlmConnection, load_connection
from cndb.plugins.llm.services.errors import LlmError, LlmOutputInvalid, LlmUpstreamError
from cndb.plugins.llm.services.parsing import parse_content, strip_json_fences
from cndb.plugins.llm.services.prompts import DEFAULT_SYSTEM_PROMPT, JSON_INSTRUCTION

# 与 core.events 的约定：动作名固定 llm.invoke，target_type 固定 llm
ACTION_LLM_INVOKE = "llm.invoke"
TARGET_LLM = "llm"


@dataclass(frozen=True, slots=True)
class LlmContext:
    """一次调用的定位上下文（进 ``llm_run.detail`` / 事件）。"""

    workspace_id: int | None = None
    target_type: str = "system"
    target_id: str | int | None = None
    request_id: str | None = None


@dataclass(slots=True)
class LlmResult:
    """一次成功调用的结果."""

    content: str
    parsed: Any
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    run_id: int | None = None


def record_run(
    db: Session,
    *,
    user_id: int,
    action: str,
    workspace_id: int | None = None,
    model: str = "",
    status: str = "success",
    latency_ms: int = 0,
    usage: dict[str, int] | None = None,
    error: str = "",
    detail: dict[str, Any] | None = None,
) -> LlmRun:
    """写一条调用留痕（**只存元数据，不存提示词 / 输出全文**）.

    同时写 ``core_event``（``llm.invoke``），失败不影响业务返回（record_event 自身尽力而为）。
    """
    usage = usage or {}
    run = LlmRun(
        user_id=user_id,
        workspace_id=workspace_id,
        action=action,
        model=model,
        status=status,
        latency_ms=max(0, int(latency_ms)),
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
        error=error[:500],
        detail=detail or {},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    # record_event 本身已尽力而为（失败只记日志），这里再兜一层避免留痕影响业务返回
    with suppress(Exception):
        record_event(
            db,
            ACTION_LLM_INVOKE,
            summary=f"AI 调用 {action}（{status}）",
            target_type=TARGET_LLM,
            target_id=run.id,
            workspace_id=workspace_id,
            actor_id=user_id,
            detail={"action": action, "status": status, "model": model},
            request_id=(detail or {}).get("request_id"),
        )
    return run


def invoke(
    db: Session,
    user: User,
    action: ActionSpec,
    *,
    user_content: str,
    context: LlmContext | None = None,
    connection: LlmConnection | None = None,
) -> LlmResult:
    """执行一次 AI 动作并留痕.

    调用方（领域路由）必须先完成权限校验与输入裁剪；``user_content`` 应已按需渲染。

    Raises:
        LlmNotConfigured / LlmUpstreamError / LlmRateLimited / LlmOutputInvalid
    """
    ctx = context or LlmContext()
    started = time.perf_counter()
    active_connection = connection or load_connection(db, user.id)
    if len(user_content) > action.max_input_chars:
        raise LlmOutputInvalid(f"输入过长（{len(user_content)} 字符 > {action.max_input_chars}），请缩短后重试")

    system = action.system_prompt.strip() or DEFAULT_SYSTEM_PROMPT
    if action.json_mode and JSON_INSTRUCTION not in system:
        system = f"{system}\n{JSON_INSTRUCTION}"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    status = "failed"
    error = ""
    response: client.LlmResponse | None = None
    parsed: Any = None
    try:
        response = client.complete(
            active_connection,
            messages=messages,
            model=active_connection.model,
            temperature=action.temperature,
            max_tokens=action.max_tokens,
            json_mode=action.json_mode,
        )
        if action.output_schema is not None:
            raw = parse_content(response.content)
            try:
                parsed = action.output_schema.model_validate(raw)
            except ValidationError as exc:
                raise LlmOutputInvalid(f"模型输出不符合预期结构: {exc.errors()[:3]}") from exc
        elif action.json_mode:
            parsed = strip_json_fences(response.content)
        else:
            parsed = response.content.strip()
        status = "success"
    except LlmError as exc:
        error = str(exc)
        raise
    except Exception as exc:  # 未预期异常也归类为上游失败，保留原始信息
        error = str(exc)
        raise LlmUpstreamError(error) from exc
    finally:
        latency = int((time.perf_counter() - started) * 1000)
        record_run(
            db,
            user_id=user.id,
            action=action.name,
            workspace_id=ctx.workspace_id,
            model=response.model if response is not None else active_connection.model,
            status=status,
            latency_ms=latency,
            usage=response.usage if response is not None else None,
            error=error,
            detail={
                "target_type": ctx.target_type,
                "target_id": str(ctx.target_id) if ctx.target_id is not None else None,
                "input_chars": len(user_content),
                "output_chars": len(response.content) if response is not None else 0,
                "request_id": ctx.request_id,
            },
        )

    assert response is not None  # 成功路径必然有响应
    latency = int((time.perf_counter() - started) * 1000)
    return LlmResult(
        content=response.content,
        parsed=parsed,
        model=response.model,
        usage=response.usage,
        latency_ms=latency,
        run_id=last_run_id(db, user.id, action.name),
    )


def last_run_id(db: Session, user_id: int, action: str) -> int | None:
    """最近一条留痕 id（给前端返回 ``run_id`` 便于排查，不额外查库依赖排序稳定性）."""
    from sqlalchemy import select

    return db.execute(
        select(LlmRun.id).where(LlmRun.user_id == user_id, LlmRun.action == action).order_by(LlmRun.id.desc()).limit(1)
    ).scalar_one_or_none()


__all__ = [
    "ACTION_LLM_INVOKE",
    "TARGET_LLM",
    "LlmContext",
    "LlmResult",
    "invoke",
    "record_run",
]
