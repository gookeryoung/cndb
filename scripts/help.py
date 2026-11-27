"""Extract ``## description`` comments from the Makefile and print ``make help`` output.

Usage::

    python scripts/help.py Makefile [other .mk ...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_TARGET = re.compile(r"^([a-zA-Z][\w -]*):.*?##\s*(.*)")


def collect(makefiles: list[str]) -> list[tuple[str, str]]:
    """Collect ``target: ## description`` entries in file order."""
    entries: list[tuple[str, str]] = []
    for name in makefiles:
        for line in Path(name).read_text(encoding="utf-8").splitlines():
            match = _TARGET.match(line)
            if match:
                entries.append((match.group(1), match.group(2).strip()))
    return entries


def main(argv: list[str]) -> int:
    # Follow the terminal encoding (cp936 on Windows) so output is never mojibake
    sys.stdout.reconfigure(errors="replace")
    entries = collect(argv or ["Makefile"])
    width = max((len(name) for name, _ in entries), default=0)
    for name, description in entries:
        print(f"  {name:<{width}}  {description}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
