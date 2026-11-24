"""行回收站保留期清理 + CLI 测试（ADR 0139 C5）。

覆盖：
- `purge_expired_rows`：过期清、未过期留、`days=0` 关闭、dry-run 不动数据、
  `_trashed_at IS NULL` 的历史已删行不自动清理（只在报告里计 unknown_time）、分批
- `cndb tables purge-trash`：--json 报告形状、默认 dry-run、--apply 真删
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core.rows_retention import purge_expired_rows
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def owner(db):
    from cndb.plugins.accounts.models import User

    u = User(username="retention_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="RetentionWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="保留期表")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    f = DataField(table_id=dt.id, name="名称", field_type="text", order=0)
    f.ensure_db_name()
    db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    return dt


def _make_trashed(db, table, name: str, *, days_ago: float | None) -> int:
    """建一行并软删；`days_ago=None` 表示把 `_trashed_at` 置空（模拟早期已删行）."""
    engine = db.get_bind()
    row = rec.create_row(engine, table, {"名称": name})
    rec.trash_rows(engine, table, [row["id"]], db=db)
    sa = ddl.get_reflected_table(engine, table.db_table_name)
    value = None if days_ago is None else datetime.now(UTC) - timedelta(days=days_ago)
    with engine.begin() as conn:
        conn.execute(sa.update().where(sa.c.id == row["id"]).values(_trashed_at=value))
    return int(row["id"])


def _physical_ids(db, table) -> list[int]:
    sa = ddl.get_reflected_table(db.get_bind(), table.db_table_name)
    with db.get_bind().connect() as conn:
        return [int(r[0]) for r in conn.execute(select(sa.c.id).order_by(sa.c.id)).all()]


class TestPurgeExpiredRows:
    def test_purges_only_expired(self, db, table):
        expired = _make_trashed(db, table, "过期", days_ago=40)
        fresh = _make_trashed(db, table, "未过期", days_ago=2)

        report = purge_expired_rows(db, days=30)

        assert report["purged"] == 1
        assert expired not in _physical_ids(db, table)
        assert fresh in _physical_ids(db, table)
        entry = report["tables"][0]
        assert entry["expired"] == 1 and entry["purged"] == 1

    def test_days_zero_disables(self, db, table):
        _make_trashed(db, table, "过期", days_ago=400)
        report = purge_expired_rows(db, days=0)
        assert report["purged"] == 0
        assert report["tables"] == []
        assert len(_physical_ids(db, table)) == 1

    def test_dry_run_keeps_rows(self, db, table):
        expired = _make_trashed(db, table, "过期", days_ago=40)
        report = purge_expired_rows(db, days=30, dry_run=True)
        assert report["dry_run"] is True
        assert report["tables"][0]["expired"] == 1
        assert report["tables"][0]["purged"] == 0
        assert expired in _physical_ids(db, table)

    def test_unknown_trashed_at_not_purged(self, db, table):
        """ADR 0139 D5：`_trashed_at` 为空的历史已删行不自动清理，只计数."""
        unknown = _make_trashed(db, table, "时间未知", days_ago=None)
        # 默认列表看不到，但物理行在
        assert unknown in _physical_ids(db, table)

        report = purge_expired_rows(db, days=1)
        assert report["purged"] == 0
        assert report["unknown_time"] == 1
        assert report["tables"][0]["unknown_time"] == 1
        assert unknown in _physical_ids(db, table)

    def test_batching_uses_small_batches(self, db, table):
        ids = [_make_trashed(db, table, f"行{i}", days_ago=40) for i in range(5)]
        report = purge_expired_rows(db, days=30, batch_size=2)
        assert report["purged"] == 5
        assert _physical_ids(db, table) == []
        assert ids

    def test_scope_by_workspace_and_table(self, db, ws, table):
        other = DataTable(workspace_id=ws.id, name="另一张表")
        other.ensure_db_name()
        db.add(other)
        db.commit()
        db.refresh(other)
        ddl.create_table(db.get_bind(), other)
        _make_trashed(db, table, "本表", days_ago=40)
        _make_trashed(db, other, "他表", days_ago=40)

        report = purge_expired_rows(db, days=30, table_id=table.id)
        assert report["purged"] == 1
        assert [t["table_id"] for t in report["tables"]] == [int(table.id)]
        assert len(_physical_ids(db, other)) == 1

        report = purge_expired_rows(db, days=30, workspace_id=ws.id)
        assert report["purged"] == 1


class TestTablesCli:
    def _ns(self, **kwargs) -> argparse.Namespace:
        base = {"tables_cmd": "purge-trash", "days": None, "apply": False, "json": True}
        base.update(kwargs)
        return argparse.Namespace(**base)

    def test_cli_default_dry_run(self, db, table, monkeypatch, capsys):
        from cndb.cli import tables as cli_tables

        _make_trashed(db, table, "过期", days_ago=40)
        monkeypatch.setattr(cli_tables, "_get_session", lambda: db)

        cli_tables.tables_command(self._ns())

        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is True
        assert payload["tables"][0]["expired"] == 1
        assert len(_physical_ids(db, table)) == 1

    def test_cli_apply_deletes(self, db, table, monkeypatch, capsys):
        from cndb.cli import tables as cli_tables

        _make_trashed(db, table, "过期", days_ago=40)
        monkeypatch.setattr(cli_tables, "_get_session", lambda: db)

        cli_tables.tables_command(self._ns(apply=True))

        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is False
        assert payload["purged"] == 1
        assert _physical_ids(db, table) == []

    def test_cli_human_output(self, db, table, monkeypatch, capsys):
        from cndb.cli import tables as cli_tables

        _make_trashed(db, table, "过期", days_ago=40)
        _make_trashed(db, table, "时间未知", days_ago=None)
        monkeypatch.setattr(cli_tables, "_get_session", lambda: db)

        cli_tables.tables_command(self._ns(json=False))

        out = capsys.readouterr().out
        assert "体检（dry-run，未删除）" in out
        assert "不会自动清理" in out

    def test_cli_days_zero_message(self, db, monkeypatch, capsys):
        from cndb.cli import tables as cli_tables

        monkeypatch.setattr(cli_tables, "_get_session", lambda: db)
        cli_tables.tables_command(self._ns(days=0, json=False))
        assert "保留期已关闭" in capsys.readouterr().out


class TestCliSession:
    def test_get_session_opens_configured_db(self, tmp_path, monkeypatch, db):
        """CLI 入口自己开 session：目标库缺失元数据表时按 ORM 元数据补建（与 cndb views 一致）."""
        from sqlalchemy import create_engine, inspect

        from cndb.cli import tables as cli_tables
        from cndb.core.config import settings
        from cndb.models.base import Base

        db_path = tmp_path / "cli_tables.db"
        monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        engine.dispose()

        session = cli_tables._get_session()
        try:
            assert session is not None
            assert inspect(session.get_bind()).has_table("tables_datatable")
        finally:
            session.close()


class TestCliBoundaries:
    def test_unknown_subcommand_exits(self, db, monkeypatch, capsys):
        from cndb.cli import tables as cli_tables

        monkeypatch.setattr(cli_tables, "_get_session", lambda: db)
        with pytest.raises(SystemExit) as exc:
            cli_tables.tables_command(argparse.Namespace(tables_cmd="bogus"))
        assert exc.value.code == 2
        assert "未知 tables 子命令" in capsys.readouterr().err


class TestBackupKeepsTrashState:
    def test_archive_carries_trash_state(self, db, ws, owner, table):
        """ADR 0139 C10：归档对已删行附带 __trashed / __trashed_at（活动行不带）."""
        from cndb.plugins.workspaces.services import workspace_backup

        engine = db.get_bind()
        rec.create_row(engine, table, {"名称": "活动行"}, db=db)
        _make_trashed(db, table, "已删行", days_ago=3)

        backup, _files = workspace_backup.build_workspace_backup_v9(db, ws.id, owner)
        rows = backup["tables"][0]["rows"]
        by_name = {r["名称"]: r for r in rows}
        assert "__trashed" not in by_name["活动行"]
        assert by_name["已删行"]["__trashed"] is True
        assert by_name["已删行"]["__trashed_at"] is not None

    def test_restore_keeps_trashed_rows(self, db, ws, owner, table):
        """覆盖恢复后，原回收站里的行仍在回收站（不是悄悄变成活动行）."""
        from cndb.plugins.workspaces.services import workspace_backup
        from cndb.plugins.workspaces.services.workspace_restore import restore_workspace_from_backup

        engine = db.get_bind()
        rec.create_row(engine, table, {"名称": "活动行"}, db=db)
        _make_trashed(db, table, "已删行", days_ago=3)

        backup, _files = workspace_backup.build_workspace_backup_v9(db, ws.id, owner)
        restore_workspace_from_backup(ws.id, backup, None, owner, db)

        db.expire_all()
        restored = db.query(DataTable).filter(DataTable.workspace_id == ws.id).one_or_none()
        assert restored is not None
        sa = ddl.get_reflected_table(engine, restored.db_table_name)
        with engine.connect() as conn:
            states = sorted(bool(r[0]) for r in conn.execute(select(sa.c._trashed)).all())
        assert states == [False, True]
