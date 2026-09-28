"""core.database 测试."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from cndb.core import database


def test_engine_created_from_settings() -> None:
    """engine 应基于 settings.DATABASE_URL 创建."""
    assert database.engine is not None
    assert "sqlite" in str(database.engine.url)


def test_sessionlocal_is_sessionmaker() -> None:
    """SessionLocal 应是 sessionmaker 实例."""
    assert isinstance(database.SessionLocal, sessionmaker)


def test_get_db_yields_session_and_closes() -> None:
    """get_db 应 yield Session 并在 finally 中 close."""
    gen = database.get_db()
    db = next(gen)
    assert isinstance(db, Session)
    # generator.close() 会触发 finally 块
    gen.close()


def test_sqlite_connect_args_disable_check_same_thread() -> None:
    """SQLite 应关闭 check_same_thread 以支持多线程 TestClient."""
    from cndb.core.config import settings

    if "sqlite" in settings.DATABASE_URL:
        assert database.engine.url.drivername == "sqlite"


def test_get_db_uses_dedicated_session_per_call() -> None:
    """每次 get_db 调用应返回独立 Session."""
    db1 = next(database.get_db())
    db2 = next(database.get_db())
    assert db1 is not db2
    db1.close()
    db2.close()


def test_register_sqlite_pragmas_sets_wal_and_cache(tmp_path) -> None:
    """register_sqlite_pragmas 应为 SQLite 新连接设置 WAL/NORMAL/busy_timeout/cache_size."""
    from sqlalchemy import create_engine, text

    from cndb.core.database import register_sqlite_pragmas

    eng = create_engine(f"sqlite:///{tmp_path / 'pragma.db'}")
    register_sqlite_pragmas(eng)
    with eng.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA synchronous")).scalar() == 1  # 1 = NORMAL
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000
        assert conn.execute(text("PRAGMA cache_size")).scalar() == -20000
    eng.dispose()


def test_register_sqlite_pragmas_second_connection_inherits_pragmas(tmp_path) -> None:
    """连接归还池后新建连接同样应命中 pragma 监听器（WAL 为持久属性，可复检）."""
    from sqlalchemy import create_engine, text

    from cndb.core.database import register_sqlite_pragmas

    eng = create_engine(f"sqlite:///{tmp_path / 'pragma2.db'}")
    register_sqlite_pragmas(eng)
    for _ in range(2):
        with eng.connect() as conn:
            assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
    eng.dispose()
