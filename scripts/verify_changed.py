"""按 git 变更定向跑相关测试（四级验证漏斗的 L1）。

需求 0181 C2 / 验收：变更单个后端模块时只跑相关用例且全绿；改动核心文件时回退全量。

设计原则是 **fail-safe**：静态分析算不准「哪些测试覆盖了这个改动」时，宁可跑全量也不漏跑。

判定链：

1. 收集变更集：``git diff --name-only <base>``（base 默认 ``HEAD``，即未提交改动）+
   ``git ls-files --others --exclude-standard``（未跟踪新文件，避免新测试漏跑）。
2. 命中 DANGER（``core/`` / ``models/`` / ``app.py`` / ``alembic/`` / ``conftest.py`` /
   依赖与 pytest 配置）→ 后端全量。
3. 其余按「测试文件 import 了哪个模块前缀」建反向依赖：``src/cndb/plugins/documents/``
   的改动 → 所有 ``from cndb.plugins.documents... import`` 的测试。
4. 选中的测试文件超过全部测试的 60%，或一个都没命中 → 后端全量（前者跑定向已无收益，
   后者说明该模块缺少直接引用它的测试，不能凭静态分析判定「无需验证」）。
5. 前端 ``frontend/src`` 有改动 → ``vitest related``；共享设施（``vite.config.ts`` /
   ``test/setup.ts`` / ``index.css``）或改动文件过多 → 前端全量。

用法::

    make verify-changed                    # 对比 HEAD（当前未提交改动）
    make verify-changed BASE=origin/main   # 对比远程分支（PR / 阶段收尾自查）
    uv run python scripts/verify_changed.py --dry-run   # 只看会跑什么，不执行
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess  # nosec B404 - 门禁脚本需调用 git / pytest / pnpm
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
TESTS = ROOT / "tests"


def runnable(cmd: list[str]) -> list[str]:
    """让 ``pnpm`` 这类 Windows 上是 ``.cmd`` 的命令也能被 subprocess 直接执行。

    CreateProcess 不能直接启动 ``pnpm.cmd``（报 ``WinError 2``），必须经 ``cmd /c``；
    POSIX 上原样返回，行为不变。
    """
    if os.name != "nt":
        return cmd
    exe = shutil.which(cmd[0])
    if exe and Path(exe).suffix.lower() in {".cmd", ".bat"}:
        return ["cmd", "/c", exe, *cmd[1:]]
    return cmd


# 改动这些路径时无法用静态 import 图推断影响面 → 后端全量
BACKEND_DANGER = (
    "src/cndb/core/",
    "src/cndb/models/",
    "src/cndb/app.py",
    "src/cndb/alembic/",
    "tests/conftest.py",
    "tests/helpers.py",
    "tests/fixtures/",
    "pyproject.toml",
    "uv.lock",
    "pytest.ini",
)

# 改动这些前端文件时 vitest related 会命中几乎所有用例，直接全量
FRONTEND_SHARED = (
    "frontend/vite.config.ts",
    "frontend/src/test/setup.ts",
    "frontend/src/test/msw.ts",
    "frontend/src/index.css",
    "frontend/package.json",
)

# 定向选择超过这个比例就没意义了（全量与定向耗时接近，还多了漏跑风险）
MAX_SELECT_RATIO = 0.6
# 前端一次 related 传太多入口文件会让 vitest 自身的图计算变慢
MAX_FRONTEND_ENTRIES = 20

TEST_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(cndb[\w.]*)", re.MULTILINE)


def _git(*args: str) -> str:
    return subprocess.run(  # nosec B603 B607 - 命令为固定常量
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout


def changed_files(base: str) -> list[str]:
    """返回 base 以来（含未跟踪新文件）的变更文件相对路径（posix 风格）."""
    diffed = _git("diff", "--name-only", base)
    untracked = _git("ls-files", "--others", "--exclude-standard")
    paths = {line.strip().replace("\\", "/") for line in (diffed + "\n" + untracked).splitlines()}
    return sorted(p for p in paths if p)


def module_of(path: str) -> str | None:
    """``src/cndb/plugins/x/y.py`` → ``cndb.plugins.x.y``；非 src 下返回 None."""
    if not path.startswith("src/cndb/") or not path.endswith(".py"):
        return None
    rel = path[len("src/") : -len(".py")].replace("/", ".")
    return rel.removesuffix(".__init__")


def impact_key(path: str) -> str | None:
    """把改动模块收敛成「测试 import 前缀」：插件按插件包，其余按模块的父包."""
    module = module_of(path)
    if module is None:
        return None
    parts = module.split(".")
    # cndb.plugins.<name>.* → 整个插件包（插件内模块互相引用很密，按包收更安全）
    if len(parts) >= 3 and parts[1] == "plugins":
        return ".".join(parts[:3])
    # 其余取父包：cndb.cli.seed.x → cndb.cli.seed；cndb.core.config → cndb.core
    return ".".join(parts[:-1]) or module


def build_reverse_index() -> dict[str, set[str]]:
    """``模块前缀 → 引用它的测试文件（相对仓库根）``."""
    index: dict[str, set[str]] = {}
    for test in sorted(TESTS.glob("test_*.py")):
        rel = test.relative_to(ROOT).as_posix()
        for module in TEST_IMPORT_RE.findall(test.read_text(encoding="utf-8", errors="replace")):
            index.setdefault(module, set()).add(rel)
    return index


def tests_for_key(key: str, index: dict[str, set[str]]) -> set[str]:
    """命中 import 前缀能覆盖 key 的测试文件（``cndb.plugins.documents`` 覆盖其子模块）."""
    hits: set[str] = set()
    for module, files in index.items():
        if module == key or module.startswith(key + "."):
            hits |= files
    return hits


def plan_backend(changed: list[str]) -> tuple[list[str] | None, str]:
    """返回 (测试文件列表 或 None 表示全量, 原因)."""
    danger = [p for p in changed if p.startswith(BACKEND_DANGER)]
    if danger:
        # 先判危险路径：pyproject.toml / pytest.ini / uv.lock 不是 .py，按后端过滤会漏判，
        # 但它们决定测试发现与依赖，改了就必须跑全量。
        return None, f"命中共享基础设施 {danger[0]}"

    backend = [p for p in changed if p.startswith(("src/cndb/", "tests/")) and p.endswith(".py")]
    if not backend:
        return [], "无后端 Python 改动"

    index = build_reverse_index()
    selected: set[str] = {p for p in backend if p.startswith("tests/")}
    keys: list[str] = []
    for path in backend:
        key = impact_key(path)
        if key is None:
            continue
        keys.append(key)
        selected |= tests_for_key(key, index)

    total = len(list(TESTS.glob("test_*.py")))
    if not selected:
        return None, "改动模块没有任何测试直接引用它，无法静态判定影响面"
    if total and len(selected) / total > MAX_SELECT_RATIO:
        return None, f"定向命中 {len(selected)}/{total} 个测试文件，已无提速收益"

    return sorted(selected), f"按 import 前缀 {', '.join(sorted(set(keys)))} 命中"


def plan_frontend(changed: list[str]) -> tuple[list[str] | None, str]:
    """返回 (相关入口文件 或 None 表示全量, 原因)."""
    if not any(p.startswith("frontend/") for p in changed):
        return [], "无前端改动"

    # 只有 frontend/src/ 下的文件才是 vitest 入口：根目录的 *.config.ts、scripts/*.mjs
    # 不进 related（传进去只会让 vitest 白算一遍依赖图）。
    src_changed = [p for p in changed if p.startswith("frontend/src/") and p.endswith((".ts", ".tsx"))]
    shared = [p for p in changed if p.startswith(FRONTEND_SHARED)]
    if shared:
        return None, f"命中共享设施 {shared[0]}"
    if not src_changed:
        return [], "前端只改了配置 / 文档，无 TS 改动"
    if len(src_changed) > MAX_FRONTEND_ENTRIES:
        return None, f"改动文件 {len(src_changed)} 个，超过 related 入口上限 {MAX_FRONTEND_ENTRIES}"

    # vitest related 需要相对 frontend/ 的路径
    return [p[len("frontend/") :] for p in src_changed], "vitest related 按改动入口反查"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="按 git 变更定向跑相关测试（需求 0181 C2）")
    parser.add_argument("--base", default="HEAD", help="对比基线（默认 HEAD，含工作区未提交改动）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不执行")
    args = parser.parse_args(argv)

    changed = changed_files(args.base)
    if not changed:
        print(f"[verify-changed] 相对 {args.base} 无变更，无需验证。")
        return 0

    print(f"[verify-changed] 相对 {args.base} 变更 {len(changed)} 个文件：")
    for path in changed[:40]:
        print(f"  - {path}")
    if len(changed) > 40:
        print(f"  … 另有 {len(changed) - 40} 个")

    backend_tests, backend_why = plan_backend(changed)
    frontend_entries, frontend_why = plan_frontend(changed)

    jobs = os.environ.get("PYTEST_JOBS", "8")
    commands: list[tuple[str, list[str], Path]] = []

    if backend_tests is None:
        print(f"[verify-changed] 后端：全量（{backend_why}）")
        commands.append(("后端全量", ["uv", "run", "pytest", "-m", "not slow", "-n", jobs], ROOT))
    elif backend_tests:
        print(f"[verify-changed] 后端：{len(backend_tests)} 个测试文件（{backend_why}）")
        for path in backend_tests:
            print(f"  - {path}")
        commands.append(("后端定向", ["uv", "run", "pytest", "-m", "not slow", "-n", jobs, *backend_tests], ROOT))
    else:
        print(f"[verify-changed] 后端：跳过（{backend_why}）")

    if frontend_entries is None:
        print(f"[verify-changed] 前端：全量（{frontend_why}）")
        commands.append(("前端全量", ["pnpm", "exec", "vitest", "run"], FRONTEND))
    elif frontend_entries:
        print(f"[verify-changed] 前端：{len(frontend_entries)} 个入口（{frontend_why}）")
        for path in frontend_entries:
            print(f"  - {path}")
        commands.append(("前端定向", ["pnpm", "exec", "vitest", "related", "--run", *frontend_entries], FRONTEND))
    else:
        print(f"[verify-changed] 前端：跳过（{frontend_why}）")

    if not commands:
        print("[verify-changed] 无需运行测试（仅文档或非代码改动，改用 make check-docs / check-fast）。")
        return 0

    if args.dry_run:
        print("[verify-changed] --dry-run：不执行以下命令")
        for name, cmd, cwd in commands:
            print(f"  [{name}] (cd {cwd.relative_to(ROOT).as_posix() or '.'}) {' '.join(cmd)}")
        return 0

    for name, cmd, cwd in commands:
        print(f"\n[verify-changed] >> {name}: {' '.join(cmd)}", flush=True)
        code = subprocess.call(runnable(cmd), cwd=cwd)  # nosec B603 - 命令由本脚本构造
        if code != 0:
            print(f"[verify-changed] FAIL {name} 失败（exit={code}）；修完重跑本命令。", file=sys.stderr)
            return code

    print("\n[verify-changed] OK 定向验证全绿。阶段收尾仍须跑 make flow / make check（L2）。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
