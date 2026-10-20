"""推送当前分支到全部 git remote，并同步 tags.

用法::

    python scripts/push.py
"""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    remotes = subprocess.check_output(["git", "remote"], text=True).split()
    if not remotes:
        print("[push] 未配置 git remote", file=sys.stderr)
        return 1
    try:
        for remote in remotes:
            print(f"[push] 推送 {remote} ...", flush=True)
            subprocess.run(["git", "push", remote], check=True)
            subprocess.run(["git", "push", remote, "--tags"], check=True)
    except subprocess.CalledProcessError as exc:
        print(f"[push] 失败（退出码 {exc.returncode}），已中止", file=sys.stderr)
        return exc.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
