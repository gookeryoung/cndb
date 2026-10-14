"""cndb users 子命令 —— 运维侧用户管理（不走 API 鉴权，直接操作数据库）.

子命令：
- create    创建单个用户（可指定角色 / 自动生成密码）
- delete    删除用户（检查 OWNER 工作区；--cascade 级联删除）
- list      列出用户（按角色 / 激活状态筛选）
- import    从 csv / xlsx 批量导入用户（逐行 + 不回滚 + 报告）

实现按层拆到同包：io（输入读取）/ db（会话与查询）/ commands（业务）/ printing（输出）。

注意：`users_command` 与 `register_users_subparser` **必须留在本模块** —— 测试通过
`monkeypatch.setattr("cndb.cli.users.<cmd>", ...)` 替换分发目标，而分发函数读取的正是
本模块的全局命名空间；若把它移到子模块，patch 会静默失效。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from cndb.cli.users.commands import (
    CreateResult,
    DeleteCheckResult,
    ImportReport,
    ImportRowResult,
    _import_single_user,
    _validate_row,
    cmd_create,
    cmd_delete,
    cmd_delete_check,
    cmd_import,
    cmd_list,
)
from cndb.cli.users.db import (
    _get_session,
    _list_member_count,
    _list_owned_workspaces,
    _resolve_user,
)
from cndb.cli.users.io import (
    _USER_IMPORT_COLUMN_ALIASES,
    _generate_password,
    _map_header,
    _map_row,
    _normalize_header,
    _open_tabfile,
    _pw_field,
    _read_csv,
    _read_xlsx,
)
from cndb.cli.users.printing import (
    print_create_result,
    print_delete_check,
    print_delete_result,
    print_import_report,
    print_list,
)
from cndb.plugins.accounts.models import UserRole


def register_users_subparser(sub: Any) -> None:
    """向顶层 ArgumentParser 注册 `cndb users` 子命令组."""
    p_users = sub.add_parser("users", help="用户管理（create/delete/list/import）")
    users_sub = p_users.add_subparsers(dest="users_cmd")

    # --- create ---
    p_create = users_sub.add_parser("create", help="创建单个用户")
    p_create.add_argument("-u", "--username", required=True, help="用户名（必填）")
    p_create.add_argument("-p", "--password", default=None, help="明文密码（留空自动生成 12 位）")
    p_create.add_argument("-e", "--email", default=None, help="邮箱（可选）")
    p_create.add_argument("-n", "--nickname", default=None, help="昵称（可选，留空则用角色中文名）")
    p_create.add_argument(
        "-r",
        "--role",
        default=UserRole.USER.value,
        help=f"角色（默认 {UserRole.USER.value}）: system_admin / security_admin / audit_admin / user",
    )
    p_create.add_argument("--is-superuser", action="store_true", help="同时设置 is_superuser=True（危险）")

    # --- delete ---
    p_delete = users_sub.add_parser("delete", help="删除用户（检查 OWNER 工作区）")
    p_delete.add_argument("target", help="用户名或用户 ID")
    p_delete.add_argument("--cascade", action="store_true", help="级联删除用户作为 OWNER 的工作区（不可逆）")
    p_delete.add_argument("--yes", action="store_true", help="跳过二次确认（供脚本调用）")
    p_delete.add_argument("--check-only", action="store_true", help="仅打印安全检查结果，不实际删除")

    # --- list ---
    p_list = users_sub.add_parser("list", help="列出用户")
    p_list.add_argument(
        "-r", "--role", default=None, help="按角色筛选: system_admin / security_admin / audit_admin / user"
    )
    p_list.add_argument("--active", action="store_true", help="只列出 is_active=True")
    p_list.add_argument("--inactive", action="store_true", help="只列出 is_active=False")

    # --- import ---
    p_import = users_sub.add_parser("import", help="从 csv / xlsx 批量导入用户")
    p_import.add_argument("file", help="源文件路径（.csv / .xlsx）")
    p_import.add_argument("--dry-run", action="store_true", help="只做校验和预演，不写入 DB")


def users_command(args: argparse.Namespace) -> None:
    """分发 `cndb users <sub>`."""
    cmd = getattr(args, "users_cmd", None)
    if cmd is None:
        print("[error] 缺少 users 子命令，可用: create / delete / list / import", file=sys.stderr)
        sys.exit(2)

    if cmd == "create":
        result = cmd_create(args)
        print_create_result(result)
    elif cmd == "delete":
        if getattr(args, "check_only", False):
            check = cmd_delete_check(args)
            print_delete_check(check)
        else:
            result = cmd_delete(args)
            print_delete_result(result)
    elif cmd == "list":
        users = cmd_list(args)
        print_list(users)
    elif cmd == "import":
        report = cmd_import(args)
        target = Path(args.file)
        print_import_report(report, target, dry_run=bool(getattr(args, "dry_run", False)))
    else:  # pragma: no cover — argparse 已在子命令层校验
        print(f"[error] 未知子命令 '{cmd}'", file=sys.stderr)
        sys.exit(2)


__all__ = [
    "_USER_IMPORT_COLUMN_ALIASES",
    "CreateResult",
    "DeleteCheckResult",
    "ImportReport",
    "ImportRowResult",
    "_generate_password",
    "_get_session",
    "_import_single_user",
    "_list_member_count",
    "_list_owned_workspaces",
    "_map_header",
    "_map_row",
    "_normalize_header",
    "_open_tabfile",
    "_pw_field",
    "_read_csv",
    "_read_xlsx",
    "_resolve_user",
    "_validate_row",
    "cmd_create",
    "cmd_delete",
    "cmd_delete_check",
    "cmd_import",
    "cmd_list",
    "print_create_result",
    "print_delete_check",
    "print_delete_result",
    "print_import_report",
    "print_list",
    "register_users_subparser",
    "users_command",
]
