"""core.database.checkpoint_wal 单测（ADR 0043 D4）.

覆盖：

- SQLite + WAL：执行 TRUNCATE，WAL 文件回落、返回 True；
- 非 WAL（回滚日志模式）：直接跳过返回 False；
- 非 SQLite 方言：跳过返回 False；
- 写锁忙（busy 位非 0）：返回 False 且不抛错；
- 执行异常：吞掉并返回 False；
- 非法 mode：返回 False。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine

from cndb.core.database import checkpoint_wal, register_sqlite_pragmas


class _FakeResult:
    def __init__(self, *, scalar: object = None, row: tuple[object, ...] | None = None) -> None:
        self._scalar = scalar
        self._row = row

    def scalar(self):
        return self._scalar

    def first(self):
        return self._row

    def all(self):  # pragma: no cover - 本模块未用
        return []


class _FakeConn:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = list(results)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def exec_driver_sql(self, _sql: str):
        return self._results.pop(0)


class _FakeEngine:
    def __init__(self, name: str, results: list[_FakeResult] | None = None, *, boom: bool = False) -> None:
        self.dialect = SimpleNamespace(name=name)
        self._results = results or []
        self._boom = boom

    def connect(self):
        if self._boom:
            raise RuntimeError("database is locked")
        return _FakeConn(self._results)


def _wal_engine(tmp_path: Path) -> object:
    engine = create_engine(f"sqlite:///{tmp_path / 'wal.db'}")
    register_sqlite_pragmas(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        for i in range(200):
            conn.exec_driver_sql("INSERT INTO t (v) VALUES (?)", (f"v{i}",))
    return engine


class TestCheckpointWal:
    def test_sqlite_wal_truncates(self, tmp_path):
        engine = _wal_engine(tmp_path)
        try:
            wal = Path(f"{tmp_path / 'wal.db'}-wal")
            assert wal.exists() and wal.stat().st_size > 0
            assert checkpoint_wal(engine) is True
            assert wal.stat().st_size == 0
        finally:
            engine.dispose()

    def test_sqlite_non_wal_skipped(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'plain.db'}")
        try:
            with engine.connect() as conn:
                assert str(conn.exec_driver_sql("PRAGMA journal_mode=delete").scalar()).lower() == "delete"
            assert checkpoint_wal(engine) is False
        finally:
            engine.dispose()

    def test_non_sqlite_dialect_skipped(self):
        assert checkpoint_wal(_FakeEngine("postgresql")) is False

    def test_busy_bit_returns_false(self):
        engine = _FakeEngine("sqlite", [_FakeResult(scalar="wal"), _FakeResult(row=(1, 3, 0))])
        assert checkpoint_wal(engine) is False

    def test_error_swallowed(self):
        assert checkpoint_wal(_FakeEngine("sqlite", boom=True)) is False

    def test_invalid_mode_rejected(self):
        assert checkpoint_wal(_FakeEngine("sqlite"), mode="VACUUM") is False
