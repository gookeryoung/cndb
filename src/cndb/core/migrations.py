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
from typing import Any, NoReturn

import alembic.command
import alembic.config
from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateColumn, CreateIndex
from sqlalchemy.sql.schema import Column

from cndb.core.config import settings
from cndb.models.base import Base

logger = logging.getLogger(__name__)


def _alembic_dir() -> Path:
    """定位包内 alembic 目录.

    从当前文件向上两级：core/migrations.py → cndb/ → cndb/alembic/
    """
    return Path(__file__).resolve().parent.parent / "alembic"


def _build_config(database_url: str | None = None) -> alembic.config.Config:
    """构造 alembic.Config（编程式，不读外部 ini）.

    Args:
        database_url: 目标数据库 URL。None 时使用 settings.DATABASE_URL（默认行为），
            指定时以传入值为准（供恢复端对非默认库执行迁移/补标记）.
    """
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
    db_url = database_url or settings.DATABASE_URL
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


def stamp_head(database_url: str | None = None) -> None:
    """将数据库标记为最新迁移版本（alembic stamp head）.

    供自行 create_all 建表的流程（如 seed）在建表后调用：
    补写 alembic_version，避免 serve 启动时 ensure_db_migrated
    误判为"半迁移库"而重放建表迁移报"table already exists"。
    对已存在 alembic_version 的库幂等（仅更新版本行）。

    Args:
        database_url: 目标数据库 URL。None 时使用 settings.DATABASE_URL.
    """
    cfg = _build_config(database_url)
    alembic.command.stamp(cfg, "head")


def upgrade_to_head(database_url: str) -> None:
    """对指定数据库执行 alembic upgrade head.

    供恢复端（restore）在覆盖目标库后把旧 schema 升级到当前程序版本，
    实现"旧备份可在新版本恢复"。与 ensure_db_migrated 不同，本函数
    不依赖全局 engine，也不做空库兜底，失败时由调用方决定如何处置。

    Args:
        database_url: 目标数据库 URL（必填，restore 场景明确知道目标）.
    """
    cfg = _build_config(database_url)
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


def _scalar_server_default(col: Column[Any]) -> str | None:
    """把 ORM 列的 Python 端标量默认值合成为 SQL server_default 字面量.

    历史上部分列只声明了 Python 端 default（如 ``default=""``），迁移链与
    server_default 均未覆盖。自愈补建这类 NOT NULL 列时，缺 DEFAULT 会导致
    存量表 ADD COLUMN 直接失败，因此用 Python 默认值合成 DEFAULT 子句。

    Returns:
        可内联到 DDL 的 DEFAULT 字面量；无法合成时返回 None.
    """
    if col.server_default is not None:
        return None  # 已有 server_default，CreateColumn 可直接编译
    default = col.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    value = getattr(default, "arg", None)
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def _render_add_column_ddl(col: Column[Any], dialect: Any) -> str | None:
    """将 ORM 列编译为 ``ALTER TABLE ADD COLUMN`` 的列定义片段.

    返回 None 表示该列无法安全补建：
    - 主键自增列（表已存在时不会缺失）
    - NOT NULL 且无 server_default、也无法从 Python 端标量 default 合成的列
      （存量表有数据时 ADD COLUMN 必失败）
    """
    if col.primary_key:
        return None
    if not col.nullable and col.server_default is None:
        if _scalar_server_default(col) is None:
            return None
        # 用合成的 server_default 构造影子列参与编译（不改动原 Column 对象）
        col = Column(col.name, col.type, nullable=col.nullable, server_default=text(_scalar_server_default(col)))  # type: ignore[assignment]
    return str(CreateColumn(col).compile(dialect=dialect)).strip()


def _heal_missing_columns(engine: Any) -> list[str]:
    """对照 ORM 元数据，为库中已存在但缺列的表补建列.

    返回补建的 ``表名.列名`` 列表。单列补建失败只记 warning 不中断，
    避免个别异常列让启动从"缺列可用"变成"完全不可启动"。
    """
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    healed: list[str] = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                continue
            actual = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in actual:
                    continue
                ddl = _render_add_column_ddl(col, engine.dialect)
                if ddl is None:
                    logger.warning(
                        "列 %s.%s 缺失且无法安全补建（NOT NULL 且无 server_default），跳过",
                        table.name,
                        col.name,
                    )
                    continue
                try:
                    conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {ddl}"))
                except Exception as exc:
                    logger.warning("补建列 %s.%s 失败: %s", table.name, col.name, exc)
                    continue
                healed.append(f"{table.name}.{col.name}")
                logger.info("补建缺失列 %s.%s", table.name, col.name)
    return healed


def _heal_missing_indexes(engine: Any) -> list[str]:
    """对照 ORM 元数据，为库中已存在但缺索引的表补建索引.

    返回补建的索引名列表。与缺列同源：版本标记越过建索引迁移后，
    正常 upgrade 不再重放，这里兜底补齐（仅限 ORM 元数据声明的显式索引）。
    """
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    healed: list[str] = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                continue
            have = {ix["name"] for ix in insp.get_indexes(table.name)}
            for ix in table.indexes:
                if not ix.name or ix.name in have:
                    continue
                try:
                    conn.execute(text(str(CreateIndex(ix).compile(dialect=engine.dialect)).strip()))
                except Exception as exc:
                    logger.warning("补建索引 %s 失败: %s", ix.name, exc)
                    continue
                healed.append(ix.name)
                logger.info("补建缺失索引 %s", ix.name)
    return healed


def _heal_schema_drift() -> None:
    """schema 自愈：对照 ORM 元数据修复存量库的缺列/缺索引.

    背景：历史上 create_all 兜底 / seed / restore 等流程曾把 alembic_version
    stamp 到当时的 head，而表结构是更旧模型建的 —— 版本标记越过了中间的
    加列迁移，之后 upgrade head 永远 no-op，缺列永不修复（表现为 INSERT 报
    "no column named ..."）。本层在每次启动迁移完成后统一校验实际 schema，
    纯增量补建（ADD COLUMN / CREATE INDEX），不改动既有数据。

    自愈失败只记 warning，不阻断启动（保持"缺列可诊断"优于"整库不可用"）。
    """
    from cndb.core.database import engine

    try:
        healed_cols = _heal_missing_columns(engine)
        healed_idx = _heal_missing_indexes(engine)
    except Exception as exc:
        logger.warning("schema 自愈检查失败（不阻断启动）: %s", exc)
        return
    if healed_cols or healed_idx:
        logger.warning("schema 自愈完成：补建缺失列 %s，补建缺失索引 %s", healed_cols, healed_idx)


def heal_schema_drift(database_url: str | None = None) -> list[str]:
    """对指定数据库执行一次 schema 自愈，返回补建的列/索引清单.

    供 restore 等非默认库流程调用：与启动期 ``_heal_schema_drift`` 同源，
    但目标库由参数显式指定，且失败向上抛出（恢复流程需要显式感知），
    不像启动期那样静默降级。

    Args:
        database_url: 目标数据库 URL。None 时使用 settings.DATABASE_URL.

    Returns:
        补建的 ``表名.列名`` 与索引名列表.

    Raises:
        SQLAlchemyError: 自愈过程数据库访问失败时向上抛出.
    """
    from sqlalchemy import create_engine

    target = database_url or settings.DATABASE_URL
    engine = create_engine(target)
    try:
        healed_cols = _heal_missing_columns(engine)
        healed_idx = _heal_missing_indexes(engine)
    finally:
        engine.dispose()
    if healed_cols or healed_idx:
        logger.warning("schema 自愈完成：补建缺失列 %s，补建缺失索引 %s", healed_cols, healed_idx)
    return [*healed_cols, *healed_idx]


def ensure_db_migrated() -> None:
    """确保数据库 schema 已处于最新迁移版本.

    启动时调用一次即可，幂等设计：
    - 已在 head → 跳过（alembic 自己会处理）
    - 有未应用迁移 → upgrade
    - 全新空库 → create_all + stamp
    - 半迁移残留 → 先尝试 upgrade，失败则兜底 create_all
    - 任一路径结束后跑 schema 自愈，对照 ORM 元数据补齐缺列/缺索引
    """
    cfg = _build_config()

    if _db_is_fresh():
        # 全新数据库：create_all + stamp 最快
        from cndb.core.database import engine

        logger.info("检测到全新数据库，执行 create_all + stamp head")
        Base.metadata.create_all(bind=engine)
        stamp_head()
        _heal_schema_drift()
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

    _heal_schema_drift()


__all__ = ["ensure_db_migrated", "stamp_head"]


def __getattr__(name: str) -> NoReturn:  # pragma: no cover - 防御性
    """未导出的符号访问时报 AttributeError."""
    raise AttributeError(f"module {__name__!r} 未导出 {name!r}")
