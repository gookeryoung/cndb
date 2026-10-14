"""硬编码业务表（部门表 / 员工表）与报告模板种子。

员工名册模板与参数提为模块级常量，便于单元测试直接渲染。"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import MetaData

from cndb.cli.seed.samples import REPORT_TEMPLATE_SPECS

# ── 员工名册模板定义 ────────────────────────────────────
# 提取为常量便于单元测试直接渲染；参数化"在职状态"过滤名册范围（在职/离职/全部）。
# records 为员工表扁平 dict（姓名/部门/负责人/入职日期/薪资/是否在职，link/lookup 已展开为字符串）。
EMPLOYEE_ROSTER_PARAMETER: dict[str, Any] = {
    "name": "在职状态",
    "type": "string",
    "default": "在职",
    "required": False,
    "label": "名册范围（在职/离职/全部）",
    # 可选值列表：渲染参数弹窗据此渲染下拉菜单，渲染端点据此校验取值
    "options": ["在职", "离职", "全部"],
}

EMPLOYEE_ROSTER_TEMPLATE: str = (
    "# 员工名册\n"
    "\n"
    "{% set status = params.get('在职状态', '在职') %}\n"
    "{% if status == '离职' %}{% set shown = records | rejectattr('是否在职', 'equalto', '是') | list %}"
    "{% elif status == '全部' %}{% set shown = records %}"
    "{% else %}{% set shown = records | rejectattr('是否在职', 'equalto', '否') | list %}{% endif %}\n"
    "> 生成日期：{{ generated_at }} ｜ 统计范围：{{ status }}\n"
    "\n"
    "## 摘要\n"
    "\n"
    "本期名册共收录 {{ shown | length }} 人（统计范围：{{ status }}），覆盖 {{ group_stats(shown, '部门', '薪资') | length }} 个部门；其中在职 {{ shown | selectattr('是否在职', 'equalto', '是') | list | length }} 人、离职 {{ shown | rejectattr('是否在职', 'equalto', '是') | list | length }} 人，月度薪资总成本 {{ (stats(shown, '薪资').sum or 0) | int }} 元，人均月薪 {{ (stats(shown, '薪资').avg or 0) | round(0) | int }} 元。\n"
    "\n"
    "## 一、人员概览\n"
    "\n"
    "| 指标 | 数值 |\n"
    "| --- | --- |\n"
    "| 员工总数 | {{ shown | length }} |\n"
    "| 在职人数 | {{ shown | selectattr('是否在职', 'equalto', '是') | list | length }} |\n"
    "| 离职人数 | {{ shown | rejectattr('是否在职', 'equalto', '是') | list | length }} |\n"
    "| 覆盖部门数 | {{ group_stats(shown, '部门', '薪资') | length }} |\n"
    "| 平均薪资（元） | {{ (stats(shown, '薪资').avg or 0) | round(0) | int }} |\n"
    "| 薪资区间（元） | {{ (stats(shown, '薪资').min or 0) | int }} ~ {{ (stats(shown, '薪资').max or 0) | int }} |\n"
    "| 月度薪资总成本（元） | {{ (stats(shown, '薪资').sum or 0) | int }} |\n"
    "\n"
    "## 二、员工名册\n"
    "\n"
    "| 工号 | 姓名 | 职位 | 部门 | 部门负责人 | 入职日期 | 薪资（元） | 手机号 | 是否在职 |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
    "{% for r in shown %}"
    "| {{ r['工号'] }} | {{ r['姓名'] }} | {{ r['职位'] }} | {{ r['部门'] }} | {{ r['负责人'] }} "
    "| {{ r['入职日期'] }} | {{ r['薪资'] }} | {{ r['手机号'] }} | {{ r['是否在职'] }} |\n"
    "{% endfor %}"
    "\n"
    "部门与部门负责人由关联字段解析生成；薪资为月度口径，如需测算年度人力成本，请结合绩效与年终奖系数另行换算。\n"
    "\n"
    "## 三、按部门统计\n"
    "\n"
    "| 部门 | 人数 | 平均薪资（元） | 薪资合计（元） |\n"
    "| --- | --- | --- | --- |\n"
    "{% for g in group_stats(shown, '部门', '薪资') %}"
    "| {{ g.key }} | {{ g.count }} | {{ g.avg | round(0) | int }} | {{ g.sum | int }} |\n"
    "{% endfor %}"
    "\n"
    "部门人数与薪资水平反映组织的人才密度：人数多且平均薪资高的部门通常是核心交付力量，编制与预算可向其适度倾斜。\n"
    "\n"
    "## 四、按职位统计\n"
    "\n"
    "| 职位 | 人数 | 平均薪资（元） | 最高薪资（元） |\n"
    "| --- | --- | --- | --- |\n"
    "{% for g in group_stats(shown, '职位', '薪资') %}"
    "| {{ g.key }} | {{ g.count }} | {{ g.avg | round(0) | int }} | {{ g.max | int }} |\n"
    "{% endfor %}"
    "\n"
    "职位维度的薪资带宽可用于校准招聘定价：同职位内薪资差距过大时，建议结合绩效与司龄复核定薪合理性。\n"
    "\n"
    "## 五、离职人员名单\n"
    "\n"
    "{% set left = records | rejectattr('是否在职', 'equalto', '是') | list %}\n"
    "{% if left %}\n"
    "| 工号 | 姓名 | 部门 | 入职日期 | 手机号 |\n"
    "| --- | --- | --- | --- | --- |\n"
    "{% for r in left %}"
    "| {{ r['工号'] }} | {{ r['姓名'] }} | {{ r['部门'] }} | {{ r['入职日期'] }} | {{ r['手机号'] }} |\n"
    "{% endfor %}"
    "{% else %}\n"
    "无离职人员。\n"
    "{% endif %}\n"
    "\n"
    "## 结论与建议\n"
    "\n"
    "1. 编制管理：结合各部门人数与业务量复核编制合理性，人员缺口优先补充核心交付岗位。\n"
    "2. 薪酬校准：参照职位薪资带宽复核个别偏离样本，保持内部公平与外部竞争力。\n"
    "3. 口径说明：本名册统计范围由参数「在职状态」控制，离职人员名单固定按全量口径列示，供离职管理参考。\n"
    "\n"
    "---PAGE---\n"
    "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
)


def _seed_sales_tables(db: Any, engine: Any, ws: Any, owner_id: int | None = None) -> tuple[int, dict[str, Any]]:
    """在"某企业销售管理"工作区下创建硬编码业务表（部门/员工/报告）.

    Returns:
        (创建的数据表数量, 表名 -> DataTable 映射)
    """
    from cndb.plugins.reports.models import ReportTemplate
    from cndb.plugins.tables.models import DataField, DataTable
    from cndb.plugins.tables.services.core.ddl import create_table
    from cndb.plugins.tables.services.core.records import create_row

    extra_tables: dict[str, Any] = {}

    # 部门表（先建，员工表 link 字段要引用它）
    dept_tbl = DataTable(workspace_id=ws.id, owner_id=owner_id, name="部门表", description="公司部门", order=1)
    dept_tbl.ensure_db_name()
    db.add(dept_tbl)
    db.commit()
    db.refresh(dept_tbl)
    extra_tables["部门表"] = dept_tbl
    print(f"[seed] 创建数据表: 部门表 (id={dept_tbl.id})")

    dept_fields: list[tuple[str, str, dict[str, Any], bool]] = [
        ("部门名称", "text", {}, True),
        ("负责人", "text", {}, False),
    ]
    for idx, (fname, ftype, cfg, req) in enumerate(dept_fields):
        f = DataField(
            table_id=dept_tbl.id,
            name=fname,
            field_type=ftype,
            config=cfg,
            order=idx,
            required=req,
        )
        f.ensure_db_name()
        db.add(f)
    db.commit()
    create_table(engine, dept_tbl)
    for dname, head in [("技术部", "张三"), ("市场部", "李四"), ("人事部", "王五"), ("财务部", "赵六")]:
        create_row(engine, dept_tbl, values={"部门名称": dname, "负责人": head})
    print("[seed] 插入 4 条部门记录")

    # 员工表
    emp_tbl = DataTable(workspace_id=ws.id, owner_id=owner_id, name="员工表", description="公司员工信息", order=2)
    emp_tbl.ensure_db_name()
    db.add(emp_tbl)
    db.commit()
    db.refresh(emp_tbl)
    extra_tables["员工表"] = emp_tbl
    print(f"[seed] 创建数据表: 员工表 (id={emp_tbl.id})")

    field_specs: list[tuple[str, str, dict[str, Any], bool]] = [
        ("姓名", "text", {}, True),
        ("工号", "text", {}, True),
        # 部门为单选关联（multiple=False）：一名员工仅归属一个部门
        ("部门", "link", {"target_table_id": dept_tbl.id, "multiple": False}, False),
        ("职位", "select", {"options": ["总监", "经理", "工程师", "专员", "会计", "出纳"]}, False),
        ("入职日期", "date", {}, False),
        ("薪资", "number", {}, False),
        ("手机号", "phone", {}, False),
        ("邮箱", "email", {}, False),
        ("是否在职", "select", {"options": ["是", "否"]}, False),
    ]
    emp_fields: dict[str, DataField] = {}
    for idx, (fname, ftype, cfg, req) in enumerate(field_specs):
        f = DataField(
            table_id=emp_tbl.id,
            name=fname,
            field_type=ftype,
            config=cfg,
            order=idx,
            required=req,
        )
        f.ensure_db_name()
        db.add(f)
        emp_fields[fname] = f
    # flush 先拿到字段 id，再追加引用部门表「负责人」的 lookup 字段（经「部门」关联实时解析）
    db.flush()
    dept_head_field = next(f for f in dept_tbl.fields if f.name == "负责人")
    lookup_head = DataField(
        table_id=emp_tbl.id,
        name="负责人",
        field_type="lookup",
        config={
            "source_table_id": dept_tbl.id,
            "source_field_id": dept_head_field.id,
            "via_link_field_id": emp_fields["部门"].id,
            "source_field_type": dept_head_field.field_type,
        },
        order=len(field_specs),
        required=False,
    )
    lookup_head.ensure_db_name()
    db.add(lookup_head)
    db.commit()
    create_table(engine, emp_tbl)

    # 查部门行 id 供 link 字段使用
    dept_name_col = {f.name: f.db_column_name for f in dept_tbl.fields}["部门名称"]
    metadata = MetaData()
    metadata.reflect(bind=engine, only=[dept_tbl.db_table_name])
    dept_sa = metadata.tables[dept_tbl.db_table_name]
    with engine.connect() as _conn:
        dept_rows = {r[dept_name_col]: r.id for r in _conn.execute(dept_sa.select()).mappings()}

    samples = [
        {
            "工号": "E001",
            "姓名": "张三",
            "部门": [dept_rows["技术部"]],
            "职位": "总监",
            "入职日期": date(2023, 1, 15),
            "薪资": 15000,
            "手机号": "13800138001",
            "邮箱": "zhangsan@example.com",
            "是否在职": "是",
        },
        {
            "工号": "E002",
            "姓名": "李四",
            "部门": [dept_rows["市场部"]],
            "职位": "总监",
            "入职日期": date(2022, 6, 1),
            "薪资": 12000,
            "手机号": "13800138002",
            "邮箱": "lisi@example.com",
            "是否在职": "是",
        },
        {
            "工号": "E003",
            "姓名": "王五",
            "部门": [dept_rows["人事部"]],
            "职位": "经理",
            "入职日期": date(2024, 3, 20),
            "薪资": 10000,
            "手机号": "13800138003",
            "邮箱": "wangwu@example.com",
            "是否在职": "是",
        },
        {
            "工号": "E004",
            "姓名": "赵六",
            "部门": [dept_rows["财务部"]],
            "职位": "经理",
            "入职日期": date(2021, 11, 10),
            "薪资": 13000,
            "手机号": "13800138004",
            "邮箱": "zhaoliu@example.com",
            "是否在职": "否",
        },
        {
            "工号": "E005",
            "姓名": "钱七",
            "部门": [dept_rows["技术部"]],
            "职位": "工程师",
            "入职日期": date(2023, 8, 5),
            "薪资": 18000,
            "手机号": "13900139005",
            "邮箱": "qianqi@example.com",
            "是否在职": "是",
        },
        {
            "工号": "E006",
            "姓名": "孙八",
            "部门": [dept_rows["技术部"]],
            "职位": "工程师",
            "入职日期": date(2024, 2, 14),
            "薪资": 16000,
            "手机号": "13900139006",
            "邮箱": "sunba@example.com",
            "是否在职": "是",
        },
        {
            "工号": "E007",
            "姓名": "周九",
            "部门": [dept_rows["技术部"]],
            "职位": "工程师",
            "入职日期": date(2023, 12, 1),
            "薪资": 14000,
            "手机号": "13900139007",
            "邮箱": "zhoujiu@example.com",
            "是否在职": "是",
        },
        {
            "工号": "E008",
            "姓名": "吴十",
            "部门": [dept_rows["市场部"]],
            "职位": "专员",
            "入职日期": date(2024, 7, 1),
            "薪资": 9000,
            "手机号": "13900139008",
            "邮箱": "wushi@example.com",
            "是否在职": "是",
        },
        {
            "工号": "E009",
            "姓名": "郑一",
            "部门": [dept_rows["市场部"]],
            "职位": "经理",
            "入职日期": date(2022, 9, 15),
            "薪资": 13000,
            "手机号": "13900139009",
            "邮箱": "zhengyi@example.com",
            "是否在职": "否",
        },
        {
            "工号": "E010",
            "姓名": "冯二",
            "部门": [dept_rows["人事部"]],
            "职位": "专员",
            "入职日期": date(2025, 4, 1),
            "薪资": 8000,
            "手机号": "13900139010",
            "邮箱": "fenger@example.com",
            "是否在职": "是",
        },
        {
            "工号": "E011",
            "姓名": "陈三",
            "部门": [dept_rows["财务部"]],
            "职位": "会计",
            "入职日期": date(2023, 5, 20),
            "薪资": 11000,
            "手机号": "13900139011",
            "邮箱": "chensan@example.com",
            "是否在职": "是",
        },
        {
            "工号": "E012",
            "姓名": "褚四",
            "部门": [dept_rows["财务部"]],
            "职位": "出纳",
            "入职日期": date(2024, 10, 8),
            "薪资": 9500,
            "手机号": "13900139012",
            "邮箱": "chusi@example.com",
            "是否在职": "否",
        },
    ]
    for data in samples:
        create_row(engine, emp_tbl, values=data, db=db)
    print(f"[seed] 插入 {len(samples)} 条员工记录")

    # 报告模板（绑定员工表）：内容提取为模块级常量，pdf + business 主题 + 在职状态参数
    tpl = ReportTemplate(
        name="员工名册",
        description="按在职状态筛选并列出员工名册，含人员概览、按部门统计与离职名单",
        table_id=emp_tbl.id,
        workspace_id=emp_tbl.workspace_id,
        output_format="pdf",
        theme="business",
        template_content=EMPLOYEE_ROSTER_TEMPLATE,
        parameters=[dict(EMPLOYEE_ROSTER_PARAMETER)],
    )
    db.add(tpl)
    db.commit()
    print(f"[seed] 创建报告模板: 员工名册 (table_id={emp_tbl.id})")

    return 2, extra_tables


def _seed_report_templates(db: Any, tables_map: dict[str, dict[str, Any]]) -> None:
    """幂等创建报告模板：按工作区+模板名查重，已存在跳过.

    模板定义统一收敛到 REPORT_TEMPLATE_SPECS（数据驱动），
    内容使用 Jinja2 SandboxedEnvironment 安全子集，
    结合 stats / group_stats 统计函数与 generated_at 日期标签。
    """
    from cndb.plugins.reports.models import ReportTemplate

    for spec in REPORT_TEMPLATE_SPECS:
        ws_tables = tables_map.get(spec["workspace"])
        if not ws_tables:
            print(f"[seed-模板] 跳过：工作区 '{spec['workspace']}' 不存在（{spec['name']}）")
            continue
        main_tbl = ws_tables.get(spec["table"])
        if main_tbl is None:
            print(f"[seed-模板] 跳过：{spec['workspace']} 缺少主表 '{spec['table']}'（{spec['name']}）")
            continue
        existing = (
            db.query(ReportTemplate)
            .filter(
                ReportTemplate.table_id == main_tbl.id,
                ReportTemplate.name == spec["name"],
            )
            .first()
        )
        if existing:
            print(f"[seed-模板] 已存在: {spec['name']} (id={existing.id})")
            continue
        extra_tbls = [ws_tables.get(extra_name) for extra_name in spec["extra_tables"]]
        # 跨工作区引用：从 tables_map 全局解析（工作区名, 表名）
        cross_tables = [
            tables_map.get(ws_name, {}).get(tbl_name) for ws_name, tbl_name in spec.get("cross_workspace_tables", [])
        ]
        extra_tbls.extend(t for t in cross_tables if t is not None)
        tpl = ReportTemplate(
            name=spec["name"],
            description=spec["description"],
            table_id=main_tbl.id,
            workspace_id=main_tbl.workspace_id,
            output_format=spec.get("output_format", "docx"),
            theme=spec.get("theme", "minimal"),
            template_content=spec["content"],
            parameters=[dict(p) for p in spec.get("parameters", [])],
            extra_table_ids=[t.id for t in extra_tbls if t is not None],
        )
        db.add(tpl)
        db.commit()
        db.refresh(tpl)
        print(f"[seed-模板] 创建: {spec['name']} (id={tpl.id}, extra={tpl.extra_table_ids})")
