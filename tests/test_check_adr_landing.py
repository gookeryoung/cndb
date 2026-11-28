"""锁定 scripts/check_adr_landing.py 的判定口径（ADR 落地门禁自身的回归）.

门禁脚本本身失效比没有门禁更危险，故用单元测试钉住五种结论：
路径缺失 / 落地表缺项 → error；全部落地但未回填评审 → warning；CHANGELOG 缺条目 → error；失效状态未删除 → error。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_adr_landing.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_adr_landing", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adr_check = _load_module()


def _write_adr(tmp_path: Path, *, status: str, rows: str, handoff: bool = True) -> Path:
    """在 tmp_path 下落一份最小 ADR + 可解析的代码 / 测试文件."""
    (tmp_path / "code.py").write_text("", encoding="utf-8")
    (tmp_path / "test_x.py").write_text("", encoding="utf-8")
    body = (
        "# ADR 0007: 测试用\n\n"
        f"Status: {status}\n"
        "Date: 2026-01-01\n"
        "Related: `code.py`\n\n"
        "## 落地状态（随实现更新）\n\n"
        "| 期 | 状态 | 代码落点 | 测试 | 提交 |\n"
        "|---|---|---|---|---|\n"
        f"{rows}\n"
    )
    if handoff:
        body += "\n## 交接（会话结束更新）\n\n- 当前阶段：P0\n- 下一步：补测试\n- 已知坑：无\n"
    path = tmp_path / "0007-sample.md"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """路径解析只在 tmp_path 内查找，避免命中真实仓库文件."""
    monkeypatch.setattr(adr_check, "PATH_BASES", (tmp_path,))
    return tmp_path


class TestLandingRows:
    def test_landed_phase_is_clean(self, isolated: Path) -> None:
        path = _write_adr(
            isolated,
            status="Implemented",
            rows="| P0 | 已落地 | `code.py` | `test_x.py` | `0123456` |",
        )

        errors, warnings = adr_check._check_file(path, "## 未发布\n- 某某 (ADR 0007 P0)")

        assert errors == []
        assert warnings == []

    def test_landed_without_tests_is_error(self, isolated: Path) -> None:
        path = _write_adr(
            isolated,
            status="Implemented",
            rows="| P0 | 已落地 | `code.py` | | `0123456` |",
        )

        errors, _ = adr_check._check_file(path, "ADR 0007")

        assert any("the tests are empty" in item for item in errors)

    def test_landed_with_missing_code_path_is_error(self, isolated: Path) -> None:
        path = _write_adr(
            isolated,
            status="Implemented",
            rows="| P0 | 已落地 | `nope.py` | `test_x.py` | `0123456` |",
        )

        errors, _ = adr_check._check_file(path, "ADR 0007")

        assert any("path does not exist: nope.py" in item for item in errors)

    def test_invalid_phase_state_is_error(self, isolated: Path) -> None:
        path = _write_adr(
            isolated,
            status="Proposed",
            rows="| P0 | 做完了 | `code.py` | `test_x.py` | |",
        )

        errors, _ = adr_check._check_file(path, "")

        assert any("is not one of 未开始 / 进行中 / 已落地" in item for item in errors)

    def test_accepted_requires_landing_section(self, isolated: Path) -> None:
        path = isolated / "0007-sample.md"
        path.write_text(
            "# ADR 0007: 测试用\n\nStatus: Accepted\nDate: 2026-01-01\nRelated: `code.py`\n",
            encoding="utf-8",
        )
        (isolated / "code.py").write_text("", encoding="utf-8")

        errors, _ = adr_check._check_file(path, "")

        assert any("'落地状态' table is missing" in item for item in errors)


class TestCrossChecks:
    def test_all_landed_but_proposed_warns(self, isolated: Path) -> None:
        path = _write_adr(
            isolated,
            status="Proposed",
            rows="| P0 | 已落地 | `code.py` | `test_x.py` | `0123456` |",
        )

        errors, warnings = adr_check._check_file(path, "ADR 0007")

        assert errors == []
        assert any("Status is still Proposed" in item for item in warnings)

    def test_all_landed_but_accepted_warns(self, isolated: Path) -> None:
        """已评审但期次后来才补齐的 ADR 会停在 Accepted，README 要求置 Implemented."""
        path = _write_adr(
            isolated,
            status="Accepted",
            rows="| P0 | 已落地 | `code.py` | `test_x.py` | `0123456` |",
        )

        errors, warnings = adr_check._check_file(path, "ADR 0007")

        assert errors == []
        assert any("Status is still Accepted" in item for item in warnings)

    def test_partially_landed_accepted_does_not_warn(self, isolated: Path) -> None:
        """还有未开始分期时 Accepted 是正确状态，不得报漂移."""
        path = _write_adr(
            isolated,
            status="Accepted",
            rows=("| P0 | 已落地 | `code.py` | `test_x.py` | `0123456` |\n| P1 | 未开始 | — | — | — |"),
        )

        errors, warnings = adr_check._check_file(path, "ADR 0007")

        assert errors == []
        assert warnings == []

    def test_missing_changelog_entry_is_error(self, isolated: Path) -> None:
        path = _write_adr(
            isolated,
            status="Implemented",
            rows="| P0 | 已落地 | `code.py` | `test_x.py` | `0123456` |",
        )

        errors, _ = adr_check._check_file(path, "## 未发布\n- 与 ADR 无关的条目")

        assert any("CHANGELOG does not mention ADR 0007" in item for item in errors)

    def test_missing_related_path_is_error(self, isolated: Path) -> None:
        path = isolated / "0007-sample.md"
        path.write_text(
            "# ADR 0007: 测试用\n\nStatus: Proposed\nDate: 2026-01-01\nRelated: `gone.py`\n",
            encoding="utf-8",
        )

        errors, _ = adr_check._check_file(path, "")

        assert any("Related path does not exist: gone.py" in item for item in errors)

    def test_handoff_missing_keys_warns(self, isolated: Path) -> None:
        path = _write_adr(
            isolated,
            status="Proposed",
            rows="| P0 | 进行中 | `code.py` | `test_x.py` | |",
            handoff=False,
        )

        errors, warnings = adr_check._check_file(path, "")

        assert errors == []
        assert any("missing the '交接' section" in item for item in warnings)


class TestLifecycle:
    @pytest.mark.parametrize("status", ["Superseded", "Deprecated"])
    def test_removed_status_must_be_deleted(self, isolated: Path, status: str) -> None:
        path = _write_adr(isolated, status=status, rows="| P0 | 已落地 | `code.py` | `test_x.py` | `0123456` |")

        errors, _ = adr_check._check_file(path, "ADR 0007")

        assert any("delete the file and its README index row directly" in item for item in errors)

    def _write_index(self, directory: Path, adr_name: str, status: str) -> None:
        # 编号台账行是必需的：编号不复用（H8），缺失编号必须有交代
        (directory / "README.md").write_text(
            "# ADR 索引\n\n"
            "- 编号缺口是已删除或只留需求卡片的编号，**不要复用**。\n"
            "  - **已删除且无卡片**：0001–0006\n"
            "- **已并入的编号**：0015→0012。\n\n"
            "| 编号 | 标题 | Status | 落地阶段 | 代码 | 测试 | CHANGELOG |\n"
            "|---|---|---|---|---|---|---|\n"
            f"| [0007]({adr_name}) | 测试用 | {status} | P0 已落地 | `code.py` | `test_x.py` | - |\n",
            encoding="utf-8",
        )

    def test_index_status_drift_is_error(self, isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = _write_adr(
            isolated,
            status="Implemented",
            rows="| P0 | 已落地 | `code.py` | `test_x.py` | `0123456` |",
        )
        self._write_index(isolated, path.name, "Proposed")
        monkeypatch.setattr(adr_check, "ADR_DIR", isolated)

        errors, _ = adr_check._check_index([path])

        assert any("index Status(Proposed) does not match ADR Status(Implemented)" in item for item in errors)

    def test_index_status_consistent_passes(self, isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = _write_adr(
            isolated,
            status="Implemented",
            rows="| P0 | 已落地 | `code.py` | `test_x.py` | `0123456` |",
        )
        self._write_index(isolated, path.name, "Implemented")
        monkeypatch.setattr(adr_check, "ADR_DIR", isolated)

        errors, _ = adr_check._check_index([path])

        assert errors == []


class TestStaleHandoffNote:
    """Status 已落定，交接仍写「待人工评审回填 Implemented」= 历史残留，必须告警."""

    def test_implemented_with_stale_review_note_warns(self, isolated: Path) -> None:
        path = _write_adr(
            isolated,
            status="Implemented",
            rows="| P0 | 已落地 | `code.py` | `test_x.py` | `0123456` |",
        )
        text = path.read_text(encoding="utf-8")
        assert "- 下一步：补测试" in text
        path.write_text(
            text.replace(
                "- 当前阶段：P0",
                "- 当前阶段：P0-P2 已落地（待人工评审回填 Implemented）",
            ),
            encoding="utf-8",
        )

        errors, warnings = adr_check._check_file(path, "ADR 0007")

        assert errors == []
        assert any("stale review note" in item for item in warnings)

    def test_accepted_with_review_note_is_fine(self, isolated: Path) -> None:
        """Status 还是 Accepted 时，交接写「待评审」是正确状态，不得误报."""
        path = _write_adr(
            isolated,
            status="Accepted",
            rows="| P0 | 已落地 | `code.py` | `test_x.py` | `0123456` |\n| P1 | 未开始 | — | — | — |",
        )
        text = path.read_text(encoding="utf-8").replace(
            "- 下一步：补测试",
            "- 下一步：人工评审后 Status 转 `Implemented`",
        )
        path.write_text(text, encoding="utf-8")

        errors, warnings = adr_check._check_file(path, "ADR 0007")

        assert errors == []
        assert warnings == []


class TestNumberRegistry:
    """ADR 编号不复用（H8）：缺失编号必须在 README 台账里有交代，否则会被当成空号复用."""

    def _index(self, directory: Path, deleted: str) -> None:
        (directory / "README.md").write_text(
            "# ADR 索引\n\n"
            "- 编号缺口是已删除或只留需求卡片的编号，**不要复用**。\n"
            f"  - **已删除且无卡片**：{deleted}\n"
            "- **已并入的编号**：0015→0012。\n",
            encoding="utf-8",
        )

    def _adrs(self, directory: Path, numbers: list[int]) -> list[Path]:
        out = []
        for n in numbers:
            p = directory / f"{n:04d}-sample.md"
            p.write_text(f"# ADR {n:04d}\n\nStatus: Implemented\n", encoding="utf-8")
            out.append(p)
        return out

    def test_registered_gap_passes(self, isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        paths = self._adrs(isolated, [2, 4])
        self._index(isolated, "0001 / 0003")
        monkeypatch.setattr(adr_check, "ROOT", isolated)

        problems = adr_check._check_number_registry((isolated / "README.md").read_text(encoding="utf-8"), paths)

        assert problems == []

    def test_unregistered_gap_is_error(self, isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """0003 既无 ADR、也无卡片、也没登记 —— 必须报错，否则会被当成空号复用."""
        paths = self._adrs(isolated, [2, 4])
        self._index(isolated, "0001")
        monkeypatch.setattr(adr_check, "ROOT", isolated)

        problems = adr_check._check_number_registry((isolated / "README.md").read_text(encoding="utf-8"), paths)

        assert any("0003" in p and "no registry entry" in p for p in problems)

    def test_requirement_card_only_gap_passes(self, isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """S1 项有需求卡片、无 ADR，属正常机制，不应报错."""
        paths = self._adrs(isolated, [2, 4])
        self._index(isolated, "0001")
        cards = isolated / "docs" / "requirements"
        cards.mkdir(parents=True)
        (cards / "0003-s1-item.md").write_text("# 0003\n", encoding="utf-8")
        monkeypatch.setattr(adr_check, "ROOT", isolated)

        problems = adr_check._check_number_registry((isolated / "README.md").read_text(encoding="utf-8"), paths)

        assert problems == []

    def test_range_spec_is_expanded(self) -> None:
        assert adr_check._parse_number_spec("0061–0073") == set(range(61, 74))
        assert adr_check._parse_number_spec("0032 / 0033") == {32, 33}
