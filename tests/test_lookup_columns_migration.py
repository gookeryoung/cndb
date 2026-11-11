"""迁移 e3f4a5b6c7d8（add_lookup_columns）回归测试（ADR 0131）.

背景：lookup 虚拟字段的过滤 / 排序原先走内存全表 attach，且有 2 万行硬上限。
本迁移为每个未回收 lookup 字段在持有它的物理表上补三列冗余值并回填历史数据：

- ``_lk_<db_column>``        多值用 U+001F 拼接 / 单值原值
- ``_lk_<db_column>_first``  最小解析值（升序 / 比较）
- ``_lk_<db_column>_max``    最大解析值（降序）

关键约束：加列幂等（create_all 时代旧库可能已含列）、物理表缺失时跳过、
回填复用迁移连接（SQLite 下新列对其它连接不可见）、downgrade 可重复执行。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.script import ScriptDirectory

from cndb.core.migrations import _build_config, upgrade_to_head

PRE_REVISION = "d2e3f4a5b6c7"  # 本迁移之前的 head

SRC_TABLE = "table_srcmig0001"
DST_TABLE = "table_dstmig0001"
SRC_COLUMN = "field_srcmig01"
LINK_COLUMN = "field_lnmig01"
LINK_TABLE = f"link_{LINK_COLUMN[len('field_') :]}"
LOOKUP_COLUMN = "field_lkmig01"
LK_JOINED = f"_lk_{LOOKUP_COLUMN}"
LK_FIRST = f"{LK_JOINED}_first"
LK_MAX = f"{LK_JOINED}_max"
LK_INDEX = f"ix_{DST_TABLE}_{LK_FIRST}"


def _upgrade_to(engine_target: str, revision: str) -> None:
    from alembic import command

    command.upgrade(_build_config(engine_target), revision)


def _downgrade_to(engine_target: str, revision: str) -> None:
    from alembic import command

    command.downgrade(_build_config(engine_target), revision)


def _current_head() -> str:
    return str(ScriptDirectory.from_config(_build_config("sqlite:///:memory:")).get_current_head())


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}  # nosec B608 - 测试内部常量表名
    finally:
        conn.close()


def _indexes(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA index_list({table})").fetchall()}  # nosec B608 - 测试内部常量表名
    finally:
        conn.close()


def _create_physical_tables(db_path: Path) -> None:
    """造旧结构物理表：源表 2 行、消费表 2 行、关联表把行 1 关联到两个源行."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(f'CREATE TABLE "{SRC_TABLE}" (id INTEGER PRIMARY KEY AUTOINCREMENT, "{SRC_COLUMN}" TEXT)')
        conn.execute(f'CREATE TABLE "{DST_TABLE}" (id INTEGER PRIMARY KEY AUTOINCREMENT)')
        conn.execute(
            f'CREATE TABLE "{LINK_TABLE}" ('
            "id INTEGER PRIMARY KEY AUTOINCREMENT, row_id INTEGER NOT NULL, target_row_id INTEGER NOT NULL, "
            "UNIQUE (row_id, target_row_id))"
        )
        conn.executemany(
            f'INSERT INTO "{SRC_TABLE}" (id, "{SRC_COLUMN}") VALUES (?, ?)',
            [(1, "alpha"), (2, "beta")],
        )
        conn.executemany(f'INSERT INTO "{DST_TABLE}" (id) VALUES (?)', [(1,), (2,)])
        conn.executemany(
            f'INSERT INTO "{LINK_TABLE}" (row_id, target_row_id) VALUES (?, ?)',
            [(1, 1), (1, 2), (2, 1)],
        )
        conn.commit()
    finally:
        conn.close()


def _insert_metadata(url: str) -> None:
    """在当前 revision 上写入 DataTable / DataField 元数据（源表 text + link + lookup）."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from cndb.plugins.tables.models import DataField, DataTable

    engine = create_engine(url)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        src = DataTable(workspace_id=1, name="SrcMig", db_table_name=SRC_TABLE, order=0, trashed=False)
        dst = DataTable(workspace_id=1, name="DstMig", db_table_name=DST_TABLE, order=1, trashed=False)
        db.add_all([src, dst])
        db.flush()

        src_field = DataField(
            table_id=src.id,
            name="src_title",
            field_type="text",
            db_column_name=SRC_COLUMN,
            config={},
            order=0,
            trashed=False,
        )
        link_field = DataField(
            table_id=dst.id,
            name="关联源表",
            field_type="link",
            db_column_name=LINK_COLUMN,
            config={"target_table_id": src.id, "multiple": True},
            order=0,
            trashed=False,
        )
        db.add_all([src_field, link_field])
        db.flush()

        lookup = DataField(
            table_id=dst.id,
            name="src_title",
            field_type="lookup",
            db_column_name=LOOKUP_COLUMN,
            config={
                "source_table_id": src.id,
                "source_field_id": src_field.id,
                "via_link_field_id": link_field.id,
                "source_field_type": "text",
            },
            order=1,
            trashed=False,
        )
        db.add(lookup)
        db.commit()
    engine.dispose()


def _prepare_old_db(tmp_path: Path) -> tuple[Path, str]:
    db_path = tmp_path / "old.db"
    url = f"sqlite:///{db_path.as_posix()}"
    _upgrade_to(url, PRE_REVISION)
    _create_physical_tables(db_path)
    _insert_metadata(url)
    return db_path, url


def _read_lk_rows(db_path: Path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            f'SELECT id, "{LK_JOINED}", "{LK_FIRST}", "{LK_MAX}" FROM "{DST_TABLE}" ORDER BY id'
        ).fetchall()
    finally:
        conn.close()


class TestLookupColumnsMigration:
    def test_upgrade_adds_columns_index_and_backfills(self, tmp_path: Path) -> None:
        db_path, url = _prepare_old_db(tmp_path)
        assert not {LK_JOINED, LK_FIRST, LK_MAX} & _columns(db_path, DST_TABLE)

        upgrade_to_head(url)

        assert {LK_JOINED, LK_FIRST, LK_MAX} <= _columns(db_path, DST_TABLE)
        assert LK_INDEX in _indexes(db_path, DST_TABLE)
        # 行 1 关联 [alpha, beta]（按关联表写入顺序）；行 2 关联 [alpha]
        assert _read_lk_rows(db_path) == [
            (1, "alpha\x1fbeta", "alpha", "beta"),
            (2, "alpha", "alpha", "alpha"),
        ]
        conn = sqlite3.connect(str(db_path))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        finally:
            conn.close()
        assert version == _current_head()

    def test_upgrade_idempotent_when_columns_preexist(self, tmp_path: Path) -> None:
        """create_all 时代旧库已含三列 / 索引 → upgrade head 不报 duplicate column."""
        db_path, url = _prepare_old_db(tmp_path)
        conn = sqlite3.connect(str(db_path))
        try:
            for name in (LK_JOINED, LK_FIRST, LK_MAX):
                conn.execute(f'ALTER TABLE "{DST_TABLE}" ADD COLUMN "{name}" BLOB')
            conn.execute(f'CREATE INDEX "{LK_INDEX}" ON "{DST_TABLE}" ("{LK_FIRST}")')
            conn.commit()
        finally:
            conn.close()

        upgrade_to_head(url)  # 不抛 duplicate column / index 即通过
        upgrade_to_head(url)  # 重复升级仍幂等

        assert LK_INDEX in _indexes(db_path, DST_TABLE)
        rows = _read_lk_rows(db_path)
        assert rows[0][1] == "alpha\x1fbeta"
        assert rows[1][1] == "alpha"

    def test_upgrade_skips_missing_physical_table(self, tmp_path: Path) -> None:
        """物理表整体缺失（元数据残留）→ 跳过不失败，由启动 create_all / CLI 兜底."""
        db_path = tmp_path / "missing.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        _insert_metadata(url)  # 不创建物理表

        upgrade_to_head(url)  # 不抛 no such table 即通过

        conn = sqlite3.connect(str(db_path))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        finally:
            conn.close()
        assert version == _current_head()

    def test_downgrade_removes_columns_then_idempotent(self, tmp_path: Path) -> None:
        db_path, url = _prepare_old_db(tmp_path)
        upgrade_to_head(url)
        assert {LK_JOINED, LK_FIRST, LK_MAX} <= _columns(db_path, DST_TABLE)

        _downgrade_to(url, PRE_REVISION)
        assert not {LK_JOINED, LK_FIRST, LK_MAX} & _columns(db_path, DST_TABLE)
        assert LK_INDEX not in _indexes(db_path, DST_TABLE)

        _downgrade_to(url, PRE_REVISION)  # 第二次：列已不存在，跳过
        assert not {LK_JOINED, LK_FIRST, LK_MAX} & _columns(db_path, DST_TABLE)
