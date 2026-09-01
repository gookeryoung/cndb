"""Django 管理入口（开发用，不随 wheel 发布）."""

from __future__ import annotations

import os
import sys


def main() -> None:
    """执行 Django 管理命令."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cndb.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError("未能导入 Django，请确认已安装依赖：uv sync --extra dev") from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
