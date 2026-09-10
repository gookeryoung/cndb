"""数据库引擎和会话管理.

基于 SQLAlchemy 2.0 风格，提供 engine / SessionLocal / get_db 三件套。
默认使用 SQLite，无需额外安装驱动，迁移到 PostgreSQL/MySQL 时只需修改 DATABASE_URL。
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from pyweb_template.core.config import settings

# SQLite 特殊参数：跨线程访问需关闭 check_same_thread
_connect_args: dict[str, object] = {}
if "sqlite" in settings.DATABASE_URL:
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    echo=settings.DEBUG,
)

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
