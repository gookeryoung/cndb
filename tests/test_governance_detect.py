"""重复检测测试：精确匹配分组 / 归一化选项 / 分页扫描 / 报告写入（plan 步骤 6）。"""

from __future__ import annotations

import json

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core.records import bulk_create, trash_row
from cndb.plugins.tables.services.governance import detect as gov_detect
from cndb.plugins.tables.services.governance.tasks import (
    GovernanceTaskError,
    _transition_status,
    create_governance_task,
)
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def owner(db):
    u = User(username="gov_detect_owner", nickname="GovDetectOwner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="GovDetectWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


def _make_table(db, ws, name: str, fields: list[tuple[str, str]]) -> DataTable:
    dt = DataTable(workspace_id=ws.id, name=name)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for fname, ftype in fields:
        f = DataField(table_id=dt.id, name=fname, field_type=ftype)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(db.get_bind(), dt)
    return dt


@pytest.fixture
def people_table(db, ws):
    return _make_table(db, ws, "人员", [("姓名", "text"), ("城市", "text"), ("年龄", "number")])


def _add_rows(db, table, rows: list[dict]) -> list[int]:
    return bulk_create(db.get_bind(), table, rows, db=db)


class TestExactMatcher:
    """ExactMatcher.detect：分组与归一化."""

    def test_group_duplicates(self, db, people_table) -> None:
        _add_rows(
            db,
            people_table,
            [
                {"姓名": "张三", "城市": "北京", "年龄": 20},
                {"姓名": "李四", "城市": "上海", "年龄": 30},
                {"姓名": "张三", "城市": "广州", "年龄": 40},
            ],
        )
        report = gov_detect.ExactMatcher().detect(
            db.get_bind(), people_table, ["姓名"], ignore_case=False, ignore_whitespace=False
        )
        assert report["total_rows"] == 3
        assert report["group_count"] == 1
        group = report["groups"][0]
        assert sorted(group["member_row_ids"]) == [1, 3]
        assert group["match_key_values"] == {"姓名": "张三"}
        assert report["duplicate_row_count"] == 2

    def test_multi_field_key(self, db, people_table) -> None:
        _add_rows(
            db,
            people_table,
            [
                {"姓名": "张三", "城市": "北京"},
                {"姓名": "张三", "城市": "上海"},
                {"姓名": "张三", "城市": "北京"},
            ],
        )
        report = gov_detect.ExactMatcher().detect(db.get_bind(), people_table, ["姓名", "城市"])
        assert report["group_count"] == 1
        assert sorted(report["groups"][0]["member_row_ids"]) == [1, 3]

    def test_ignore_case(self, db, people_table) -> None:
        _add_rows(db, people_table, [{"姓名": "abc"}, {"姓名": "ABC"}, {"姓名": "abcd"}])
        strict = gov_detect.ExactMatcher().detect(db.get_bind(), people_table, ["姓名"], ignore_case=False)
        assert strict["group_count"] == 0
        loose = gov_detect.ExactMatcher().detect(db.get_bind(), people_table, ["姓名"], ignore_case=True)
        assert loose["group_count"] == 1
        assert loose["groups"][0]["match_key_values"] == {"姓名": "abc"}

    def test_ignore_whitespace(self, db, people_table) -> None:
        _add_rows(db, people_table, [{"姓名": " 张三 "}, {"姓名": "张三"}, {"姓名": "李四"}])
        report = gov_detect.ExactMatcher().detect(db.get_bind(), people_table, ["姓名"], ignore_whitespace=True)
        assert report["group_count"] == 1
        assert sorted(report["groups"][0]["member_row_ids"]) == [1, 2]

    def test_null_matches_null(self, db, people_table) -> None:
        _add_rows(db, people_table, [{"姓名": None}, {"姓名": None}, {"姓名": "张三"}])
        report = gov_detect.ExactMatcher().detect(db.get_bind(), people_table, ["姓名"])
        assert report["group_count"] == 1
        assert sorted(report["groups"][0]["member_row_ids"]) == [1, 2]

    def test_empty_table(self, db, people_table) -> None:
        report = gov_detect.ExactMatcher().detect(db.get_bind(), people_table, ["姓名"])
        assert report == {"total_rows": 0, "duplicate_row_count": 0, "group_count": 0, "groups": []}

    def test_trashed_rows_excluded(self, db, people_table) -> None:
        ids = _add_rows(db, people_table, [{"姓名": "张三"}, {"姓名": "张三"}, {"姓名": "张三"}])
        trash_row(db.get_bind(), people_table, ids[0], db=db)
        report = gov_detect.ExactMatcher().detect(db.get_bind(), people_table, ["姓名"])
        assert report["total_rows"] == 2
        assert sorted(report["groups"][0]["member_row_ids"]) == sorted(ids[1:])

    def test_pagination_boundary(self, db, people_table) -> None:
        """batch_size 小于行数时分页扫描仍完整分组."""
        ids = _add_rows(db, people_table, [{"姓名": "张三"} for _ in range(5)])
        matcher = gov_detect.ExactMatcher()
        matcher.batch_size = 2
        report = matcher.detect(db.get_bind(), people_table, ["姓名"])
        assert report["total_rows"] == 5
        assert sorted(report["groups"][0]["member_row_ids"]) == sorted(ids)

    def test_missing_field_rejected(self, db, people_table) -> None:
        with pytest.raises(GovernanceTaskError, match="判重字段不存在"):
            gov_detect.ExactMatcher().detect(db.get_bind(), people_table, ["不存在"])

    def test_link_field_rejected(self, db, ws, people_table) -> None:
        f = DataField(
            table_id=people_table.id, name="关联", field_type="link", config={"target_table_id": people_table.id}
        )
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(people_table)
        with pytest.raises(GovernanceTaskError, match="不支持作为判重字段"):
            gov_detect.ExactMatcher().detect(db.get_bind(), people_table, ["关联"])


class TestExecuteDetectTask:
    """execute_detect_task：报告落盘与分组进度."""

    def test_report_written(self, db, people_table) -> None:
        _add_rows(db, people_table, [{"姓名": "张三"}, {"姓名": "张三"}, {"姓名": "李四"}])
        task = create_governance_task(
            db,
            table=people_table,
            user_id=None,
            kind="detect",
            config={"match_fields": ["姓名"], "ignore_case": False, "ignore_whitespace": True},
        )
        _transition_status(task, "running")
        db.commit()
        gov_detect.execute_detect_task(db, task)
        db.refresh(task)
        assert task.status == "running"  # 生命周期由 tasks 层收尾
        assert task.total_groups == 1
        assert task.done_groups == 1
        report = json.loads(task.report)
        assert report["group_count"] == 1
        assert report["groups"][0]["match_key_values"] == {"姓名": "张三"}

    def test_missing_match_fields_rejected(self, db, people_table) -> None:
        task = create_governance_task(db, table=people_table, user_id=None, kind="detect", config={})
        _transition_status(task, "running")
        db.commit()
        with pytest.raises(GovernanceTaskError, match="match_fields"):
            gov_detect.execute_detect_task(db, task)
