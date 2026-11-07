"""check_constraints.py 的判定层单测（ADR 0119 P1）.

用 tmp_path 构造微型仓库（CONSTRAINTS.md + docs/adr/ + Makefile），
不依赖真实仓库文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_constraints import check, main

VALID_LEDGER = """# 硬约束台账

> 唯一编号源。

## 使用方式（LLM 必读）

- **开工前对表**：触碰任一 H# 先核对口径。
- **提交前自查**：机器条目跑命令。
- **冲突处理**：从严执行。

## 流程与门禁

| # | 约束 | 校验 | 来源 |
|---|---|---|---|
| H1 | 禁止跳过提交钩子 | `make test` | 全局 |
| H2 | 权限天花板 | `make cov` | ADR 0004 I1 |

## 已删除

| # | 原因 | 日期 |
|---|---|---|
"""

MAKEFILE = "test:\n\techo ok\n\ncov:\n\techo ok\n"


def _make_root(tmp_path: Path, ledger: str | None = VALID_LEDGER, adr_files: list[str] | None = None) -> Path:
    """构造微型仓库根：docs/CONSTRAINTS.md + docs/adr/* + Makefile."""
    if ledger is not None:
        (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "CONSTRAINTS.md").write_text(ledger, encoding="utf-8")
    for name in adr_files or ["0004-row-level-permission-rules.md"]:
        (tmp_path / "docs" / "adr").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "adr" / name).write_text("# ADR\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text(MAKEFILE, encoding="utf-8")
    return tmp_path


def test_valid_ledger_passes(tmp_path: Path) -> None:
    errors, warnings = check(_make_root(tmp_path))
    assert errors == []
    assert warnings == []
    assert main(["--root", str(tmp_path)]) == 0


def test_missing_ledger_is_error(tmp_path: Path) -> None:
    errors, _ = check(_make_root(tmp_path, ledger=None))
    assert any("不存在" in e for e in errors)


def test_bad_header_is_error(tmp_path: Path) -> None:
    bad = VALID_LEDGER.replace("| # | 约束 | 校验 | 来源 |", "| # | 内容 | 校验 | 来源 |")
    errors, _ = check(_make_root(tmp_path, ledger=bad))
    assert any("四列约束表" in e for e in errors)


def test_duplicate_id_is_error(tmp_path: Path) -> None:
    bad = VALID_LEDGER.replace(
        "| H2 | 权限天花板 | `make cov` | ADR 0004 I1 |", "| H1 | 权限天花板 | `make cov` | ADR 0004 I1 |"
    )
    errors, _ = check(_make_root(tmp_path, ledger=bad))
    assert any("编号重复" in e for e in errors)


def test_invalid_id_format_is_error(tmp_path: Path) -> None:
    bad = VALID_LEDGER.replace("| H2 |", "| X2 |")
    errors, _ = check(_make_root(tmp_path, ledger=bad))
    assert any("编号格式非法" in e for e in errors)


def test_orphan_adr_source_is_error(tmp_path: Path) -> None:
    errors, _ = check(_make_root(tmp_path, adr_files=["0099-some-other.md"]))
    assert any("孤儿约束" in e for e in errors)


def test_missing_make_target_is_error(tmp_path: Path) -> None:
    bad = VALID_LEDGER.replace("`make cov`", "`make no-such-target`")
    errors, _ = check(_make_root(tmp_path, ledger=bad))
    assert any("make 目标不存在" in e for e in errors)


def test_deleted_id_still_in_body_warns(tmp_path: Path) -> None:
    bad = VALID_LEDGER.replace(
        "| # | 原因 | 日期 |\n|---|---|---|",
        "| # | 原因 | 日期 |\n|---|---|---|\n| H1 | 收编调整 | 2026-11-07 |",
    )
    errors, warnings = check(_make_root(tmp_path, ledger=bad))
    assert errors == []
    assert any("仍出现在正文分组表" in w for w in warnings)
    assert main(["--root", str(tmp_path), "--strict"]) == 1
    assert main(["--root", str(tmp_path)]) == 0


def test_missing_usage_keyword_warns(tmp_path: Path) -> None:
    bad = VALID_LEDGER.replace("- **冲突处理**：从严执行。", "- **其他**：无。")
    _, warnings = check(_make_root(tmp_path, ledger=bad))
    assert any("冲突处理" in w for w in warnings)
