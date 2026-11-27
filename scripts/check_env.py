"""Dev environment check: block the runtime pollution that makes backend tests hang.

Trae injects ``LD_LIBRARY_PATH`` into child processes, and the bundled old libsqlite3 does not
provide ``sqlite3_deserialize``. Once the Python ``_sqlite3`` extension links against it,
``sqlite3.Connection.deserialize`` disappears: in the mild case tests fail, in the worst case
``import sqlite3`` hangs and ``make test`` / ``make cov`` print nothing for a long time (the
tests are not slow, the process is stuck loading the shared library).

The Makefile already purifies recipes started by make via ``unexport LD_LIBRARY_PATH``; this
script moves the same guard to the entry of every gate: an unhealthy environment gives a
verdict and a fix command within a second instead of letting the gate run into a timeout.

Usage::

    python scripts/check_env.py

Exit code 0 means the environment is healthy, 1 means the current shell must be fixed before
running any gate.
"""

from __future__ import annotations

import os
import sys

# Variables that rewrite the shared-library search order: report them so the same trap is not
# hit again in another terminal
_LIB_PATH_VARS: tuple[str, ...] = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH")


def probe() -> tuple[bool, str, str]:
    """Probe whether sqlite3 in the current interpreter supports deserialize.

    Returns:
        (available, failure reason (empty when available), SQLite version).
    """
    try:
        import sqlite3
    except Exception as exc:  # a failed shared-library load raises at import time
        return False, f"import sqlite3 failed ({exc})", "unknown"

    version = sqlite3.sqlite_version
    if hasattr(sqlite3.Connection, "deserialize"):
        return True, "", version
    return (
        False,
        "the libsqlite3 linked by this Python was built without sqlite3_deserialize"
        " (sqlite3.Connection.deserialize is missing)",
        version,
    )


def polluted_vars() -> dict[str, str]:
    """Return the non-empty variables in the current shell that rewrite the library search path."""
    return {name: value for name in _LIB_PATH_VARS if (value := os.environ.get(name, ""))}


def print_fix_guide(polluted: dict[str, str]) -> None:
    """Print fix commands that can be copied directly on the current platform."""
    print()
    print("Fix (pick one, then re-run this script to confirm):")
    for name, value in polluted.items():
        print(f"  - current {name}={value}")
    print("  1) bash / zsh: unset LD_LIBRARY_PATH")
    print("  2) PowerShell: Remove-Item Env:LD_LIBRARY_PATH -ErrorAction SilentlyContinue")
    print("  3) just use a make target (the Makefile unexports it, recipes do not inherit it): make flow / make test")
    print("  4) switch to a terminal without the variable, or reopen the IDE panel, then retry")
    print()
    print("Root cause: the old libsqlite3 injected by Trae lacks sqlite3_deserialize, so backend tests")
    print("hang during import instead of failing.")


def main() -> int:
    ok, reason, version = probe()
    polluted = polluted_vars()

    if not ok:
        print(f"[env] environment unhealthy: {reason}")
        print(f"[env] interpreter: {sys.executable}")
        print(f"[env] loaded SQLite: {version}")
        if not polluted:
            print(
                "[env] LD_LIBRARY_PATH / DYLD_LIBRARY_PATH is not set; check PATH or whether the venv links an old libsqlite3."
            )
        print_fix_guide(polluted)
        return 1

    print(f"[env] ok: Python {sys.version.split()[0]} / SQLite {version} / deserialize available")
    if polluted:
        print(f"[env] note: {', '.join(polluted)} is set but sqlite3 works (the Makefile unexports it).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
