"""清理构建产物与工具缓存（跨平台替代 rm -rf 白名单）.

用法::

    python scripts/clean.py
"""

from __future__ import annotations

import pathlib
import shutil
import sys

# 仓库根下的构建产物 / 工具缓存
_ROOT_PATTERNS = (
    "build",
    "dist",
    "wheels",
    "*.egg-info",
    "htmlcov",
    ".coverage",
    ".coverage.*",
    "coverage.xml",
    ".ruff_cache",
    ".pyrefly_cache",
    ".mypy_cache",
)
# 需要递归清理 __pycache__ / *.pyc 的源码目录
_SOURCE_DIRS = ("src", "tests")


def _remove(path: pathlib.Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def main() -> int:
    for pattern in _ROOT_PATTERNS:
        for path in pathlib.Path().glob(pattern):
            _remove(path)
    for base in map(pathlib.Path, _SOURCE_DIRS):
        for cache in base.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
        for artifact in base.rglob("*"):
            if artifact.suffix in {".pyc", ".pyo"}:
                artifact.unlink(missing_ok=True)
    print("[clean] 构建产物与缓存已清理")
    return 0


if __name__ == "__main__":
    sys.exit(main())
