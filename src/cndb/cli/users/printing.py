"""用户管理命令的输出层：结果落到 stdout 的格式化."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cndb.cli.users.commands import (
    CreateResult,
    DeleteCheckResult,
    ImportReport,
)
from cndb.plugins.accounts.models import User


def print_create_result(result: CreateResult) -> None:
    parts = [f"[ok] id={result.user_id}, username={result.username}, role={result.role}"]
    if result.note:
        parts.append(result.note)
    print(" ".join(parts))
    print(f"     password: {result.password}")


def print_delete_check(check: DeleteCheckResult | None) -> None:
    if check is None:
        print("[info] 用户不存在")
        return
    print(f"[info] 目标: id={check.user_id}, username={check.username}, superuser={check.is_superuser}")
    print(f"[info] OWNER 工作区: {len(check.owned_workspaces)} 个")
    print(f"[info] 成员关系: {check.member_count} 条（通过外键自动清理）")
    if check.owned_workspaces:
        for ws in check.owned_workspaces:
            print(f"       - #{ws.id} {ws.name}")


def print_delete_result(result: dict[str, Any]) -> None:
    print(f"[ok] 已删除用户 {result['deleted_username']} (id={result['deleted_user_id']})")
    if result["deleted_workspace_count"]:
        print(f"[ok] 级联删除了 {result['deleted_workspace_count']} 个 OWNER 工作区: {result['deleted_workspace_ids']}")


def print_list(users: list[User]) -> None:
    if not users:
        print("[info] 没有匹配的用户")
        return
    # 表头
    print(f"{'id':>6}  {'username':<18}  {'role':<16}  {'nickname':<18}  {'active':<7}  {'su':<3}  {'email'}")
    print("-" * 80)
    for u in users:
        email = u.email or ""
        print(
            f"{u.id:>6}  {u.username:<18}  {u.role:<16}  {u.nickname:<18}  "
            f"{'yes' if u.is_active else 'no':<7}  {'Y' if u.is_superuser else '':<3}  {email}"
        )
    print(f"\n[info] 共 {len(users)} 条")


def print_import_report(report: ImportReport, target_file: Path, dry_run: bool) -> None:
    mode = "预演模式" if dry_run else "实际导入"
    print(f"[info] users import: {mode}  源文件={target_file}  总行数={report.total}")
    print(f"  ok={len(report.ok)}  skipped={len(report.skipped)}  failed={len(report.failed)}")
    if report.ok:
        print("")
        print("成功:")
        for r in report.ok:
            pw_note = f"  密码={r.generated_password}" if r.generated_password else ""
            print(f"  L{r.row_index}: {r.username}{pw_note}")
    if report.skipped:
        print("")
        print("跳过:")
        for r in report.skipped:
            print(f"  L{r.row_index}: {r.username} — {r.message}")
    if report.failed:
        print("")
        print("失败:")
        for r in report.failed:
            print(f"  L{r.row_index}: {r.message}")
    if not dry_run and report.ok and any(r.generated_password for r in report.ok):
        print("")
        print("[warn] 部分用户密码已自动生成，务必通知用户登录后尽快修改！")
