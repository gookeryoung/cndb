"""seed 专用 SQLite 加速与全量清库辅助。

seed 是一次性重建演示库场景，因此单独放置连接级 PRAGMA 与逐表 DROP 逻辑。"""

from __future__ import annotations

from typing import Any


def _set_seed_sqlite_pragmas(engine: Any) -> Any:
    """seed 加速：SQLite 连接建立时关闭 fsync（synchronous=OFF），返回监听器句柄.

    seed 为一次性批量重建演示库场景，崩溃安全性由"重建即覆盖"语义兜底；
    关闭 fsync 后逐条写入从 ~2ms/条（每次独立事务刷盘）降到 ~0.3ms/条。
    非 SQLite 方言（PostgreSQL 等）无操作，返回 None。
    """
    from sqlalchemy import event

    if engine.dialect.name != "sqlite":
        return None

    def _set_pragma(dbapi_conn: Any, _record: Any) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA synchronous=OFF")
        cursor.close()

    event.listen(engine, "connect", _set_pragma)
    return _set_pragma


def _remove_seed_sqlite_pragmas(engine: Any, handler: Any) -> None:
    """移除 _set_seed_sqlite_pragmas 注册的连接监听器（handler 为 None 时无操作）."""
    from sqlalchemy import event

    if handler is not None:
        event.remove(engine, "connect", handler)


def _drop_all_tables_sqlite(engine: Any) -> None:
    """SQLite 全量清库：按 sqlite_master 逐表 DROP，含 ORM metadata 外的残留表.

    背景（线上 bug）：Base.metadata.drop_all 只删 ORM 注册表，历史遗留表
    （迁移建过、模型已下线的 wechat_accounts，旧版本残留表）不在 metadata 内
    而存活。在全局 PRAGMA foreign_keys=ON 下，DROP TABLE 会先对被删表做隐式
    DELETE，级联传播到带"指向已删表外键"的残留表时，SQLite 解析悬空外键报
    "no such table: main.xxx"（如 DROP TABLE accounts_user 时炸）。

    做法：临时关闭 foreign_keys（外键关闭后 DROP 不再做隐式 DELETE 级联与
    悬空外键解析，SQLite 官方推荐做法），再按 sqlite_master 全量 DROP ——
    顺带清掉动态物理表 table_*/link_* 与孤儿表，符合 seed"清空重建"语义。
    注意 PRAGMA foreign_keys 在事务内是空操作，故必须用 AUTOCOMMIT 连接
    （engine.begin() 里设置无效）；结束前恢复 ON，避免归还连接池后污染
    后续复用该连接的请求。

    Args:
        engine: 目标 SQLAlchemy 引擎（须为 SQLite 方言）.
    """
    from sqlalchemy import text

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        try:
            rows = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            ).fetchall()
            for (name,) in rows:
                quoted = name.replace('"', '""')
                conn.execute(text(f'DROP TABLE IF EXISTS "{quoted}"'))
        finally:
            conn.execute(text("PRAGMA foreign_keys=ON"))
