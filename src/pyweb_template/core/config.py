"""pyweb_template 应用配置.

基于 pydantic-settings，支持从环境变量和 .env 文件加载。
所有字段均可通过环境变量覆盖（自动转换为大写+下划线风格）。
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from pydantic_settings import BaseSettings


def _find_project_root() -> Path:
    """从当前文件向上递归查找 pyproject.toml 所在目录.

    兼容 editable install（src layout）、wheel 安装和直接运行脚本三种场景。
    """
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    # 兜底：回退到 src 的上一级
    return here.parent.parent


BASE_DIR = _find_project_root()


def _get_version() -> str:
    """从已安装的包元数据中读取版本号.

    优先从 importlib.metadata 获取（安装后的真实版本），
    回退到硬编码版本（开发模式/未安装时）。
    """
    try:
        return importlib.metadata.version("pyweb_template")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0.dev"


class Settings(BaseSettings):
    """应用配置，支持从环境变量和 .env 文件加载.

    所有字段均可通过环境变量覆盖，环境变量名 = 字段名的大写形式。
    例如：`DEBUG=false` 可覆盖默认值。
    """

    APP_NAME: str = "pyweb_template"
    APP_VERSION: str = _get_version()
    DEBUG: bool = True

    # 数据库配置（默认 SQLite，迁移到生产时可替换为 PostgreSQL/MySQL）
    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'pyweb_template.db'}"

    # CORS 配置（开发期放开 Vite 默认端口）
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8000",
    ]

    # API 前缀
    API_V1_PREFIX: str = "/api/v1"

    # 运行时文件目录
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    STATIC_DIR: Path = BASE_DIR / "static"

    # ── 认证授权（基础占位，启用 auth extra 时自动生效）─────────
    JWT_SECRET: str = "pyweb-template-dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24  # 默认 24 小时
    AUTH_ENABLED: bool = False  # 默认关闭，模板期不强制认证

    # ── 插件自动发现目录 ─────────────────────────────────────
    PLUGINS_AUTO_DISCOVER: bool = True
    PLUGINS_DIR: Path = BASE_DIR / "plugins"

    model_config = {"env_file": str(BASE_DIR / ".env"), "env_file_encoding": "utf-8"}


settings = Settings()
