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

        assert any("测试为空" in item for item in errors)

    def test_landed_with_missing_code_path_is_error(self, isolated: Path) -> None:
        path = _write_adr(
            isolated,
            status="Implemented",
            rows="| P0 | 已落地 | `nope.py` | `test_x.py` | `0123456` |",
        )

        errors, _ = adr_check._check_file(path, "ADR 0007")

        assert any("路径不存在: nope.py" in item for item in errors)

    def test_invalid_phase_state_is_error(self, isolated: Path) -> None:
        path = _write_adr(
            isolated,
            status="Proposed",
            rows="| P0 | 做完了 | `code.py` | `test_x.py` | |",
        )

        errors, _ = adr_check._check_file(path, "")

        assert any("不在 未开始 / 进行中 / 已落地" in item for item in errors)

    def test_accepted_requires_landing_section(self, isolated: Path) -> None:
        path = isolated / "0007-sample.md"
        path.write_text(
            "# ADR 0007: 测试用\n\nStatus: Accepted\nDate: 2026-01-01\nRelated: `code.py`\n",
            encoding="utf-8",
        )
        (isolated / "code.py").write_text("", encoding="utf-8")

        errors, _ = adr_check._check_file(path, "")

        assert any("缺少「落地状态」表" in item for item in errors)


class TestCrossChecks:
    def test_all_landed_but_proposed_warns(self, isolated: Path) -> None:
        path = _write_adr(
            isolated,
            status="Proposed",
            rows="| P0 | 已落地 | `code.py` | `test_x.py` | `0123456` |",
        )

        errors, warnings = adr_check._check_file(path, "ADR 0007")

        assert errors == []
        assert any("Status 仍为 Proposed" in item for item in warnings)

    def test_missing_changelog_entry_is_error(self, isolated: Path) -> None:
        path = _write_adr(
            isolated,
            status="Implemented",
            rows="| P0 | 已落地 | `code.py` | `test_x.py` | `0123456` |",
        )

        errors, _ = adr_check._check_file(path, "## 未发布\n- 与 ADR 无关的条目")

        assert any("CHANGELOG 未出现 ADR 0007" in item for item in errors)

    def test_missing_related_path_is_error(self, isolated: Path) -> None:
        path = isolated / "0007-sample.md"
        path.write_text(
            "# ADR 0007: 测试用\n\nStatus: Proposed\nDate: 2026-01-01\nRelated: `gone.py`\n",
            encoding="utf-8",
        )

        errors, _ = adr_check._check_file(path, "")

        assert any("Related 路径不存在: gone.py" in item for item in errors)

    def test_handoff_missing_keys_warns(self, isolated: Path) -> None:
        path = _write_adr(
            isolated,
            status="Proposed",
            rows="| P0 | 进行中 | `code.py` | `test_x.py` | |",
            handoff=False,
        )

        errors, warnings = adr_check._check_file(path, "")

        assert errors == []
        assert any("缺少「交接」节" in item for item in warnings)


class TestLifecycle:
    @pytest.mark.parametrize("status", ["Superseded", "Deprecated"])
    def test_removed_status_must_be_deleted(self, isolated: Path, status: str) -> None:
        path = _write_adr(isolated, status=status, rows="| P0 | 已落地 | `code.py` | `test_x.py` | `0123456` |")

        errors, _ = adr_check._check_file(path, "ADR 0007")

        assert any("应直接删除" in item for item in errors)

    def _write_index(self, directory: Path, adr_name: str, status: str) -> None:
        (directory / "README.md").write_text(
            "# ADR 索引\n\n"
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

        assert any("索引 Status(Proposed) 与 ADR Status(Implemented) 不一致" in item for item in errors)

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
