"""校验 ADR 的落地状态、Related 链接与 CHANGELOG 关联.

用法::

    python scripts/check_adr_landing.py            # 有 error 时退出 1，warning 不阻断
    python scripts/check_adr_landing.py --strict   # warning 也视为失败

检查项：

- ``Status`` 只允许 ``Proposed`` / ``Accepted`` / ``Implemented``；``Superseded`` / ``Deprecated`` 属失效文档，应直接删除。
- ``Accepted`` / ``Implemented`` 必须有「落地状态」表。
- 标为「已落地」的期：代码落点与测试文件必须存在，提交列应为 sha。
- 全部期已落地但 ``Status`` 仍为 ``Proposed`` → 告警；CHANGELOG 未出现 ``ADR NNNN`` → 错误。
- ``Related`` 中的文件路径必须存在；``docs/adr/README.md`` 索引必须覆盖本 ADR、链接可达且 Status 与 ADR 一致。
- 「交接」节应包含当前阶段 / 下一步 / 已知坑（缺失告警）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = ROOT / "docs" / "adr"
SKIP_FILES = {"TEMPLATE.md", "README.md"}
VALID_STATUS = {"Proposed", "Accepted", "Implemented"}
REMOVED_STATUS = {"Superseded", "Deprecated"}
VALID_PHASE = {"未开始", "进行中", "已落地"}
PATH_BASES = (ROOT, ROOT / "src" / "cndb", ROOT / "frontend", ROOT / "src")
BACKTICK = re.compile(r"`([^`]+)`")


def _section(text: str, name: str) -> str | None:
    """取 ``## <name>...`` 到下一个二级标题之间的正文."""
    match = re.search(rf"^##\s*{re.escape(name)}.*$", text, re.MULTILINE)
    if match is None:
        return None
    rest = text[match.end() :]
    next_heading = re.search(r"^##\s+", rest, re.MULTILINE)
    return rest[: next_heading.start()] if next_heading else rest


def _table_rows(section: str) -> list[dict[str, str]]:
    """解析 Markdown 表格；单元格按 ``|`` 切分（本仓库 ADR 表格不含转义竖线）."""
    lines = [line.strip() for line in section.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return []
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == len(header):
            rows.append(dict(zip(header, cells, strict=True)))
    return rows


def _resolve(token: str) -> Path | None:
    """按仓库根 / src/cndb / frontend / src 依次解析路径，支持 glob."""
    token = token.strip().strip("`")
    if not token or "<" in token or ">" in token:
        return None
    if token.startswith("./"):
        token = token[2:]
    for base in PATH_BASES:
        candidate = base / token
        if candidate.exists():
            return candidate
    if any(ch in token for ch in "*?["):
        for base in PATH_BASES:
            matches = sorted(base.glob(token))
            if matches:
                return matches[0]
    return None


def _file_tokens(text: str) -> list[str]:
    return [token for token in BACKTICK.findall(text) if token.rsplit(".", 1)[-1] in {"md", "py", "ts", "tsx"}]


def _status(text: str) -> str | None:
    match = re.search(r"^Status:\s*([A-Za-z]+)", text, re.MULTILINE)
    return match.group(1) if match else None


def _adr_id(path: Path) -> str | None:
    match = re.match(r"(\d{4})", path.stem)
    return match.group(1) if match else None


def _check_file(path: Path, changelog: str) -> tuple[list[str], list[str]]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []

    status = _status(text)
    if status is None:
        errors.append("缺少 Status 行")
    elif status in REMOVED_STATUS:
        errors.append(f"Status 为 {status}：ADR 已失效，应直接删除文件与 README 索引行（git 历史可追溯），不在仓库保留")
    elif status not in VALID_STATUS:
        errors.append(f"Status 取值非法: {status}")

    related = re.search(r"^Related:\s*(.+)$", text, re.MULTILINE)
    if related is not None:
        for token in _file_tokens(related.group(1)):
            if _resolve(token) is None:
                errors.append(f"Related 路径不存在: {token}")

    landing = _section(text, "落地状态")
    rows = _table_rows(landing) if landing is not None else []
    if status in {"Accepted", "Implemented"} and landing is None:
        errors.append(f"Status 为 {status} 但缺少「落地状态」表")
    if landing is not None and not rows:
        errors.append("「落地状态」表为空或表头不是 期 / 状态 / 代码落点 / 测试 / 提交")

    for row in rows:
        phase = row.get("期", "?").strip()
        state = row.get("状态", "").strip()
        if state not in VALID_PHASE:
            errors.append(f"{phase}: 状态「{state}」不在 未开始 / 进行中 / 已落地")
            continue
        if state != "已落地":
            continue
        code_paths = BACKTICK.findall(row.get("代码落点", ""))
        test_paths = BACKTICK.findall(row.get("测试", ""))
        if not code_paths:
            errors.append(f"{phase}: 已落地但代码落点为空")
        if not test_paths:
            errors.append(f"{phase}: 已落地但测试为空")
        for token in code_paths + test_paths:
            if _resolve(token) is None:
                errors.append(f"{phase}: 路径不存在: {token}")
        commit = row.get("提交", "").strip().strip("`")
        if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
            warnings.append(f"{phase}: 已落地但提交列不是 sha: {commit or '<空>'}")

    if rows and all(row.get("状态", "").strip() == "已落地" for row in rows):
        adr_id = _adr_id(path)
        if status == "Proposed":
            warnings.append("全部阶段已落地，但 Status 仍为 Proposed（需人工评审回填）")
        if adr_id and f"ADR {adr_id}" not in changelog:
            errors.append(f"CHANGELOG 未出现 ADR {adr_id}（已落地的期需带 `(ADR {adr_id} Pn)` 条目）")

    handoff = _section(text, "交接")
    if handoff is None:
        if rows:
            warnings.append("缺少「交接」节（当前阶段 / 下一步 / 已知坑）")
    else:
        for key in ("当前阶段", "下一步", "已知坑"):
            if key not in handoff:
                warnings.append(f"「交接」缺少 {key}")

    return errors, warnings


def _check_index(adr_paths: list[Path]) -> tuple[list[str], list[str]]:
    index = ADR_DIR / "README.md"
    if not index.exists():
        return [], ["docs/adr/README.md 不存在"]
    text = index.read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []

    indexed_status: dict[str, str] = {}
    for row in _table_rows(text):
        match = re.search(r"\(([^)]+\.md)\)", row.get("编号", ""))
        if match is not None:
            indexed_status[Path(match.group(1)).name] = row.get("Status", "").strip()

    for path in adr_paths:
        if path.name not in text:
            warnings.append(f"README.md 未索引 {path.name}")
            continue
        # 索引与 ADR 本体双份记录 Status，最容易在需求变更后漂移，故强制一致
        listed = indexed_status.get(path.name)
        actual = _status(path.read_text(encoding="utf-8"))
        if listed and actual and listed != actual:
            errors.append(f"索引 Status({listed}) 与 ADR Status({actual}) 不一致: {path.name}")
    for target in re.findall(r"\]\(([^)#]+?\.md)\)", text):
        if target.startswith(("http://", "https://")):
            continue
        if not (ADR_DIR / target).exists():
            errors.append(f"README.md 链接不存在: {target}")
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 ADR 落地状态、Related 链接与 CHANGELOG 关联。")
    parser.add_argument("--strict", action="store_true", help="warning 也视为失败")
    args = parser.parse_args(argv)

    paths = sorted(path for path in ADR_DIR.glob("*.md") if path.name not in SKIP_FILES)
    if not paths:
        print("[adr-check] 未找到 ADR")
        return 0

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8") if (ROOT / "CHANGELOG.md").exists() else ""
    total_errors = 0
    total_warnings = 0
    for path in paths:
        errors, warnings = _check_file(path, changelog)
        status = _status(path.read_text(encoding="utf-8")) or "?"
        print(f"[adr-check] {path.name} (Status: {status})")
        for item in errors:
            print(f"  error: {item}")
        for item in warnings:
            print(f"  warn:  {item}")
        total_errors += len(errors)
        total_warnings += len(warnings)

    errors, warnings = _check_index(paths)
    if errors or warnings:
        print("[adr-check] docs/adr/README.md")
        for item in errors:
            print(f"  error: {item}")
        for item in warnings:
            print(f"  warn:  {item}")
        total_errors += len(errors)
        total_warnings += len(warnings)

    print(f"[adr-check] {len(paths)} 个 ADR，{total_errors} error，{total_warnings} warning")
    return 1 if total_errors or (args.strict and total_warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
