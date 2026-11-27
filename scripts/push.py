"""Push the current branch to every git remote and sync tags.

Usage::

    python scripts/push.py
"""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    remotes = subprocess.check_output(["git", "remote"], text=True).split()
    if not remotes:
        print("[push] no git remote configured", file=sys.stderr)
        return 1
    try:
        for remote in remotes:
            print(f"[push] pushing {remote} ...", flush=True)
            subprocess.run(["git", "push", remote], check=True)
            subprocess.run(["git", "push", remote, "--tags"], check=True)
    except subprocess.CalledProcessError as exc:
        print(f"[push] failed (exit code {exc.returncode}), aborted", file=sys.stderr)
        return exc.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
