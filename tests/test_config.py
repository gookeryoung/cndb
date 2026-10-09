"""core.config Settings 测试."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from unittest.mock import patch

import pytest

from cndb.core.config import BASE_DIR, STATIC_DIR, Settings, _get_version


def test_defaults() -> None:
    """默认值应符合预期."""
    s = Settings()
    assert s.APP_NAME == "cndb"
    assert s.DEBUG is True
    assert s.API_V1_PREFIX == "/api/v1"
    assert s.AUTH_ENABLED is True


def test_get_version_pkg_installed() -> None:
    """包已安装时应返回 importlib.metadata.version."""
    try:
        expected = importlib.metadata.version("cndb")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("包未安装，跳过")
    assert _get_version() == expected


def test_get_version_fallback_when_not_installed() -> None:
    """包未安装时 _get_version 应返回 fallback 值."""

    def raise_pkg_not_found(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError("cndb")

    with patch.object(importlib.metadata, "version", side_effect=raise_pkg_not_found):
        v = _get_version()
        assert v  # 非空字符串
        assert "." in v  # 版本号格式


def test_database_url_default_sqlite() -> None:
    """默认 DATABASE_URL 为 SQLite."""
    s = Settings()
    assert s.DATABASE_URL.startswith("sqlite:///")


def test_cors_origins_contains_vite() -> None:
    """CORS 默认包含 Vite 5173 端口."""
    s = Settings()
    assert "http://localhost:5173" in s.CORS_ORIGINS


def test_base_dir_is_project_root() -> None:
    """BASE_DIR 应指向项目根目录."""
    assert (BASE_DIR / "pyproject.toml").exists()


def test_version_is_str() -> None:
    """APP_VERSION 应是非空字符串."""
    assert isinstance(Settings().APP_VERSION, str)
    assert Settings().APP_VERSION


def test_find_project_root_falls_back_when_no_pyproject() -> None:
    """找不到 pyproject.toml 时应回退到 src 的上一级."""
    from cndb.core import config as config_module

    with patch.object(config_module.Path, "is_file", return_value=False):
        # 直接调私有函数，验证兜底返回值
        result = config_module._find_project_root()
        assert result is not None


def test_database_url_accepts_cndb_prefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """CNDATABASE_URL 必须生效（compose/.env 模板统一用 CNDB_ 前缀）.

    回归背景：Settings 早期只按字段名读 DATABASE_URL，compose 传入的
    CNDATABASE_URL 被静默忽略 —— 容器正常启动但始终连 SQLite，无任何报错。
    """
    monkeypatch.setenv("CNDATABASE_URL", "postgresql+psycopg://u:p@db:5432/cndb")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert Settings().DATABASE_URL == "postgresql+psycopg://u:p@db:5432/cndb"


def test_database_url_still_accepts_plain_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """DATABASE_URL 保持可用，避免加alias 后破坏既有部署."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/plain.db")
    monkeypatch.delenv("CNDATABASE_URL", raising=False)
    assert Settings().DATABASE_URL == "sqlite:////tmp/plain.db"


def test_database_url_default_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """两个变量都未设置时回落到 SQLite 默认值."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CNDATABASE_URL", raising=False)
    assert Settings().DATABASE_URL.startswith("sqlite:///")


def test_static_dir_lives_under_package_dir() -> None:
    """STATIC_DIR 必须挂在包目录下，不能挂在 BASE_DIR 下.

    回归背景：曾写成 ``BASE_DIR / "static"``。开发模式下两者都指向
    src/cndb，测试全绿；但 wheel 安装时 _find_project_root() 找不到
    pyproject.toml / alembic.ini，会兜底返回 site-packages，于是
    STATIC_DIR 变成不存在的 ``site-packages/static``（真实文件在其下的
    cndb/ 里）。

    这个错误在开发环境完全不可见，却让 deploy-tencent.yml 的 CI 冒烟检查
    ``assert STATIC_DIR.is_dir()`` 变成假通过 —— 镜像里前端产物缺失也会绿灯。
    """
    package_dir = Path(__file__).resolve().parents[1] / "src" / "cndb"
    # 开发模式下应精确等于 src/cndb/static；wheel/fspack 模式下路径前缀不同，
    # 但父目录名必须是 cndb —— 这正是旧实现（BASE_DIR/static）会踩空的地方。
    assert STATIC_DIR.parent.name == "cndb", f"STATIC_DIR 应位于包目录内，实际: {STATIC_DIR}"
    assert STATIC_DIR.is_dir(), f"STATIC_DIR 不存在: {STATIC_DIR}"
    assert package_dir.name == "cndb"


def test_static_dir_matches_app_serving_path() -> None:
    """STATIC_DIR 必须与 app.py 实际挂载的 _STATIC 指向同一目录.

    STATIC_DIR 是对外暴露的配置项，app.py 的 _STATIC 才是真正服务的目录。
    两者算法必须一致，否则配置显示就绪但页面 404。
    """
    from cndb.app import _STATIC

    assert STATIC_DIR.resolve() == _STATIC.resolve()
