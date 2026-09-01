"""settings 环境模块测试."""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured


def test_prod_requires_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产环境缺失 CNDB_SECRET_KEY 时拒绝启动."""
    monkeypatch.setenv("CNDB_SECRET_KEY", "placeholder")
    from cndb.settings import prod

    monkeypatch.delenv("CNDB_SECRET_KEY")
    with pytest.raises(ImproperlyConfigured, match="CNDB_SECRET_KEY"):
        prod._require_secret_key()


def test_prod_secret_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """密钥从环境变量读取."""
    monkeypatch.setenv("CNDB_SECRET_KEY", "abc123")
    from cndb.settings import prod

    assert prod._require_secret_key() == "abc123"


def test_dev_settings_debug_true() -> None:
    """开发环境开启 DEBUG."""
    from cndb.settings import dev

    assert dev.DEBUG is True
