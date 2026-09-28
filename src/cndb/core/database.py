"""数据库引擎和会话管理.

基于 SQLAlchemy 2.0 风格，提供 engine / SessionLocal / get_db 三件套。
默认使用 SQLite，无需额外安装驱动，迁移到 PostgreSQL/MySQL 时只需修改 DATABASE_URL。
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from cndb.core.config import settings

logger = logging.getLogger(__name__)

# SQLite 特殊参数：跨线程访问需关闭 check_same_thread；
# isolation_level=None 禁用 sqlite3 的隐式事务（默认 "" 模式），
# 让 SQLAlchemy 的 Transaction/Connection 完整掌控事务生命周期，
# 避免嵌套 engine.begin() 在 autoload_with 时触发隐式 ROLLBACK 导致数据丢失。
_connect_args: dict[str, object] = {}
if "sqlite" in settings.DATABASE_URL:
    _connect_args = {"check_same_thread": False, "isolation_level": None}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    echo=settings.DEBUG,
)


def register_sqlite_pragmas(target_engine: Any) -> None:
    """为 SQLite 引擎注册连接级 pragma（WAL / 忙等待 / 页缓存 / 同步策略）.

    监听器在每条新连接建立时按序执行：
    1. busy_timeout=5000 —— 写锁竞争时等待而非立即报 database is locked；
    2. cache_size=-20000 —— 页缓存提升到 20MB（默认 2MB）；
    3. journal_mode=WAL —— 读写不互斥，Web 并发下显著提升写吞吐；
       切换失败（锁竞争/文件系统不支持）仅记 warning，本次连接沿用默认日志模式；
    4. synchronous=NORMAL —— 仅 WAL 生效时设置（回滚日志模式下保持默认 FULL 的耐久性）。

    非 SQLite 方言无操作。seed 一次性加速的 synchronous=OFF 监听器在本监听器
    之后注册（同事件按注册序执行），seed 期间覆盖 NORMAL、卸载后自动恢复。
    """
    if target_engine.dialect.name != "sqlite":
        return

    def _set_pragmas(dbapi_conn: Any, _record: Any) -> None:
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA cache_size=-20000")
            journal_mode = "delete"
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                row = cursor.fetchone()
                journal_mode = str(row[0]) if row else "delete"
            except Exception:
                logger.warning("SQLite 切换 WAL 模式失败，本次连接沿用默认日志模式", exc_info=True)
            if journal_mode.lower() == "wal":
                cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    event.listen(target_engine, "connect", _set_pragmas)


register_sqlite_pragmas(engine)

# 会话工厂：autoflush=False 避免隐式 flush 带来的性能问题
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session]:
    """FastAPI 依赖注入：为每个请求提供独立的数据库会话.

    使用 generator + yield + finally 保证请求结束后自动关闭会话。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
