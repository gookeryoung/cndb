"""审计 / 事件流保留期清理（需求 0143 / 路线图 P0-2）.

覆盖：保留期默认值与关闭、dry-run 不改库、apply 真删、分批、逐表明细、CLI 输出。
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from cndb.core.events import CoreEvent
from cndb.plugins.tables.models import AuditLog, DataTable
from cndb.plugins.tables.services.core.audit_retention import (
    AUDIT_PURGE_BATCH_SIZE,
    purge_old_audit,
)
from cndb.plugins.workspaces.models import Workspace

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def ws(db):
    w = Workspace(name="AuditRetentionWS")
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    dt = DataTable(workspace_id=ws.id, name="审计表")
    dt.ensure_db_name()
    db.add(dt)
    db.commit()
    db.refresh(dt)
    return dt


def _mk_audit(db, table, *, days_ago: int, action: str = "update") -> int:
    entry = AuditLog(
        table_id=table.id,
        action=action,
        target_id=1,
        detail={"姓名": "旧"},
        created_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return int(entry.id)


def _mk_event(db, *, days_ago: int, action: str = "record.update") -> int:
    entry = CoreEvent(
        action=action,
        target_type="record",
        target_id="1",
        summary="x",
        created_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return int(entry.id)


def _count(db, model) -> int:
    with db.bind.connect() as conn:  # type: ignore[union-attr]
        return int(conn.execute(select(func.count()).select_from(model)).scalar() or 0)


class TestPurgeOldAudit:
    def test_dry_run_reports_without_deleting(self, db, table):
        _mk_audit(db, table, days_ago=400)
        _mk_audit(db, table, days_ago=10)
        _mk_event(db, days_ago=400)
        _mk_event(db, days_ago=10)

        report = purge_old_audit(db, days=180)

        assert report["dry_run"] is True
        assert report["days"] == 180
        assert report["audit_deleted"] == 1
        assert report["events_deleted"] == 1
        assert report["tables"] == [{"table_id": int(table.id), "audit_rows": 1}]
        # 未真删
        assert _count(db, AuditLog) == 2
        assert _count(db, CoreEvent) == 2

    def test_apply_deletes_expired_only(self, db, table):
        old_audit = _mk_audit(db, table, days_ago=400)
        new_audit = _mk_audit(db, table, days_ago=5)
        old_event = _mk_event(db, days_ago=400)
        new_event = _mk_event(db, days_ago=5)

        report = purge_old_audit(db, days=180, dry_run=False)

        assert report["audit_deleted"] == 1
        assert report["events_deleted"] == 1
        db.expire_all()
        assert db.get(AuditLog, old_audit) is None
        assert db.get(AuditLog, new_audit) is not None
        assert db.get(CoreEvent, old_event) is None
        assert db.get(CoreEvent, new_event) is not None

    def test_days_zero_disables(self, db, table):
        _mk_audit(db, table, days_ago=4000)
        report = purge_old_audit(db, days=0, dry_run=False)
        assert report["days"] == 0
        assert report["cutoff"] is None
        assert report["audit_deleted"] == 0
        assert _count(db, AuditLog) == 1

    def test_default_days_from_settings(self, db, table, monkeypatch):
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "AUDIT_RETENTION_DAYS", 7)
        _mk_audit(db, table, days_ago=10)
        _mk_audit(db, table, days_ago=1)
        report = purge_old_audit(db, dry_run=False)
        assert report["days"] == 7
        assert report["audit_deleted"] == 1

    def test_batching_deletes_everything(self, db, table):
        for i in range(5):
            _mk_audit(db, table, days_ago=400 + i)
        report = purge_old_audit(db, days=180, dry_run=False, batch_size=2)
        assert report["audit_deleted"] == 5
        assert _count(db, AuditLog) == 0

    def test_idempotent_second_run(self, db, table):
        _mk_audit(db, table, days_ago=400)
        assert purge_old_audit(db, days=180, dry_run=False)["audit_deleted"] == 1
        assert purge_old_audit(db, days=180, dry_run=False)["audit_deleted"] == 0

    def test_empty_tables_are_safe(self, db):
        report = purge_old_audit(db, days=1, dry_run=False)
        assert report["audit_deleted"] == 0 and report["events_deleted"] == 0
        assert report["tables"] == []

    def test_negative_days_treated_as_disabled(self, db, table):
        _mk_audit(db, table, days_ago=9999)
        assert purge_old_audit(db, days=-5, dry_run=False)["audit_deleted"] == 0


class TestPurgeAuditCli:
    def _ns(self, **kwargs) -> argparse.Namespace:
        base = {"tables_cmd": "purge-audit", "days": None, "apply": False, "json": True}
        base.update(kwargs)
        return argparse.Namespace(**base)

    def test_cli_dry_run_json(self, db, table, monkeypatch, capsys):
        from cndb.cli import tables as cli_tables

        _mk_audit(db, table, days_ago=400)
        monkeypatch.setattr(cli_tables, "_get_session", lambda: db)

        cli_tables.tables_command(self._ns(days=180))

        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is True
        assert payload["audit_deleted"] == 1
        assert _count(db, AuditLog) == 1

    def test_cli_apply_deletes(self, db, table, monkeypatch, capsys):
        from cndb.cli import tables as cli_tables

        _mk_audit(db, table, days_ago=400)
        monkeypatch.setattr(cli_tables, "_get_session", lambda: db)

        cli_tables.tables_command(self._ns(days=180, apply=True))

        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is False
        assert _count(db, AuditLog) == 0

    def test_cli_human_output(self, db, table, monkeypatch, capsys):
        from cndb.cli import tables as cli_tables

        _mk_audit(db, table, days_ago=400)
        monkeypatch.setattr(cli_tables, "_get_session", lambda: db)

        cli_tables.tables_command(self._ns(days=180, json=False))

        out = capsys.readouterr().out
        assert "体检（dry-run，未删除）" in out
        assert "审计日志 1 行" in out
        assert "--apply" in out

    def test_cli_days_zero_message(self, db, monkeypatch, capsys):
        from cndb.cli import tables as cli_tables

        monkeypatch.setattr(cli_tables, "_get_session", lambda: db)
        cli_tables.tables_command(self._ns(days=0, json=False))
        assert "保留期已关闭" in capsys.readouterr().out

    def test_batch_size_constant_is_positive(self):
        assert AUDIT_PURGE_BATCH_SIZE >= 1
