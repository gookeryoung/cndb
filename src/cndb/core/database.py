"""数据库引擎和会话管理.

基于 SQLAlchemy 2.0 风格，提供 engine / SessionLocal / get_db 三件套。
默认使用 SQLite，无需额外安装驱动，迁移到 PostgreSQL/MySQL 时只需修改 DATABASE_URL。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event, text
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
    1. foreign_keys=ON —— 启用外键约束，使 DDL 中的 ondelete=CASCADE/SET NULL
       真正生效（SQLite 默认关闭，否则删除用户后 WorkspaceMember/TableMember
       等成员行成为孤儿，工作区/表的成员计数大于实际成员）；
    2. busy_timeout=5000 —— 写锁竞争时等待而非立即报 database is locked；
    3. cache_size=-20000 —— 页缓存提升到 20MB（默认 2MB）；
    4. journal_mode=WAL —— 读写不互斥，Web 并发下显著提升写吞吐；
       切换失败（锁竞争/文件系统不支持）仅记 warning，本次连接沿用默认日志模式；
    5. synchronous=NORMAL —— 仅 WAL 生效时设置（回滚日志模式下保持默认 FULL 的耐久性）。

    非 SQLite 方言无操作。seed 一次性加速的 synchronous=OFF 监听器在本监听器
    之后注册（同事件按注册序执行），seed 期间覆盖 NORMAL、卸载后自动恢复。
    """
    if target_engine.dialect.name != "sqlite":
        return

    def _set_pragmas(dbapi_conn: Any, _record: Any) -> None:
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
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

# 慢查询阈值（秒）：超过则记 warning 日志，便于单机排障。
# 默认取 settings.SLOW_QUERY_MS（500ms，可用 CNDB_SLOW_QUERY_MS 覆盖）；
# 保留模块常量名便于测试与调用方 monkeypatch。
SLOW_QUERY_SECONDS = max(0.0, settings.SLOW_QUERY_MS / 1000)


@event.listens_for(engine, "before_cursor_execute")
def _before_cursor_execute(
    _conn: Any, _cursor: Any, _statement: str, _parameters: Any, context: Any, _executemany: Any
) -> None:
    """记录 SQL 执行起始时间，供慢查询检测."""
    context._cndb_query_start = time.perf_counter()  # type: ignore[attr-defined]


@event.listens_for(engine, "after_cursor_execute")
def _after_cursor_execute(
    _conn: Any, _cursor: Any, statement: str, _parameters: Any, context: Any, _executemany: Any
) -> None:
    """SQL 执行结束后检测慢查询，超过阈值记 warning."""
    start = getattr(context, "_cndb_query_start", None)
    if start is None:
        return
    elapsed = time.perf_counter() - start
    if elapsed >= SLOW_QUERY_SECONDS:
        # request_id 来自观测中间件（非请求上下文时为空）：便于把慢 SQL 与具体请求对上
        from cndb.core.observability import get_request_id

        request_id = get_request_id()
        suffix = f" request_id={request_id}" if request_id else ""
        logger.warning(
            "慢查询 %.3fs%s: %s",
            elapsed,
            suffix,
            " ".join(statement.split())[:200],
        )


def checkpoint_wal(target_engine: Any, *, mode: str = "TRUNCATE") -> bool:
    """把 WAL 落回主库并截断 WAL 文件（ADR 0043 D4，同步收尾用）.

    只在「SQLite + 当前连接 journal_mode=wal」时执行；非 SQLite、非 WAL 直接返回
    ``False``。``PRAGMA wal_checkpoint`` 在写锁竞争时返回 ``busy`` 位而不抛错，
    因此必须读第一列判断；任何异常都吞掉并记 warning（收尾动作不得影响已落库批次
    与运行记录状态）。

    Args:
        target_engine: SQLAlchemy engine。
        mode: ``TRUNCATE``（默认，重置 WAL 文件）/ ``PASSIVE`` / ``FULL`` / ``RESTART``。

    Returns:
        真正执行了 checkpoint 且未因忙跳过时为 ``True``。
    """
    if mode.upper() not in {"TRUNCATE", "PASSIVE", "FULL", "RESTART"}:
        logger.warning("WAL checkpoint 模式非法: %r，跳过", mode)
        return False
    try:
        if getattr(getattr(target_engine, "dialect", None), "name", "") != "sqlite":
            return False
        with target_engine.connect() as conn:
            journal_mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
            if str(journal_mode or "").lower() != "wal":
                return False
            row = conn.exec_driver_sql(f"PRAGMA wal_checkpoint({mode.upper()})").first()
        busy = int(row[0]) if row is not None and row[0] is not None else 0
        if busy:
            logger.info("WAL checkpoint(%s) 因写锁忙跳过（busy=%s）", mode, busy)
            return False
        return True
    except Exception:
        logger.warning("WAL checkpoint(%s) 失败，跳过", mode, exc_info=True)
        return False


def db_readiness() -> dict[str, Any]:
    """就绪探测快照：DB ping + 迁移版本.

    Returns:
        {"ok": bool, "db": bool, "migration_current": str | None, "error": str}
        供 /api/health/ready 返回；DB 不可达时 ok=False。
    """
    snapshot: dict[str, Any] = {"db": False, "migration_current": None, "error": ""}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        snapshot["db"] = True
    except Exception as exc:
        snapshot["error"] = str(exc)
        return snapshot
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
        snapshot["migration_current"] = row[0] if row else None
    except Exception:
        # alembic_version 缺失属未迁移状态，DB 本身可达，不算失败
        logger.debug("读取 alembic_version 失败（可能未迁移）", exc_info=True)
    return snapshot


# 会话工厂：autoflush=False 避免隐式 flush 带来的性能问题
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session]:
    """FastAPI 依赖注入：为每个请求提供独立的数据库会话.

    使用 generator + yield + finally 保证请求结束后自动关闭会话；
    请求路径抛异常时先显式 rollback 再关闭，不依赖 close 的隐式回滚语义，
    避免半提交状态污染连接池中的连接。
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
