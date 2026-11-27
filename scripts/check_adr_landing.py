"""Verify ADR landing status, Related links and CHANGELOG references.

Usage::

    python scripts/check_adr_landing.py            # exit 1 on errors, warnings do not block
    python scripts/check_adr_landing.py --strict   # warnings count as failures too

Checks:

- ``Status`` may only be ``Proposed`` / ``Accepted`` / ``Implemented``; ``Superseded`` /
  ``Deprecated`` are retired documents and should be deleted outright.
- ``Accepted`` / ``Implemented`` must carry a landing-status table (``落地状态``).
- A phase marked as landed (``已落地``) must have existing code and test paths, and a sha in the
  commit column.
- All phases landed while ``Status`` is still ``Proposed`` -> warning; a CHANGELOG without
  ``ADR NNNN`` -> error.
- ``Related`` file paths must exist; ``docs/adr/README.md`` must index this ADR, its links must
  resolve and its Status must match the ADR.
- The handoff section (``交接``) should list current phase / next step / known pitfalls
  (missing -> warning).

Note: the section names and column headers below are Chinese because they are the data
contract of ``docs/adr/*.md``; only the console output is English.
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
VALID_PHASE = ("未开始", "进行中", "已落地")
PATH_BASES = (ROOT, ROOT / "src" / "cndb", ROOT / "frontend", ROOT / "src")
BACKTICK = re.compile(r"`([^`]+)`")

LANDING_HEADING = "落地状态"
HANDOFF_HEADING = "交接"
COL_PHASE = "期"
COL_STATE = "状态"
COL_CODE = "代码落点"
COL_TESTS = "测试"
COL_COMMIT = "提交"


def _section(text: str, name: str) -> str | None:
    """Return the body between ``## <name>...`` and the next level-2 heading."""
    match = re.search(rf"^##\s*{re.escape(name)}.*$", text, re.MULTILINE)
    if match is None:
        return None
    rest = text[match.end() :]
    next_heading = re.search(r"^##\s+", rest, re.MULTILINE)
    return rest[: next_heading.start()] if next_heading else rest


def _table_rows(section: str) -> list[dict[str, str]]:
    """Parse a Markdown table; cells are split on ``|`` (ADR tables have no escaped pipes)."""
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
    """Resolve a path against repo root / src/cndb / frontend / src in order, glob supported."""
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
        errors.append("missing Status line")
    elif status in REMOVED_STATUS:
        errors.append(
            f"Status is {status}: the ADR is retired — delete the file and its README index row directly "
            "(git history keeps it), do not keep it in the repository"
        )
    elif status not in VALID_STATUS:
        errors.append(f"invalid Status value: {status}")

    related = re.search(r"^Related:\s*(.+)$", text, re.MULTILINE)
    if related is not None:
        for token in _file_tokens(related.group(1)):
            if _resolve(token) is None:
                errors.append(f"Related path does not exist: {token}")

    landing = _section(text, LANDING_HEADING)
    rows = _table_rows(landing) if landing is not None else []
    if status in {"Accepted", "Implemented"} and landing is None:
        errors.append(f"Status is {status} but the '{LANDING_HEADING}' table is missing")
    if landing is not None and not rows:
        errors.append(
            f"the '{LANDING_HEADING}' table is empty or its header is not "
            f"{COL_PHASE} / {COL_STATE} / {COL_CODE} / {COL_TESTS} / {COL_COMMIT}"
        )

    for row in rows:
        phase = row.get(COL_PHASE, "?").strip()
        state = row.get(COL_STATE, "").strip()
        if state not in VALID_PHASE:
            errors.append(f"{phase}: state '{state}' is not one of {' / '.join(VALID_PHASE)}")
            continue
        if state != "已落地":
            continue
        code_paths = BACKTICK.findall(row.get(COL_CODE, ""))
        test_paths = BACKTICK.findall(row.get(COL_TESTS, ""))
        if not code_paths:
            errors.append(f"{phase}: landed but the code locations are empty")
        if not test_paths:
            errors.append(f"{phase}: landed but the tests are empty")
        for token in code_paths + test_paths:
            if _resolve(token) is None:
                errors.append(f"{phase}: path does not exist: {token}")
        commit = row.get(COL_COMMIT, "").strip().strip("`")
        if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
            warnings.append(f"{phase}: landed but the commit column is not a sha: {commit or '<empty>'}")

    if rows and all(row.get(COL_STATE, "").strip() == "已落地" for row in rows):
        adr_id = _adr_id(path)
        if status == "Proposed":
            warnings.append("all phases landed but Status is still Proposed (needs a human review update)")
        if adr_id and f"ADR {adr_id}" not in changelog:
            errors.append(f"CHANGELOG does not mention ADR {adr_id} (landed phases need an `(ADR {adr_id} Pn)` entry)")

    handoff = _section(text, HANDOFF_HEADING)
    if handoff is None:
        if rows:
            warnings.append(f"missing the '{HANDOFF_HEADING}' section (current phase / next step / known pitfalls)")
    else:
        for key in ("当前阶段", "下一步", "已知坑"):
            if key not in handoff:
                warnings.append(f"the '{HANDOFF_HEADING}' section is missing {key}")

    return errors, warnings


def _check_index(adr_paths: list[Path]) -> tuple[list[str], list[str]]:
    index = ADR_DIR / "README.md"
    if not index.exists():
        return [], ["docs/adr/README.md does not exist"]
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
            warnings.append(f"README.md does not index {path.name}")
            continue
        # Status is recorded twice (index and ADR) and drifts most easily after requirement
        # changes, so the two are forced to agree.
        listed = indexed_status.get(path.name)
        actual = _status(path.read_text(encoding="utf-8"))
        if listed and actual and listed != actual:
            errors.append(f"index Status({listed}) does not match ADR Status({actual}): {path.name}")
    for target in re.findall(r"\]\(([^)#]+?\.md)\)", text):
        if target.startswith(("http://", "https://")):
            continue
        if not (ADR_DIR / target).exists():
            errors.append(f"README.md link target does not exist: {target}")
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify ADR landing status, Related links and CHANGELOG references.")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = parser.parse_args(argv)

    paths = sorted(path for path in ADR_DIR.glob("*.md") if path.name not in SKIP_FILES)
    if not paths:
        print("[adr-check] no ADR found")
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

    print(f"[adr-check] {len(paths)} ADR(s), {total_errors} error, {total_warnings} warning")
    return 1 if total_errors or (args.strict and total_warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
