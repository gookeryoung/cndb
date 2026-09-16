"""cndb 应用配置.

基于 pydantic-settings，支持从环境变量和 .env 文件加载。
所有字段均可通过环境变量覆盖（自动转换为大写+下划线风格）。

路径分层：
- BASE_DIR：代码/静态资源目录（只读），定位 pyproject.toml 或 alembic.ini。
- DATA_DIR：用户可写数据目录（数据库、上传附件等）。
  开发模式与 BASE_DIR 相同；打包安装到只读目录（如 Program Files）时
  自动重定向到用户数据目录（Windows %APPDATA%/cndb、Linux ~/.local/share/cndb
  等），避免"attempt to write a readonly database"错误。
"""

from __future__ import annotations

import importlib.metadata
import os
import sys
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


def _get_user_data_dir() -> Path:
    """返回跨平台用户可写数据目录.

    - Windows: %APPDATA%/cndb （优先）或 %LOCALAPPDATA%/cndb
    - macOS:   ~/Library/Application Support/cndb
    - Linux:   $XDG_DATA_HOME/cndb 或 ~/.local/share/cndb
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "cndb"
        return Path.home() / ".cndb"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "cndb"
    # Linux / 其他 POSIX
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "cndb"
    return Path.home() / ".local" / "share" / "cndb"


BASE_DIR = _find_project_root()

# 可写数据目录：打包模式 → 用户目录，开发模式 → BASE_DIR
DATA_DIR = _get_user_data_dir() if _is_frozen() else BASE_DIR

# 确保用户数据目录存在（打包模式下首次启动时创建）
if _is_frozen():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


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
    - DATA_DIR（用户数据）→ 可写，开发模式 = BASE_DIR；打包模式 = 用户数据目录
    """

    APP_NAME: str = "cndb"
    APP_VERSION: str = _get_version()
    DEBUG: bool = True

    # 数据库配置（默认 SQLite，迁移到生产时可替换为 PostgreSQL/MySQL）
    # 打包模式下数据库存放在用户数据目录，避免写入 Program Files 等只读位置
    DATABASE_URL: str = f"sqlite:///{DATA_DIR / 'cndb.db'}"

    # CORS 配置（开发期放开 Vite 默认端口）
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8000",
    ]

    # API 前缀
    API_V1_PREFIX: str = "/api/v1"

    # 运行时文件目录
    # UPLOAD_DIR / PLUGINS_DIR 指向 DATA_DIR（可写）；STATIC_DIR 指向 BASE_DIR（只读资源）
    UPLOAD_DIR: Path = DATA_DIR / "uploads"
    STATIC_DIR: Path = BASE_DIR / "static"

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
    PLUGINS_DIR: Path = DATA_DIR / "plugins"

    model_config = {"env_file": str(BASE_DIR / ".env"), "env_file_encoding": "utf-8"}


settings = Settings()
