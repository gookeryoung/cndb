"""cndb 根包 smoke 测试."""

from __future__ import annotations

import subprocess
import sys

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


def test_facade_import_does_not_eagerly_load_app() -> None:
    """GUI 冷启动回归：import cndb 不容许串起 FastAPI app 依赖图.

    历史问题：``cndb/__init__.py`` eager 导入 ``cndb.app`` 会构建整个
    FastAPI/插件后端，导致 fspack 打包后的 GUI 启动被拖慢数秒。
    本测试在独立子进程断言 ``import cndb`` 后 ``cndb.app`` 未进入
    ``sys.modules``（惰性门面生效），守护该性能契约。
    """
    code = "import cndb, sys; assert 'cndb.app' not in sys.modules, 'cndb.app was eagerly imported'; print('LAZY_OK')"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"惰性门面失效: {result.stdout}\n{result.stderr}"
    assert "LAZY_OK" in result.stdout
