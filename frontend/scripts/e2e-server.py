"""E2E 后端一键启动（供 Playwright webServer 使用）。

流程：seed 注入演示数据（幂等 drop_all 重建）→ 启动后端:8000。
前置：前端已构建到 src/cndb/static（make frontend-build / pnpm build）。
跨平台（Windows/macOS/Linux），替代 bash/PowerShell 脚本。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    # 定位项目根目录（scripts/ → frontend/ → 项目根）
    root = Path(__file__).resolve().parent.parent.parent
    os.chdir(root)

    port = os.environ.get("E2E_PORT", "8000")

    print("[e2e-server] seed 演示数据...", flush=True)
    seed = subprocess.run(
        ["uv", "run", "cndb", "seed"],
        cwd=root,
    )
    if seed.returncode != 0:
        print(f"[e2e-server] seed 失败 (exit={seed.returncode})", file=sys.stderr, flush=True)
        return seed.returncode

    print(f"[e2e-server] 启动后端 http://127.0.0.1:{port} ...", flush=True)
    # exec 语义：用 serve 进程替换当前进程，Playwright 能正确感知进程生命周期
    return subprocess.call(
        ["uv", "run", "cndb", "serve", "--host", "127.0.0.1", "--port", port],
        cwd=root,
    )


if __name__ == "__main__":
    sys.exit(main())
