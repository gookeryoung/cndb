"""重复合并测试：融合策略 / link 迁移 / 回收站 / 键漂移跳过 / 审计（plan 步骤 7）。"""

from __future__ import annotations

import json

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import AuditLog, DataField, DataTable, GovernanceTask
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core.links import load_links, set_links
from cndb.plugins.tables.services.core.records import bulk_create, restore_row, update_row
from cndb.plugins.tables.services.governance import merge as gov_merge
from cndb.plugins.tables.services.governance.tasks import (
    _transition_status,
    create_governance_task,
)
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def owner(db):
    u = User(username="gov_merge_owner", nickname="GovMergeOwner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="GovMergeWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


def _make_table(db, ws, name: str, fields: list[tuple[str, str]], config: dict | None = None) -> DataTable:
    dt = DataTable(workspace_id=ws.id, name=name)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for fname, ftype in fields:
        f = DataField(table_id=dt.id, name=fname, field_type=ftype, config=dict(config) if ftype == "link" else {})
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(db.get_bind(), dt)
    return dt


def _rows(db, engine, table, rows: list[dict]) -> list[int]:
    return bulk_create(engine, table, rows, db=db)


def _get_row(db, engine, table, row_id: int) -> dict:
    from cndb.plugins.tables.services.core.records import get_row

    return get_row(engine, table, row_id, db=db)


def _merge(db, table, config: dict) -> GovernanceTask:
    task = create_governance_task(db, table=table, user_id=None, kind="merge", config=config)
    _transition_status(task, "running")
    db.commit()
    gov_merge.execute_merge_task(db, task)
    db.refresh(task)
    return task


class TestMergeSurvivorship:
    """SurvivorshipRule 融合策略."""

    def _table(self, db, ws):
        return _make_table(db, ws, "客户", [("姓名", "text"), ("城市", "text"), ("年龄", "number")])

    def test_non_empty_first_default(self, db, ws) -> None:
        table = self._table(db, ws)
        _rows(db, db.get_bind(), table, [{"姓名": "张三"}, {"姓名": "张三", "城市": "广州", "年龄": 40}])
        task = _merge(
            db,
            table,
            {
                "match_fields": ["姓名"],
                "groups": [{"member_row_ids": [1, 2], "survivor_row_id": 1}],
            },
        )
        assert task.status == "running"
        survivor = _get_row(db, db.get_bind(), table, 1)
        assert survivor["城市"] == "广州"
        assert survivor["年龄"] == 40
        merged = _get_row(db, db.get_bind(), table, 2)
        assert merged is None  # 已进回收站

    def test_latest_oldest_policy(self, db, ws) -> None:
        table = self._table(db, ws)
        _rows(db, db.get_bind(), table, [{"姓名": "张三", "城市": "北京"}, {"姓名": "张三", "城市": "广州"}])
        latest = _merge(
            db,
            table,
            {
                "match_fields": ["姓名"],
                "groups": [{"member_row_ids": [1, 2], "survivor_row_id": 1, "field_policies": {"城市": "latest"}}],
            },
        )
        assert latest.done_groups == 1
        assert _get_row(db, db.get_bind(), table, 1)["城市"] == "广州"

        # oldest：重置后用新表验证（复用同表 id 会漂移，这里直接再建一组）
        table2 = _make_table(db, ws, "客户2", [("姓名", "text"), ("城市", "text")])
        _rows(db, db.get_bind(), table2, [{"姓名": "李四", "城市": "北京"}, {"姓名": "李四", "城市": "广州"}])
        _merge(
            db,
            table2,
            {
                "match_fields": ["姓名"],
                "groups": [{"member_row_ids": [1, 2], "survivor_row_id": 2, "field_policies": {"城市": "oldest"}}],
            },
        )
        assert _get_row(db, db.get_bind(), table2, 2)["城市"] == "北京"

    def test_manual_policy(self, db, ws) -> None:
        table = self._table(db, ws)
        _rows(db, db.get_bind(), table, [{"姓名": "张三", "城市": "北京"}, {"姓名": "张三", "城市": "广州"}])
        _merge(
            db,
            table,
            {
                "match_fields": ["姓名"],
                "groups": [
                    {
                        "member_row_ids": [1, 2],
                        "survivor_row_id": 1,
                        "field_policies": {"城市": "manual"},
                        "manual_values": {"城市": "手动值"},
                    }
                ],
            },
        )
        assert _get_row(db, db.get_bind(), table, 1)["城市"] == "手动值"

    def test_trashed_rows_restorable(self, db, ws) -> None:
        table = self._table(db, ws)
        _rows(db, db.get_bind(), table, [{"姓名": "张三", "城市": "北京"}, {"姓名": "张三", "城市": "广州"}])
        _merge(
            db,
            table,
            {"match_fields": ["姓名"], "groups": [{"member_row_ids": [1, 2], "survivor_row_id": 1}]},
        )
        assert restore_row(db.get_bind(), table, 2, db=db) is True
        restored = _get_row(db, db.get_bind(), table, 2)
        assert restored["城市"] == "广州"


class TestMergeLinkMigration:
    """link 引用迁移到保留行."""

    def test_inbound_links_migrated(self, db, ws) -> None:
        people = _make_table(db, ws, "客户", [("姓名", "text")])
        orders = _make_table(db, ws, "订单", [("编号", "text"), ("客户", "link")], {"target_table_id": people.id})
        _rows(db, db.get_bind(), people, [{"姓名": "张三"}, {"姓名": "张三"}])
        _rows(db, db.get_bind(), orders, [{"编号": "A"}, {"编号": "B"}])
        engine = db.get_bind()
        link_field = next(f for f in orders.active_fields() if f.field_type == "link")
        set_links(engine, link_field, 1, [1], db=db)  # 订单1 -> 客户1
        set_links(engine, link_field, 2, [2], db=db)  # 订单2 -> 客户2（将被合并）

        _merge(db, people, {"match_fields": ["姓名"], "groups": [{"member_row_ids": [1, 2], "survivor_row_id": 1}]})

        assert load_links(engine, link_field, [1]) == {1: [1]}
        assert load_links(engine, link_field, [2]) == {2: [1]}  # 迁移到保留行

    def test_intra_group_self_reference_not_migrated(self, db, ws) -> None:
        """组内成员引用组成员的 link 不迁移（成员行本身进回收站）."""
        people = _make_table(db, ws, "员工", [("姓名", "text"), ("同事", "link")], {"target_table_id": 0})
        # 修正 link 目标为自身表
        link_field = next(f for f in people.active_fields() if f.field_type == "link")
        link_field.config = {"target_table_id": people.id}
        db.commit()
        _rows(db, db.get_bind(), people, [{"姓名": "张三"}, {"姓名": "张三"}])
        engine = db.get_bind()
        set_links(engine, link_field, 1, [2], db=db)  # 成员1 引用成员2（组内自引用）

        _merge(db, people, {"match_fields": ["姓名"], "groups": [{"member_row_ids": [1, 2], "survivor_row_id": 1}]})

        assert load_links(engine, link_field, [1]) == {1: [2]}  # 未迁移


class TestMergeSafety:
    """键漂移 / 坏组跳过 / 审计."""

    def test_key_drift_skips_group(self, db, ws) -> None:
        table = _make_table(db, ws, "客户", [("姓名", "text")])
        _rows(db, db.get_bind(), table, [{"姓名": "张三"}, {"姓名": "张三"}])
        # 检测后外部修改了判重键
        update_row(db.get_bind(), table, 2, {"姓名": "王五"}, db=db)
        task = _merge(
            db,
            table,
            {"match_fields": ["姓名"], "groups": [{"member_row_ids": [1, 2], "survivor_row_id": 1}]},
        )
        report = json.loads(task.report)
        assert len(report["skipped"]) == 1
        assert "漂移" in report["skipped"][0]["reason"]
        assert _get_row(db, db.get_bind(), table, 2) is not None  # 未被合并

    def test_valid_group_proceeds_after_invalid(self, db, ws) -> None:
        table = _make_table(db, ws, "客户", [("姓名", "text")])
        _rows(db, db.get_bind(), table, [{"姓名": "张三"}, {"姓名": "张三"}, {"姓名": "李四"}, {"姓名": "李四"}])
        task = _merge(
            db,
            table,
            {
                "match_fields": ["姓名"],
                "groups": [
                    {"member_row_ids": [1, 2], "survivor_row_id": 1},
                    {"member_row_ids": [3, 999], "survivor_row_id": 3},  # 999 不存在
                ],
            },
        )
        report = json.loads(task.report)
        assert report["merged_count"] == 1
        assert len(report["skipped"]) == 1
        assert _get_row(db, db.get_bind(), table, 4) is not None
        assert task.done_groups == 2

    def test_survivor_not_in_members_skipped(self, db, ws) -> None:
        table = _make_table(db, ws, "客户", [("姓名", "text")])
        _rows(db, db.get_bind(), table, [{"姓名": "张三"}, {"姓名": "张三"}])
        task = _merge(
            db,
            table,
            {"match_fields": ["姓名"], "groups": [{"member_row_ids": [1, 2], "survivor_row_id": 3}]},
        )
        report = json.loads(task.report)
        assert len(report["skipped"]) == 1

    def test_empty_groups_rejected(self, db, ws) -> None:
        table = _make_table(db, ws, "客户", [("姓名", "text")])
        task = create_governance_task(db, table=table, user_id=None, kind="merge", config={})
        _transition_status(task, "running")
        db.commit()
        with pytest.raises(gov_merge.GovernanceTaskError, match="groups"):
            gov_merge.execute_merge_task(db, task)


class TestMergeAuditAndProgress:
    """审计与进度."""

    def test_audit_logged_per_group(self, db, ws) -> None:
        table = _make_table(db, ws, "客户", [("姓名", "text")])
        _rows(db, db.get_bind(), table, [{"姓名": "张三"}, {"姓名": "张三"}])
        _merge(db, table, {"match_fields": ["姓名"], "groups": [{"member_row_ids": [1, 2], "survivor_row_id": 1}]})
        logs = db.query(AuditLog).filter(AuditLog.table_id == table.id, AuditLog.action == "merge").all()
        assert len(logs) == 1
        assert logs[0].target_id == 1
        assert logs[0].detail.get("survivor_row_id") == 1

    def test_progress_and_report(self, db, ws) -> None:
        table = _make_table(db, ws, "客户", [("姓名", "text")])
        _rows(db, db.get_bind(), table, [{"姓名": "张三"}, {"姓名": "张三"}, {"姓名": "李四"}, {"姓名": "李四"}])
        task = _merge(
            db,
            table,
            {
                "match_fields": ["姓名"],
                "groups": [
                    {"member_row_ids": [1, 2], "survivor_row_id": 1},
                    {"member_row_ids": [3, 4], "survivor_row_id": 3},
                ],
            },
        )
        assert task.total_groups == 2
        assert task.done_groups == 2
        report = json.loads(task.report)
        assert report["merged_count"] == 2
        assert report["mode"] == "execute"
