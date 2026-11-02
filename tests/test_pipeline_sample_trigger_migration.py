"""示例流水线「工作区综合巡检」触发事件迁移（document.saved → record.updated）."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from alembic import command

from cndb.core.migrations import _build_config

PREVIOUS = "c8e2f4a6b8d0"
REVISION = "f1a2b3c4d5e6"

OLD_CONTENT = """# 工作区内容物综合巡检（ADR 0076 示例）：数据表 + 文档混合检查。
# document 检查族三类动作全覆盖，与数据表 job 并列执行互不阻断。
name: 工作区综合巡检
on:
  manual: false
  events: [document.saved]
jobs:
  文档体检:
    steps:
      - uses: document/links
"""


def _seed_row(db_path: Path, content: str = OLD_CONTENT) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS pipeline_workflow "
            "(id INTEGER PRIMARY KEY, name TEXT, content TEXT, compiled TEXT)"
        )
        conn.execute(
            "INSERT INTO pipeline_workflow (id, name, content, compiled) VALUES (1, '工作区综合巡检', ?, ?)",
            (content, json.dumps({}, ensure_ascii=False)),
        )
        conn.commit()


def _row(db_path: Path) -> tuple[str, dict]:
    with sqlite3.connect(str(db_path)) as conn:
        content, compiled = conn.execute("SELECT content, compiled FROM pipeline_workflow WHERE id = 1").fetchone()
    return str(content), json.loads(compiled)


def _upgrade(url: str, revision: str = REVISION) -> None:
    command.upgrade(_build_config(url), revision)


def _downgrade(url: str, revision: str = PREVIOUS) -> None:
    command.downgrade(_build_config(url), revision)


def test_upgrade_rewrites_seed_trigger_and_recompiles(tmp_path: Path):
    db_path = tmp_path / "pipeline.db"
    url = f"sqlite:///{db_path}"
    command.stamp(_build_config(url), PREVIOUS)
    _seed_row(db_path)

    _upgrade(url)

    content, compiled = _row(db_path)
    assert "  events: [record.updated]" in content
    assert "document.saved" not in content
    assert compiled["on"]["events"] == ["record.updated"]

    _downgrade(url)
    content, compiled = _row(db_path)
    assert "  events: [document.saved]" in content
    assert compiled["on"]["events"] == ["document.saved"]


def test_upgrade_keeps_user_edited_workflow(tmp_path: Path):
    db_path = tmp_path / "pipeline_edited.db"
    url = f"sqlite:///{db_path}"
    command.stamp(_build_config(url), PREVIOUS)
    edited = "# 我自己的巡检\nname: 我自己的巡检\non:\n  manual: true\n"
    _seed_row(db_path, edited)

    _upgrade(url)

    content, _ = _row(db_path)
    assert content == edited
