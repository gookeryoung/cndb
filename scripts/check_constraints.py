"""校验硬约束台账（docs/CONSTRAINTS.md）的格式与引用完整性.

用法::

    python scripts/check_constraints.py             # 有 error 时退出 1，warning 不阻断
    python scripts/check_constraints.py --strict    # warning 也视为失败
    python scripts/check_constraints.py --root PATH # 指定仓库根（测试用）

检查项（ADR 0119 §3）：

- 台账存在且含四列固定列头（``#`` / ``约束`` / ``校验`` / ``来源``）。
- H 编号格式合法（``H\\d+``）且全局唯一。
- ``来源`` 含 ``ADR NNNN`` 的：``docs/adr/NNNN-*.md`` 存在（防孤儿约束）。
- ``校验`` 含 ``make <t>`` 的：``<t>`` 在 Makefile 目标中存在。
- ``已删除`` 清单中的编号仍出现在正文分组表 → warning。
- 「使用方式」节缺失「开工前 / 提交前 / 冲突处理」任一关键词 → warning。
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
    """解析 Markdown 表格；单元格按 ``|`` 切分（台账不含转义竖线）."""
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
    """把正文按空行切块，返回 (块内非空行, 解析出的表格行)."""
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
    """提取 Makefile 目标名（排除变量赋值 / 模式规则的常规目标）."""
    if not makefile.exists():
        return set()
    return set(MAKEFILE_TARGET.findall(makefile.read_text(encoding="utf-8")))


def check(root: Path) -> tuple[list[str], list[str]]:
    """返回 (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    path = root / "docs" / "CONSTRAINTS.md"
    if not path.exists():
        return ["docs/CONSTRAINTS.md 不存在"], []

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
        errors.append("未找到四列约束表（列头须为 # / 约束 / 校验 / 来源）")

    targets = _makefile_targets(root / "Makefile")
    seen_ids: dict[str, int] = {}
    for row in constraint_rows:
        hid = row.get("#", "").strip()
        if not H_ID.match(hid):
            errors.append(f"编号格式非法: {hid or '<空>'}（应为 H\\d+）")
            continue
        if hid in seen_ids:
            errors.append(f"编号重复: {hid}")
        seen_ids[hid] = seen_ids.get(hid, 0) + 1

        source = row.get("来源", "")
        for adr in ADR_REF.findall(source):
            if not list((root / "docs" / "adr").glob(f"{adr}-*.md")):
                errors.append(f"{hid}: 来源 ADR {adr} 文件不存在（孤儿约束）")

        for target in MAKE_TARGET.findall(row.get("校验", "")):
            if target not in targets:
                errors.append(f"{hid}: make 目标不存在: {target}")

    body_ids = set(seen_ids)
    for row in deleted_rows:
        hid = row.get("#", "").strip()
        if H_ID.match(hid) and hid in body_ids:
            warnings.append(f"已删除清单中的编号 {hid} 仍出现在正文分组表")

    usage = re.search(r"^##\s*使用方式.*$", text, re.MULTILINE)
    if usage is None:
        warnings.append("缺少「使用方式」节")
    else:
        rest = text[usage.end() :]
        nxt = re.search(r"^##\s+", rest, re.MULTILINE)
        section = rest[: nxt.start()] if nxt else rest
        for keyword in USAGE_KEYWORDS:
            if keyword not in section:
                warnings.append(f"「使用方式」缺少关键词: {keyword}")

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验硬约束台账 docs/CONSTRAINTS.md。")
    parser.add_argument("--strict", action="store_true", help="warning 也视为失败")
    parser.add_argument("--root", type=Path, default=ROOT, help="仓库根目录（测试用）")
    args = parser.parse_args(argv)

    errors, warnings = check(args.root)
    print("[constraint-check] docs/CONSTRAINTS.md")
    for item in errors:
        print(f"  error: {item}")
    for item in warnings:
        print(f"  warn:  {item}")
    print(f"[constraint-check] {len(errors)} error，{len(warnings)} warning")
    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
