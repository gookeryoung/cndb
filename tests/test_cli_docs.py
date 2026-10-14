"""cndb docs CLI 测试：外存孤儿文件体检 / 回收命令.

测试策略与 test_cli_users.py 一致：直接调用 cli.docs 函数（不走 subprocess），
用 tmp_path 建临时 SQLite 与临时外存目录。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from cndb.core.config import settings

DOCS_API = "/api/v1/workspaces/{wid}/documents"


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch) -> Path:
    """临时 SQLite（settings.DATABASE_URL）+ 临时外存根目录（content._DOCS_DIR）."""
    from sqlalchemy import create_engine

    import cndb.plugins.accounts.models
    import cndb.plugins.change_requests.models
    import cndb.plugins.documents.models
    import cndb.plugins.issues.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401
    from cndb.models.base import Base
    from cndb.plugins.documents.services import content as content_service

    db_path = tmp_path / "cli_docs.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    engine.dispose()

    docs_root = tmp_path / "docs"
    docs_root.mkdir(parents=True)
    monkeypatch.setattr(content_service, "_DOCS_DIR", docs_root)
    return docs_root


def _ns(**kwargs) -> argparse.Namespace:
    ns = argparse.Namespace()
    for key, value in kwargs.items():
        setattr(ns, key, value)
    return ns


def _seed_orphan(root: Path, name: str = "v1.md.gz", doc_dir: str = "999") -> Path:
    target_dir = root / doc_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / name
    path.write_bytes(b"orphan")
    return path


class TestCmdGc:
    def test_dry_run_reports_without_deleting(self, cli_env, capsys):
        from cndb.cli.docs import cmd_gc, docs_command

        orphan = _seed_orphan(cli_env)

        payload = cmd_gc(_ns(apply=False))

        assert payload["dry_run"] is True
        assert payload["root"] == str(cli_env)
        assert len(payload["orphan_files"]) == 1
        assert payload["orphan_bytes"] == 6
        assert orphan.is_file()

        docs_command(_ns(docs_cmd="gc", apply=False, json=False))
        out = capsys.readouterr().out
        assert "[docs gc]" in out and "dry-run" in out and "--apply" in out

    def test_apply_deletes_orphans(self, cli_env):
        from cndb.cli.docs import cmd_gc

        orphan = _seed_orphan(cli_env)

        payload = cmd_gc(_ns(apply=True))

        assert payload["dry_run"] is False
        assert payload["removed_files"] == 1
        assert payload["removed_dirs"] == 1
        assert not orphan.exists()

    def test_json_output_is_parseable(self, cli_env, capsys):
        from cndb.cli.docs import docs_command

        _seed_orphan(cli_env)
        docs_command(_ns(docs_cmd="gc", apply=False, json=True))
        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is True
        assert payload["orphan_files"][0]["reason"] == "失去版本引用"

    def test_plain_output_lists_orphan_and_missing(self, cli_env, capsys):
        from cndb.cli.docs import _print_gc

        _print_gc(
            {
                "root": str(cli_env),
                "dry_run": False,
                "referenced_files": 2,
                "missing_files": ["/tmp/docs/1/v3.md.gz"],
                "orphan_files": [{"path": "/tmp/docs/9/v9.md.gz", "size": 3, "reason": "失去版本引用"}],
                "orphan_bytes": 3,
                "removed_files": 1,
                "removed_dirs": 1,
            }
        )
        out = capsys.readouterr().out
        assert "已删除文件 1 个" in out
        assert "丢失: /tmp/docs/1/v3.md.gz" in out
        assert "失去版本引用" in out

    def test_missing_subcommand_exits(self, capsys):
        from cndb.cli.docs import docs_command

        with pytest.raises(SystemExit) as exc:
            docs_command(_ns(docs_cmd=None))
        assert exc.value.code == 2
        assert "缺少 docs 子命令" in capsys.readouterr().err


class TestRegisterDocsSubparser:
    def test_parser_registers_gc_options(self):
        parser = argparse.ArgumentParser(prog="cndb")
        sub = parser.add_subparsers(dest="command")
        from cndb.cli.docs import register_docs_subparser

        register_docs_subparser(sub)

        args = parser.parse_args(["docs", "gc", "--apply", "--json"])
        assert args.command == "docs"
        assert args.docs_cmd == "gc"
        assert args.apply is True and args.json is True

        plain = parser.parse_args(["docs", "gc"])
        assert plain.apply is False and plain.json is False
