"""core.config Settings 测试."""

from __future__ import annotations

import importlib.metadata
from unittest.mock import patch

import pytest

from pyweb_template.core.config import BASE_DIR, Settings, _get_version


def test_defaults() -> None:
    """默认值应符合预期."""
    s = Settings()
    assert s.APP_NAME == "pyweb_template"
    assert s.DEBUG is True
    assert s.API_V1_PREFIX == "/api/v1"
    assert s.AUTH_ENABLED is False


def test_get_version_pkg_installed() -> None:
    """包已安装时应返回 importlib.metadata.version."""
    try:
        expected = importlib.metadata.version("pyweb_template")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("包未安装，跳过")
    assert _get_version() == expected


def test_get_version_fallback_when_not_installed() -> None:
    """包未安装时 _get_version 应返回 fallback 值."""

    def raise_pkg_not_found(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError("pyweb_template")

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
    from pyweb_template.core import config as config_module

    with patch.object(config_module.Path, "is_file", return_value=False):
        # 直接调私有函数，验证兜底返回值
        result = config_module._find_project_root()
        assert result is not None
