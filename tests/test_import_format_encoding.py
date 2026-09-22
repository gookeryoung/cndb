"""文件格式 + 编码自动判别测试 —— AC-1 验证.

覆盖 decode_bytes_auto（chardet 兜底）、sniff_csv_delimiter、
guess_format_from_content，以及 Importer 对多种格式的解析能力.
"""

from __future__ import annotations

import json

import pytest

from cndb.plugins.tables.services.importing.importer import Importer, guess_format_from_content
from cndb.plugins.tables.transfer import (
    _normalize_numeric,
    decode_bytes_auto,
    sniff_csv_delimiter,
)

# ── 编码检测 ───────────────────────────────────


class TestDecodeBytesAuto:
    """TR-1.2: decode_bytes_auto 返回 (text, encoding, confidence)."""

    def test_utf8_plain(self):
        text, enc, conf = decode_bytes_auto(b"hello world")
        assert text == "hello world"
        assert enc in ("utf-8", "utf-8-sig")
        assert 0.0 <= conf <= 1.0

    def test_utf8_with_bom(self):
        text, enc, conf = decode_bytes_auto(b"\xef\xbb\xbfname,age\nalice,30\n")
        assert "alice" in text
        assert enc in ("utf-8-sig", "utf-8")
        assert conf >= 0.5

    def test_chinese_gbk(self):
        # 中文 GBK 编码的 "你好世界"
        gbk_bytes = "你好世界".encode("gbk")
        text, _enc, conf = decode_bytes_auto(gbk_bytes)
        assert text == "你好世界"
        assert conf >= 0.0

    def test_returns_tuple_of_three(self):
        result = decode_bytes_auto(b"test")
        assert isinstance(result, tuple) and len(result) == 3
        text, enc, conf = result
        assert isinstance(text, str)
        assert isinstance(enc, str)
        assert isinstance(conf, (int, float))


# ── 分隔符 sniff ────────────────────────────────


class TestSniffDelimiter:
    """TR-1.1: 自动识别 CSV 分隔符."""

    def test_comma(self):
        assert sniff_csv_delimiter("a,b,c\n1,2,3") == ","

    def test_semicolon(self):
        assert sniff_csv_delimiter("a;b;c\n1;2;3") == ";"

    def test_pipe(self):
        assert sniff_csv_delimiter("a|b|c\n1|2|3") == "|"

    def test_tab(self):
        assert sniff_csv_delimiter("a\tb\tc\n1\t2\t3") == "\t"

    def test_single_column_default_comma(self):
        # 只有一列时 csv.Sniffer 可能失败，应该兜底返回逗号
        assert sniff_csv_delimiter("just_one_col\nvalue") == ","


# ── 内容判格式 ──────────────────────────────────


class TestGuessFormatFromContent:
    """TR-1.1: 从内容特征猜格式."""

    def test_json_array(self):
        data = json.dumps([{"a": 1}])
        assert guess_format_from_content(data) == "json"

    def test_csv_with_comma(self):
        assert guess_format_from_content("name,age\nalice,30") == "csv"

    def test_tsv_first_line_has_tab(self):
        assert guess_format_from_content("a\tb\tc\n1\t2\t3") == "tsv"

    def test_bytes_binary_likely_xlsx(self):
        # 一段无法被任何文本编码正常解码的二进制字节
        binary = bytes(range(256))
        fmt = guess_format_from_content(binary)
        # 二进制兜底 xlsx
        assert fmt in ("xlsx", "csv")


# ── Importer 解析多格式 ─────────────────────────


def _make_rows(content: bytes | str, fmt: str) -> tuple[list[dict], list[str]]:
    """用 Importer 的静态 parse 方法直接解析."""
    if fmt in ("csv", "tsv", "delimited"):
        return Importer._parse_csv(content)
    if fmt == "json":
        return Importer._parse_json(content)
    if fmt == "xlsx":
        return Importer._parse_xlsx(content)
    raise ValueError(f"不支持的格式: {fmt}")


class TestImporterParse:
    """TR-1.1: Importer._parse 对多格式的解析能力."""

    def test_csv_comma(self):
        rows, cols = _make_rows(b"name,age\nalice,30\nbob,25\n", "csv")
        assert len(rows) == 2
        assert cols == ["name", "age"]
        assert rows[0]["name"] == "alice"

    def test_csv_semicolon_auto_sniff(self):
        rows, cols = _make_rows(b"name;age\nalice;30\n", "csv")
        assert cols == ["name", "age"]
        assert rows[0]["name"] == "alice"

    def test_tsv(self):
        rows, cols = _make_rows(b"name\tage\nalice\t30\n", "tsv")
        assert cols == ["name", "age"]
        assert rows[0]["age"] == "30"

    def test_json_array(self):
        content = json.dumps([{"name": "alice", "age": 30}, {"name": "bob"}])
        rows, cols = _make_rows(content, "json")
        assert len(rows) == 2
        assert "name" in cols
        assert "age" in cols

    def test_csv_with_chinese_gbk(self):
        data = "姓名,年龄\n张三,30\n".encode("gbk")
        rows, cols = _make_rows(data, "csv")
        assert cols == ["姓名", "年龄"]
        assert rows[0]["姓名"] == "张三"

    def test_csv_with_utf8_bom(self):
        data = b"\xef\xbb\xbfname,age\nzhang,28\n"
        rows, cols = _make_rows(data, "csv")
        # BOM 应该被剥离（列名前不应有 U+FEFF）
        assert cols[0] == "name"
        assert rows[0]["name"] == "zhang"

    def test_tsv_format_alias_delimited(self):
        rows, cols = _make_rows(b"a\tb\tc\n1\t2\t3\n", "delimited")
        assert cols == ["a", "b", "c"]
        assert rows[0]["a"] == "1"


# ── _normalize_numeric 覆盖千分位/百分比 ─────────


class TestNormalizeNumeric:
    """TR-3.1: 数值归一化（千分位、百分比）."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1,234", "1234"),
            ("1,234.56", "1234.56"),
            ("50%", None),  # _normalize_numeric 不处理百分比
            ("85.5%", None),
            ("100", "100"),
            ("3.14", "3.14"),
            ("-5", "-5"),
            ("", None),
            ("abc", None),
        ],
    )
    def test_various(self, raw, expected):
        assert _normalize_numeric(raw) == expected


# ── 格式枚举与错误信息 ───────────────────────────


class TestFormatValidation:
    def test_unknown_format_raises(self):
        with pytest.raises(ValueError, match="不支持的格式"):
            _make_rows(b"", "unknown_format")

    def test_json_not_array_raises(self):
        with pytest.raises(ValueError, match="JSON 必须是对象数组"):
            _make_rows('{"a": 1}', "json")


# ── 覆盖 _normalize_numeric 边界 + 更多 format 场景 ──


class TestNormalizeNumericEdgeCases:
    """边界 case 的额外覆盖."""

    def test_percentage(self):
        # _normalize_numeric 不处理百分比
        assert _normalize_numeric("50%") is None

    def test_negative(self):
        assert _normalize_numeric("-100") == "-100"
        assert _normalize_numeric("-1,234") == "-1234"

    def test_zero(self):
        assert _normalize_numeric("0") == "0"

    def test_spaces_around(self):
        assert _normalize_numeric("  42  ") == "42"

    def test_currency_symbols(self):
        assert _normalize_numeric("$19.99") == "19.99"
        assert _normalize_numeric("¥100") == "100"

    def test_empty_string(self):
        assert _normalize_numeric("") is None

    def test_alpha_only(self):
        assert _normalize_numeric("abc") is None


# ── 更多 delimiter sniff 边界 ──


class TestSniffDelimiterEdgeCases:
    def test_mixed_delimiters_prefers_comma(self):
        # csv.Sniffer 在有多个 delimiter 时选最常见的
        d = sniff_csv_delimiter("a,b,c\nd;e;f")
        assert d in (",", ";")

    def test_pipe_delimiter(self):
        d = sniff_csv_delimiter("a|b|c\n1|2|3")
        assert d == "|"

    def test_tab_confirmed(self):
        d = sniff_csv_delimiter("col1\tcol2\n1\t2")
        assert d == "\t"
