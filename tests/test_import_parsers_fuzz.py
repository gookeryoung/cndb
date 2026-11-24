"""导入解析器「随机输入」鲁棒性（路线图 0141 P0-4，需求 0141 C1 ④）.

不用 hypothesis（不引新依赖）：用固定种子的 `random.Random(seed)` 生成大量结构化
随机输入，断言三条不变量：

- I1 任意分隔符文本：解析成功时 `file_columns` 与行键一致、有效行数一致；结构缺陷
  一律抛 `ValueError`（可映射 400），不裸穿其它异常；
- I2 只有表头时列名 == 表头（0 数据行不报「没有有效列」）；
- I3 XLSX / JSON 的随机形状同样只允许 `ValueError` 或成功（含只有表头）。

注意「整行空白」被解析器按惯例跳过（CSV / XLSX 同口径），断言按有效行数比较。
种子固定 → 失败可复现；每例覆盖 10-15 组输入，成本可控（在 `-m "not slow"` 内）。
"""

from __future__ import annotations

import csv
import io
import json
import random

import pytest
from openpyxl import Workbook

from cndb.plugins.tables.services.transfer import (
    analyze_file_columns_with_detection,
    create_table_from_file_with_detection,
    parse_file_to_rows_with_detection,
)
from cndb.plugins.tables.services.transfer.spreadsheet import (
    _parse_delimited_detailed,
    _parse_json_text,
    _parse_xlsx_detailed,
)

SEED = 20261124


def _rand_cell(rng: random.Random, alphabet: str) -> str:
    kind = rng.choice(["text", "empty", "quote", "comma", "newline", "cjk"])
    if kind == "empty":
        return ""
    if kind == "quote":
        return '"' + "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 4))) + '"'
    if kind == "comma":
        return ",".join("".join(rng.choice(alphabet) for _ in range(3)) for _ in range(rng.randint(1, 3)))
    if kind == "newline":
        return "a\nb"
    if kind == "cjk":
        return "".join(rng.choice("日月星辰山川河海") for _ in range(rng.randint(1, 4)))
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 6)))


def _gen_rows(rng: random.Random, header: list[str], count: int) -> list[list[str]]:
    return [[_rand_cell(rng, "abcxyz") for _ in header] for _ in range(count)]


def _non_blank_rows(rows: list[list[object]]) -> list[list[object]]:
    """解析器跳过「整行空白」（CSV / XLSX 同口径），断言按有效行数比较."""
    return [row for row in rows if any(str(v).strip() for v in row if v is not None)]


def _delimited_text(*, delimiter: str, header: list[str], rows: list[list[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


class TestDelimitedParsers:
    @pytest.mark.parametrize("delimiter", [",", "\t", ";"])
    def test_random_delimited_roundtrip(self, delimiter: str):
        """I1：随机分隔符文本解析后列名 == 表头，有效行数一致，键顺序一致."""
        rng = random.Random(SEED + ord(delimiter))
        for _case in range(15):
            header = [f"列{i}" for i in range(rng.randint(1, 5))]
            rows = _gen_rows(rng, header, rng.randint(0, 5))
            text = _delimited_text(delimiter=delimiter, header=header, rows=rows)

            parsed_rows, columns, _detection = _parse_delimited_detailed(text, delimiter=delimiter)
            assert columns == header
            assert len(parsed_rows) == len(_non_blank_rows(rows))
            for row in parsed_rows:
                assert list(row) == header

    def test_random_delimited_only_header(self):
        """I2：只有表头时也给出列名（不因 0 数据行报「没有有效列」）."""
        rng = random.Random(SEED + 7)
        for _case in range(10):
            header = [f"h{i}" for i in range(rng.randint(1, 4))]
            text = _delimited_text(delimiter=",", header=header, rows=[])

            rows, columns, actual_fmt, _detection = parse_file_to_rows_with_detection(text, "csv")
            assert rows == []
            assert columns == header
            assert actual_fmt == "csv"

            analyzed, total, fmt, _d = analyze_file_columns_with_detection(
                rows=rows, file_columns=columns, format=actual_fmt
            )
            assert total == 0
            assert fmt == "csv"
            assert [c["name"] for c in analyzed] == header

    def test_structural_guards_raise_value_error_only(self):
        """I1 的负向面：结构缺陷一律 `ValueError`（可映射 400）."""
        cases = [
            "a,b\n1\n2,3,4\n",  # 行值多于表头
            "a,,c\n1,2,3\n",  # 空列名
            "a,b,a\n1,2,3\n",  # 重复列名
        ]
        for text in cases:
            with pytest.raises(ValueError):
                _parse_delimited_detailed(text)


class TestJsonParsers:
    def test_random_object_arrays(self):
        """JSON：随机键集合 / 值类型，列名为键的并集且保序，行原样返回."""
        rng = random.Random(SEED + 31)
        for _case in range(15):
            keys = [f"k{i}" for i in range(rng.randint(1, 4))]
            payload = [
                {k: rng.choice([1, 1.5, True, None, "x", "", [1, 2], {"a": 1}]) for k in keys if rng.random() > 0.2}
                for _ in range(rng.randint(0, 4))
            ]
            rows, columns = _parse_json_text(json.dumps(payload))
            assert rows == payload
            assert columns == list(dict.fromkeys(k for item in payload for k in item))

    def test_non_array_rejected(self):
        for text in ("{}", '"x"', "1", "null"):
            with pytest.raises(ValueError):
                _parse_json_text(text)


class TestXlsxParsers:
    def _build(self, header: list[str], rows: list[list[object]]) -> bytes:
        wb = Workbook()
        sheet = wb.active
        sheet.append(header)
        for row in rows:
            sheet.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_random_sheets_parse(self):
        """XLSX：随机表头 / 行数，列名与有效行数一致（含 0 行）."""
        rng = random.Random(SEED + 53)
        for _case in range(12):
            header = [f"字段{i}" for i in range(rng.randint(1, 4))]
            rows = [[rng.choice(["文本", "", 1, 2.5, None]) for _ in header] for _ in range(rng.randint(0, 4))]
            raw = self._build(header, rows)
            parsed_rows, columns, _detection = _parse_xlsx_detailed(raw)
            assert columns == header
            assert len(parsed_rows) == len(_non_blank_rows(rows))

    def test_header_only_creates_table(self, db, db_engine):
        """只有表头的 XLSX 也能建出字段齐全的空表（上一轮修复的回归护栏）."""
        from cndb.plugins.workspaces.models import Workspace

        ws = Workspace(name="fuzz-xlsx")
        db.add(ws)
        db.commit()
        db.refresh(ws)
        raw = self._build(["编号", "名称"], [])
        rows, columns, _fmt, _d = parse_file_to_rows_with_detection(raw, "xlsx")
        assert rows == [] and columns == ["编号", "名称"]

        table, ids, analyzed, _detection = create_table_from_file_with_detection(
            db_engine, db, ws.id, "fuzz 空表", raw, format="xlsx"
        )
        db.refresh(table)
        assert ids == []
        assert [c["name"] for c in analyzed] == ["编号", "名称"]
        assert [f.name for f in table.fields] == ["编号", "名称"]
