"""已存表清洗测试：分批统计 / 预览一致 / 执行写回 / 审计（plan 步骤 9）。"""

from __future__ import annotations

import json

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import AuditLog, DataField, DataTable, GovernanceTask
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core.records import bulk_create, get_row
from cndb.plugins.tables.services.governance import clean as gov_clean
from cndb.plugins.tables.services.governance.tasks import (
    GovernanceTaskError,
    _transition_status,
    create_governance_task,
)
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def owner(db):
    u = User(username="gov_clean_owner", nickname="GovCleanOwner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="GovCleanWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


def _make_table(db, ws, name: str = "清洗表") -> DataTable:
    dt = DataTable(workspace_id=ws.id, name=name)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for fname, ftype in [("姓名", "text"), ("城市", "text"), ("年龄", "number")]:
        f = DataField(table_id=dt.id, name=fname, field_type=ftype)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(db.get_bind(), dt)
    return dt


def _run_clean(db, table, actions: list[dict], *, preview: bool = True) -> GovernanceTask:
    task = create_governance_task(
        db, table=table, user_id=None, kind="clean", config={"actions": actions, "preview": preview}
    )
    _transition_status(task, "running")
    db.commit()
    gov_clean.execute_clean_task(db, task)
    db.refresh(task)
    return task


class TestCleanPreview:
    """预览模式：不改库，产出受影响统计与样例."""

    def test_preview_no_db_change(self, db, ws) -> None:
        table = _make_table(db, ws)
        bulk_create(
            db.get_bind(),
            table,
            [{"姓名": " 张三 ", "年龄": None}, {"姓名": "李四", "年龄": 10}],
            db=db,
        )
        task = _run_clean(
            db,
            table,
            [
                {"action": "trim_whitespace", "column": "姓名"},
                {"action": "fill_null", "column": "年龄", "strategy": "mean"},
            ],
            preview=True,
        )
        assert task.status == "running"
        report = json.loads(task.report)
        assert report["mode"] == "preview"
        # 库未变
        assert get_row(db.get_bind(), table, 1, db=db)["姓名"] == " 张三 "
        affected = {(a["action"], a["column"]): a["affected_rows"] for a in report["affected"]}
        assert affected[("trim_whitespace", "姓名")] == 1
        assert affected[("fill_null", "年龄")] == 1

    def test_preview_mean_and_samples(self, db, ws) -> None:
        table = _make_table(db, ws)
        bulk_create(
            db.get_bind(),
            table,
            [{"年龄": None}, {"年龄": 10}, {"年龄": 20}, {"年龄": 30}],
            db=db,
        )
        task = _run_clean(db, table, [{"action": "fill_null", "column": "年龄", "strategy": "mean"}], preview=True)
        report = json.loads(task.report)
        assert report["affected"][0]["affected_rows"] == 1
        # 均值 = (10+20+30)/3 = 20
        assert report["samples"][0]["after"]["年龄"] == 20
        assert report["samples"][0]["row_id"] == 1

    def test_preview_drop_outliers_iqr(self, db, ws) -> None:
        table = _make_table(db, ws)
        bulk_create(
            db.get_bind(),
            table,
            [{"年龄": 1}, {"年龄": 2}, {"年龄": 3}, {"年龄": 4}, {"年龄": 5}, {"年龄": 100}],
            db=db,
        )
        task = _run_clean(db, table, [{"action": "drop_outliers", "column": "年龄", "strategy": "iqr"}], preview=True)
        report = json.loads(task.report)
        assert report["affected"][0]["affected_rows"] == 1
        assert report["samples"][0]["before"]["年龄"] == 100
        assert report["samples"][0]["after"]["年龄"] is None

    def test_preview_max_three_samples(self, db, ws) -> None:
        table = _make_table(db, ws)
        bulk_create(db.get_bind(), table, [{"姓名": " a "}, {"姓名": " b "}, {"姓名": " c "}, {"姓名": " d "}], db=db)
        task = _run_clean(db, table, [{"action": "trim_whitespace", "column": "姓名"}], preview=True)
        report = json.loads(task.report)
        assert len(report["samples"]) == 3


class TestCleanExecute:
    """执行模式：分批写回 + 审计."""

    def test_execute_updates_rows(self, db, ws) -> None:
        table = _make_table(db, ws)
        bulk_create(
            db.get_bind(),
            table,
            [
                {"姓名": " 张三 ", "城市": None, "年龄": None},
                {"姓名": "李四", "城市": "上海", "年龄": 10},
                {"年龄": 20},
            ],
            db=db,
        )
        task = _run_clean(
            db,
            table,
            [
                {"action": "trim_whitespace", "column": "姓名"},
                {"action": "fill_null", "column": "年龄", "strategy": "mean"},
                {"action": "fill_null", "column": "城市", "strategy": "default", "fill_value": "未知"},
            ],
            preview=False,
        )
        assert task.status == "running"
        report = json.loads(task.report)
        assert report["mode"] == "execute"
        # 均值 = (10+20)/2 = 15
        row1 = get_row(db.get_bind(), table, 1, db=db)
        assert row1["姓名"] == "张三"
        assert row1["年龄"] == 15
        assert row1["城市"] == "未知"
        assert get_row(db.get_bind(), table, 3, db=db)["姓名"] is None

    def test_execute_audits_and_progress(self, db, ws) -> None:
        table = _make_table(db, ws)
        bulk_create(db.get_bind(), table, [{"姓名": " 张三 "}], db=db)
        task = _run_clean(db, table, [{"action": "trim_whitespace", "column": "姓名"}], preview=False)
        logs = db.query(AuditLog).filter(AuditLog.table_id == table.id, AuditLog.action == "clean").all()
        assert len(logs) == 1
        assert task.total_groups >= 1
        assert task.done_groups == task.total_groups

    def test_unchanged_rows_not_written(self, db, ws) -> None:
        """值本就干净的行不产生 UPDATE（无审计外表现，仅验证无副作用）."""
        table = _make_table(db, ws)
        bulk_create(db.get_bind(), table, [{"姓名": "张三"}], db=db)
        task = _run_clean(db, table, [{"action": "trim_whitespace", "column": "姓名"}], preview=False)
        report = json.loads(task.report)
        assert report["updated_rows"] == 0


class TestCleanConsistency:
    """预览与执行结果一致（AC-3）."""

    def test_preview_matches_execute(self, db, ws) -> None:
        actions = [
            {"action": "trim_whitespace", "column": "姓名"},
            {"action": "fill_null", "column": "年龄", "strategy": "mean"},
            {"action": "drop_outliers", "column": "年龄", "strategy": "iqr"},
        ]
        rows = [
            {"姓名": " 张三 ", "年龄": None},
            {"姓名": " 李四 ", "年龄": 10},
            {"姓名": "王五", "年龄": 20},
            {"姓名": "赵六", "年龄": 1000},
        ]
        t1 = _make_table(db, ws, "一致性A")
        bulk_create(db.get_bind(), t1, [dict(r) for r in rows], db=db)
        preview_task = _run_clean(db, t1, actions, preview=True)
        preview_report = json.loads(preview_task.report)

        t2 = _make_table(db, ws, "一致性B")
        bulk_create(db.get_bind(), t2, [dict(r) for r in rows], db=db)
        execute_task = _run_clean(db, t2, actions, preview=False)
        execute_report = json.loads(execute_task.report)

        assert preview_report["affected"] == execute_report["affected"]


class TestCleanValidation:
    """配置校验."""

    def test_empty_actions_rejected(self, db, ws) -> None:
        table = _make_table(db, ws)
        task = create_governance_task(db, table=table, user_id=None, kind="clean", config={})
        _transition_status(task, "running")
        db.commit()
        with pytest.raises(GovernanceTaskError, match="actions"):
            gov_clean.execute_clean_task(db, task)

    def test_unknown_column_rejected(self, db, ws) -> None:
        table = _make_table(db, ws)
        task = create_governance_task(
            db,
            table=table,
            user_id=None,
            kind="clean",
            config={"actions": [{"action": "trim_whitespace", "column": "不存在"}]},
        )
        _transition_status(task, "running")
        db.commit()
        with pytest.raises(GovernanceTaskError, match="不存在"):
            gov_clean.execute_clean_task(db, task)

    def test_unknown_action_rejected(self, db, ws) -> None:
        table = _make_table(db, ws)
        task = create_governance_task(
            db,
            table=table,
            user_id=None,
            kind="clean",
            config={"actions": [{"action": "dedupe_rows", "column": "姓名"}]},
        )
        _transition_status(task, "running")
        db.commit()
        with pytest.raises(GovernanceTaskError, match="action"):
            gov_clean.execute_clean_task(db, task)
