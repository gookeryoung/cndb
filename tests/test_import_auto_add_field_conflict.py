"""导入自动新增字段撞"软删除同名字段"的回归测试.

线上现象（2026-10-16，https://gookeryoung.cn/）：更新已有数据表时导入 WPS 生成的
XLSX，点"确认"后进度停在 25% 不动，界面没有任何报错。

两条根因，本文件各锁一条：
1. ``tables_datafield`` 的 ``(table_id, name)`` 唯一约束**不区分 trashed**，软删除
   字段仍占着名字；``Importer._auto_add_fields`` 只按"未删除字段"判重，于是同名
   字段 INSERT 直接撞约束抛 IntegrityError，整个 execute 失败。
2. 异常后 Session 处于 PendingRollback 状态，旧实现在 ``except`` 里直接 commit
   又抛 ``PendingRollbackError``；第二个异常逃逸出后台线程（且无人再写任务状态），
   任务行永远停在 ``running`` / "执行子步骤 25%" —— 前端表现就是"进度卡住"。
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from cndb.plugins.tables.models import DataField, DataTable, ImportTask
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.importing import import_tasks
from cndb.plugins.tables.services.importing.importer import Importer


@pytest.fixture
def test_session(db_engine, db):
    yield db_engine, db


def _make_table(session: Session, *, workspace_id: int = 1) -> DataTable:
    dt = DataTable(workspace_id=workspace_id, name="问题记录")
    dt.ensure_db_name()
    session.add(dt)
    session.commit()
    session.refresh(dt)
    return dt


def _add_field(
    session: Session,
    table: DataTable,
    name: str,
    field_type: str,
    *,
    order: int = 0,
    trashed: bool = False,
) -> DataField:
    f = DataField(
        table_id=table.id,
        name=name,
        field_type=field_type,
        config={},
        order=order,
        trashed=trashed,
    )
    f.ensure_db_name()
    session.add(f)
    session.flush()
    return f


class TestTrashedNameCollision:
    """软删除字段占名 → 同名新增必须先让位，再建字段."""

    def test_trashed_duplicate_is_renamed_then_recreated(self, test_session):
        engine, session = test_session
        table = _make_table(session)
        _add_field(session, table, "序号", "text", order=0, trashed=True)
        session.commit()
        ddl.create_table(engine, table)

        imp = Importer(engine, session, table)
        # 修复前：这里抛 IntegrityError(UNIQUE constraint failed: tables_datafield...)
        imp._auto_add_fields([{"name": "序号", "field_type": "number", "sample_values": ["1", "2"]}])

        rows = session.query(DataField).filter(DataField.table_id == table.id).all()
        active = [f for f in rows if not f.trashed]
        trashed = [f for f in rows if f.trashed]

        assert [f.name for f in active] == ["序号"]
        assert active[0].field_type == "number"
        # 让位后的旧字段：名字带「（已删）」且唯一约束不再被占用
        assert len(trashed) == 1
        assert trashed[0].name == "序号（已删）"

    def test_active_duplicate_is_still_skipped(self, test_session):
        """未删除的同名字段仍按幂等处理（不重复建、也不改名）."""
        engine, session = test_session
        table = _make_table(session)
        _add_field(session, table, "序号", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)

        imp = Importer(engine, session, table)
        imp._auto_add_fields([{"name": "序号", "field_type": "number"}])

        rows = session.query(DataField).filter(DataField.table_id == table.id).all()
        assert [f.name for f in rows] == ["序号"]
        assert rows[0].field_type == "text"


class TestFailureLandsOnTask:
    """执行阶段异常必须落库为 failed（含 session 已进入 PendingRollback 的情况）."""

    def _make_task(self, db: Session, table_id: int) -> ImportTask:
        task = ImportTask(
            table_id=table_id,
            status="pending_confirm",
            progress=95,
            format="xlsx",
            file_content="",
            filename="问题记录.xlsx",
            error_message="",
            validation_report="{}",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    def test_flush_conflict_lands_as_failed_not_stuck(self, test_session, monkeypatch):
        engine, db = test_session
        table = _make_table(db)
        _add_field(db, table, "序号", "text", order=0)
        db.commit()
        ddl.create_table(engine, table)

        task = self._make_task(db, table.id)

        def boom(self, *args, **kwargs):
            # 制造真实 flush 冲突：session 随后处于 PendingRollback 状态 ——
            # 正是线上"失败处理又抛异常、任务永远停在 25%"的触发条件
            dup = DataField(table_id=table.id, name="序号", field_type="text", config={}, order=99)
            dup.ensure_db_name()
            db.add(dup)
            db.flush()

        monkeypatch.setattr(Importer, "execute", boom, raising=True)

        # 修复前：PendingRollbackError 从 execute_import_task 逃逸（后台线程崩溃）
        import_tasks.execute_import_task(db, task.id)

        db.expire_all()
        stored = db.get(ImportTask, task.id)
        assert stored.status == "failed"
        assert stored.progress == 100
        assert "字段写入冲突" in (stored.error_message or "")
        assert "PendingRollback" not in (stored.error_message or "")
