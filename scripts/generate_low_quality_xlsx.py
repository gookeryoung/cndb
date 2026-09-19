"""为 examples/datasets/工作区-低质量数据/ 生成典型低质量 xlsx 示例.

每个文件聚焦一类（或一组相关）数据质量问题，便于前端/后端的
导入校验、清洗建议、Diff Reporter 等模块做端到端测试。
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

OUT = Path("examples/datasets/工作区-低质量数据")
OUT.mkdir(parents=True, exist_ok=True)


# ── 工具 ────────────────────────────────────────


def _write(ws, headers, rows, *, start_row=1, header_fill=None):
    """在 ws 指定行写表头 + 数据；表头可加背景色."""
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=c, value=h)
        if header_fill is not None:
            cell.fill = header_fill
            cell.font = Font(bold=True)
    for r, row in enumerate(rows, start=start_row + 1):
        for c, val in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=val)
    # 自动列宽（粗略估算；允许各行长度不一）
    for c, h in enumerate(headers, start=1):
        col_vals = [str(h)]
        for row in rows:
            if c - 1 < len(row) and row[c - 1] is not None:
                col_vals.append(str(row[c - 1]))
        max_len = max((len(v) for v in col_vals), default=len(str(h)))
        ws.column_dimensions[get_column_letter(c)].width = max(min(max_len + 2, 40), 8)


def _freeze(ws):
    ws.freeze_panes = "A2"


# ── 1. 类型混合列 (mixed_types) ────────────────


def build_mixed_types():
    """同一数值列混入文本、同一日期列混入布尔和文本。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "员工工资"
    headers = ["工号", "姓名", "月薪", "入职日期", "是否转正"]
    rows = [
        ["E001", "张三", 8000, "2021-03-15", "是"],
        ["E002", "李四", "面议", "2022/07/01", "Y"],
        ["E003", "王五", 9500.5, "2023-01-20", 1],
        ["E004", "赵六", "12,000", "1月1日", "true"],
        ["E005", "钱七", 0, "not a date", "否"],
        ["E006", "孙八", -500, 45365, None],  # Excel 日期序列号
        ["E007", "周九", "8k", "2024-06-30", "No"],
        ["E008", "吴十", None, "2022-12-31", "√"],
    ]
    _write(ws, headers, rows)
    _freeze(ws)
    wb.save(OUT / "01-类型混合列-员工工资.xlsx")


# ── 2. 畸形数字 (malformed_numbers) ─────────────


def build_malformed_numbers():
    """数字列含千分位、货币符号、科学计数、汉字数字、非法串."""
    wb = Workbook()
    ws = wb.active
    ws.title = "订单金额"
    headers = ["订单号", "商品", "单价", "数量", "总价", "折扣率"]
    rows = [
        ["SO-1001", "键盘", 399, 2, 798, 0.9],
        ["SO-1002", "鼠标", "￥159", "3件", "477.00", "10%"],
        ["SO-1003", "显示器", "1,299.00", "四", "无效", "未知"],
        ["SO-1004", "耳机", 2.5e2, 1, "250元", "NONE"],
        ["SO-1005", "硬盘", "--", "N/A", "无", ""],
        ["SO-1006", "U盘", "叁佰贰拾", 5, 1600, "off"],
        ["SO-1007", "主板", -999, 1, 999, "0.15"],
        ["SO-1008", "风扇", 49.99, 10, 499.9, "五折"],
    ]
    _write(ws, headers, rows)
    _freeze(ws)
    wb.save(OUT / "02-畸形数字-订单金额.xlsx")


# ── 3. 日期混乱 (mixed_dates) ───────────────────


def build_mixed_dates():
    """同一日期列混用 ISO、斜杠、中文、Excel 序列号、非法值."""
    from datetime import date

    wb = Workbook()
    ws = wb.active
    ws.title = "活动日程"
    headers = ["活动", "开始日期", "结束日期", "报名截止"]
    rows = [
        ["春季发布会", "2024-03-15", "2024-03-17", "2024-03-10"],
        ["产品培训", "2024/04/05", "4/7/2024", "4-1-24"],
        ["客户拜访", "2024年5月20日", "5月22日", "5.18"],
        ["内部评审", date(2024, 6, 10), 45431, None],  # Excel 原生日期 / 序列号
        ["市场活动", "2024-13-45", "not-a-date", "abc"],  # 非法
        ["年度会议", "", "2024-12-31", "永 不"],
        ["临时加班", "2024-02-30", "2024-04-31", "2/29/2024"],  # 不存在日期
    ]
    _write(ws, headers, rows)
    _freeze(ws)
    wb.save(OUT / "03-日期混乱-活动日程.xlsx")


# ── 4. 高空值率 (high_null_ratio) ───────────────


def build_high_null_ratio():
    """员工表：联系方式 95% 空、身份证 80% 空、部门正常."""
    wb = Workbook()
    ws = wb.active
    ws.title = "员工档案"
    headers = ["工号", "姓名", "部门", "手机号", "身份证号", "紧急联系人", "备注"]
    # 18 行，前两列和部门完整，其余大部分为空
    rows = []
    depts = ["研发", "销售", "市场", "财务"]
    for i in range(18):
        emp_id = f"E{i + 1:03d}"
        name = f"员工{i + 1}"
        dept = depts[i % 4]
        # 手机号仅 2 个有值（2/18≈11%）
        phone = None if i > 1 else f"1380000000{i}"
        # 身份证仅 3 个有值
        idcard = None if i > 2 else f"11010119900101123{i}"
        # 紧急联系人仅 1 个
        contact = "张三" if i == 0 else None
        # 备注 17/18 空
        note = "试用期" if i == 3 else None
        rows.append([emp_id, name, dept, phone, idcard, contact, note])
    _write(ws, headers, rows)
    _freeze(ws)
    wb.save(OUT / "04-高空值率-员工档案.xlsx")


# ── 5. 重复行 (duplicate_rows) ──────────────────


def build_duplicate_rows():
    """包含完全重复 + 部分列重复（疑似重复）+ 真实差异行."""
    wb = Workbook()
    ws = wb.active
    ws.title = "销售记录"
    headers = ["日期", "销售员", "客户", "产品", "金额"]
    rows = [
        ["2024-06-01", "张三", "A公司", "键盘", 798],
        ["2024-06-01", "张三", "A公司", "键盘", 798],  # 完全重复
        ["2024-06-01", "张三", "A公司", "键盘", 798],  # 完全重复（三连）
        ["2024-06-02", "李四", "B公司", "鼠标", 450],
        ["2024-06-02", "李四", "B公司", "鼠标", 450],  # 完全重复
        ["2024-06-03", "王五", "C公司", "显示器", 2598],
        ["2024-06-03", "王五", "C公司", "显示器", 2599],  # 仅金额差 1（疑似录错）
        ["2024-06-04", "张三", "A公司", "耳机", 598],  # 与第一行是同一天同客户不同产品
        ["2024-06-04", "张三", "A公司", "耳机", 598],  # 完全重复
        ["2024-06-05", "赵六", "D公司", "主板", 1299],
    ]
    _write(ws, headers, rows)
    _freeze(ws)
    wb.save(OUT / "05-重复行-销售记录.xlsx")


# ── 6. 极端异常值 (extreme_outliers) ────────────


def build_extreme_outliers():
    """数值列中混入若干离谱值（天文数字、负价格、零、NaN、字符串）."""
    import math

    wb = Workbook()
    ws = wb.active
    ws.title = "商品库存"
    headers = ["SKU", "商品", "单价", "库存", "月销量", "评分"]
    rows = [
        ["SKU-001", "键盘", 399, 120, 45, 4.7],
        ["SKU-002", "鼠标", 159, 300, 180, 4.5],
        ["SKU-003", "显示器", 1299, 45, 12, 4.8],
        ["SKU-004", "耳机", 599, 80, 33, 4.6],
        ["SKU-005", "硬盘", 499, 200, 78, 4.4],
        ["SKU-006", "天价主板", 99999999.99, 1, 0, 5.0],  # 极端单价
        ["SKU-007", "负价清仓", -999, 50, 10, 4.0],  # 负单价
        ["SKU-008", "幽灵库存", 399, 99999999, 200, 3.9],  # 极端库存
        ["SKU-009", "滞销王", 299, 0, 0, 0.0],  # 零库存零销量
        ["SKU-010", "评分爆炸", 199, 10, 5, 99.0],  # 评分 0~5 范围外
        ["SKU-011", "评分缺失", 299, 10, 5, None],
        ["SKU-012", "NaN 价格", math.nan, 10, 5, 4.2],  # NaN —— Excel 会写成 #NUM!
    ]
    _write(ws, headers, rows)
    _freeze(ws)
    wb.save(OUT / "06-极端异常值-商品库存.xlsx")


# ── 7. 布尔值混乱 (inconsistent_booleans) ───────


def build_inconsistent_booleans():
    """同一布尔列混入是/否/true/false/1/0/√/×/Y/N/空."""
    wb = Workbook()
    ws = wb.active
    ws.title = "项目开关"
    headers = ["项目", "已启动", "已验收", "是否紧急", "是否付费"]
    rows = [
        ["P-001", "是", "否", "true", 1],
        ["P-002", "Y", "N", "TRUE", 0],
        ["P-003", "√", "×", "True", "Yes"],
        ["P-004", "1", "0", "False", "No"],
        ["P-005", "true", "false", "", "ON"],
        ["P-006", "YES", "NO", "off", "已付款"],
        ["P-007", None, "是", "紧急", ""],
        ["P-008", False, True, "1", "0"],  # Excel 原生布尔
    ]
    _write(ws, headers, rows)
    _freeze(ws)
    wb.save(OUT / "07-布尔值混乱-项目开关.xlsx")


# ── 8. 表头上方说明行 (header_offset) ───────────


def build_header_offset():
    """前两行是说明和空行，真正表头在第 3 行。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "销售月报"
    ws["A1"] = "数据来源：ERP 系统导出 | 导出时间：2024-07-02"
    ws.merge_cells("A1:F1")
    ws["A2"] = "注：金额单位为人民币元"
    ws.merge_cells("A2:F2")
    header_fill = PatternFill("solid", fgColor="DDDDDD")
    headers = ["月份", "区域", "销售员", "订单数", "销售金额", "同比"]
    rows = [
        ["2024-06", "华东", "张三", 45, 128900, "12.5%"],
        ["2024-06", "华南", "李四", 38, 98760, "-3.2%"],
        ["2024-06", "华北", "王五", 52, 156200, "8.9%"],
        ["2024-06", "西南", "赵六", 29, 67800, "-15.0%"],
    ]
    _write(ws, headers, rows, start_row=3, header_fill=header_fill)
    # 合并标题样式
    ws["A1"].font = Font(bold=True, italic=True)
    ws["A2"].font = Font(italic=True, color="666666")
    ws.freeze_panes = "A3"
    wb.save(OUT / "08-表头偏移-销售月报.xlsx")


# ── 9. 含公式和 #REF! (formula_errors) ─────────


def build_formula_errors():
    """公式残留、#REF!、#N/A、#DIV/0!、空公式."""
    wb = Workbook()
    ws = wb.active
    ws.title = "月度报表"
    headers = ["项目", "预算", "实际支出", "结余", "备注"]
    rows = [
        ["A 项目", 100000, 85000, None, "正常"],
        ["B 项目", 50000, 52000, None, "超支"],
        ["C 项目", 80000, 80000, None, "持平"],
        ["D 项目", 120000, 0, None, "刚启动"],
        ["E 项目", "", 0, None, "预算未填"],
    ]
    _write(ws, headers, rows)
    # 写入公式（openpyxl 存公式字符串，Excel 打开后计算）
    for r in range(2, 7):
        ws[f"D{r}"] = f"=B{r}-C{r}"
    # 错误公式
    ws["D6"] = "=1/0"  # Excel 中会显示 #DIV/0!
    ws["C6"] = "#N/A"  # 直接写字符串
    ws["E6"] = "#REF!"
    ws.freeze_panes = "A2"
    wb.save(OUT / "09-公式错误-月度报表.xlsx")


# ── 10. 合并单元格 + 漏填 (merged_cells_gap) ───


def build_merged_cells_gap():
    """第一列合并单元格后未逐行填充，致下方行看起来是空值."""
    wb = Workbook()
    ws = wb.active
    ws.title = "部门预算"
    headers = ["部门", "团队", "季度", "预算"]
    raw = [
        ["研发部", "前端组", "Q1", 500000],
        [None, "后端组", "Q1", 450000],
        [None, "测试组", "Q1", 200000],
        ["销售部", "华东区", "Q1", 600000],
        [None, "华南区", "Q1", 420000],
        [None, "华北区", "Q1", 380000],
        ["市场部", "品牌组", "Q1", 300000],
        [None, "渠道组", "Q1", 250000],
    ]
    _write(ws, headers, raw)
    # 模拟 Excel 合并单元格后的数据空洞（真实合并后，只左上格有值）
    ws.merge_cells("A2:A4")
    ws.merge_cells("A5:A7")
    ws.merge_cells("A8:A9")
    ws.freeze_panes = "A2"
    wb.save(OUT / "10-合并单元格空洞-部门预算.xlsx")


# ── 11. 列数不一致 (ragged_rows) ───────────────


def build_ragged_rows():
    """某些行列数比表头多或少."""
    wb = Workbook()
    ws = wb.active
    ws.title = "会议记录"
    headers = ["日期", "会议名", "主持", "参与人", "决议", "待办"]
    rows = [
        ["2024-06-01", "周会", "张三", "李四,王五", "正常推进", "报告更新"],
        ["2024-06-02", "项目评审", "李四", "全员", "通过"],  # 少一列
        ["2024-06-03", "头脑风暴", "王五"],  # 少四列
        ["2024-06-04", "客户沟通", "赵六", "A公司, B公司", "续约意向", "下周三回访", "备注多余"],  # 多一列
        ["2024-06-05", "复盘会", "张三", "全员", "OK", None, None, "超超"],  # 多两列
        ["2024-06-06", "1:1", "张三", "孙八"],  # 缺决议、待办
    ]
    _write(ws, headers, rows)
    ws.freeze_panes = "A2"
    wb.save(OUT / "11-列数不齐-会议记录.xlsx")


# ── 12. 特殊字符污染 (special_chars) ────────────


def build_special_chars():
    """含换行、制表符、零宽字符、前后空格、不可见字符的文本列."""
    wb = Workbook()
    ws = wb.active
    ws.title = "用户反馈"
    headers = ["ID", "用户名", "评论", "标签"]
    rows = [
        [1, " 小明 ", "这个产品\n非常好用！", " 界面\tUI"],
        [2, "小红\u200b", "bug 不少\u200c", "功能\u200d问题"],  # 零宽字符
        [3, "  小刚  ", "还行吧，\r\n就是价格偏贵。", ""],
        [4, "小丽", "\t\t\n\n", "空"],
        [5, "\u3000老王", "全角空格开头", "体验\u00a0优化"],  # 全角空格、不换行空格
        [6, "小明", "重复的小明", "   "],
    ]
    _write(ws, headers, rows)
    ws.freeze_panes = "A2"
    wb.save(OUT / "12-特殊字符污染-用户反馈.xlsx")


# ── 13. 跨表 link 字段混乱 (malformed_links) ───


def build_malformed_links():
    """link 字段应是分号分隔的整数 id，但混入多种写法."""
    wb = Workbook()
    ws = wb.active
    ws.title = "任务分配"
    headers = ["任务", "负责人ID", "协作人IDs", "依赖IDs"]
    rows = [
        ["T-001", 5, "1;2;3", "10"],
        ["T-002", "6", "4,5,6", "11;12"],  # 逗号分隔（应能被兼容）
        ["T-003", "7", "a;b;c", "abc"],  # 非数字
        ["T-004", None, "", None],  # 空
        ["T-005", "八", "1; 2 ; 3", "1.5"],  # 中文数字、带空格、小数
        ["T-006", 9, ";1;;2;", "100"],  # 分号多余
        ["T-007", 10, "[11, 12]", "20"],  # 看起来像 list 但实际是字符串
    ]
    _write(ws, headers, rows)
    ws.freeze_panes = "A2"
    wb.save(OUT / "13-Link字段混乱-任务分配.xlsx")


# ── 14. 必填字段空值 (required_empty) ───────────


def build_required_empty():
    """姓名/手机号/身份证等必填字段批量为空或 '未知'/'N/A'."""
    wb = Workbook()
    ws = wb.active
    ws.title = "客户登记"
    headers = ["客户名", "手机号", "身份证号", "公司", "邮箱"]
    rows = [
        ["华为技术", "13800000001", "110101199001011234", "华为", "a@b.com"],
        ["", "13800000002", "", "", ""],
        ["未知", "N/A", "未知", "未知", "未知"],
        ["张三", "", "", "", ""],
        ["李四", "13800000004", "not_an_id", "XX公司", "bad-email"],
        ["王五", "13800000005", "110101199001011235", "", ""],
        ["N/A", "N/A", "N/A", "N/A", "N/A"],
        ["赵六", "13800000006", "110101199001011236", "YY公司", "z@y.com"],
    ]
    _write(ws, headers, rows)
    ws.freeze_panes = "A2"
    wb.save(OUT / "14-必填字段空值-客户登记.xlsx")


# ── 15. 列名不统一 + 多工作表 (multi_sheet_mess)


def build_multi_sheet_mess():
    """一个工作簿内多个 sheet，列名风格不同（同字段不同名）."""
    wb = Workbook()

    # Sheet 1：风格 A（中文 + 下划线）
    ws1 = wb.active
    ws1.title = "华东区"
    _write(
        ws1,
        ["订单编号", "客户名称", "产品名称", "销售金额", "下单日期"],
        [
            ["SO-1", "A公司", "键盘", 798, "2024-06-01"],
            ["SO-2", "B公司", "鼠标", 450, "2024-06-02"],
        ],
    )
    ws1.freeze_panes = "A2"

    # Sheet 2：风格 B（英文 + 驼峰）
    ws2 = wb.create_sheet("华南区")
    _write(
        ws2,
        ["orderId", "customer", "product", "amount", "orderDate"],
        [
            ["SO-3", "C Corp", "Display", 2599, "2024/06/03"],
            ["SO-4", "D Ltd", "Earphone", 598, "2024/06/04"],
        ],
    )
    ws2.freeze_panes = "A2"

    # Sheet 3：风格 C（中文 + 全角 + 空格）
    ws3 = wb.create_sheet("华北区")
    _write(
        ws3,
        ["订单 号", "客戶名稱", "商品", "金　額", "日期"],  # 混空格、全角
        [
            ["SO-5", "E 株式会社", "主機板", 1299, "2024年6月5日"],
            ["SO-6", "F 公司", "硬碟", 499, "2024年6月6日"],
        ],
    )
    ws3.freeze_panes = "A2"

    wb.save(OUT / "15-多Sheet列名不统一.xlsx")


# ── 主入口 ──────────────────────────────────────


def main():
    builders = [
        build_mixed_types,
        build_malformed_numbers,
        build_mixed_dates,
        build_high_null_ratio,
        build_duplicate_rows,
        build_extreme_outliers,
        build_inconsistent_booleans,
        build_header_offset,
        build_formula_errors,
        build_merged_cells_gap,
        build_ragged_rows,
        build_special_chars,
        build_malformed_links,
        build_required_empty,
        build_multi_sheet_mess,
    ]
    for b in builders:
        b()
        print(f"已生成: {b.__name__}")
    files = sorted(p.name for p in OUT.glob("*.xlsx"))
    print(f"\n共生成 {len(files)} 个 xlsx：")
    for f in files:
        print(f"  - {f}")


if __name__ == "__main__":
    main()
