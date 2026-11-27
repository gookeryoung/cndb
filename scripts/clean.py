"""Clean build artifacts and tool caches (cross-platform replacement for an rm -rf allowlist).

Usage::

    python scripts/clean.py
"""

from __future__ import annotations

import pathlib
import shutil
import sys

# Build artifacts / tool caches under the repository root
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
# Source directories whose __pycache__ / *.pyc are removed recursively
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
    print("[clean] build artifacts and caches removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
