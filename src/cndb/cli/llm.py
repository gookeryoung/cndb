"""cndb llm 子命令 —— 大模型能力运维入口（ADR 0020 P3）.

子命令：
- ``test``    用个人连接发一次最小请求，验证地址 / 模型 / Key
- ``runs``    查看调用记录（按用户 / 动作 / 状态过滤）
- ``prune``   清理过期调用记录（保留天数默认 ``settings.LLM_RUN_RETENTION_DAYS``）

示例：
    cndb llm test --user admin
    cndb llm runs --limit 20 --json
    cndb llm prune --days 90 --dry-run
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session


def _get_session() -> Session:
    """按当前 settings.DATABASE_URL 打开 session（与 cndb sync / docs 同口径）."""
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker

    import cndb.plugins.accounts.models
    import cndb.plugins.llm.models  # noqa: F401
    from cndb.core.config import settings
    from cndb.core.database import register_sqlite_pragmas
    from cndb.models.base import Base

    connect_args: dict[str, Any] = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, echo=settings.DEBUG)
    if "sqlite" in settings.DATABASE_URL:
        register_sqlite_pragmas(engine)
    inspector = inspect(engine)
    if not inspector.has_table("llm_user_config"):
        Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _resolve_user(db: Session, username: str | None) -> Any:
    from cndb.plugins.accounts.models import User

    if username:
        user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if user is None:
            raise SystemExit(f"[error] 用户不存在: {username}")
        return user
    users = list(db.execute(select(User).order_by(User.id)).scalars())
    if not users:
        raise SystemExit("[error] 数据库里没有用户，先 `cndb users create`")
    if len(users) > 1:
        raise SystemExit("[error] 存在多个用户，请用 --user 指定（如 --user admin）")
    return users[0]


def cmd_test(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.llm.services import client
    from cndb.plugins.llm.services.connection import load_connection

    db = _get_session()
    try:
        user = _resolve_user(db, getattr(args, "user", None))
        connection = load_connection(db, user.id)
        result = client.test_connection(connection)
        return {
            "user": user.username,
            "base_url": connection.base_url,
            "model": result.model or connection.model,
            "ok": result.ok,
            "latency_ms": result.latency_ms,
            "message": result.message,
        }
    finally:
        db.close()


def cmd_runs(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.llm.models import LlmRun

    db = _get_session()
    try:
        stmt = select(LlmRun)
        user = None
        if getattr(args, "user", None):
            user = _resolve_user(db, args.user)
            stmt = stmt.where(LlmRun.user_id == user.id)
        if getattr(args, "action", None):
            stmt = stmt.where(LlmRun.action == args.action)
        if getattr(args, "status", None):
            stmt = stmt.where(LlmRun.status == args.status)
        limit = max(1, min(int(getattr(args, "limit", 20) or 20), 200))
        rows = list(db.execute(stmt.order_by(LlmRun.id.desc()).limit(limit)).scalars())
        total = int(db.execute(select(func.count()).select_from(LlmRun)).scalar_one())
        return {
            "user": getattr(user, "username", None),
            "total": total,
            "items": [
                {
                    "id": run.id,
                    "user_id": run.user_id,
                    "action": run.action,
                    "model": run.model,
                    "status": run.status,
                    "latency_ms": run.latency_ms,
                    "total_tokens": run.total_tokens,
                    "error": run.error,
                    "created_at": run.created_at,
                }
                for run in rows
            ],
        }
    finally:
        db.close()


def cmd_prune(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.core.config import settings
    from cndb.plugins.llm.models import LlmRun

    days = int(getattr(args, "days", None) or settings.LLM_RUN_RETENTION_DAYS)
    if days < 1:
        raise SystemExit("[error] --days 必须 >= 1")
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    db = _get_session()
    try:
        stale = select(LlmRun).where(LlmRun.created_at < cutoff)
        matched = int(db.execute(select(func.count()).select_from(stale.subquery())).scalar_one())
        deleted = 0
        if not getattr(args, "dry_run", False) and matched:
            db.execute(delete(LlmRun).where(LlmRun.created_at < cutoff))
            db.commit()
            deleted = matched
        return {"days": days, "cutoff": cutoff.isoformat(), "matched": matched, "deleted": deleted}
    finally:
        db.close()


def _print_test(payload: dict[str, Any]) -> None:
    state = "成功" if payload["ok"] else "失败"
    print(f"[llm test] 用户 {payload['user']} → {payload['base_url']} / {payload['model']} {state}")
    print(f"  {payload['message']}（{payload['latency_ms']} ms）")


def _print_runs(payload: dict[str, Any]) -> None:
    scope = f"用户 {payload['user']}" if payload["user"] else "全部用户"
    print(f"[llm runs] {scope}，共 {payload['total']} 条（显示 {len(payload['items'])} 条）")
    for item in payload["items"]:
        tokens = item["total_tokens"] or 0
        print(
            f"  #{item['id']} {item['action']} status={item['status']} model={item['model'] or '-'} "
            f"tokens={tokens} {item['latency_ms']}ms @{item['created_at']}"
        )
        if item["error"]:
            print(f"    ! {item['error']}")


def _print_prune(payload: dict[str, Any]) -> None:
    print(
        f"[llm prune] 保留 {payload['days']} 天（cutoff {payload['cutoff']}）："
        f"命中 {payload['matched']} 条，删除 {payload['deleted']} 条"
    )


def llm_command(args: argparse.Namespace) -> None:
    """分发 ``cndb llm <sub>``."""
    cmd = getattr(args, "llm_cmd", None)
    if cmd is None:
        print("[error] 缺少 llm 子命令，可用: test / runs / prune", file=sys.stderr)
        sys.exit(2)
    handlers = {"test": cmd_test, "runs": cmd_runs, "prune": cmd_prune}
    printers = {"test": _print_test, "runs": _print_runs, "prune": _print_prune}
    handler = handlers.get(cmd)
    if handler is None:  # pragma: no cover - argparse 已收窄
        print(f"[error] 未知 llm 子命令: {cmd}", file=sys.stderr)
        sys.exit(2)
    payload = handler(args)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        printers[cmd](payload)
    if cmd == "test" and not payload["ok"]:
        sys.exit(1)


def register_llm_subparser(sub: Any) -> None:
    """向顶层 ArgumentParser 注册 `cndb llm` 子命令组."""
    p_llm = sub.add_parser("llm", help="大模型能力运维（test / runs / prune）")
    llm_sub = p_llm.add_subparsers(dest="llm_cmd")

    p_test = llm_sub.add_parser("test", help="用个人连接发一次最小请求验证连通性")
    p_test.add_argument("--user", help="用户名（多用户时必填；单用户可省略）")
    p_test.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_runs = llm_sub.add_parser("runs", help="查看调用记录")
    p_runs.add_argument("--user", help="只查看某个用户")
    p_runs.add_argument("--action", help="按动作过滤（如 document.polish）")
    p_runs.add_argument("--status", choices=["success", "failed"], help="按状态过滤")
    p_runs.add_argument("--limit", type=int, default=20, help="返回条数上限（≤200）")
    p_runs.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_prune = llm_sub.add_parser("prune", help="清理过期调用记录")
    p_prune.add_argument("--days", type=int, help="保留天数（默认 settings.LLM_RUN_RETENTION_DAYS）")
    p_prune.add_argument("--dry-run", action="store_true", help="只统计不删除")
    p_prune.add_argument("--json", action="store_true", help="以 JSON 输出")


__all__ = [
    "cmd_prune",
    "cmd_runs",
    "cmd_test",
    "llm_command",
    "register_llm_subparser",
]
