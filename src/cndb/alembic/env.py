"""包内 alembic env.py，供编程式迁移调用.

与根目录 alembic/env.py 的区别：
- 不依赖 config.config_file_name（编程式调用时为 None）
- 所有路径以当前文件所在目录为基准
- 收集全部插件的 ORM metadata，供 upgrade head 使用
"""

from __future__ import annotations

import contextlib
import importlib
import pkgutil
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import cndb.plugins as _plugins_pkg
from alembic import context
from cndb.core.config import settings
from cndb.models.base import Base

# ── 元数据收集：导入所有插件的 models，确保 Base.metadata 包含全部表 ──
for _importer, _modname, _ispkg in pkgutil.iter_modules(_plugins_pkg.__path__):
    if _modname.startswith("_"):
        continue
    try:
        importlib.import_module(f"cndb.plugins.{_modname}")
        with contextlib.suppress(ImportError):
            importlib.import_module(f"cndb.plugins.{_modname}.models")
    except ImportError:
        continue

config = context.config

# 编程式调用时 config_file_name 为 None，跳过 fileConfig
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 动态注入 DATABASE_URL（优先 env.py，回退 settings）
_db_url = settings.DATABASE_URL
if "+aiosqlite" in _db_url:
    _db_url = _db_url.replace("+aiosqlite", "")
config.set_main_option("sqlalchemy.url", _db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
