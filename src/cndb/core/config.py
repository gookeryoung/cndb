"""cndb 应用配置.

基于 pydantic-settings，支持从环境变量和 .env 文件加载。
所有字段均可通过环境变量覆盖（自动转换为大写+下划线风格）。

路径约定：
- BASE_DIR：代码/静态资源目录（只读），定位 pyproject.toml 或 alembic.ini。
- HOME_DIR: 用户主目录（~），全局持久化数据根目录。
- DATA_DIR：用户可写数据根目录（统一为 ~/.cndb）。
  下分子目录职责：
  - CONFIG_DIR:  配置文件（.env 等）
  - DATABASE_DIR: SQLite 数据库文件
  - UPLOAD_DIR:  用户上传的附件（按 workspace_id 隔离）
  - PLUGINS_DIR: 插件自动发现目录
  - BACKUP_DIR:  备份归档默认输出目录
  - CACHE_DIR:   运行时缓存（临时文件、API 响应缓存等）
  - LOG_DIR:     日志文件
- STATIC_DIR:  前端静态资源（只读，指向 BASE_DIR/static）
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from pydantic_settings import BaseSettings


def _find_project_root() -> Path:
    """从当前文件向上递归查找项目根目录.

    场景兼容：
    - 开发 editable install：src layout → 找到 pyproject.toml
    - wheel 安装：site-packages/cndb → 找不到 pyproject.toml，兜底到包父目录
    - fspack 打包：dist/src/src/cndb/core/ → 找不到 pyproject.toml，
      向上找 dist/src/（那里有 alembic.ini）
    """
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    # 兜底策略：向上找第一个包含 alembic.ini 的目录
    # fspack 打包后 dist/src/ 会命中；wheel 安装时回退到 here.parent.parent
    for candidate in (here, *here.parents):
        if (candidate / "alembic.ini").is_file():
            return candidate
    return here.parent.parent


def _is_frozen() -> bool:
    """检测是否处于打包安装模式（非开发模式）.

    判断依据：BASE_DIR 下没有 pyproject.toml。
    - 开发模式：有 pyproject.toml → False
    - 打包安装（fspack/wheel）：无 pyproject.toml → True
    """
    return not (BASE_DIR / "pyproject.toml").is_file()


# ── 路径常量 ──────────────────────────────────────────────────

BASE_DIR = _find_project_root()
HOME_DIR = Path.home()

# 统一的用户数据根目录（跨平台一致，不再区分开发/打包模式）
DATA_DIR = HOME_DIR / ".cndb"

# 子目录
CONFIG_DIR = DATA_DIR / "config"
DATABASE_DIR = DATA_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
PLUGINS_DIR = DATA_DIR / "plugins"
BACKUP_DIR = DATA_DIR / "backups"
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = DATA_DIR / "logs"

# 只读静态资源（前端打包产物）
STATIC_DIR = BASE_DIR / "static"

# 首次启动时自动创建必要的可写目录（打包模式 / 开发模式均需创建）
for _d in (DATA_DIR, CONFIG_DIR, DATABASE_DIR, UPLOAD_DIR, PLUGINS_DIR, BACKUP_DIR, CACHE_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _get_version() -> str:
    """从已安装的包元数据中读取版本号.

    优先从 importlib.metadata 获取（安装后的真实版本），
    回退到硬编码版本（开发模式/未安装时）。
    """
    try:
        return importlib.metadata.version("cndb")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0.dev"


class Settings(BaseSettings):
    """应用配置，支持从环境变量和 .env 文件加载.

    所有字段均可通过环境变量覆盖，环境变量名 = 字段名的大写形式。
    例如：`DEBUG=false` 可覆盖默认值。

    路径约定：
    - BASE_DIR（代码/静态资源）→ 只读，指向 pyproject.toml / alembic.ini 所在目录
    - DATA_DIR（用户数据根）→ 可写，统一为 ~/.cndb
    - CONFIG_DIR / DATABASE_DIR / UPLOAD_DIR / PLUGINS_DIR / BACKUP_DIR / CACHE_DIR / LOG_DIR
      → 均为 DATA_DIR 的子目录，启动时自动创建
    - STATIC_DIR（前端静态资源）→ 只读，指向 BASE_DIR/static
    """

    APP_NAME: str = "cndb"
    APP_VERSION: str = _get_version()
    DEBUG: bool = True

    # 数据库配置（默认 SQLite，迁移到生产时可替换为 PostgreSQL/MySQL）
    DATABASE_URL: str = f"sqlite:///{DATABASE_DIR / 'cndb.db'}"

    # CORS 配置（开发期放开 Vite 默认端口）
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8000",
    ]

    # API 前缀
    API_V1_PREFIX: str = "/api/v1"

    # 运行时文件目录（全部位于 ~/.cndb 下）
    DATA_DIR: Path = DATA_DIR
    CONFIG_DIR: Path = CONFIG_DIR
    DATABASE_DIR: Path = DATABASE_DIR
    UPLOAD_DIR: Path = UPLOAD_DIR
    STATIC_DIR: Path = STATIC_DIR
    BACKUP_DIR: Path = BACKUP_DIR
    CACHE_DIR: Path = CACHE_DIR
    LOG_DIR: Path = LOG_DIR

    # ── 认证授权（bcrypt/python-jose 已在主依赖中，始终可用）─────────
    JWT_SECRET: str = "cndb-dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24  # 默认 24 小时
    AUTH_ENABLED: bool = True  # 默认开启，生产环境必须认证

    # ── 微信小程序认证 ─────────────────────────────────────
    WECHAT_AUTH_ENABLED: bool = False
    WECHAT_APPID: str = ""
    WECHAT_SECRET: str = ""
    WECHAT_LOGIN_AUTO_REGISTER: bool = True

    # ── 插件自动发现目录 ─────────────────────────────────────
    PLUGINS_AUTO_DISCOVER: bool = True
    PLUGINS_DIR: Path = PLUGINS_DIR

    # ── 配置文件加载 ─────────────────────────────────────
    model_config = {"env_file": str(CONFIG_DIR / ".env"), "env_file_encoding": "utf-8"}


settings = Settings()
