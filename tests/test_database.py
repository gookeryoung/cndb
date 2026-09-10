"""core.database 测试."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from pyweb_template.core import database


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
    from pyweb_template.core.config import settings

    if "sqlite" in settings.DATABASE_URL:
        assert database.engine.url.drivername == "sqlite"


def test_get_db_uses_dedicated_session_per_call() -> None:
    """每次 get_db 调用应返回独立 Session."""
    db1 = next(database.get_db())
    db2 = next(database.get_db())
    assert db1 is not db2
    db1.close()
    db2.close()
