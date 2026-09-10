"""cndb 根包 smoke 测试."""

from __future__ import annotations

import cndb
from cndb import schemas, services


def test_version_is_present() -> None:
    assert cndb.__version__


def test_app_factory_is_accessible() -> None:
    """Facade re-export 应包含关键符号."""
    assert hasattr(cndb, "PluginBase")
    assert hasattr(cndb, "Settings")
    assert hasattr(cndb, "app")


def test_schemas_and_services_are_importable() -> None:
    """schema/services 包应可正常导入."""
    assert schemas is not None
    assert services is not None
