"""scripts/verify_changed.py 与 scripts/retest.py 的判定层单测（需求 0181 C2 / C4）.

两个脚本是 AI 内环的加速件，**漏跑**的代价远高于多跑，所以这里钉住三件不变量：
  · 命中共享基础设施 / 危险路径时必须回退全量（fail-safe）；
  · 定向命中面过宽或零命中时同样回退全量，不凭静态分析判定「无需验证」；
  · ``retest`` 在 lastfailed 为空时不得静默跑全量，必须显式说明并显式给命令。

脚本无覆盖率口径（``make cov`` 只统计 cndb 包），故用纯函数 + 桩隔离真实仓库规模。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import retest  # noqa: E402
import verify_changed  # noqa: E402

# ── impact_key / module_of：变更路径 → 测试 import 前缀 ─────────────────


def test_module_of_only_maps_src_python() -> None:
    assert verify_changed.module_of("src/cndb/core/config.py") == "cndb.core.config"
    assert verify_changed.module_of("src/cndb/plugins/documents/__init__.py") == "cndb.plugins.documents"
    # 非 src 下、非 python 一律 None（不参与后端定向）
    assert verify_changed.module_of("tests/test_x.py") is None
    assert verify_changed.module_of("src/cndb/core/config.ts") is None


def test_impact_key_collapses_plugin_to_package() -> None:
    # 插件内部模块互相引用很密，按插件包收比按模块收更安全
    assert verify_changed.impact_key("src/cndb/plugins/documents/services/content.py") == "cndb.plugins.documents"
    # 非插件取父包：cndb.core.config → cndb.core
    assert verify_changed.impact_key("src/cndb/core/config.py") == "cndb.core"


# ── plan_backend：fail-safe 回退 ─────────────────────────────────────────


@pytest.fixture
def fake_tests_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """用 10 个空测试文件冒充真实 346 个，隔离 60% 阈值判定."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for i in range(10):
        (tests_dir / f"test_{i}.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(verify_changed, "TESTS", tests_dir)
    return tests_dir


@pytest.fixture
def fake_index(monkeypatch: pytest.MonkeyPatch, fake_tests_dir: Path) -> dict[str, set[str]]:
    """把反向索引换成桩，避免扫真实 346 个测试文件."""
    index = {
        "cndb.plugins.documents": {"tests/test_documents_api.py"},
        "cndb.cli.seed": {"tests/test_cli.py"},
    }
    monkeypatch.setattr(verify_changed, "build_reverse_index", lambda: index)
    return index


def test_plan_backend_skips_without_python_change() -> None:
    tests, why = verify_changed.plan_backend(["docs/README.md", "Makefile"])
    assert tests == []
    assert "no backend Python change" in why


@pytest.mark.parametrize(
    "path",
    [
        "src/cndb/core/config.py",
        "src/cndb/models/base.py",
        "src/cndb/app.py",
        "src/cndb/alembic/versions/abc.py",
        "tests/conftest.py",
        "pyproject.toml",
        "pytest.ini",
    ],
)
def test_plan_backend_danger_paths_fall_back_to_full(path: str) -> None:
    tests, why = verify_changed.plan_backend([path])
    assert tests is None, "危险路径必须回退全量"
    assert "shared infrastructure hit" in why


def test_plan_backend_selects_by_import_prefix(fake_index: dict[str, set[str]]) -> None:
    tests, _ = verify_changed.plan_backend(["src/cndb/plugins/documents/routers/documents.py"])
    assert tests == ["tests/test_documents_api.py"]


def test_plan_backend_includes_changed_test_files(fake_index: dict[str, set[str]]) -> None:
    # 改测试文件本身也要跑它（是变更，不是入口）
    tests, _ = verify_changed.plan_backend(["tests/test_documents_api.py"])
    assert tests is not None and "tests/test_documents_api.py" in tests


def test_plan_backend_zero_hit_falls_back_to_full(fake_index: dict[str, set[str]]) -> None:
    # 模块没有任何测试 import 它 → 不能判定「无需验证」
    tests, why = verify_changed.plan_backend(["src/cndb/plugins/unknown/thing.py"])
    assert tests is None
    assert "no test references the changed module" in why


def test_plan_backend_too_wide_falls_back_to_full(monkeypatch: pytest.MonkeyPatch, fake_tests_dir: Path) -> None:
    # 9/10 = 90% > MAX_SELECT_RATIO(0.6)，跑定向已无收益
    monkeypatch.setattr(
        verify_changed,
        "build_reverse_index",
        lambda: {"cndb.x": {f"tests/test_{i}.py" for i in range(9)}},
    )
    tests, why = verify_changed.plan_backend(["src/cndb/x/y.py"])
    assert tests is None
    assert "no speed benefit left" in why


# ── plan_frontend：共享设施 / 面过宽 / 零改动 ────────────────────────────


def test_plan_frontend_skips_without_frontend_change() -> None:
    tests, why = verify_changed.plan_frontend(["src/cndb/core/config.py"])
    assert tests == []
    assert "no frontend change" in why


@pytest.mark.parametrize("path", ["frontend/vite.config.ts", "frontend/src/test/setup.ts", "frontend/package.json"])
def test_plan_frontend_shared_files_fall_back_to_full(path: str) -> None:
    tests, why = verify_changed.plan_frontend([path])
    assert tests is None
    assert "shared infrastructure hit" in why


def test_plan_frontend_returns_entries_relative_to_frontend() -> None:
    tests, _ = verify_changed.plan_frontend(["frontend/src/pages/documents/DocumentsPage.tsx"])
    assert tests == ["src/pages/documents/DocumentsPage.tsx"]


def test_plan_frontend_config_only_change_is_skip() -> None:
    # 只改 frontend/ 根下的配置文件 / 脚本时没有 src 入口可反查，跳过而不是跑全量
    tests, why = verify_changed.plan_frontend(["frontend/playwright.config.ts"])
    assert tests == []
    assert "no TS change" in why

    tests, why = verify_changed.plan_frontend(["frontend/scripts/e2e-affected.mjs"])
    assert tests == []
    assert "no TS change" in why


def test_plan_frontend_too_many_entries_falls_back_to_full() -> None:
    changed = [f"frontend/src/pages/p{i}/X{i}.tsx" for i in range(verify_changed.MAX_FRONTEND_ENTRIES + 1)]
    tests, why = verify_changed.plan_frontend(changed)
    assert tests is None
    assert "above the related entry cap" in why


# ── retest：lastfailed 判空 ─────────────────────────────────────────────


def test_retest_empty_lastfailed_runs_full_suite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "lastfailed"
    monkeypatch.setattr(retest, "LASTFAILED", missing)
    seen: list[list[str]] = []
    monkeypatch.setattr(retest.subprocess, "call", lambda cmd, cwd=None: seen.append(cmd) or 0)  # type: ignore[func-returns-value]

    assert retest.main([]) == 0
    assert len(seen) == 1
    assert "--lf" not in seen[0], (
        "pytest --lf silently runs the full suite on an empty cache; the full command must be explicit"
    )
    assert "-m" in seen[0] and "not slow" in seen[0]
    assert "silently run the full suite" in capsys.readouterr().out


def test_retest_reuses_lastfailed_when_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache = tmp_path / "lastfailed"
    cache.write_text(json.dumps({"tests/test_a.py::test_x": True, "tests/test_b.py::test_y": True}), encoding="utf-8")
    monkeypatch.setattr(retest, "LASTFAILED", cache)
    seen: list[list[str]] = []
    monkeypatch.setattr(retest.subprocess, "call", lambda cmd, cwd=None: seen.append(cmd) or 0)  # type: ignore[func-returns-value]

    assert retest.main(["--tb=long"]) == 0
    assert "--lf" in seen[0]
    assert "--tb=long" in seen[0], "extra arguments must be passed through"


def test_retest_corrupt_cache_is_treated_as_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache = tmp_path / "lastfailed"
    cache.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(retest, "LASTFAILED", cache)
    seen: list[list[str]] = []
    monkeypatch.setattr(retest.subprocess, "call", lambda cmd, cwd=None: seen.append(cmd) or 0)  # type: ignore[func-returns-value]

    assert retest.main([]) == 0
    assert "--lf" not in seen[0]
