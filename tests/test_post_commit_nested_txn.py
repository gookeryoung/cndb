"""验证 set_links/clear_row_links 的 conn 参数修复效果.

重要：pytest fixture 里 db_engine 设置了 isolation_level=None（autocommit 模式），
SQLite autocommit 下无真正事务，嵌套 engine.begin 本身就是空操作。
本测试自建 engine 用默认事务隔离级别（PostgreSQL 等价场景），
验证 conn 参数传递后主行写入 + link 写入参与同一事务。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

import cndb.plugins.accounts.models  # noqa: F401
import cndb.plugins.reports.models  # noqa: F401
import cndb.plugins.tables.models  # noqa: F401
import cndb.plugins.wechat_auth.models  # noqa: F401
import cndb.plugins.workspaces.models  # noqa: F401
from cndb.models.base import Base

from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import links
from cndb.plugins.tables.services.core.ddl import create_table


def _make_engine():
    """创建一个带真正事务隔离的内存 SQLite engine（非 autocommit）."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _make_tables(engine):
    """创建两张 DataTable + link 字段，并在数据库中建表."""
    S = sessionmaker(bind=engine)
    db = S()

    from cndb.plugins.workspaces.models import Workspace
    ws = Workspace(name="ws_test")
    db.add(ws); db.flush()

    tgt = DataTable(workspace_id=ws.id, name="tgt_ns")
    tgt.ensure_db_name()
    db.add(tgt); db.flush()
    f1 = DataField(table_id=tgt.id, name="tname", field_type="text", config={}, order=0)
    f1.ensure_db_name(); db.add(f1); db.flush()

    src = DataTable(workspace_id=ws.id, name="src_ns")
    src.ensure_db_name()
    db.add(src); db.flush()
    f2 = DataField(table_id=src.id, name="sname", field_type="text", config={}, order=0)
    f2.ensure_db_name(); db.add(f2); db.flush()

    lnk = DataField(
        table_id=src.id, name="link_tgt", field_type="link",
        config={"target_table_id": tgt.id, "multiple": True}, order=1,
    )
    lnk.ensure_db_name(); db.add(lnk); db.flush()
    db.commit()

    db.refresh(tgt); db.refresh(src)
    create_table(engine, tgt); create_table(engine, src)

    with engine.begin() as conn:
        conn.execute(text(
            f'INSERT INTO {tgt.db_table_name} ({f1.db_column_name}, _trashed) VALUES (:n, 0)'
        ), [{"n": "a"}, {"n": "b"}, {"n": "c"}])

    return tgt, f1, src, f2, lnk


class TestNestedBeginConnSharing:
    """修复后：外层 engine.begin() 内调用 set_links(conn=conn) 参与同一事务."""

    def test_set_links_with_conn_rolls_back_together(self):
        """外层事务 RuntimeError 后，主行 + link 都应回滚."""
        engine = _make_engine()
        _tgt, _f1, src, f2, lnk = _make_tables(engine)

        with pytest.raises(RuntimeError, match="simulated"):
            with engine.begin() as conn:
                conn.execute(text(
                    f"INSERT INTO {src.db_table_name} ({f2.db_column_name}, _trashed) VALUES (:v, 0)"
                ), {"v": "x"})
                row_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
                links.set_links(engine, lnk, row_id, [1, 2], conn=conn)
                raise RuntimeError("simulated failure after link write")

        with engine.connect() as c:
            link_count = c.execute(text(f"SELECT COUNT(*) FROM {lnk.link_table_name}")).scalar()
            src_count = c.execute(text(
                f"SELECT COUNT(*) FROM {src.db_table_name} WHERE {f2.db_column_name}='x'"
            )).scalar()
        assert link_count == 0, f"修复后 link 应随主行一起回滚，实际 {link_count}"
        assert src_count == 0, f"主行应已回滚，实际 {src_count}"

    def test_set_links_no_conn_arg_writes_independently(self):
        """不传 conn 时 set_links 独立事务写入（seed.py 等场景）."""
        engine = _make_engine()
        _tgt, _f1, src, f2, lnk = _make_tables(engine)

        with engine.begin() as conn:
            conn.execute(text(
                f"INSERT INTO {src.db_table_name} ({f2.db_column_name}, _trashed) VALUES (:v, 0)"
            ), {"v": "y"})
            row_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()

        links.set_links(engine, lnk, row_id, [1, 2])
        with engine.connect() as c:
            link_count = c.execute(text(f"SELECT COUNT(*) FROM {lnk.link_table_name}")).scalar()
        assert link_count == 2

    def test_set_links_outer_rollback_without_conn_leaks_link(self):
        """不传递 conn 时外层回滚后 link 仍残留（修复前的 Bug 复现）."""
        engine = _make_engine()
        _tgt, _f1, src, f2, lnk = _make_tables(engine)

        with pytest.raises(RuntimeError, match="simulated"):
            with engine.begin() as conn:
                conn.execute(text(
                    f"INSERT INTO {src.db_table_name} ({f2.db_column_name}, _trashed) VALUES (:v, 0)"
                ), {"v": "bug"})
                row_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
                links.set_links(engine, lnk, row_id, [1])
                raise RuntimeError("simulated outer rollback")

        with engine.connect() as c:
            link_count = c.execute(text(f"SELECT COUNT(*) FROM {lnk.link_table_name}")).scalar()
            src_count = c.execute(text(
                f"SELECT COUNT(*) FROM {src.db_table_name} WHERE {f2.db_column_name}='bug'"
            )).scalar()
        assert src_count == 0
        assert link_count == 1, "旧行为：link 独立 commit 绕过外层回滚"

    def test_clear_row_links_with_conn_rolls_back_together(self):
        """外层事务 RuntimeError 后，delete + clear_row_links 应一起回滚."""
        engine = _make_engine()
        _tgt, _f1, src, f2, lnk = _make_tables(engine)

        with engine.begin() as conn:
            conn.execute(text(
                f"INSERT INTO {src.db_table_name} ({f2.db_column_name}, _trashed) VALUES (:v, 0)"
            ), {"v": "z"})
            row_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
        links.set_links(engine, lnk, row_id, [1])

        with pytest.raises(RuntimeError, match="simulated"):
            with engine.begin() as conn:
                conn.execute(text(f"DELETE FROM {src.db_table_name} WHERE id = :rid"), {"rid": row_id})
                links.clear_row_links(engine, src, [row_id], conn=conn)
                raise RuntimeError("simulated delete failure")

        with engine.connect() as c:
            src_exists = c.execute(text(
                f"SELECT COUNT(*) FROM {src.db_table_name} WHERE {f2.db_column_name}='z'"
            )).scalar()
            link_after = c.execute(text(f"SELECT COUNT(*) FROM {lnk.link_table_name}")).scalar()
        assert src_exists == 1, "delete 应随外层回滚，主行应恢复"
        assert link_after == 1, "clear_row_links 应随外层回滚，link 不应消失"

    def test_ensure_link_targets_exist_rejects_trashed_target(self):
        """软删除的目标行不应再作为 link 写入的有效目标."""
        engine = _make_engine()
        from sqlalchemy.orm import sessionmaker as sm
        S = sm(bind=engine)
        db = S()
        tgt, _f1, _src, _f2, lnk = _make_tables(engine)

        with engine.begin() as conn:
            conn.execute(text(
                f"UPDATE {tgt.db_table_name} SET _trashed=1, _trashed_at=CURRENT_TIMESTAMP WHERE id=2"
            ))

        with pytest.raises(ValueError, match="不存在或已删除"):
            links.ensure_link_targets_exist(engine, lnk, [2], db)
        links.ensure_link_targets_exist(engine, lnk, [1, 3], db)
        db.close()
