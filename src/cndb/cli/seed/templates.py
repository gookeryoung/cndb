"""硬编码业务表种子（部门表 / 员工表）。

在"某企业销售管理"工作区下创建部门表与员工表，供演示关联字段与数据视图。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import MetaData


def _seed_sales_tables(db: Any, engine: Any, ws: Any, owner_id: int | None = None) -> tuple[int, dict[str, Any]]:
    """在"某企业销售管理"工作区下创建硬编码业务表（部门/员工）.

    Returns:
        (创建的数据表数量, 表名 -> DataTable 映射)
    """
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

    return 2, extra_tables
