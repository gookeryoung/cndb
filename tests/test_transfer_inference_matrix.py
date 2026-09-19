"""导入转换识别测试矩阵 —— 推断层与落库校验层双向锁定.

覆盖：
- 48 组列推断矩阵（analyze_csv_columns）：日期/数字/百分比/布尔/联系方式/JSON/select/multiselect 提升；
- 数值归一值正确性矩阵（_normalize_numeric）：B1 科学计数法值保真等；
- validate_value 值域对齐矩阵（field_types）：B3-B6 修复验收，推断出的格式必须能落库；
- 端到端建表导入验收：85% → 0.85、中文日期落库、"是" → True、科学计数法值保真、
  负百分比/超 100% 的 %-后缀值落库、multiselect 列表列识别与 options 预填充。

对应计划文档 .trae/documents/import-conversion-recognition-enhancement.md 的缺陷 B1-B7
及其遗留事项（负百分比、multiselect 识别含 JSON/XLSX 路径）。
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from cndb.plugins.tables import transfer
from cndb.plugins.tables.field_types import default_registry

# ── 一、列推断矩阵（组 01-44，每组一列样本 → 期望 field_type）──────────

INFERENCE_MATRIX: list[tuple[str, str, list[str], str]] = [
    # ── 01-12 日期/时间 ──
    ("01", "ISO日期", ["2024-01-15", "2023-06-20", "2024-12-31"], "date"),
    ("02", "ISO日期时间", ["2024-01-15T10:30:00", "2023-06-20 08:45:00"], "datetime"),
    ("03", "中文日期", ["2024年1月15日", "2023年6月20日", "2024年12月31日"], "date"),
    ("04", "斜杠日期", ["2024/1/15", "2023/6/20", "2024/12/31"], "date"),
    ("05", "美式日期", ["1/15/2024", "6/20/2023", "12/31/2024"], "date"),
    ("06", "点分隔日期", ["2024.1.15", "2023.6.20", "2024.12.31"], "date"),
    ("07", "紧凑日期", ["20240115", "20230620", "20241231"], "date"),
    ("08", "非法日期回落text", ["2024-02-30", "2023-04-31", "2024-13-01"], "text"),
    ("09", "非法月中文日期回落text", ["2024年13月1日", "2023年2月30日"], "text"),
    ("10", "斜杠日期加时间", ["2024/1/15 10:30", "2023/6/20 08:45:30"], "datetime"),
    ("11", "英文月名前置", ["Jan 15, 2024", "Feb 3, 2023", "Sept 30, 2024"], "date"),
    ("12", "英文月名后置", ["15 Jan 2024", "3 Feb 2023", "30 Sept 2024"], "date"),
    # ── 13-22 数字 ──
    ("13", "千分位整数", ["1,234", "56,789", "1,234,567"], "number"),
    ("14", "欧元点千分位小数", ["1.234,56", "12.345,67", "9,99"], "float"),
    ("15", "货币符号", ["￥1,234.56", "$99.50", "¥88"], "float"),
    ("16", "负数", ["-42", "-17", "-1000"], "number"),
    ("17", "科学计数法", ["1.5e10", "2.5e3", "-1.5e-3"], "float"),
    ("18", "纯指数", ["1e5", "3e8", "9e2"], "float"),
    ("19", "会计负数", ["(1,234)", "(2,500)"], "number"),
    ("20", "全角数字", ["１２３", "４５６", "７８９"], "number"),
    ("21", "前导零长编号回落text", ["00123456789", "00234567890"], "text"),
    ("22", "十五位以上长号回落text", ["1234567890123456", "9876543210987654"], "text"),
    # ── 23-26 百分比 ──
    ("23", "整数百分比", ["85%", "92%", "100%"], "percentage"),
    ("24", "小数百分比", ["85.5%", "12.5%", "7.25%"], "percentage"),
    # 负百分比/超100% 推断为 percentage；validate 层 %-后缀是显式意图，落库不再受 0~1 限制
    ("25", "负百分比", ["-12.5%", "-3%"], "percentage"),
    ("26", "全角％", ["85.5％", "12％"], "percentage"),
    # ── 27-32 布尔 ──
    ("27", "是否列", ["是", "否", "是", "否"], "boolean"),
    ("28", "truefalse列", ["true", "false", "TRUE", "False"], "boolean"),
    ("29", "真假列", ["真", "假", "真", "假"], "boolean"),
    ("30", "YN列", ["Y", "N", "y", "n"], "boolean"),
    ("31", "对勾叉列", ["√", "×", "√", "×"], "boolean"),
    ("32", "onoff列", ["on", "off", "ON", "OFF"], "boolean"),
    # ── 33-36 联系方式 ──
    ("33", "手机号", ["13800138000", "15912345678"], "phone"),
    ("34", "带区号手机号", ["+8613800138000", "+8613800138001"], "phone"),
    ("35", "邮箱", ["user@example.com", "alice@test.org"], "email"),
    ("36", "网址", ["https://example.com", "http://test.org/path?a=1"], "url"),
    # ── 37-38 JSON 字符串 ──
    ("37", "JSON对象", ['{"a":1}', '{"b":"x"}'], "json"),
    ("38", "JSON数组", ["[1,2,3]", '["x","y"]'], "json"),
    # ── 39-42 select/混合 ──
    ("39", "低基数select提升", ["active", "done", "pending", "active", "done", "pending", "active", "done"], "select"),
    ("40", "高基数保持text", ["客户-张三", "客户-李四", "客户-王五", "客户-赵六", "客户-钱七", "客户-孙八"], "text"),
    ("41", "混合列主导类型", ["1", "2", "3", "4", "5", "6", "7", "8", "9", "abc"], "number"),
    ("42", "全空列", ["", "", ""], "text"),
    # ── 43-44 补充锁定（计划决策 2 与紧凑日期回落）──
    ("43", "年月格式保持text", ["2024年1月", "2023年12月"], "text"),
    ("44", "紧凑非法日期回落number", ["20240001", "20241300"], "number"),
    # ── 45-48 multiselect 列表识别 ──
    ("45", "标签列表提升multiselect", ["前端,后端", "前端,测试", "后端,运维", "前端,后端"], "multiselect"),
    ("46", "全角分隔列表提升", ["阅读；旅行", "阅读；运动", "旅行；摄影", "阅读；旅行"], "multiselect"),
    ("47", "个人信息串不提升", ["张三,男,北京", "李四,女,上海", "王五,男,广州", "赵六,女,深圳"], "text"),
    ("48", "少数列表值不提升", ["普通备注", "a,b", "另一条", "c,d", "备注三", "e,f"], "text"),
]

# ── 二、数值归一值正确性矩阵（B1 修复验收：值不得变形）──────────────

NORMALIZE_NUMERIC_MATRIX: list[tuple[str, float]] = [
    ("1.5e10", 15_000_000_000.0),  # 修复前点被当千分位删除 → 15e10（值错 10 倍）
    ("1e5", 100_000.0),
    ("1,234", 1234.0),
    ("1,234,567", 1234567.0),
    ("1.234,56", 1234.56),  # 欧元点千分位
    ("￥1,234.56", 1234.56),
    ("$99.50", 99.5),
    ("(1,234)", -1234.0),  # 会计负数
    ("(1,234.5)", -1234.5),
    ("１２３", 123.0),  # 全角
    ("－４２", -42.0),
    ("-42", -42.0),
]

NORMALIZE_INVALID_VALUES: list[str] = ["abc", "", "12,34.5.6"]

# ── 三、validate_value 值域对齐矩阵（B3-B6 修复验收）──────────────

VALIDATE_ALIGN_MATRIX: list[tuple[str, str, dict[str, Any], Any]] = [
    # percentage：字符串带 %/％ → 剥离后 /100 存比例值（修复前 float("85%") 直接失败）
    ("percentage", "85%", {}, 0.85),
    ("percentage", "12.5%", {}, 0.125),
    ("percentage", "85.5％", {}, 0.855),
    ("percentage", "100%", {}, 1.0),
    # %-后缀是显式用户意图，不受 0~1 值域限制（修复前负百分比/超 100% 行导致整表导入失败）
    ("percentage", "-12.5%", {}, -0.125),
    ("percentage", "-200％", {}, -2.0),
    ("percentage", "200%", {}, 2.0),
    # multiselect：字符串按分隔符拆分后以半角逗号连接（修复前整串当一个值）
    ("multiselect", "前端,后端", {}, "前端,后端"),
    ("multiselect", "a；b、c", {}, "a,b,c"),
    ("multiselect", "a, b , c", {}, "a,b,c"),
    ("multiselect", "单值", {}, "单值"),
    # boolean：中文/符号真值域（修复前"是"静默存 False）
    ("boolean", "是", {}, True),
    ("boolean", "否", {}, False),
    ("boolean", "真", {}, True),
    ("boolean", "假", {}, False),
    ("boolean", "√", {}, True),
    ("boolean", "×", {}, False),
    ("boolean", "TRUE", {}, True),
    ("boolean", "y", {}, True),
    # date：与推断层格式清单一一对应（修复前仅接受 %Y-%m-%d 与 %Y/%m/%d）
    ("date", "2024年1月15日", {}, date(2024, 1, 15)),
    ("date", "2024年1月15", {}, date(2024, 1, 15)),
    ("date", "20240115", {}, date(2024, 1, 15)),
    ("date", "2024.1.15", {}, date(2024, 1, 15)),
    ("date", "1/15/2024", {}, date(2024, 1, 15)),
    ("date", "Jan 15, 2024", {}, date(2024, 1, 15)),
    ("date", "15 Jan 2024", {}, date(2024, 1, 15)),
    ("date", "December 31, 2024", {}, date(2024, 12, 31)),
    ("date", "Sept 30 2021", {}, date(2021, 9, 30)),  # strptime %b 不认 "Sept"，须归一为 Sep
    ("date", "Sept 30, 2021", {}, date(2021, 9, 30)),
    # datetime：斜杠/点分隔 + 微秒 + 时区后缀变体
    ("datetime", "2024/1/15 10:30", {}, datetime(2024, 1, 15, 10, 30)),
    ("datetime", "2024.1.15 10:30:45", {}, datetime(2024, 1, 15, 10, 30, 45)),
    ("datetime", "2024-01-15T10:30:45.123456", {}, datetime(2024, 1, 15, 10, 30, 45, 123456)),
    ("datetime", "2024-01-15T10:30:45Z", {}, datetime(2024, 1, 15, 10, 30, 45)),
    # number / float：千分位/货币/会计负数/全角/科学计数法整数值
    ("number", "1,234", {}, 1234),
    ("number", "(1,234)", {}, -1234),
    ("number", "１２３", {}, 123),
    ("number", "1.5e10", {}, 15_000_000_000),
    ("float", "￥1,234.56", {"decimals": 2}, 1234.56),
    ("float", "(2,500.5)", {"decimals": 1}, -2500.5),
    ("float", "1.5e10", {}, 1.5e10),
    # json：对象/数组字符串原样保留
    ("json", '{"a":1}', {}, '{"a":1}'),
    ("json", "[1,2,3]", {}, "[1,2,3]"),
]

VALIDATE_RAISE_MATRIX: list[tuple[str, str, dict[str, Any], str]] = [
    ("date", "2024-13-45", {}, "日期格式错误"),  # B2 对应：非法日期不得蒙混落库
    ("date", "20240132", {}, "日期格式错误"),
    ("date", "not-a-date", {}, "日期格式错误"),
    ("number", "abc", {}, "无法将 'abc' 转为整数"),
    ("number", "1.5e-3", {}, "无法将 '1.5e-3' 转为整数"),  # 非整数值的科学计数法
    ("float", "abc", {}, "无法将 'abc' 转为小数"),
    ("float", "12,34.5.6", {}, "无法将"),
    ("percentage", "1.5", {}, "0~1"),  # 裸数字无显式意图，超出比例值域仍拒绝
    ("percentage", "nan%", {}, "有限数字"),  # %-后缀绕过值域但须排除 NaN/inf
    ("percentage", "inf%", {}, "有限数字"),
    ("multiselect", "a,z", {"options": [{"label": "a", "value": "a"}]}, "不在可选值"),  # 拆分后逐项校验
]


def _column_csv(samples: list[str]) -> str:
    """把一列样本值构建成单列 CSV 文本（csv.writer 自动处理逗号/引号转义）."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["col"])
    for s in samples:
        writer.writerow([s])
    return buf.getvalue()


class TestInferenceMatrix:
    """组 01-48：analyze_csv_columns 列级推断矩阵."""

    @pytest.mark.parametrize(
        ("gid", "label", "samples", "expected"),
        INFERENCE_MATRIX,
        ids=[f"{m[0]}-{m[1]}" for m in INFERENCE_MATRIX],
    )
    def test_column_inference(self, gid: str, label: str, samples: list[str], expected: str) -> None:
        cols, _n = transfer.analyze_csv_columns(_column_csv(samples))
        assert cols[0]["field_type"] == expected, f"组{gid} {label}: 推断结果不符"


class TestNormalizeNumeric:
    """数值归一值正确性：归一结果转 float 后必须与原始数值一致."""

    @pytest.mark.parametrize(
        ("raw", "expected"), NORMALIZE_NUMERIC_MATRIX, ids=[m[0] for m in NORMALIZE_NUMERIC_MATRIX]
    )
    def test_value_preserved(self, raw: str, expected: float) -> None:
        normalized = transfer._normalize_numeric(raw)
        assert normalized is not None, f"{raw!r} 归一失败"
        assert float(normalized) == pytest.approx(expected), f"{raw!r} → {normalized!r} 值变形"

    @pytest.mark.parametrize("raw", NORMALIZE_INVALID_VALUES)
    def test_invalid_returns_none(self, raw: str) -> None:
        assert transfer._normalize_numeric(raw) is None


class TestValidateAlign:
    """validate_value 与推断值域对齐：识别出的格式一定能转换."""

    @pytest.mark.parametrize(
        ("field_type", "raw", "config", "expected"),
        VALIDATE_ALIGN_MATRIX,
        ids=[f"{m[0]}:{m[1]}" for m in VALIDATE_ALIGN_MATRIX],
    )
    def test_value_aligned(self, field_type: str, raw: str, config: dict[str, Any], expected: Any) -> None:
        ft = default_registry.get(field_type)
        assert ft is not None, f"未注册字段类型: {field_type}"
        assert ft.validate_value(raw, config) == expected

    @pytest.mark.parametrize(
        ("field_type", "raw", "config", "match"),
        VALIDATE_RAISE_MATRIX,
        ids=[f"{m[0]}:{m[1]}" for m in VALIDATE_RAISE_MATRIX],
    )
    def test_invalid_raises(self, field_type: str, raw: str, config: dict[str, Any], match: str) -> None:
        ft = default_registry.get(field_type)
        assert ft is not None
        with pytest.raises(ValueError, match=match):
            ft.validate_value(raw, config)


class TestInferenceExtras:
    """select/multiselect 提升 options、编码解码、分隔符嗅探."""

    def test_select_promotion_with_options(self):
        """组39：低基数离散值提升为 select，options 保持首次出现顺序."""
        samples = ["active", "done", "pending", "active", "done", "pending", "active", "done"]
        cols, _ = transfer.analyze_csv_columns(_column_csv(samples))
        assert cols[0]["field_type"] == "select"
        assert cols[0]["options"] == ["active", "done", "pending"]

    def test_multiselect_promotion_splits_options(self):
        """组45：multiselect 提升 options 为拆分后的独立选项（修复前整串被 select 抢走）."""
        samples = ["前端,后端", "前端,测试", "后端,运维", "前端,后端"]
        cols, _ = transfer.analyze_csv_columns(_column_csv(samples))
        assert cols[0]["field_type"] == "multiselect"
        assert cols[0]["options"] == ["前端", "后端", "测试", "运维"]

    def test_multiselect_promotion_reuse_guard(self):
        """组47：选项无复用（逐行唯一个人信息串）不提升，且不被 select 抢走."""
        samples = ["张三,男,北京", "李四,女,上海", "王五,男,广州", "赵六,女,深圳"]
        cols, _ = transfer.analyze_csv_columns(_column_csv(samples))
        assert cols[0]["field_type"] == "text"
        assert "options" not in cols[0]

    def test_multiselect_not_promoted_for_numeric_thousands(self):
        """千分位数字串（1,234）须保持 number 推断，不受列表识别影响."""
        samples = ["1,234", "5,678", "9,012"]
        cols, _ = transfer.analyze_csv_columns(_column_csv(samples))
        assert cols[0]["field_type"] == "number"
        assert "options" not in cols[0]

    def test_gbk_encoded_csv_analysis(self):
        """组43：GBK 编码字节流解码后推断不受影响."""
        text, enc, _conf = transfer.decode_bytes_auto("姓名,年龄\n张三,25\n".encode("gbk"))
        assert enc in ("gbk", "gb18030")
        cols, n = transfer.analyze_csv_columns(text)
        types = {c["name"]: c["field_type"] for c in cols}
        assert types == {"姓名": "text", "年龄": "number"}
        assert n == 1

    def test_semicolon_delimiter_sniff(self):
        """组44：分号/逗号分隔符嗅探."""
        assert transfer.sniff_csv_delimiter("a;b;c\n1;2;3\n") == ";"
        assert transfer.sniff_csv_delimiter("a,b,c\n1,2,3\n") == ","


@pytest.fixture
def csv_workspace(db, db_engine):
    """复用 conftest 内存 DB，种子 csv_user + CSVWS workspace."""
    from cndb.plugins.accounts.models import User
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

    u = User(username="csv_user")
    u.set_password("pass")
    db.add(u)
    db.flush()
    ws = Workspace(name="CSVWS", created_by_id=u.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.OWNER))
    db.commit()
    yield db_engine, db, ws


class TestEndToEndAlignment:
    """端到端对齐验收：推断出的格式必须能成功建表并落库（修复前 B3/B4/B6 整表失败）."""

    def test_mixed_enhanced_formats(self, csv_workspace):
        """百分比/中文日期/布尔/JSON/货币/会计负数混合 CSV 建表导入成功且值正确."""
        engine, db, ws = csv_workspace
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["完成率", "签约日期", "是否启用", "扩展信息", "应收金额", "序号"])
        w.writerow(["85%", "2024年1月15日", "是", '{"a":1}', "￥1,234.56", "(1,234)"])
        w.writerow(["12.5%", "2023年6月20日", "否", "[1,2,3]", "$99.50", "２０"])
        w.writerow(["100%", "2024年12月31日", "是", '{"k":"v"}', "12.5", "15"])

        dt, ids = transfer.create_table_from_csv(engine, db, ws.id, "增强格式表", buf.getvalue())
        assert len(ids) == 3
        fmap = {f.name: f.field_type for f in dt.fields}
        assert fmap["完成率"] == "percentage"
        assert fmap["签约日期"] == "date"
        assert fmap["是否启用"] == "boolean"
        assert fmap["扩展信息"] == "json"
        assert fmap["应收金额"] == "float"
        assert fmap["序号"] == "number"

        from cndb.plugins.tables import records as rec

        row1 = rec.get_row(engine, dt, ids[0])
        assert row1["完成率"] == pytest.approx(0.85)
        assert row1["签约日期"] == date(2024, 1, 15)
        assert row1["是否启用"] is True
        assert row1["扩展信息"] == '{"a":1}'
        assert row1["应收金额"] == pytest.approx(1234.56)
        assert row1["序号"] == -1234

        row2 = rec.get_row(engine, dt, ids[1])
        assert row2["完成率"] == pytest.approx(0.125)
        assert row2["是否启用"] is False
        assert row2["应收金额"] == pytest.approx(99.5)
        assert row2["序号"] == 20

        # float 字段 decimals 配置被正确推断（修复精度静默取整）
        money_field = next(f for f in dt.fields if f.name == "应收金额")
        assert money_field.config.get("decimals") == 2

    def test_scientific_notation_value_preserved(self, csv_workspace):
        """B1 修复验收：科学计数法落库值正确（修复前 1.5e10 → 15e10，值错 10 倍）."""
        engine, db, ws = csv_workspace
        dt, ids = transfer.create_table_from_csv(engine, db, ws.id, "科学计数法表", "指标\n1.5e10\n2.5e3\n")
        assert dt.fields[0].field_type == "float"

        from cndb.plugins.tables import records as rec

        row1 = rec.get_row(engine, dt, ids[0])
        assert row1["指标"] == pytest.approx(15_000_000_000.0)
        row2 = rec.get_row(engine, dt, ids[1])
        assert row2["指标"] == pytest.approx(2500.0)

    def test_negative_and_over_100_percentage(self, csv_workspace):
        """遗留②验收：负百分比/超 100% 的 %-后缀值可落库（修复前整表导入失败）."""
        engine, db, ws = csv_workspace
        dt, ids = transfer.create_table_from_csv(
            engine, db, ws.id, "负百分比表", "完成率,增幅\n85%,-12.5%\n100%,200%\n"
        )
        assert len(ids) == 2
        fmap = {f.name: f.field_type for f in dt.fields}
        assert fmap["完成率"] == "percentage"
        assert fmap["增幅"] == "percentage"

        from cndb.plugins.tables import records as rec

        row1 = rec.get_row(engine, dt, ids[0])
        assert row1["完成率"] == pytest.approx(0.85)
        assert row1["增幅"] == pytest.approx(-0.125)
        row2 = rec.get_row(engine, dt, ids[1])
        assert row2["完成率"] == pytest.approx(1.0)
        assert row2["增幅"] == pytest.approx(2.0)

    def test_multiselect_column_end_to_end(self, csv_workspace):
        """遗留③验收：列表列提升为 multiselect，options 拆分预填充且整表导入成功."""
        engine, db, ws = csv_workspace
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["姓名", "技能标签"])
        w.writerow(["甲", "前端,后端"])
        w.writerow(["乙", "前端,测试"])
        w.writerow(["丙", "后端,运维"])
        w.writerow(["丁", "前端,后端"])

        dt, ids = transfer.create_table_from_csv(engine, db, ws.id, "多选列表表", buf.getvalue())
        assert len(ids) == 4
        fmap = {f.name: f.field_type for f in dt.fields}
        assert fmap["姓名"] == "text"  # 逐行唯一值，select 低基数比例守卫拒绝
        assert fmap["技能标签"] == "multiselect"

        tags_field = next(f for f in dt.fields if f.name == "技能标签")
        assert [o["label"] for o in tags_field.config["options"]] == ["前端", "后端", "测试", "运维"]

        from cndb.plugins.tables import records as rec

        row1 = rec.get_row(engine, dt, ids[0])
        assert row1["技能标签"] == "前端,后端"
        row2 = rec.get_row(engine, dt, ids[1])
        assert row2["技能标签"] == "前端,测试"


class TestJsonInferenceAlignment:
    """analyze_json_columns 的 multiselect 提升（JSON/XLSX 文件路径）."""

    def test_scalar_array_column_promoted(self):
        """真 JSON 数组列（标量元素、高复用）提升为 multiselect."""
        rows: list[dict[str, Any]] = [
            {"tags": ["前端", "后端"]},
            {"tags": ["前端", "测试"]},
            {"tags": ["后端", "运维"]},
            {"tags": ["前端", "后端"]},
        ]
        cols = transfer.analyze_json_columns(rows)
        tags = next(c for c in cols if c["name"] == "tags")
        assert tags["field_type"] == "multiselect"
        assert tags["options"] == ["前端", "后端", "测试", "运维"]

    def test_sample_values_dedupe(self):
        """sample_values 按首次出现去重 —— 重复值不挤占样本位，保证样本代表性."""
        rows: list[dict[str, Any]] = [
            {"tag": "前端"},
            {"tag": "前端"},
            {"tag": "后端"},
            {"tag": "前端"},
            {"tag": "测试"},
        ]
        cols = transfer.analyze_json_columns(rows)
        tag = next(c for c in cols if c["name"] == "tag")
        assert tag["sample_values"] == ["前端", "后端", "测试"]

    def test_delimited_string_column_promoted(self):
        """text 推断列（分隔符串值）经 JSON 路径同样提升为 multiselect."""
        rows: list[dict[str, Any]] = [
            {"tags": "前端,后端"},
            {"tags": "前端,测试"},
            {"tags": "后端,运维"},
            {"tags": "前端,后端"},
        ]
        cols = transfer.analyze_json_columns(rows)
        tags = next(c for c in cols if c["name"] == "tags")
        assert tags["field_type"] == "multiselect"
        assert tags["options"] == ["前端", "后端", "测试", "运维"]

    def test_dict_column_stays_json(self):
        """dict 值列维持 json，不做列表提升."""
        rows: list[dict[str, Any]] = [{"data": {"a": 1}}, {"data": {"b": 2}}, {"data": {"a": 3}}]
        cols = transfer.analyze_json_columns(rows)
        data = next(c for c in cols if c["name"] == "data")
        assert data["field_type"] == "json"
        assert "options" not in data

    def test_mixed_dict_sample_blocks_promotion(self):
        """数组列混入 dict 样本 → 整列不提升（防 dict 行拆出垃圾选项）."""
        rows: list[dict[str, Any]] = [
            {"tags": ["前端", "后端"]},
            {"tags": ["前端", "测试"]},
            {"tags": {"a": 1}},
        ]
        cols = transfer.analyze_json_columns(rows)
        tags = next(c for c in cols if c["name"] == "tags")
        assert tags["field_type"] != "multiselect"
        assert "options" not in tags

    def test_nested_array_stays_json(self):
        """嵌套数组元素判非标量 → 维持 json."""
        rows: list[dict[str, Any]] = [{"data": [[1, 2], [3]]}, {"data": [[4], [5, 6]]}]
        cols = transfer.analyze_json_columns(rows)
        data = next(c for c in cols if c["name"] == "data")
        assert data["field_type"] == "json"

    def test_element_with_delimiter_stays_json(self):
        """数组元素含分隔符（逗号连接存储有歧义）→ 维持 json."""
        rows: list[dict[str, Any]] = [
            {"tags": ["a,b", "c"]},
            {"tags": ["a,b", "d"]},
            {"tags": ["a,b", "e"]},
        ]
        cols = transfer.analyze_json_columns(rows)
        tags = next(c for c in cols if c["name"] == "tags")
        assert tags["field_type"] == "json"

    def test_low_reuse_array_stays_json(self):
        """数组选项无复用（逐行唯一）→ 守卫拒绝，维持 json."""
        rows: list[dict[str, Any]] = [
            {"tags": ["甲", "乙"]},
            {"tags": ["丙", "丁"]},
            {"tags": ["戊", "己"]},
        ]
        cols = transfer.analyze_json_columns(rows)
        tags = next(c for c in cols if c["name"] == "tags")
        assert tags["field_type"] == "json"

    def test_json_array_multiselect_end_to_end(self, csv_workspace):
        """JSON 数组列端到端：提升为 multiselect，list 值落库为逗号串."""
        engine, db, ws = csv_workspace
        rows: list[dict[str, Any]] = [
            {"姓名": "甲", "技能标签": ["前端", "后端"]},
            {"姓名": "乙", "技能标签": ["前端", "测试"]},
            {"姓名": "丙", "技能标签": ["后端", "运维"]},
            {"姓名": "丁", "技能标签": ["前端", "后端"]},
        ]
        dt, ids = transfer.create_table_from_json_data(engine, db, ws.id, "JSON多选表", rows)
        assert len(ids) == 4
        fmap = {f.name: f.field_type for f in dt.fields}
        assert fmap["姓名"] == "text"  # 逐行唯一值，select 低基数比例守卫拒绝
        assert fmap["技能标签"] == "multiselect"

        tags_field = next(f for f in dt.fields if f.name == "技能标签")
        assert [o["label"] for o in tags_field.config["options"]] == ["前端", "后端", "测试", "运维"]

        from cndb.plugins.tables import records as rec

        row1 = rec.get_row(engine, dt, ids[0])
        assert row1["技能标签"] == "前端,后端"
        row2 = rec.get_row(engine, dt, ids[1])
        assert row2["技能标签"] == "前端,测试"


class TestXlsxDateInference:
    """xlsx 日期单元格（openpyxl 读出的 datetime/date 对象）推断与 select 提升守卫.

    缺陷背景：openpyxl 日期单元格返回 datetime 对象，_python_type_to_field_type
    未识别而落 text，随后被 select 低基数启发式误提升为 select（选项为
    "2026-09-01 00:00:00" 串）。修复后午夜 datetime 归一为 date，带时间
    datetime 归一为 datetime，且 date/datetime 不满足 select 提升前置条件。
    """

    def test_timed_datetime_maps_to_datetime(self):
        assert transfer._python_type_to_field_type(datetime(2026, 9, 1, 10, 30, 45)) == "datetime"

    def test_midnight_datetime_maps_to_date(self):
        # Excel 纯日期单元格经 openpyxl 读出为午夜 datetime（不含时间信息）
        assert transfer._python_type_to_field_type(datetime(2026, 9, 1)) == "date"

    def test_date_object_maps_to_date(self):
        assert transfer._python_type_to_field_type(date(2026, 9, 1)) == "date"

    def test_low_cardinality_date_column_not_promoted_to_select(self):
        """100 行仅 5 个不同日期（此前会命中 select 提升阈值）→ 保持 date."""
        base = datetime(2026, 9, 1)
        rows: list[dict[str, Any]] = [{"打卡日期": base.replace(day=1 + i % 5)} for i in range(100)]
        cols = transfer.analyze_json_columns(rows)
        col = next(c for c in cols if c["name"] == "打卡日期")
        assert col["field_type"] == "date"
        assert "options" not in col

    def test_low_cardinality_datetime_column_not_promoted_to_select(self):
        base = datetime(2026, 9, 1, 8, 0, 0)
        rows: list[dict[str, Any]] = [{"操作时间": base + timedelta(hours=i % 5)} for i in range(100)]
        cols = transfer.analyze_json_columns(rows)
        col = next(c for c in cols if c["name"] == "操作时间")
        assert col["field_type"] == "datetime"
        assert "options" not in col

    def test_date_like_samples_iso_format(self):
        """样本值输出 ISO 串：午夜 datetime 归一为日期部分，不出现 00:00:00 尾巴."""
        rows: list[dict[str, Any]] = [
            {"d": datetime(2026, 9, 1), "dt": datetime(2026, 9, 1, 10, 30, 45), "od": date(2026, 9, 2)},
            {"d": datetime(2026, 9, 2), "dt": datetime(2026, 9, 2, 11, 0, 0), "od": date(2026, 9, 3)},
        ]
        cols = transfer.analyze_json_columns(rows)
        by_name = {c["name"]: c for c in cols}
        assert by_name["d"]["sample_values"] == ["2026-09-01", "2026-09-02"]
        assert by_name["dt"]["sample_values"] == ["2026-09-01 10:30:45", "2026-09-02 11:00:00"]
        assert by_name["od"]["sample_values"] == ["2026-09-02", "2026-09-03"]

    def test_profile_layer_date_column_not_select(self):
        """画像层（导入预览）与推断层同规则：日期列不落 text/select."""
        from cndb.plugins.tables.column_profiler import profile_columns

        base = datetime(2026, 9, 1)
        rows: list[dict[str, Any]] = [{"打卡日期": base.replace(day=1 + i % 5)} for i in range(100)]
        profiles, _summary = profile_columns(rows, ["打卡日期"])
        assert profiles[0]["inferred_type"] == "date"
        assert "select_options" not in profiles[0]

    def test_xlsx_date_column_end_to_end(self, csv_workspace):
        """xlsx 端到端：日期/日期时间列建表为 date/datetime 字段，datetime 对象落库成功."""
        from openpyxl import Workbook

        engine, db, ws = csv_workspace
        wb = Workbook()
        sheet = wb.active
        sheet.append(["打卡日期", "操作时间", "姓名"])
        base = datetime(2026, 9, 1)
        for i in range(20):
            sheet.append(
                [
                    base + timedelta(days=i % 5),
                    datetime(2026, 9, 1, 8, i % 60, 0),
                    f"员工{i}",
                ]
            )
        buf = io.BytesIO()
        wb.save(buf)

        dt, ids, columns = transfer.create_table_from_file(
            engine, db, ws.id, "XLSX日期表", buf.getvalue(), filename="考勤.xlsx"
        )
        assert len(ids) == 20
        fmap = {f.name: f.field_type for f in dt.fields}
        assert fmap["打卡日期"] == "date"
        assert fmap["操作时间"] == "datetime"
        assert fmap["姓名"] == "text"

        from cndb.plugins.tables import records as rec

        row1 = rec.get_row(engine, dt, ids[0])
        assert row1["打卡日期"] == date(2026, 9, 1)
        assert row1["操作时间"] == datetime(2026, 9, 1, 8, 0, 0)

        # 列信息不含 select options，样本值为 ISO 格式
        date_col = next(c for c in columns if c["name"] == "打卡日期")
        assert "options" not in date_col
        assert date_col["sample_values"][0] == "2026-09-01"


__all__ = []
