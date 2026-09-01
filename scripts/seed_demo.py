"""演示数据脚本：写入示例用户/工作区/表/视图/行，幂等可重复执行（由 Makefile seed 调用）.

用法：uv run python scripts/seed_demo.py
"""

from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cndb.settings.dev")

import django

django.setup()

from cndb.accounts.models import User  # noqa: E402
from cndb.tables import records, services  # noqa: E402
from cndb.tables.models import DataView  # noqa: E402
from cndb.workspaces.models import Workspace, WorkspaceMember  # noqa: E402

DEMO_PASSWORD = "Demo-Pass-42"


def ensure_user(username: str, nickname: str) -> User:
    """取或建演示用户（已存在则仅更新昵称）."""
    user = User.objects.filter(username=username).first()
    if user is None:
        user = User.objects.create_user(username, f"{username}@example.com", DEMO_PASSWORD, nickname=nickname)
        print(f"  创建用户 {username}（密码 {DEMO_PASSWORD}）")
    return user


def main() -> None:
    """写入演示数据：两个用户 + 工作区 + 任务表（看板/日历/表单视图）+ 示例行."""
    print("写入演示数据...")
    owner = ensure_user("demo-owner", "演示管理员")
    editor = ensure_user("demo-editor", "演示编辑")

    workspace, created = Workspace.objects.get_or_create(name="演示工作区")
    if created:
        print("  创建工作区 演示工作区")
    WorkspaceMember.objects.get_or_create(workspace=workspace, user=owner, role=WorkspaceMember.Role.OWNER)
    WorkspaceMember.objects.get_or_create(workspace=workspace, user=editor, role=WorkspaceMember.Role.EDITOR)

    if DataView.objects.filter(table__workspace=workspace, table__name="任务表").exists():
        print("演示数据已存在，跳过（如需重建请先删除演示工作区）")
        return

    table = services.create_table(
        workspace=workspace,
        name="任务表",
        field_defs=[
            {"name": "标题", "field_type": "text"},
            {"name": "状态", "field_type": "single_select", "config": {"choices": ["待办", "进行中", "完成"]}},
            {"name": "优先级", "field_type": "number", "config": {"precision": 3, "scale": 0}},
            {"name": "标签", "field_type": "multi_select", "config": {"choices": ["前端", "后端", "紧急"]}},
            {"name": "截止", "field_type": "date"},
        ],
    )
    print("  创建表 任务表（含 5 个字段与默认视图）")

    DataView.objects.create(table=table, name="看板")
    DataView.objects.create(table=table, name="日历")
    DataView.objects.create(
        table=table,
        name="需求收集",
        view_type=DataView.ViewType.FORM,
        public=True,
        form_options={
            "title": "需求收集表",
            "description": "欢迎提交你的需求，我们会尽快跟进",
            "submit_text": "提交需求",
            "fields": {
                "标题": {"enabled": True, "required": True},
                "标签": {"enabled": True},
            },
        },
    )
    shared = DataView.objects.create(table=table, name="进度共享", public=True)
    print(f"  创建视图 看板/日历/需求收集(公开表单)/进度共享(共享 slug: {shared.slug})")

    rows = [
        {"标题": "搭建登录页", "状态": "完成", "优先级": Decimal("1"), "标签": ["前端"], "截止": date(2026, 8, 20)},
        {"标题": "行数据 CRUD", "状态": "完成", "优先级": Decimal("2"), "标签": ["后端"], "截止": date(2026, 8, 28)},
        {
            "标题": "看板视图",
            "状态": "进行中",
            "优先级": Decimal("3"),
            "标签": ["前端", "紧急"],
            "截止": date(2026, 9, 5),
        },
        {"标题": "日历视图", "状态": "进行中", "优先级": Decimal("3"), "标签": ["前端"], "截止": date(2026, 9, 8)},
        {
            "标题": "行内编辑",
            "状态": "待办",
            "优先级": Decimal("4"),
            "标签": ["前端", "后端"],
            "截止": date(2026, 9, 15),
        },
        {"标题": "Excel 导入", "状态": "待办", "优先级": Decimal("5"), "标签": ["后端"], "截止": None},
    ]
    cleaned = [records.clean_row(table, row, partial=True) for row in rows]
    records.insert_rows(table, cleaned)
    print(f"  写入 {len(rows)} 行示例数据")
    print("完成。开发账号：demo-owner / demo-editor，密码均为 Demo-Pass-42")


if __name__ == "__main__":
    main()
