"""cndb design-refactor 子命令 —— 旧设计批量重构为分文件库（ADR 0086 D8 / §6）.

把存量单文件设计的顶层 ``module`` 提取为 ``part`` 文件、调用点重写为
``use`` 引用，编译前后 ``nodes`` 等价才落库；不可拆分的设计保留原文并计入
``failed``（退出码非 0）。幂等：``refactored_from_version`` 非空的设计自动跳过。

示例：
    cndb design-refactor --dry-run
    cndb design-refactor --workspace-id 1
    cndb design-refactor --json
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy.orm import Session


def _get_session() -> Session:
    """按当前 settings.DATABASE_URL 打开 session（与 cndb sync / pipeline 同口径）."""
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker

    import cndb.plugins.design.models
    import cndb.plugins.workspaces.models  # noqa: F401
    from cndb.core.config import settings
    from cndb.core.database import register_sqlite_pragmas
    from cndb.models.base import Base

    connect_args: dict[str, Any] = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, echo=settings.DEBUG)
    if "sqlite" in settings.DATABASE_URL:
        register_sqlite_pragmas(engine)
    inspector = inspect(engine)
    if not inspector.has_table("design_design"):
        Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def cmd_refactor(args: argparse.Namespace) -> dict[str, Any]:
    from cndb.plugins.design.services.refactor import run_refactor

    db = _get_session()
    try:
        report = run_refactor(
            db,
            workspace_id=getattr(args, "workspace_id", None),
            dry_run=bool(getattr(args, "dry_run", False)),
        )
        return report.to_dict()
    finally:
        db.close()


def _print_report(payload: dict[str, Any]) -> None:
    mode = "dry-run " if payload.get("dry_run") else ""
    print(
        f"[design-refactor] {mode}refactored={len(payload['refactored'])} "
        f"skipped={len(payload['skipped'])} failed={len(payload['failed'])}"
    )
    for entry in payload["refactored"]:
        print(f"  + #{entry['design_id']} {entry['title']} -> parts: {', '.join(entry['parts'])}")
    for entry in payload["skipped"]:
        print(f"  = #{entry['design_id']} {entry['title']} 跳过：{entry['reason']}")
    for entry in payload["failed"]:
        print(f"  ! #{entry['design_id']} {entry['title']} 失败：{entry['error']}")


def design_command(args: argparse.Namespace) -> None:
    """分发 ``cndb design-refactor``."""
    payload = cmd_refactor(args)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        _print_report(payload)
    if payload["failed"]:
        sys.exit(1)


def register_design_subparser(sub: Any) -> None:
    """向顶层 ArgumentParser 注册 ``cndb design-refactor``."""
    p_design = sub.add_parser("design-refactor", help="旧设计批量重构：拆分顶层 module 为 part 文件")
    p_design.add_argument("--workspace-id", type=int, help="只处理某个工作区（缺省全部）")
    p_design.add_argument("--dry-run", action="store_true", help="只做等价校验与报告，不写库")
    p_design.add_argument("--json", action="store_true", help="以 JSON 输出")


__all__ = [
    "design_command",
    "register_design_subparser",
]
