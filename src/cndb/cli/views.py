"""cndb views 子命令 —— 视图运维（孤儿视图体检与回收）.

子命令：
- prune-orphans   孤儿视图体检 / 回收（默认 dry-run，--apply 才实际删除）

**为什么必须有这个出口**：ADR 0003 的 D2 关闭了管理员可见通道（私有视图对表 owner /
工作区 OWNER / 超管一律 404），D3 又把 `owner_id` 外键改成了 `ON DELETE SET NULL`
以保留孤儿视图 —— 二者叠加的必然结果是"孤儿没人看得见，也就没人删得掉"。CLI 是它
唯一的清理出口。

孤儿定义（ADR 0003 §7-2）：`visibility='private'` **且**（`owner_id IS NULL` 或
创建者已不是该工作区成员）。`table` / `shared` 档即使 `owner_id` 为空也不是孤儿 ——
前者仍对全表可见，后者仍对名单内可见。

CLI 是运维侧工具，调用者已具备服务端数据库访问权限，等价于超级管理员。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy.orm import Session


def _get_session() -> Session:
    """按当前 settings.DATABASE_URL 打开一个 DB session.

    每次调用新建 engine（与 ``cndb users`` / ``cndb docs`` 一致），保证 monkeypatch
    settings 的测试能拿到独立 DB；目标库缺少 tables 表时按 ORM 元数据建表兜底。
    """
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker

    import cndb.plugins.tables.models  # noqa: F401  确保 Base.metadata 完整
    from cndb.core.config import settings
    from cndb.core.database import register_sqlite_pragmas
    from cndb.models.base import Base

    connect_args: dict[str, Any] = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, echo=settings.DEBUG)
    if "sqlite" in settings.DATABASE_URL:
        register_sqlite_pragmas(engine)
    if not inspect(engine).has_table("tables_dataview"):
        Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _resolve_workspace(db: Session, ref: str) -> Any:
    """解析 ``--workspace``：纯数字按 id，否则按名称（重名报错）."""
    from cndb.plugins.workspaces.models import Workspace

    text = str(ref).strip()
    if text.isdigit():
        ws = db.get(Workspace, int(text))
        if ws is None:
            raise SystemExit(f"[error] 工作区 id={text} 不存在")
        return ws
    matches = db.query(Workspace).filter(Workspace.name == text).all()
    if not matches:
        raise SystemExit(f"[error] 工作区名称 {text!r} 不存在")
    if len(matches) > 1:
        ids = ", ".join(str(w.id) for w in matches)
        raise SystemExit(f"[error] 工作区名称 {text!r} 不唯一（id: {ids}），请改用 id")
    return matches[0]


def _resolve_table(db: Session, workspace_id: int, ref: str) -> Any:
    """解析 ``--table``：纯数字按 id，否则按名称（限该工作区内，重名报错）."""
    from cndb.plugins.tables.models import DataTable

    text = str(ref).strip()
    if text.isdigit():
        dt = db.query(DataTable).filter(DataTable.id == int(text), DataTable.workspace_id == workspace_id).first()
        if dt is None:
            raise SystemExit(f"[error] 该工作区下不存在数据表 id={text}")
        return dt
    matches = db.query(DataTable).filter(DataTable.name == text, DataTable.workspace_id == workspace_id).all()
    if not matches:
        raise SystemExit(f"[error] 该工作区下不存在数据表名称 {text!r}")
    if len(matches) > 1:
        ids = ", ".join(str(t.id) for t in matches)
        raise SystemExit(f"[error] 数据表名称 {text!r} 不唯一（id: {ids}），请改用 id")
    return matches[0]


def find_orphan_views(db: Session, workspace_id: int, table_id: int | None = None) -> list[dict[str, Any]]:
    """列出该工作区（可限定单表）的孤儿私有视图，按 (表, 视图 id) 排序."""
    from cndb.plugins.tables.models import DataTable, DataView, ViewVisibility
    from cndb.plugins.workspaces.models import WorkspaceMember

    q = (
        db.query(DataView, DataTable)
        .join(DataTable, DataTable.id == DataView.table_id)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataView.visibility == ViewVisibility.PRIVATE,
        )
    )
    if table_id is not None:
        q = q.filter(DataView.table_id == table_id)

    member_ids = {
        int(uid)
        for (uid,) in db.query(WorkspaceMember.user_id).filter(WorkspaceMember.workspace_id == workspace_id).all()
    }
    out: list[dict[str, Any]] = []
    for view, table in q.all():
        owner_id = int(view.owner_id) if view.owner_id is not None else None
        if owner_id is not None and owner_id in member_ids:
            continue  # 创建者还在工作区里 → 不是孤儿
        out.append(
            {
                "id": int(view.id),
                "name": str(view.name),
                "table_id": int(table.id),
                "table_name": str(table.name),
                "owner_id": owner_id,
                "scope_key": int(view.scope_key),
                "reason": "创建者已注销" if owner_id is None else "创建者已不在该工作区",
                "created_at": view.created_at.isoformat(sep=" ", timespec="seconds")
                if view.created_at is not None
                else "",
                "updated_at": view.updated_at.isoformat(sep=" ", timespec="seconds")
                if view.updated_at is not None
                else "",
            }
        )
    out.sort(key=lambda r: (r["table_id"], r["id"]))
    return out


def cmd_prune_orphans(args: argparse.Namespace) -> dict[str, Any]:
    """体检 / 回收孤儿视图，返回可序列化报告."""
    from cndb.plugins.tables.models import DataView

    db = _get_session()
    try:
        ws = _resolve_workspace(db, args.workspace)
        table = _resolve_table(db, int(ws.id), args.table) if getattr(args, "table", None) else None
        orphans = find_orphan_views(db, int(ws.id), int(table.id) if table is not None else None)
        dry_run = not getattr(args, "apply", False)
        removed: list[int] = []
        if not dry_run:
            for item in orphans:
                obj = db.get(DataView, int(item["id"]))
                if obj is not None:
                    db.delete(obj)
                    removed.append(int(item["id"]))
            db.commit()
        return {
            "workspace": {"id": int(ws.id), "name": str(ws.name)},
            "table": {"id": int(table.id), "name": str(table.name)} if table is not None else None,
            "dry_run": dry_run,
            "orphans": orphans,
            "removed": removed,
        }
    finally:
        db.close()


def _print_prune(payload: dict[str, Any]) -> None:
    ws = payload["workspace"]
    scope = f"工作区 {ws['name']}(id={ws['id']})"
    if payload["table"] is not None:
        scope += f" / 数据表 {payload['table']['name']}(id={payload['table']['id']})"
    mode = "体检（dry-run，未删除）" if payload["dry_run"] else "回收"
    orphans = payload["orphans"]
    print(f"[views prune-orphans] {scope} — {mode}")
    print(f"[views prune-orphans] 检出孤儿视图 {len(orphans)} 个")
    for item in orphans:
        print(
            f"  - id={item['id']} {item['name']!r} @ 表 {item['table_name']}(id={item['table_id']})"
            f" [{item['reason']}, owner_id={item['owner_id']}, scope_key={item['scope_key']}]"
            f" 创建 {item['created_at']} / 修改 {item['updated_at']}"
        )
    if payload["dry_run"] and orphans:
        print("[views prune-orphans] 加 --apply 执行删除")
    elif not payload["dry_run"]:
        print(f"[views prune-orphans] 已删除 {len(payload['removed'])} 个孤儿视图")


def views_command(args: argparse.Namespace) -> None:
    """分发 ``cndb views <sub>``."""
    cmd = getattr(args, "views_cmd", None)
    if cmd is None:
        print("[error] 缺少 views 子命令，可用: prune-orphans", file=sys.stderr)
        sys.exit(2)
    if cmd == "prune-orphans":
        payload = cmd_prune_orphans(args)
        if getattr(args, "json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_prune(payload)
        return
    print(f"[error] 未知 views 子命令: {cmd}", file=sys.stderr)  # pragma: no cover - argparse 已收窄
    sys.exit(2)


def register_views_subparser(sub: Any) -> None:
    """向顶层 ArgumentParser 注册 `cndb views` 子命令组."""
    p_views = sub.add_parser("views", help="视图运维（prune-orphans：孤儿视图体检与回收）")
    views_sub = p_views.add_subparsers(dest="views_cmd")

    p_prune = views_sub.add_parser(
        "prune-orphans",
        help="孤儿视图（私有档且创建者已注销/已离开工作区）体检/回收（默认仅体检，不删除）",
    )
    p_prune.add_argument("--workspace", required=True, help="工作区 id 或名称（名称需唯一）")
    p_prune.add_argument("--table", default=None, help="限定单个数据表（id 或名称，可省略）")
    p_prune.add_argument("--apply", action="store_true", help="实际删除孤儿视图（默认 dry-run）")
    p_prune.add_argument(
        "--dry-run",
        action="store_true",
        help="显式声明仅体检（默认行为，仅用于脚本可读性；与 --apply 同时给出时以 --apply 为准）",
    )
    p_prune.add_argument("--json", action="store_true", help="以 JSON 输出报告")


__all__ = ["cmd_prune_orphans", "find_orphan_views", "register_views_subparser", "views_command"]
