"""只重跑上轮失败用例（``pytest --lf``），并在 lastfailed 为空时显式回退。

背景（需求 0181 C4）：``pytest --lf`` 在 ``.pytest_cache/v/cache/lastfailed`` 为空时
不会报错，而是**静默跑全量**——AI 内环以为在跑 3 个用例，实际吃了整轮全量耗时。

本脚本先判空再决定命令，并把真实行为打印出来：

- lastfailed 有内容 → ``pytest --lf``，只跑失败项；
- lastfailed 缺失 / 为空 → 打印提示后跑全量（``-m "not slow"``），语义显式；
- 传 ``--`` 之后的参数原样透传（如 ``--tb=long`` / ``-x``）。

并发度取环境变量 ``PYTEST_JOBS``（由 Makefile 求值后导出），缺省 8。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404 - 门禁脚本需调用 pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LASTFAILED = ROOT / ".pytest_cache" / "v" / "cache" / "lastfailed"


def _failed_nodes() -> list[str]:
    """读取 lastfailed 缓存里的用例 nodeid 列表（文件缺失 / 损坏一律视为空）."""
    try:
        data = json.loads(LASTFAILED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    return [str(k) for k, v in data.items() if v]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="重跑上轮失败用例（lastfailed 为空时显式回退全量）")
    parser.add_argument("extra", nargs="*", help="透传给 pytest 的其余参数")
    # 用 parse_known_args：本脚本的参数只有 --help，其余（--tb=long / -x / -k ...）
    # 一律原样透传给 pytest，不能让 argparse 因为不认识就退出。
    args, extra = parser.parse_known_args(argv)
    extra = [*args.extra, *extra]

    jobs = os.environ.get("PYTEST_JOBS", "8")
    failed = _failed_nodes()

    if failed:
        print(f"[retest] lastfailed 命中 {len(failed)} 个用例，只重跑这些：", flush=True)
        for node in failed[:20]:
            print(f"  - {node}", flush=True)
        if len(failed) > 20:
            print(f"  … 另有 {len(failed) - 20} 个", flush=True)
        cmd = ["uv", "run", "pytest", "--lf", "-n", jobs, *extra]
    else:
        print(
            "[retest] lastfailed 为空（无失败记录或缓存已清），"
            "`--lf` 此时会静默跑全量——改为显式跑全量，别误以为只跑了几个用例。",
            flush=True,
        )
        cmd = ["uv", "run", "pytest", "-m", "not slow", "-n", jobs, *extra]

    print(f"[retest] 执行: {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=ROOT)  # nosec B603 - 命令为固定常量


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
