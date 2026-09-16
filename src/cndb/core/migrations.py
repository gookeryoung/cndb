"""编程式数据库迁移模块.

不依赖外部 alembic.ini 文件，运行时动态构造 alembic.Config，
指向包内 ``alembic/`` 目录。兼容以下场景：

- 开发模式（editable install）：数据库已有部分表或全空
- wheel 安装：site-packages 内的 alembic 迁移文件
- fspack 打包：dist 内嵌的 cndb/alembic/ 目录
- 首次启动：cndb.db 不存在或为空，自动 create_all + stamp

迁移失败兜底：
  若 upgrade head 抛异常（典型为"alembic_version 表不存在"），
  退化到 ``Base.metadata.create_all()`` + ``alembic stamp head``，
  保证首次启动或半失败后能自愈。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import NoReturn

import alembic.command
import alembic.config
from sqlalchemy import inspect

from cndb.core.config import settings
from cndb.models.base import Base

logger = logging.getLogger(__name__)


def _alembic_dir() -> Path:
    """定位包内 alembic 目录.

    从当前文件向上两级：core/migrations.py → cndb/ → cndb/alembic/
    """
    return Path(__file__).resolve().parent.parent / "alembic"


def _build_config() -> alembic.config.Config:
    """构造 alembic.Config（编程式，不读外部 ini）."""
    alembic_dir = _alembic_dir()
    if not alembic_dir.is_dir():
        raise RuntimeError(f"包内 alembic 目录不存在: {alembic_dir}")

    # 创建空 Config（None 表示没有关联的 ini 文件）
    cfg = alembic.config.Config(None)

    # 关键：设置 script_location 指向包内 alembic/ 目录
    cfg.set_main_option("script_location", str(alembic_dir))

    # env.py 所在目录（env.py 在包内 alembic/ 下）
    cfg.set_main_option("prepend_sys_path", str(alembic_dir))

    # 指定路径分隔符以消除 Alembic DeprecationWarning
    cfg.set_main_option("path_separator", "os")

    # 注入数据库 URL
    db_url = settings.DATABASE_URL
    if "+aiosqlite" in db_url:
        db_url = db_url.replace("+aiosqlite", "")
    cfg.set_main_option("sqlalchemy.url", db_url)

    # 必需：让 alembic 能找到 env.py（env.py 在 script_location 下）
    # alembic 的默认行为就是从 script_location 加载 env.py，不需要额外配置

    return cfg


def _db_is_fresh() -> bool:
    """判断数据库是否"全新"（无任何用户表）.

    用于区分：
    - 首次启动（cndb.db 刚创建，除 sqlite_sequence 外零表）
    - 已有数据库（可能含 alembic_version 或业务表）
    """
    from cndb.core.database import engine

    try:
        insp = inspect(engine)
        tables = insp.get_table_names()
        # SQLite 自带 sqlite_sequence / sqlite_schema 等系统表要排除
        user_tables = [t for t in tables if not t.startswith("sqlite_")]
        return len(user_tables) == 0
    except Exception:  # pragma: no cover - 数据库文件不存在时抛 OperationalError
        return True


def _run_upgrade(cfg: alembic.config.Config) -> None:
    """执行 alembic upgrade head."""
    alembic.command.upgrade(cfg, "head")


def _run_create_all_and_stamp(cfg: alembic.config.Config) -> None:
    """兜底：用 SQLAlchemy create_all 建表 + alembic stamp head.

    适用于首次启动、或 upgrade 因缺少 alembic_version 表失败的场景。
    create_all 只建新表，不影响已存在的表。
    """
    from cndb.core.database import engine

    logger.warning("alembic upgrade head 失败，退化到 create_all + stamp head 兜底")
    Base.metadata.create_all(bind=engine)
    alembic.command.stamp(cfg, "head")
    logger.info("兜底迁移完成（create_all + stamp head）")


def ensure_db_migrated() -> None:
    """确保数据库 schema 已处于最新迁移版本.

    启动时调用一次即可，幂等设计：
    - 已在 head → 跳过（alembic 自己会处理）
    - 有未应用迁移 → upgrade
    - 全新空库 → create_all + stamp
    - 半迁移残留 → 先尝试 upgrade，失败则兜底 create_all
    """
    cfg = _build_config()

    if _db_is_fresh():
        # 全新数据库：create_all + stamp 最快
        from cndb.core.database import engine

        logger.info("检测到全新数据库，执行 create_all + stamp head")
        Base.metadata.create_all(bind=engine)
        alembic.command.stamp(cfg, "head")
        logger.info("数据库初始化完成（create_all + stamp head）")
        return

    # 已有表：尝试 upgrade head
    try:
        _run_upgrade(cfg)
        logger.info("alembic upgrade head 执行成功")
    except Exception as exc:
        logger.warning("alembic upgrade head 失败 (%s)，尝试 create_all + stamp 兜底", exc)
        try:
            _run_create_all_and_stamp(cfg)
        except Exception as exc2:
            logger.error("兜底迁移也失败: %s", exc2)
            raise RuntimeError(f"数据库迁移彻底失败: {exc2}") from exc


__all__ = ["ensure_db_migrated"]


def __getattr__(name: str) -> NoReturn:  # pragma: no cover - 防御性
    """未导出的符号访问时报 AttributeError."""
    raise AttributeError(f"module {__name__!r} 未导出 {name!r}")
