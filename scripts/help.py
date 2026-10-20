"""从 Makefile 提取 ``## 说明`` 注释，生成 ``make help`` 输出.

用法::

    python scripts/help.py Makefile [其它 .mk ...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_TARGET = re.compile(r"^([a-zA-Z][\w -]*):.*?##\s*(.*)")


def collect(makefiles: list[str]) -> list[tuple[str, str]]:
    """按文件顺序收集 ``目标名: ## 说明`` 形式的条目."""
    entries: list[tuple[str, str]] = []
    for name in makefiles:
        for line in Path(name).read_text(encoding="utf-8").splitlines():
            match = _TARGET.match(line)
            if match:
                entries.append((match.group(1), match.group(2).strip()))
    return entries


def main(argv: list[str]) -> int:
    # 跟随终端编码（Windows 常见 cp936），避免按 UTF-8 输出在控制台显示乱码
    sys.stdout.reconfigure(errors="replace")
    entries = collect(argv or ["Makefile"])
    width = max((len(name) for name, _ in entries), default=0)
    for name, description in entries:
        print(f"  {name:<{width}}  {description}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
