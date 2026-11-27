"""Run the tests related to a git change (L1 of the four-level verification funnel).

Requirement 0181 C2 / acceptance: changing a single backend module runs only the related tests
and they all pass; touching a core file falls back to the full suite.

The design principle is **fail-safe**: when static analysis cannot tell which tests cover the
change, run everything rather than risk missing one.

Decision chain:

1. Collect the change set: ``git diff --name-only <base>`` (base defaults to ``HEAD``, i.e.
   uncommitted changes) + ``git ls-files --others --exclude-standard`` (untracked new files, so
   new tests are not skipped).
2. A hit on DANGER (``core/`` / ``models/`` / ``app.py`` / ``alembic/`` / ``conftest.py`` /
   dependency and pytest config) -> full backend suite.
3. Everything else builds a reverse dependency from "which module prefix the test imports":
   a change under ``src/cndb/plugins/documents/`` -> every test doing
   ``from cndb.plugins.documents... import``.
4. More than 60% of all tests selected, or no hit at all -> full backend suite (the former has
   no speed benefit left, the latter means the module has no test referencing it directly and
   static analysis must not conclude "no verification needed").
5. Changes under ``frontend/src`` -> ``vitest related``; shared infrastructure
   (``vite.config.ts`` / ``test/setup.ts`` / ``index.css``) or too many changed files -> full
   frontend suite.

Usage::

    make verify-changed                    # compare against HEAD (current uncommitted changes)
    make verify-changed BASE=origin/main   # compare against a remote branch (PR / phase wrap-up)
    uv run python scripts/verify_changed.py --dry-run   # only show what would run
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess  # nosec B404 - gate scripts need git / pytest / pnpm
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
TESTS = ROOT / "tests"


def runnable(cmd: list[str]) -> list[str]:
    """Make commands such as ``pnpm`` executable on Windows, where they are ``.cmd`` shims.

    CreateProcess cannot start ``pnpm.cmd`` directly (``WinError 2``), it must go through
    ``cmd /c``; on POSIX the command is returned unchanged.
    """
    if os.name != "nt":
        return cmd
    exe = shutil.which(cmd[0])
    if exe and Path(exe).suffix.lower() in {".cmd", ".bat"}:
        return ["cmd", "/c", exe, *cmd[1:]]
    return cmd


# Changing these paths makes the impact impossible to infer from the static import graph
# -> full backend suite
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

# Changing these frontend files makes vitest related hit almost every test, so go full
FRONTEND_SHARED = (
    "frontend/vite.config.ts",
    "frontend/src/test/setup.ts",
    "frontend/src/test/msw.ts",
    "frontend/src/index.css",
    "frontend/package.json",
)

# Beyond this ratio targeted selection is pointless (the full suite takes about as long and
# carries no risk of missing tests)
MAX_SELECT_RATIO = 0.6
# Passing too many entry files to one related run slows vitest's own graph computation
MAX_FRONTEND_ENTRIES = 20

TEST_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(cndb[\w.]*)", re.MULTILINE)


def _git(*args: str) -> str:
    return subprocess.run(  # nosec B603 B607 - fixed command constants
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout


def changed_files(base: str) -> list[str]:
    """Return changed file paths since base (untracked files included), posix style."""
    diffed = _git("diff", "--name-only", base)
    untracked = _git("ls-files", "--others", "--exclude-standard")
    paths = {line.strip().replace("\\", "/") for line in (diffed + "\n" + untracked).splitlines()}
    return sorted(p for p in paths if p)


def module_of(path: str) -> str | None:
    """``src/cndb/plugins/x/y.py`` -> ``cndb.plugins.x.y``; None outside src."""
    if not path.startswith("src/cndb/") or not path.endswith(".py"):
        return None
    rel = path[len("src/") : -len(".py")].replace("/", ".")
    return rel.removesuffix(".__init__")


def impact_key(path: str) -> str | None:
    """Collapse the changed module into a "test import prefix": plug-ins by package, rest by parent package."""
    module = module_of(path)
    if module is None:
        return None
    parts = module.split(".")
    # cndb.plugins.<name>.* -> the whole plugin package (modules inside a plugin import each
    # other densely, so collapsing to the package is safer)
    if len(parts) >= 3 and parts[1] == "plugins":
        return ".".join(parts[:3])
    # Everything else uses the parent package:
    # cndb.cli.seed.x -> cndb.cli.seed; cndb.core.config -> cndb.core
    return ".".join(parts[:-1]) or module


def build_reverse_index() -> dict[str, set[str]]:
    """``module prefix -> tests importing it (relative to the repository root)``."""
    index: dict[str, set[str]] = {}
    for test in sorted(TESTS.glob("test_*.py")):
        rel = test.relative_to(ROOT).as_posix()
        for module in TEST_IMPORT_RE.findall(test.read_text(encoding="utf-8", errors="replace")):
            index.setdefault(module, set()).add(rel)
    return index


def tests_for_key(key: str, index: dict[str, set[str]]) -> set[str]:
    """Tests whose import prefix is covered by key (``cndb.plugins.documents`` covers submodules)."""
    hits: set[str] = set()
    for module, files in index.items():
        if module == key or module.startswith(key + "."):
            hits |= files
    return hits


def plan_backend(changed: list[str]) -> tuple[list[str] | None, str]:
    """Return (test files, or None for the full suite, reason)."""
    danger = [p for p in changed if p.startswith(BACKEND_DANGER)]
    if danger:
        # Check danger paths first: pyproject.toml / pytest.ini / uv.lock are not .py files and
        # would be missed by a backend filter, yet they decide test discovery and dependencies,
        # so a change to them requires the full suite.
        return None, f"shared infrastructure hit: {danger[0]}"

    backend = [p for p in changed if p.startswith(("src/cndb/", "tests/")) and p.endswith(".py")]
    if not backend:
        return [], "no backend Python change"

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
        return None, "no test references the changed module directly, impact cannot be inferred statically"
    if total and len(selected) / total > MAX_SELECT_RATIO:
        return None, f"targeted run hit {len(selected)}/{total} test files, no speed benefit left"

    return sorted(selected), f"hit via import prefix {', '.join(sorted(set(keys)))}"


def plan_frontend(changed: list[str]) -> tuple[list[str] | None, str]:
    """Return (related entry files, or None for the full suite, reason)."""
    if not any(p.startswith("frontend/") for p in changed):
        return [], "no frontend change"

    # Only files under frontend/src/ are vitest entries: root-level *.config.ts and
    # scripts/*.mjs do not go into related (passing them just makes vitest compute the graph
    # for nothing).
    src_changed = [p for p in changed if p.startswith("frontend/src/") and p.endswith((".ts", ".tsx"))]
    shared = [p for p in changed if p.startswith(FRONTEND_SHARED)]
    if shared:
        return None, f"shared infrastructure hit: {shared[0]}"
    if not src_changed:
        return [], "frontend changed only config / docs, no TS change"
    if len(src_changed) > MAX_FRONTEND_ENTRIES:
        return None, f"{len(src_changed)} files changed, above the related entry cap of {MAX_FRONTEND_ENTRIES}"

    # vitest related needs paths relative to frontend/
    return [p[len("frontend/") :] for p in src_changed], "vitest related resolved from changed entries"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run only the tests related to a git change (requirement 0181 C2)")
    parser.add_argument(
        "--base", default="HEAD", help="base to compare against (default HEAD, includes uncommitted changes)"
    )
    parser.add_argument("--dry-run", action="store_true", help="only print the plan, execute nothing")
    args = parser.parse_args(argv)

    changed = changed_files(args.base)
    if not changed:
        print(f"[verify-changed] no changes relative to {args.base}, nothing to verify.")
        return 0

    print(f"[verify-changed] {len(changed)} file(s) changed relative to {args.base}:")
    for path in changed[:40]:
        print(f"  - {path}")
    if len(changed) > 40:
        print(f"  ... {len(changed) - 40} more")

    backend_tests, backend_why = plan_backend(changed)
    frontend_entries, frontend_why = plan_frontend(changed)

    jobs = os.environ.get("PYTEST_JOBS", "8")
    commands: list[tuple[str, list[str], Path]] = []

    if backend_tests is None:
        print(f"[verify-changed] backend: full suite ({backend_why})")
        commands.append(("backend full", ["uv", "run", "pytest", "-m", "not slow", "-n", jobs], ROOT))
    elif backend_tests:
        print(f"[verify-changed] backend: {len(backend_tests)} test file(s) ({backend_why})")
        for path in backend_tests:
            print(f"  - {path}")
        commands.append(
            ("backend targeted", ["uv", "run", "pytest", "-m", "not slow", "-n", jobs, *backend_tests], ROOT)
        )
    else:
        print(f"[verify-changed] backend: skipped ({backend_why})")

    if frontend_entries is None:
        print(f"[verify-changed] frontend: full suite ({frontend_why})")
        commands.append(("frontend full", ["pnpm", "exec", "vitest", "run"], FRONTEND))
    elif frontend_entries:
        print(f"[verify-changed] frontend: {len(frontend_entries)} entry file(s) ({frontend_why})")
        for path in frontend_entries:
            print(f"  - {path}")
        commands.append(
            ("frontend targeted", ["pnpm", "exec", "vitest", "related", "--run", *frontend_entries], FRONTEND)
        )
    else:
        print(f"[verify-changed] frontend: skipped ({frontend_why})")

    if not commands:
        print("[verify-changed] nothing to run (docs-only or non-code change; use make check-docs / check-fast).")
        return 0

    if args.dry_run:
        print("[verify-changed] --dry-run: the following commands are not executed")
        for name, cmd, cwd in commands:
            print(f"  [{name}] (cd {cwd.relative_to(ROOT).as_posix() or '.'}) {' '.join(cmd)}")
        return 0

    for name, cmd, cwd in commands:
        print(f"\n[verify-changed] >> {name}: {' '.join(cmd)}", flush=True)
        code = subprocess.call(runnable(cmd), cwd=cwd)  # nosec B603 - commands built by this script
        if code != 0:
            print(
                f"[verify-changed] FAIL {name} failed (exit={code}); fix it and re-run this command.", file=sys.stderr
            )
            return code

    print(
        "\n[verify-changed] OK targeted verification is green. Phase wrap-up still requires make flow / make check (L2)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
