"""Verify that the key .gitkeep files exist in the repository.

These empty placeholders keep otherwise empty directories alive after ``git clone`` / CI
checkout; once lost, steps such as hatchling force-include that depend on the real directory
path fail immediately. The script is called from the pre-commit hook and the
``make check`` flow to fail fast.

Usage::

    python scripts/check_gitkeep.py              # check the default list
    python scripts/check_gitkeep.py --fix        # recreate missing files
    python scripts/check_gitkeep.py path1 path2  # check the given paths (relative to repo root)

Exit code 0 means everything is present, 1 means something is missing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ── Default list: .gitkeep files whose absence breaks CI/CD or packaging ──────
# Paths are relative to the repository root (this file lives in scripts/, hence one level up)
_DEFAULT_KEEPS: tuple[str, ...] = (
    # hatchling force-include requires src/cndb/static/ to really exist
    "src/cndb/static/.gitkeep",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def check(paths: list[str], *, fix: bool = False) -> int:
    """Check whether the given .gitkeep paths exist.

    Args:
        paths: .gitkeep paths relative to the repository root.
        fix: create the empty file and its parent directory when missing.

    Returns:
        Number of missing files (0 means everything is present).
    """
    root = _repo_root()
    missing: list[Path] = []

    for rel in paths:
        fp = root / rel
        if fp.is_file():
            continue
        if fix:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.touch()
            print(f"[gitkeep] restored {rel}")
        else:
            missing.append(fp)
            print(f"[gitkeep] missing: {rel}  (directory {fp.parent})")

    if missing:
        print()
        print(f"{len(missing)} .gitkeep file(s) missing.")
        print("Once these files leave the working tree, the empty directories no longer exist after")
        print("git checkout, which breaks steps such as hatchling force-include.")
        print("Run `python scripts/check_gitkeep.py --fix` to restore them, or touch them manually.")
        return 1

    print(f"[gitkeep] all present ({len(paths)} checked)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify that key .gitkeep files exist, optionally restoring missing ones.",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Create the missing empty .gitkeep files and their parent directories.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help=".gitkeep paths to check, relative to the repository root; defaults to the project list.",
    )
    args = parser.parse_args(argv)

    targets = args.paths if args.paths else list(_DEFAULT_KEEPS)
    return check(targets, fix=args.fix)


if __name__ == "__main__":
    sys.exit(main())
