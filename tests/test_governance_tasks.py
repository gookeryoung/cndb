"""治理任务执行器测试：创建校验 / 状态机 / 分发 / 后台调度（plan 步骤 5）。"""

from __future__ import annotations

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable, GovernanceTask
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.governance import tasks as gov_tasks
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def gov_owner(db):
    u = User(username="gov_tasks_owner", nickname="GovTasksOwner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def gov_table(db, gov_owner):
    """带工作区的表（不含物理表，供创建/状态机测试用）."""
    w = Workspace(name="GovTasksWS", created_by_id=gov_owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=gov_owner.id, role=WorkspaceRole.OWNER))
    dt = DataTable(workspace_id=w.id, name="GovTasksTable")
    dt.ensure_db_name()
    db.add(dt)
    db.commit()
    db.refresh(dt)
    return dt


@pytest.fixture
def detect_ready_table(db, gov_owner):
    """带 text 字段且物理表已建的表（供后台调度真实执行用）."""
    w = Workspace(name="GovTasksWS2", created_by_id=gov_owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=gov_owner.id, role=WorkspaceRole.OWNER))
    dt = DataTable(workspace_id=w.id, name="GovTasksDetectTable")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    f = DataField(table_id=dt.id, name="姓名", field_type="text")
    f.ensure_db_name()
    db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(db.get_bind(), dt)
    return dt


class TestCreateGovernanceTask:
    """create_governance_task：创建校验与同表 active 互斥."""

    def test_create_defaults(self, db, gov_table, gov_owner) -> None:
        task = gov_tasks.create_governance_task(
            db, table=gov_table, user_id=gov_owner.id, kind="detect", config={"match_fields": ["姓名"]}
        )
        assert task.id is not None
        assert task.kind == "detect"
        assert task.status == "pending"
        assert task.progress == 0
        assert task.config == {"match_fields": ["姓名"]}
        assert task.user_id == gov_owner.id

    def test_invalid_kind_rejected(self, db, gov_table) -> None:
        with pytest.raises(gov_tasks.GovernanceTaskError):
            gov_tasks.create_governance_task(db, table=gov_table, user_id=None, kind="export", config={})

    def test_same_table_rejects_second_active_task(self, db, gov_table) -> None:
        gov_tasks.create_governance_task(db, table=gov_table, user_id=None, kind="detect", config={})
        with pytest.raises(gov_tasks.GovernanceTaskError):
            gov_tasks.create_governance_task(db, table=gov_table, user_id=None, kind="clean", config={})

    @pytest.mark.parametrize("finished", ["done", "failed"])
    def test_new_task_allowed_after_finish(self, db, gov_table, finished: str) -> None:
        first = gov_tasks.create_governance_task(db, table=gov_table, user_id=None, kind="detect", config={})
        first.status = finished
        db.commit()
        second = gov_tasks.create_governance_task(db, table=gov_table, user_id=None, kind="clean", config={})
        assert second.id is not None


class TestTransitionStatus:
    """_transition_status：pending -> running -> done/failed 状态机."""

    def test_valid_chain(self) -> None:
        task = GovernanceTask(table_id=1, kind="detect", status="pending")
        gov_tasks._transition_status(task, "running")
        assert task.status == "running"
        gov_tasks._transition_status(task, "done")
        assert task.status == "done"

    def test_pending_to_done_is_invalid(self) -> None:
        task = GovernanceTask(table_id=1, kind="detect")
        with pytest.raises(ValueError, match="非法状态转换"):
            gov_tasks._transition_status(task, "done")

    def test_done_is_terminal(self) -> None:
        task = GovernanceTask(table_id=1, kind="detect", status="done")
        with pytest.raises(ValueError):
            gov_tasks._transition_status(task, "running")


class TestExecuteDispatch:
    """execute_governance_task：按 kind 分发并管理生命周期."""

    def test_dispatch_detect_and_done(self, db, gov_table, monkeypatch) -> None:
        from cndb.plugins.tables.services.governance import detect

        called: dict = {}
        monkeypatch.setattr(detect, "execute_detect_task", lambda session, task: called.setdefault("id", task.id))
        task = gov_tasks.create_governance_task(db, table=gov_table, user_id=None, kind="detect", config={})
        gov_tasks.execute_governance_task(db, task.id)
        db.refresh(task)
        assert called["id"] == task.id
        assert task.status == "done"
        assert task.progress == 100

    def test_failure_marks_failed(self, db, gov_table, monkeypatch) -> None:
        from cndb.plugins.tables.services.governance import detect

        def _boom(session, task):
            raise RuntimeError("boom")

        monkeypatch.setattr(detect, "execute_detect_task", _boom)
        task = gov_tasks.create_governance_task(db, table=gov_table, user_id=None, kind="detect", config={})
        gov_tasks.execute_governance_task(db, task.id)
        db.refresh(task)
        assert task.status == "failed"
        assert "boom" in task.error_message
        assert task.progress == 100

    def test_missing_task_is_noop(self, db) -> None:
        gov_tasks.execute_governance_task(db, 999999)  # 不抛异常即通过

    def test_missing_table_marks_failed(self, db) -> None:
        orphan = GovernanceTask(table_id=99999999, kind="detect", config={})
        db.add(orphan)
        db.commit()
        gov_tasks.execute_governance_task(db, orphan.id)
        db.refresh(orphan)
        assert orphan.status == "failed"
        assert "不存在" in orphan.error_message


class TestRunInBackground:
    """run_governance_task_in_background：线程调度与真实执行."""

    def test_background_detect_completes(self, db, _session_factory, detect_ready_table) -> None:
        task = gov_tasks.create_governance_task(
            db,
            table=detect_ready_table,
            user_id=None,
            kind="detect",
            config={"match_fields": ["姓名"]},
        )
        gov_tasks.run_governance_task_in_background(_session_factory, task.id)
        gov_tasks.join_background_threads(timeout=10)
        db.expire_all()
        finished = db.get(GovernanceTask, task.id)
        assert finished is not None
        assert finished.status == "done"
        assert finished.progress == 100
        assert '"total_rows": 0' in finished.report


class TestGovernanceSchemas:
    """治理 Pydantic schemas 校验（plan 步骤 10）."""

    def test_detect_request(self) -> None:
        from cndb.plugins.tables.schemas import DetectRequest

        req = DetectRequest(match_fields=["姓名"], ignore_case=True)
        assert req.ignore_whitespace is False
        with pytest.raises(ValueError):
            DetectRequest(match_fields=[])

    def test_merge_request(self) -> None:
        from cndb.plugins.tables.schemas import MergeGroup, MergeRequest

        req = MergeRequest(
            match_fields=["姓名"],
            groups=[
                {
                    "member_row_ids": [1, 2],
                    "survivor_row_id": 1,
                    "field_policies": {"城市": "latest"},
                    "manual_values": {"城市": "x"},
                }
            ],
        )
        assert req.groups[0].survivorship == "non_empty_first"
        with pytest.raises(ValueError):
            MergeGroup(member_row_ids=[1], survivor_row_id=1)
        with pytest.raises(ValueError):
            MergeGroup(member_row_ids=[1, 2], survivor_row_id=1, survivorship="bogus")

    def test_clean_request(self) -> None:
        from cndb.plugins.tables.schemas import CleanRequest

        req = CleanRequest(actions=[{"action": "fill_null", "column": "年龄", "strategy": "mean"}])
        assert req.preview is True
        with pytest.raises(ValueError):
            CleanRequest(actions=[{"action": "dedupe_rows", "column": "姓名"}])
        with pytest.raises(ValueError):
            CleanRequest(actions=[])

    def test_task_out_from_attributes(self, db, gov_table) -> None:
        from cndb.plugins.tables.schemas import GovernanceTaskOut

        task = gov_tasks.create_governance_task(db, table=gov_table, user_id=None, kind="detect", config={})
        out = GovernanceTaskOut.model_validate(task)
        assert out.kind == "detect"
        assert out.status == "pending"
        assert out.total_groups == 0
