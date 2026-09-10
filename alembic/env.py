from __future__ import annotations

import contextlib

# ── 元数据收集：导入所有插件的 models 包，确保 Base.metadata 包含全部表 ──
# 插件注册时已调用 register_models()，这里再显式扫一遍避免遗漏
import importlib
import pkgutil
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import cndb.plugins as _plugins_pkg
from alembic import context
from cndb.core.config import settings
from cndb.models.base import Base

for _importer, _modname, _ispkg in pkgutil.iter_modules(_plugins_pkg.__path__):
    if _modname.startswith("_"):
        continue
    try:
        importlib.import_module(f"cndb.plugins.{_modname}")
        # 尝试导入 models 子模块
        with contextlib.suppress(ImportError):
            importlib.import_module(f"cndb.plugins.{_modname}.models")
    except ImportError:
        continue

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# 动态注入 DATABASE_URL（优先 env.py，回退 settings）
_db_url = settings.DATABASE_URL
# SQLite 特殊：去除 +aiosqlite 等异步后缀，Alembic 用同步驱动
if "+aiosqlite" in _db_url:
    _db_url = _db_url.replace("+aiosqlite", "")
config.set_main_option("sqlalchemy.url", _db_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
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
