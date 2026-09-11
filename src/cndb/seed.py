"""演示数据注入 — 幂等，重复执行不会重复造数据."""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any

from sqlalchemy import MetaData


def seed(_args: argparse.Namespace) -> None:
    """向数据库注入演示数据."""
    from cndb.core.database import SessionLocal, engine
    from cndb.models.base import Base
    from cndb.plugins.accounts.models import User
    from cndb.plugins.reports.models import ReportTemplate
    from cndb.plugins.tables.ddl import create_table
    from cndb.plugins.tables.models import DataField, DataTable
    from cndb.plugins.tables.records import create_row
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember

    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        # 用户
        user = db.query(User).filter_by(username="demo").first()
        if not user:
            user = User(username="demo", email="demo@cndb.local", nickname="演示账号")
            user.set_password("demo1234")
            db.add(user)
            db.commit()
            db.refresh(user)
            print("[seed] 创建用户: demo / demo1234")

        # 工作区
        ws = db.query(Workspace).filter_by(name="演示工作区").first()
        if not ws:
            ws = Workspace(name="演示工作区", description="用于体验 cndb 功能的示例工作区")
            db.add(ws)
            db.commit()
            db.refresh(ws)
            member = WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner")
            db.add(member)
            db.commit()
            wid = ws.id
            print(f"[seed] 创建工作区: {ws.name} (id={wid})")

        # 部门表（先建，员工表 link 字段要引用它）
        dept_tbl = db.query(DataTable).filter_by(workspace_id=ws.id, name="部门表").first()
        if not dept_tbl:
            dept_tbl = DataTable(workspace_id=ws.id, name="部门表", description="公司部门", order=1)
            dept_tbl.ensure_db_name()
            db.add(dept_tbl)
            db.commit()
            db.refresh(dept_tbl)
            did = dept_tbl.id
            print(f"[seed] 创建数据表: 部门表 (id={did})")

            dept_fields: list[tuple[str, str, dict[str, Any], bool]] = [
                ("部门名称", "text", {}, True),
                ("负责人", "text", {}, False),
            ]
            for idx, (fname, ftype, cfg, req) in enumerate(dept_fields):
                f = DataField(
                    table_id=dept_tbl.id, name=fname, field_type=ftype,
                    config=cfg, order=idx, required=req,
                )
                f.ensure_db_name()
                db.add(f)
            db.commit()
            create_table(engine, dept_tbl)
            for dname, head in [("技术部", "张三"), ("市场部", "李四"), ("人事部", "王五"), ("财务部", "赵六")]:
                create_row(engine, dept_tbl, values={"部门名称": dname, "负责人": head})
            print("[seed] 插入 4 条部门记录")

        # 员工表
        emp_tbl = db.query(DataTable).filter_by(workspace_id=ws.id, name="员工表").first()
        if not emp_tbl:
            emp_tbl = DataTable(workspace_id=ws.id, name="员工表", description="公司员工信息", order=2)
            emp_tbl.ensure_db_name()
            db.add(emp_tbl)
            db.commit()
            db.refresh(emp_tbl)
            eid = emp_tbl.id
            print(f"[seed] 创建数据表: 员工表 (id={eid})")

            field_specs: list[tuple[str, str, dict[str, Any], bool]] = [
                ("姓名", "text", {}, True),
                ("部门", "link", {"target_table_id": dept_tbl.id}, False),
                ("入职日期", "date", {}, False),
                ("薪资", "number", {}, False),
                ("是否在职", "select", {"options": ["是", "否"]}, False),
            ]
            for idx, (fname, ftype, cfg, req) in enumerate(field_specs):
                f = DataField(
                    table_id=emp_tbl.id, name=fname, field_type=ftype,
                    config=cfg, order=idx, required=req,
                )
                f.ensure_db_name()
                db.add(f)
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
                {"姓名": "张三", "部门": dept_rows["技术部"], "入职日期": date(2023, 1, 15), "薪资": 15000, "是否在职": "是"},
                {"姓名": "李四", "部门": dept_rows["市场部"], "入职日期": date(2022, 6, 1), "薪资": 12000, "是否在职": "是"},
                {"姓名": "王五", "部门": dept_rows["人事部"], "入职日期": date(2024, 3, 20), "薪资": 10000, "是否在职": "是"},
                {"姓名": "赵六", "部门": dept_rows["财务部"], "入职日期": date(2021, 11, 10), "薪资": 13000, "是否在职": "否"},
                {"姓名": "钱七", "部门": dept_rows["技术部"], "入职日期": date(2023, 8, 5), "薪资": 18000, "是否在职": "是"},
            ]
            for data in samples:
                create_row(engine, emp_tbl, values=data)
            print("[seed] 插入 5 条员工记录")

        # 报告模板（绑定员工表 — B2 table_id）
        tpl = db.query(ReportTemplate).filter_by(name="员工名册").first()
        if not tpl:
            tpl = ReportTemplate(
                name="员工名册", description="列出所有在职员工的基本信息",
                table_id=emp_tbl.id, output_format="docx",
                template_content="# {{ table_name }}", parameters=[],
            )
            db.add(tpl)
            db.commit()
            eid2 = emp_tbl.id
            print(f"[seed] 创建报告模板: 员工名册 (table_id={eid2})")

        print("[seed] 完成！运行 uv run cndb serve 启动服务后用 demo / demo1234 登录")
    finally:
        db.close()
