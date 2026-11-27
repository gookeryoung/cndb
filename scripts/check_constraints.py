"""Verify the format and reference integrity of the hard-constraint ledger (docs/CONSTRAINTS.md).

Usage::

    python scripts/check_constraints.py             # exit 1 on errors, warnings do not block
    python scripts/check_constraints.py --strict    # warnings count as failures too
    python scripts/check_constraints.py --root PATH # specify the repository root (for tests)

Checks (ADR 0119 §3):

- The ledger exists and has the four fixed column headers (``#`` / ``约束`` / ``校验`` / ``来源``).
- H ids are well formed (``H\\d+``) and globally unique.
- Rows whose source mentions ``ADR NNNN``: ``docs/adr/NNNN-*.md`` exists (no orphan constraints).
- Rows whose check column mentions ``make <t>``: ``<t>`` is a Makefile target.
- An id in the deleted list that still appears in a body table -> warning.
- The usage section is missing any of "开工前 / 提交前 / 冲突处理" -> warning.

Note: the ledger headings and column headers below are Chinese because they are the data
contract of ``docs/CONSTRAINTS.md``; only the console output is English.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONSTRAINT_HEADER = ["#", "约束", "校验", "来源"]
DELETED_HEADER = ["#", "原因", "日期"]
USAGE_KEYWORDS = ("开工前", "提交前", "冲突处理")
H_ID = re.compile(r"^H(\d+)$")
MAKE_TARGET = re.compile(r"\bmake\s+([A-Za-z0-9_.\-]+)")
ADR_REF = re.compile(r"ADR\s+(\d{4})")
MAKEFILE_TARGET = re.compile(r"^([A-Za-z0-9_.\-/]+)\s*:", re.MULTILINE)


def _table_rows(lines: list[str]) -> list[dict[str, str]]:
    """Parse a Markdown table; cells are split on ``|`` (the ledger has no escaped pipes)."""
    rows = [line.strip() for line in lines if line.strip().startswith("|")]
    if len(rows) < 3:
        return []
    header = [cell.strip() for cell in rows[0].strip("|").split("|")]
    parsed: list[dict[str, str]] = []
    for line in rows[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == len(header):
            parsed.append(dict(zip(header, cells, strict=True)))
    return parsed


def _split_tables(text: str) -> list[tuple[list[str], list[dict[str, str]]]]:
    """Split the body on blank lines, returning (non-empty lines in the block, parsed rows)."""
    blocks: list[tuple[list[str], list[dict[str, str]]]] = []
    block: list[str] = []
    for line in text.splitlines():
        if line.strip():
            block.append(line)
        elif block:
            blocks.append((block, _table_rows(block)))
            block = []
    if block:
        blocks.append((block, _table_rows(block)))
    return blocks


def _makefile_targets(makefile: Path) -> set[str]:
    """Extract Makefile target names (skipping variable assignments / pattern-rule noise)."""
    if not makefile.exists():
        return set()
    return set(MAKEFILE_TARGET.findall(makefile.read_text(encoding="utf-8")))


def check(root: Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    path = root / "docs" / "CONSTRAINTS.md"
    if not path.exists():
        return ["docs/CONSTRAINTS.md does not exist"], []

    text = path.read_text(encoding="utf-8")
    blocks = _split_tables(text)

    constraint_rows: list[dict[str, str]] = []
    deleted_rows: list[dict[str, str]] = []
    for _, rows in blocks:
        if not rows:
            continue
        keys = set(rows[0])
        if keys == set(CONSTRAINT_HEADER):
            constraint_rows.extend(rows)
        elif keys == set(DELETED_HEADER):
            deleted_rows.extend(rows)

    if not constraint_rows:
        errors.append("no four-column constraint table found (headers must be # / 约束 / 校验 / 来源)")

    targets = _makefile_targets(root / "Makefile")
    seen_ids: dict[str, int] = {}
    for row in constraint_rows:
        hid = row.get("#", "").strip()
        if not H_ID.match(hid):
            errors.append(f"invalid id: {hid or '<empty>'} (expected H\\d+)")
            continue
        if hid in seen_ids:
            errors.append(f"duplicate id: {hid}")
        seen_ids[hid] = seen_ids.get(hid, 0) + 1

        source = row.get("来源", "")
        for adr in ADR_REF.findall(source):
            if not list((root / "docs" / "adr").glob(f"{adr}-*.md")):
                errors.append(f"{hid}: source ADR {adr} does not exist (orphan constraint)")

        for target in MAKE_TARGET.findall(row.get("校验", "")):
            if target not in targets:
                errors.append(f"{hid}: make target does not exist: {target}")

    body_ids = set(seen_ids)
    for row in deleted_rows:
        hid = row.get("#", "").strip()
        if H_ID.match(hid) and hid in body_ids:
            warnings.append(f"deleted id {hid} still appears in a body table")

    usage = re.search(r"^##\s*使用方式.*$", text, re.MULTILINE)
    if usage is None:
        warnings.append("missing the usage section")
    else:
        rest = text[usage.end() :]
        nxt = re.search(r"^##\s+", rest, re.MULTILINE)
        section = rest[: nxt.start()] if nxt else rest
        for keyword in USAGE_KEYWORDS:
            if keyword not in section:
                warnings.append(f"usage section is missing the keyword: {keyword}")

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the hard-constraint ledger docs/CONSTRAINTS.md.")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (for tests)")
    args = parser.parse_args(argv)

    errors, warnings = check(args.root)
    print("[constraint-check] docs/CONSTRAINTS.md")
    for item in errors:
        print(f"  error: {item}")
    for item in warnings:
        print(f"  warn:  {item}")
    print(f"[constraint-check] {len(errors)} error, {len(warnings)} warning")
    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
