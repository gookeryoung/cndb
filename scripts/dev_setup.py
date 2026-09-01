"""开发辅助脚本：创建超级用户、列出路由（由 Makefile su/routes 调用）.

用法：
    uv run python scripts/dev_setup.py --superuser   # 需 DJANGO_SUPERUSER_PASSWORD 环境变量
    uv run python scripts/dev_setup.py --routes
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cndb.settings.dev")

import django

django.setup()


def create_superuser() -> None:
    """创建超级用户：用户名/邮箱/密码取 DJANGO_SUPERUSER_* 环境变量，已存在则跳过."""
    from django.contrib.auth import get_user_model

    username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "admin")
    email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "admin@example.com")
    password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
    if not password:
        print("请先设置 DJANGO_SUPERUSER_PASSWORD 环境变量，例如：")
        print('  PowerShell:  $env:DJANGO_SUPERUSER_PASSWORD="你的密码"; make su')
        return
    user_model = get_user_model()
    if user_model.objects.filter(username=username).exists():
        print(f"超级用户 {username} 已存在，跳过创建")
        return
    user_model.objects.create_superuser(username, email, password)
    print(f"超级用户 {username} 创建成功")


def show_routes() -> None:
    """按 pattern 排序打印全部 URL 路由."""
    from django.urls import get_resolver

    def walk(patterns: list[object], prefix: str = "") -> None:
        for pattern in patterns:
            route = prefix + str(pattern.pattern)
            if hasattr(pattern, "url_patterns"):
                walk(pattern.url_patterns, route)  # type: ignore[attr-defined]
            else:
                callback = pattern.callback  # type: ignore[attr-defined]
                name = getattr(pattern, "name", "") or ""  # type: ignore[attr-defined]
                print(f"{route:<52} {callback.__module__}.{callback.__qualname__} {name}")

    walk(get_resolver().url_patterns)  # type: ignore[bad-argument-type]


def main() -> None:
    """按命令行参数分发子命令."""
    if "--superuser" in sys.argv:
        create_superuser()
    elif "--routes" in sys.argv:
        show_routes()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
