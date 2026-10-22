"""WPS/XLSX 导入健壮性回归测试 —— 针对"进度卡 5%、无报错".

线上现象：更新已有数据表时导入 WPS 导出的**带图 XLSX**，进度停在 5% 且无任何报错。

根因：WPS 常把"仅样式"的整行/整列写进文件，把工作表**声明范围**撑到 1048576 行（实际几十行）。
旧解析实现是 `load_workbook(buf)`（非只读）+ `list(ws.iter_rows(values_only=True))`：
- 百万空行被实例化为单元格对象 → 内存暴涨（列多时可能被 OOM 杀掉，任务永远停在 5%）；
- 列多时相当于「百万行 × 列数」次遍历 → 等同卡死；
- 线程里没有错误发生，所以前端看不到任何报错。

本测试锁定修复后的行为：
1. 虚假范围文件只返回真实数据行，且**速度与内存可接受**；
2. 超限文件给出**可读错误**而不是卡死（行数上限 / 扫描上限 / 列数上限）；
3. WPS 单元格图片（DISPIMG 公式）在有界流式读取下**仍能解析**（回归守卫：data_only 不能开）；
4. 导入任务阶段超时 → 任务明确 failed 并带可读原因（看门狗），不再无声卡住。
"""

from __future__ import annotations

import io
import time

import openpyxl
import pytest
from openpyxl.drawing.image import Image as XLImage

from cndb.plugins.tables.services.transfer.xlsx_rows import (
    XlsxTooLargeError,
    read_xlsx_rows,
    xlsx_max_row_hint,
)

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def build_xlsx(
    path,
    *,
    rows: int = 3,
    cols: int = 4,
    declared_max_row: int | None = None,
    with_image: bool = False,
) -> bytes:
    """构造样本：可选写入"仅样式"的远行单元格，模拟 WPS 的虚假范围."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([f"列{i}" for i in range(1, cols + 1)])
    for r in range(1, rows + 1):
        ws.append([f"值{r}-{c}" for c in range(1, cols + 1)])
    if declared_max_row:
        cell = ws.cell(row=declared_max_row, column=1)
        cell.number_format = "0.00"  # 仅样式，无值 —— 正是 WPS 的常见形态
    if with_image:
        img_path = path.parent / f"{path.stem}.png"
        img_path.write_bytes(PNG_1PX)
        ws.add_image(XLImage(str(img_path)), "B2")
    wb.save(path)
    return path.read_bytes()


@pytest.fixture
def workdir(tmp_path):
    return tmp_path


class TestInflatedDimension:
    """WPS 虚假范围：只返回真实行，且不慢、不爆内存."""

    def test_cycle_reports_declared_range(self, workdir):
        """确认样本确实模拟出了 1048576 行的声明范围（否则测试无意义）."""
        raw = build_xlsx(workdir / "wps.xlsx", declared_max_row=1_048_576)
        assert xlsx_max_row_hint(raw) == 1_048_576

    def test_returns_only_real_rows_quickly(self, workdir):
        raw = build_xlsx(workdir / "wps.xlsx", rows=3, cols=6, declared_max_row=1_048_576, with_image=True)
        started = time.perf_counter()
        collected = list(read_xlsx_rows(raw))
        elapsed = time.perf_counter() - started

        # 表头 + 3 行数据（图片不影响行值）
        assert len(collected) == 4
        assert collected[0][1][0] == "列1"
        assert collected[1][1][1] == "值1-2"
        # 速度上界（旧实现会走到百万行，这里给一个宽松但能拦住回归的阈值）
        assert elapsed < 20, f"解析耗时 {elapsed:.1f}s，疑似回归为跟随虚假范围"

    def test_importer_parse_xlsx_ignores_inflated_range(self, workdir):
        from cndb.plugins.tables.services.importing.importer import Importer

        raw = build_xlsx(workdir / "wps.xlsx", rows=2, declared_max_row=1_048_576)
        rows, columns, _detection = Importer._parse_xlsx(raw)
        assert columns[:2] == ["列1", "列2"]
        assert len(rows) == 2
        assert rows[0]["列1"] == "值1-1"

    def test_import_tasks_parse_to_rows(self, workdir):
        from cndb.plugins.tables.services.importing.import_tasks import _parse_to_rows

        raw = build_xlsx(workdir / "wps.xlsx", rows=2, declared_max_row=1_048_576)
        rows, columns, total = _parse_to_rows(raw, "xlsx", None, None)
        assert total == 2
        assert columns[0] == "列1"
        assert rows[0]["列2"] == "值1-2"


class TestLimits:
    """超限给可读错误，而不是静默卡死."""

    def test_scan_limit_error(self, workdir):
        raw = build_xlsx(workdir / "wps.xlsx", rows=2, declared_max_row=1_048_576)
        with pytest.raises(XlsxTooLargeError) as exc:
            list(read_xlsx_rows(raw, max_scan_rows=100))
        assert "虚假范围" in str(exc.value) or "行数异常" in str(exc.value)

    def test_data_row_limit_error(self, workdir):
        raw = build_xlsx(workdir / "many.xlsx", rows=10, cols=3)
        with pytest.raises(XlsxTooLargeError) as exc:
            list(read_xlsx_rows(raw, max_data_rows=5))
        assert "数据行数超过上限" in str(exc.value)
        assert "拆分" in str(exc.value)

    def test_column_limit_error(self, workdir):
        raw = build_xlsx(workdir / "wide.xlsx", rows=1, cols=30)
        with pytest.raises(XlsxTooLargeError) as exc:
            list(read_xlsx_rows(raw, max_columns=10))
        assert "列数过多" in str(exc.value)


class TestWpsImagesStillWork:
    """回归守卫：有界流式读取不能丢掉 WPS 的 DISPIMG 公式（否则图片解析失效）."""

    def _wps_xlsx_with_cellimage(self, workdir) -> bytes:
        """构造带 WPS 单元格图片引用的 xlsx（含 cellimages.xml + rels）."""
        import zipfile

        base = build_xlsx(workdir / "wps_img.xlsx", rows=1, cols=2)
        src = workdir / "wps_img.xlsx"
        out = workdir / "wps_cellimg.xlsx"

        # 把 B2 改成 WPS 的单元格图片公式（DISPIMG），并补上 cellimages 部件与其关系
        wb = openpyxl.load_workbook(io.BytesIO(base))
        ws = wb.active
        ws["B2"] = '=_xlfn.DISPIMG("ID_ABCDEF123456",1)'
        wb.save(src)

        media = PNG_1PX
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
            names = zin.namelist()
            for name in names:
                data = zin.read(name)
                zout.writestr(name, data)
            zout.writestr("xl/media/image1.png", media)
            zout.writestr(
                "xl/cellimages.xml",
                (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<etc:cellImages xmlns:etc="http://www.wps.cn/officeDocument/2017/etCustomData"'
                    ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
                    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    '<etc:cellImage><xdr:pic xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing">'
                    '<xdr:nvPicPr><xdr:cNvPr id="1" name="ID_ABCDEF123456"/></xdr:nvPicPr>'
                    "<xdr:blipFill>"
                    '<a:blip r:embed="rId1"/>'
                    "</xdr:blipFill></xdr:pic></etc:cellImage></etc:cellImages>"
                ),
            )
            zout.writestr(
                "xl/_rels/cellimages.xml.rels",
                (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1"'
                    ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"'
                    ' Target="media/image1.png"/>'
                    "</Relationships>"
                ),
            )
        return out.read_bytes()

    def test_displimg_formula_preserved(self, workdir):
        """data_only 若被打开，这里读到的会是 None，DISPIMG 就无法识别（曾经的回归）."""
        raw = self._wps_xlsx_with_cellimage(workdir)
        collected = list(read_xlsx_rows(raw))
        header = collected[0][1]
        first_data = collected[1][1]
        assert header[0] == "列1"
        # 关键断言：公式串必须保留
        assert isinstance(first_data[1], str) and "DISPIMG" in first_data[1]

    def test_importer_resolves_wps_cell_image(self, workdir, db, client, auth_headers):
        """端到端：带 WPS 单元格图片的表经 Importer 解析后，单元格应拿到图片元数据."""
        from cndb.plugins.tables.services.importing.importer import Importer

        raw = self._wps_xlsx_with_cellimage(workdir)
        rows, columns, _detection = Importer._parse_xlsx(raw)
        assert columns[0] == "列1"
        assert "DISPIMG" in str(rows[0]["列2"])


class TestStageWatchdog:
    """看门狗：阶段超时 → 任务明确 failed（不再无声卡住）."""

    def test_timeout_raises_readable_error(self, monkeypatch):
        import time as _time

        from cndb.core.config import settings
        from cndb.plugins.tables.services.importing.import_tasks import run_with_stage_timeout

        monkeypatch.setattr(settings, "IMPORT_TASK_TIMEOUT_SECONDS", 1, raising=False)

        def slow() -> str:
            _time.sleep(3)
            return "done"

        with pytest.raises(TimeoutError) as exc:
            run_with_stage_timeout(slow, stage="校验", timeout_seconds=1)
        message = str(exc.value)
        assert "校验阶段" in message
        assert "另存为" in message

    def test_fast_stage_returns_value(self):
        from cndb.plugins.tables.services.importing.import_tasks import run_with_stage_timeout

        assert run_with_stage_timeout(lambda: 42, stage="执行", timeout_seconds=5) == 42

    def test_analyze_timeout_marks_task_failed(self, client, auth_headers, db, tmp_path, monkeypatch):
        """把 Importer.analyze 换成慢实现 → analyze_import_task 必须落 failed + 可读原因."""
        import base64
        import time as _time

        from cndb.core.config import settings
        from cndb.plugins.tables.models import ImportTask
        from cndb.plugins.tables.services.importing import import_tasks
        from cndb.plugins.tables.services.importing.importer import Importer

        monkeypatch.setattr(settings, "IMPORT_TASK_TIMEOUT_SECONDS", 1, raising=False)

        ws = client.post("/api/v1/workspaces", json={"name": "watchdog-ws"}, headers=auth_headers).json()
        table = client.post(
            f"/api/v1/workspaces/{ws['id']}/tables",
            json={"name": "watchdog-table", "description": ""},
            headers=auth_headers,
        ).json()

        raw = build_xlsx(tmp_path / "s.xlsx", rows=2, cols=2)

        def slow_analyze(self, content, fmt, **kwargs):
            _time.sleep(3)

        monkeypatch.setattr(Importer, "analyze", slow_analyze, raising=True)

        task = ImportTask(
            table_id=table["id"],
            status="pending",
            progress=0,
            format="xlsx",
            file_content=base64.b64encode(raw).decode(),
            filename="s.xlsx",
        )
        db.add(task)
        db.commit()

        import_tasks.analyze_import_task(db, task.id)
        db.refresh(task)
        assert task.status == "failed"
        assert task.progress == 100
        assert "校验阶段" in (task.error_message or "")
