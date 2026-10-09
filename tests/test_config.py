"""core.config Settings 测试."""

from __future__ import annotations

import importlib.metadata
from unittest.mock import patch

import pytest

from cndb.core.config import BASE_DIR, Settings, _get_version


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
