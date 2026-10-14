"""用户管理命令实现（create / delete / list / import）与结果结构."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cndb.cli.users.db import (
    _get_session,
    _list_member_count,
    _list_owned_workspaces,
    _resolve_user,
)
from cndb.cli.users.io import (
    _generate_password,
    _open_tabfile,
)
from cndb.plugins.accounts.models import User, UserRole
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember


@dataclass
class CreateResult:
    user_id: int
    username: str
    role: str
    password: str
    note: str = ""


def cmd_create(args: argparse.Namespace) -> CreateResult:
    """创建单个用户.

    Returns:
        CreateResult
    Raises:
        SystemExit: 参数错误 / 用户名冲突 / 角色非法
    """
    db = _get_session()
    try:
        # 角色校验
        role = getattr(args, "role", None) or UserRole.USER.value
        try:
            user_role = UserRole(role)
        except ValueError:
            valid = ", ".join(r.value for r in UserRole)
            raise SystemExit(f"[error] 无效角色 '{role}'，可选值: {valid}") from None
        role_value = user_role.value

        # 用户名去重
        existing = db.query(User).filter(User.username == args.username).first()
        if existing is not None:
            raise SystemExit(f"[error] 用户名 '{args.username}' 已存在 (id={existing.id})")
        if args.email:
            dup_email = db.query(User).filter(User.email == args.email).first()
            if dup_email is not None:
                raise SystemExit(f"[error] 邮箱 '{args.email}' 已被使用 (id={dup_email.id})")

        # 密码处理（明文仅用于创建时一次性展示，不落库）
        if not args.password:
            plain_password = _generate_password()
            password_note = "（自动生成）"  # nosec B105 - 展示备注，非密码值
        else:
            plain_password = args.password
            password_note = ""  # nosec B105 - 展示备注，非密码值
            if len(plain_password) < 6:
                raise SystemExit("[error] 密码至少 6 位")

        nickname = args.nickname or user_role.display_name

        user = User(
            username=args.username,
            email=args.email or None,
            nickname=nickname,
            role=role_value,
        )
        user.set_password(plain_password)
        if getattr(args, "is_superuser", False):
            user.is_superuser = True
        db.add(user)
        db.commit()
        db.refresh(user)

        note_parts: list[str] = []
        if password_note:
            note_parts.append(password_note)
        if user.is_superuser:
            note_parts.append("[superuser]")
        note = " ".join(note_parts)

        return CreateResult(
            user_id=user.id,
            username=user.username,
            role=user.role,
            password=plain_password,
            note=note,
        )
    finally:
        db.close()


# ── cmd_delete ─


@dataclass
class DeleteCheckResult:
    """删除前的安全检查结果."""

    user_id: int
    username: str
    is_superuser: bool
    owned_workspaces: list[Workspace]  # OWNER 工作区
    member_count: int  # 成员关系总数
    can_delete_without_cascade: bool  # OWNER 工作区为空 → 可直接删


def cmd_delete_check(args: argparse.Namespace) -> DeleteCheckResult | None:
    """查询用户的工作区持有情况（dry-run / 列出待处理工作区用）.

    Returns:
        DeleteCheckResult；找不到用户返回 None.
    """
    db = _get_session()
    try:
        user = _resolve_user(db, args.target)
        if user is None:
            return None
        owned = _list_owned_workspaces(db, user.id)
        member_count = _list_member_count(db, user.id)
        return DeleteCheckResult(
            user_id=user.id,
            username=user.username,
            is_superuser=user.is_superuser,
            owned_workspaces=owned,
            member_count=member_count,
            can_delete_without_cascade=len(owned) == 0,
        )
    finally:
        db.close()


def cmd_delete(args: argparse.Namespace) -> dict[str, Any]:
    """删除用户.

    检查顺序：
    1. 解析用户（username 或 id）
    2. 列出 OWNER 工作区数量；若 > 0 且未传 --cascade → 拒绝删除
    3. 若传 --cascade → 要求 --yes 或交互确认 → 删除 OWNER 工作区 → 删除用户

    Returns:
        dict 包含删除统计
    """
    db = _get_session()
    try:
        user = _resolve_user(db, args.target)
        if user is None:
            raise SystemExit(f"[error] 用户 '{args.target}' 不存在")

        owned = _list_owned_workspaces(db, user.id)
        member_count = _list_member_count(db, user.id)

        if user.is_superuser:
            print(f"[warn] 目标用户 '{user.username}' 是 superuser，继续操作前请确认！", file=sys.stderr)

        print(f"[info] 目标: id={user.id}, username={user.username}, role={user.role}, superuser={user.is_superuser}")
        print(f"[info] OWNER 工作区: {len(owned)} 个")
        print(f"[info] 成员关系: {member_count} 条（通过外键自动清理）")

        if owned and not getattr(args, "cascade", False):
            print(f"[warn] 未传 --cascade，拒绝删除。该用户拥有 {len(owned)} 个工作区：", file=sys.stderr)
            for ws in owned:
                print(f"       - #{ws.id} {ws.name}", file=sys.stderr)
            print("[info] 加 --cascade 将级联删除上述工作区（不可逆）。", file=sys.stderr)
            raise SystemExit(2)

        # 级联删除 OWNER 工作区
        deleted_workspace_ids: list[int] = []
        if owned:
            # 二次确认
            if not getattr(args, "yes", False):
                ans = input(f"[confirm] 将级联删除 {len(owned)} 个工作区 + 用户 '{user.username}'，确认？[y/N] ")
                if ans.strip().lower() not in ("y", "yes"):
                    print("[abort] 用户取消")
                    raise SystemExit(1)
            for ws in owned:
                deleted_workspace_ids.append(ws.id)
                db.delete(ws)

        # 显式清理成员关系行：不依赖 foreign_keys pragma（兼容历史库 /
        # FK 未开启的会话），避免孤儿成员行导致工作区成员计数虚高
        from cndb.plugins.tables.models import TableMember

        ws_member_rows = (
            db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).delete(synchronize_session=False)
        )
        table_member_rows = (
            db.query(TableMember).filter(TableMember.user_id == user.id).delete(synchronize_session=False)
        )

        db.delete(user)
        db.commit()

        return {
            "deleted_user_id": user.id,
            "deleted_username": user.username,
            "deleted_workspace_count": len(deleted_workspace_ids),
            "deleted_workspace_ids": deleted_workspace_ids,
            "deleted_workspace_member_rows": int(ws_member_rows),
            "deleted_table_member_rows": int(table_member_rows),
        }
    finally:
        db.close()


# ── cmd_list ─


def cmd_list(args: argparse.Namespace) -> list[User]:
    """列出用户（可按角色 / 激活状态筛选）."""
    db = _get_session()
    try:
        q = db.query(User)
        role_filter = getattr(args, "role", None)
        if role_filter:
            try:
                UserRole(role_filter)
            except ValueError:
                valid = ", ".join(r.value for r in UserRole)
                raise SystemExit(f"[error] 无效角色 '{role_filter}'，可选值: {valid}") from None
            q = q.filter(User.role == role_filter)
        if getattr(args, "active", False):
            q = q.filter(User.is_active.is_(True))
        if getattr(args, "inactive", False):
            q = q.filter(User.is_active.is_(False))
        return list(q.order_by(User.id).all())
    finally:
        db.close()


# ── cmd_import ─


@dataclass
class ImportRowResult:
    row_index: int
    status: str  # "ok" / "skipped" / "failed"
    message: str
    user_id: int | None = None
    username: str | None = None
    generated_password: str | None = None


@dataclass
class ImportReport:
    total: int
    ok: list[ImportRowResult]
    skipped: list[ImportRowResult]
    failed: list[ImportRowResult]


def _validate_row(row: dict[str, Any]) -> str | None:
    """校验行数据，返回错误原因（None 表示 OK）."""
    username = str(row.get("username", "") or "").strip()
    if not username:
        return "缺少 username"
    if len(username) < 2:
        return "username 至少 2 个字符"

    role = str(row.get("role", "") or "").strip() or UserRole.USER.value
    try:
        UserRole(role)
    except ValueError:
        valid = ", ".join(r.value for r in UserRole)
        return f"无效角色 '{role}'，可选值: {valid}"

    password = str(row.get("password", "") or "").strip()
    if password and len(password) < 6:
        return "password 至少 6 位"

    return None


def cmd_import(args: argparse.Namespace) -> ImportReport:
    """从 csv / xlsx 批量导入用户.

    - 逐行处理，失败不回滚
    - username 冲突 → 跳过（不修改已有用户）
    - role 非法 / 密码过短 / username 缺失 → 该行 failed
    - password 留空 → 自动生成 12 位
    - --dry-run 只做校验 + 打印，不写入 DB
    """
    path = Path(args.file)
    rows = _open_tabfile(path)

    dry_run = bool(getattr(args, "dry_run", False))
    report = ImportReport(total=len(rows), ok=[], skipped=[], failed=[])

    for idx, raw_row in enumerate(rows, start=1):
        error = _validate_row(raw_row)
        if error:
            report.failed.append(ImportRowResult(row_index=idx, status="failed", message=error))
            continue

        username = str(raw_row.get("username", "")).strip()
        email_val = raw_row.get("email", "")
        email = str(email_val).strip() if email_val else None
        nickname = str(raw_row.get("nickname", "")).strip() or ""
        role = str(raw_row.get("role", "") or "").strip() or UserRole.USER.value
        password = str(raw_row.get("password", "") or "").strip()

        generated_pw: str | None = None
        if not password:
            password = _generate_password()
            generated_pw = password

        if dry_run:
            # dry-run 只校验，不检查 DB 冲突
            report.ok.append(
                ImportRowResult(
                    row_index=idx,
                    status="ok",
                    message="预演通过",
                    username=username,
                    generated_password=generated_pw,
                )
            )
            continue

        # DB 操作块（dry_run=False 时才有意义）
        _import_single_user(report, idx, username, email, nickname, role, password, generated_pw)

    return report


def _import_single_user(
    report: ImportReport,
    row_index: int,
    username: str,
    email: str | None,
    nickname: str,
    role: str,
    password: str,
    generated_pw: str | None,
) -> None:
    """导入单个用户（带 DB 写入 + 冲突跳过 + 异常回滚）."""
    db = _get_session()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing is not None:
            report.skipped.append(
                ImportRowResult(
                    row_index=row_index,
                    status="skipped",
                    message=f"username 已存在 (id={existing.id})",
                    username=username,
                )
            )
            return

        try:
            user = User(
                username=username,
                email=email,
                nickname=nickname,
                role=role,
            )
            user.set_password(password)
            db.add(user)
            db.commit()
            db.refresh(user)
            report.ok.append(
                ImportRowResult(
                    row_index=row_index,
                    status="ok",
                    message="",
                    user_id=user.id,
                    username=username,
                    generated_password=generated_pw,
                )
            )
        except Exception as exc:
            db.rollback()
            report.failed.append(
                ImportRowResult(
                    row_index=row_index,
                    status="failed",
                    message=f"DB 错误: {exc}",
                    username=username,
                )
            )
    finally:
        db.close()
