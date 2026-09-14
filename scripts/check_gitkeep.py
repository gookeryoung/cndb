"""校验仓库内关键 .gitkeep 文件是否存在.

这些空占位文件一旦被删除，对应的空目录在 git clone / CI checkout 后就会消失，
导致 hatchling force-include / Sphinx html_static_path 等依赖实际目录路径的步骤
直接报错。本脚本在 pre-commit 阶段和 ``make check`` 流程中被调用，提前阻断。

用法::

    python scripts/check_gitkeep.py              # 检查默认清单
    python scripts/check_gitkeep.py --fix        # 缺失时自动补回
    python scripts/check_gitkeep.py path1 path2   # 检查指定路径（相对仓库根）

退出码 0 表示全部存在，1 表示有缺失。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ── 默认清单：删掉会导致 CI/CD 或打包失败的 .gitkeep ──────────────
# 路径相对仓库根（本文件位于 scripts/，需回退一层）
_DEFAULT_KEEPS: tuple[str, ...] = (
    # hatchling force-include 依赖 src/cndb/static/ 真实存在
    "src/cndb/static/.gitkeep",
    # Sphinx html_static_path = ["_static"] 要求目录存在
    "docs/_static/.gitkeep",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def check(paths: list[str], *, fix: bool = False) -> int:
    """检查给定的 .gitkeep 路径是否存在.

    Args:
        paths: 相对仓库根的 .gitkeep 路径列表.
        fix: 缺失时是否自动创建空文件及其父目录.

    Returns:
        缺失数量（0 表示全部存在）.
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
            print(f"[gitkeep] 已补回 {rel}")
        else:
            missing.append(fp)
            print(f"[gitkeep] 缺失: {rel}  (目录 {fp.parent})")

    if missing:
        print()
        print(f"共 {len(missing)} 个 .gitkeep 缺失。")
        print("这些文件一旦从工作树消失，对应的空目录在 git checkout 后也不复存在，")
        print("会导致 hatchling force-include / Sphinx html_static_path 等步骤报错。")
        print("请执行 `python scripts/check_gitkeep.py --fix` 补回，或手动 `touch` 对应文件。")
        return 1

    print(f"[gitkeep] 全部就绪（检查了 {len(paths)} 个）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="校验关键 .gitkeep 文件是否存在，缺失时可选自动补回。",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="缺失时自动创建空 .gitkeep 及其父目录。",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="要检查的 .gitkeep 相对路径；不传则使用项目默认清单。",
    )
    args = parser.parse_args(argv)

    targets = args.paths if args.paths else list(_DEFAULT_KEEPS)
    return check(targets, fix=args.fix)


if __name__ == "__main__":
    sys.exit(main())
