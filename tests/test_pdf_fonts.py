"""PDF 中文字体发现 / 注册的单元测试.

通过 mock 外部命令隔离系统字体环境，覆盖 fc-match / fc-list / 目录扫描 /
Windows 路径 / 注册失败跳过 / 三态缓存等分支，保证 CI 与本地口径一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cndb.plugins.documents.services.export import pdf_fonts


def test_run_command_reports_missing_binary() -> None:
    assert pdf_fonts._run_command(["definitely-not-a-real-command-xyz"]) == (-1, "")


def test_run_command_returns_stdout() -> None:
    code, out = pdf_fonts._run_command([sys.executable, "-c", "print('ok')"])
    assert code == 0
    assert out.strip() == "ok"


def test_run_command_handles_timeout() -> None:
    result = pdf_fonts._run_command([sys.executable, "-c", "import time; time.sleep(1)"], timeout=0.01)
    assert result == (-1, "")


def test_cjk_font_candidates_parse_fc_match_and_fc_list(tmp_path, monkeypatch) -> None:
    font = tmp_path / "cjk.ttf"
    font.write_bytes(b"fake")
    other = tmp_path / "other.ttf"
    other.write_bytes(b"x")

    linux_dir = tmp_path / "fonts"
    linux_dir.mkdir()
    scanned = linux_dir / "NotoSansCJK-Regular.ttc"
    scanned.write_bytes(b"x")

    def fake_run(cmd: list[str], timeout: float = 3.0) -> tuple[int, str]:
        assert timeout > 0
        if cmd[0] == "fc-match":
            if "WenQuanYi Micro Hei" in cmd[1]:
                return 0, f"{font}|WenQuanYi Micro Hei|1"
            return 0, f"{other}|DejaVu Sans|0"
        # 用相对路径模拟 fc-list（Windows 盘符冒号会被当成分隔符）
        return 0, "cjk.ttf:WenQuanYi Micro Hei:index=2\nplain.ttf:SimSun:index=abc\nplain.ttf:SimSun\nnonsense\n"

    original_is_file = Path.is_file

    def fake_is_file(self: Path) -> bool:
        return str(self) in {"cjk.ttf", "plain.ttf"} or original_is_file(self)

    monkeypatch.setattr(pdf_fonts, "_run_command", fake_run)
    monkeypatch.setattr(pdf_fonts, "_LINUX_FONT_DIRS", [str(linux_dir)])
    monkeypatch.setattr(Path, "is_file", fake_is_file)
    candidates = pdf_fonts._cjk_font_candidates()

    # fc-match：CJK family 命中；fontconfig 回退到西文字体时不收录
    assert ("WQY-MicroHei", str(font), 1) in candidates
    assert ("WQY-MicroHei", str(other), 0) not in candidates
    # fc-list：family 名作注册名，:index= 解析为 subfontIndex；非法 index 降级为 None
    assert ("WenQuanYi Micro Hei", "cjk.ttf", 2) in candidates
    assert ("SimSun", "plain.ttf", None) in candidates
    # 目录扫描：文件名含 CJK 关键词
    assert ("NotoSansCJK-Regular", str(scanned), None) in candidates


def test_cjk_font_candidates_report_empty_output(tmp_path, monkeypatch) -> None:
    def fake_run(cmd: list[str], timeout: float = 3.0) -> tuple[int, str]:
        if cmd[0] == "fc-match":
            return 1, ""
        return 0, ""

    monkeypatch.setattr(pdf_fonts, "_run_command", fake_run)
    monkeypatch.setattr(pdf_fonts, "_LINUX_FONT_DIRS", [str(tmp_path / "missing")])
    assert pdf_fonts._cjk_font_candidates() == [
        ("SimHei", "C:/Windows/Fonts/simhei.ttf", None),
        ("MicrosoftYaHei", "C:/Windows/Fonts/msyh.ttc", 0),
        ("MicrosoftJhengHei", "C:/Windows/Fonts/msjh.ttc", 0),
        ("SimSun", "C:/Windows/Fonts/simsun.ttc", 0),
    ]


def test_ensure_pdf_font_registers_first_usable_font(tmp_path, monkeypatch) -> None:
    reportlab = pytest.importorskip("reportlab")
    from reportlab.pdfbase import pdfmetrics

    vera = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
    assert vera.is_file()

    bad_ttf = tmp_path / "bad.ttf"
    bad_ttf.write_bytes(b"not a font")
    otf = tmp_path / "skip.otf"
    otf.write_bytes(b"cff")

    state: list[str | None] = [None]
    monkeypatch.setattr(pdf_fonts, "_pdf_font_state", state)
    monkeypatch.setattr(
        pdf_fonts,
        "_cjk_font_candidates",
        lambda: [
            ("SkippedEmpty", "", None),
            ("SkippedMissing", str(tmp_path / "none.ttf"), None),
            ("SkippedOtf", str(otf), None),
            ("BadCandidate", str(bad_ttf), None),
            ("QoderTestFont", str(vera), 0),
        ],
    )

    try:
        assert pdf_fonts._ensure_pdf_font() == "QoderTestFont"
        assert state[0] == "QoderTestFont"
        # 三态缓存：已注册后再次调用直接返回，不再扫描候选
        assert pdf_fonts._ensure_pdf_font() == "QoderTestFont"
    finally:
        pdfmetrics._fonts.pop("QoderTestFont", None)


def test_ensure_pdf_font_caches_scan_failure(monkeypatch) -> None:
    state: list[str | None] = [None]
    monkeypatch.setattr(pdf_fonts, "_pdf_font_state", state)
    monkeypatch.setattr(pdf_fonts, "_cjk_font_candidates", list)

    assert pdf_fonts._ensure_pdf_font() is None
    assert state[0] == ""
    # 空串缓存：第二次调用不再重跑扫描
    assert pdf_fonts._ensure_pdf_font() is None
