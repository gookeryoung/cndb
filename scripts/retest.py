"""Re-run only last round's failing tests (``pytest --lf``), falling back explicitly when empty.

Background (requirement 0181 C4): when ``.pytest_cache/v/cache/lastfailed`` is empty,
``pytest --lf`` does not fail — it **silently runs the whole suite**, so the AI inner loop
believes it is running three tests while paying for a full round.

This script decides after checking for emptiness and prints what it actually does:

- lastfailed has entries -> ``pytest --lf``, only the failures;
- lastfailed missing / empty -> print a notice and run the full suite (``-m "not slow"``);
- arguments after ``--`` are passed through (e.g. ``--tb=long`` / ``-x``).

Concurrency comes from the ``PYTEST_JOBS`` environment variable (exported by the Makefile),
defaulting to 8.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404 - gate scripts need to call pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LASTFAILED = ROOT / ".pytest_cache" / "v" / "cache" / "lastfailed"


def _failed_nodes() -> list[str]:
    """Read the test node ids from the lastfailed cache (missing / corrupt counts as empty)."""
    try:
        data = json.loads(LASTFAILED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    return [str(k) for k, v in data.items() if v]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Re-run last round's failures (falls back to the full suite explicitly)"
    )
    parser.add_argument("extra", nargs="*", help="remaining arguments passed through to pytest")
    # parse_known_args: this script only owns --help, everything else (--tb=long / -x / -k ...)
    # is passed to pytest verbatim instead of making argparse exit on an unknown option.
    args, extra = parser.parse_known_args(argv)
    extra = [*args.extra, *extra]

    jobs = os.environ.get("PYTEST_JOBS", "8")
    failed = _failed_nodes()

    if failed:
        print(f"[retest] lastfailed has {len(failed)} test(s), re-running those only:", flush=True)
        for node in failed[:20]:
            print(f"  - {node}", flush=True)
        if len(failed) > 20:
            print(f"  ... {len(failed) - 20} more", flush=True)
        cmd = ["uv", "run", "pytest", "--lf", "-n", jobs, *extra]
    else:
        print(
            "[retest] lastfailed is empty (no failures recorded or the cache was cleared); "
            "`--lf` would silently run the full suite here — running the full suite explicitly instead.",
            flush=True,
        )
        cmd = ["uv", "run", "pytest", "-m", "not slow", "-n", jobs, *extra]

    print(f"[retest] running: {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=ROOT)  # nosec B603 - fixed command constants


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
