"""`cndb seed` 防误伤守卫（需求 0106 C1）.

seed 仍是开发 / e2e 夹具：空库直接执行；目标库已有用户或工作区时默认拒绝，
只有显式 `--force` 才重建。
"""

from __future__ import annotations

import argparse

import pytest
from sqlalchemy import create_engine, text

from cndb.cli.seed.runner import _database_has_data, seed


def _make_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'guard.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE accounts_user (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE workspaces_workspace (id INTEGER PRIMARY KEY)"))
    return engine


def test_database_has_data_false_for_empty_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    assert _database_has_data(engine) is False


def test_database_has_data_true_when_users_exist(tmp_path):
    engine = _make_engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO accounts_user (id) VALUES (1)"))
    assert _database_has_data(engine) is True


def test_database_has_data_true_when_workspaces_exist(tmp_path):
    engine = _make_engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO workspaces_workspace (id) VALUES (1)"))
    assert _database_has_data(engine) is True


def test_seed_refuses_non_empty_db_without_force(monkeypatch, capsys):
    from cndb.cli.seed import runner

    monkeypatch.setattr(runner, "_database_has_data", lambda _engine: True)

    with pytest.raises(SystemExit) as exc:
        seed(argparse.Namespace(force=False))

    assert exc.value.code == 2
    message = capsys.readouterr().err
    assert "拒绝覆盖" in message
    assert "创建示例工作区" in message
