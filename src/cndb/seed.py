"""演示数据注入."""

from __future__ import annotations

import argparse


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
        user = db.query(User).filter_by(username="demo").first()
        if not user:
            user = User(username="demo", email="demo@cndb.local", nickname="演示账号")
            user.set_password("demo1234")
            db.add(user)
            db.commit()
            db.refresh(user)
            print("[seed] 创建用户: demo / demo1234")

        ws = db.query(Workspace).filter_by(name="演示工作区").first()
        if not ws:
            ws = Workspace(name="演示工作区", description="用于体验 cndb 功能的示例工作区")
            db.add(ws)
            db.commit()
            db.refresh(ws)
            member = WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner")
            db.add(member)
            db.commit()
            print(f"[seed] 创建工作区: {ws.name} (id={ws.id})")

        table = db.query(DataTable).filter_by(workspace_id=ws.id, name="员工表").first()
        if not table:
            table = DataTable(workspace_id=ws.id, name="员工表", description="公司员工信息", order=1)
            table.ensure_db_name()
            db.add(table)
            db.commit()
            db.refresh(table)
            print(f"[seed] 创建数据表: 员工表 (id={table.id}, db={table.db_table_name})")

            fields = [
                ("姓名", "text"),
                ("部门", "select"),
                ("入职日期", "date"),
                ("薪资", "number"),
                ("是否在职", "select"),
            ]
            for idx, (fname, ftype) in enumerate(fields):
                field = DataField(
                    table_id=table.id,
                    name=fname,
                    field_type=ftype,
                    config={} if ftype != "select" else {"options": ["技术部", "市场部", "人事部", "财务部"]},
                    order=idx,
                    required=(fname == "姓名"),
                )
                field.ensure_db_name()
                db.add(field)
            db.commit()

            create_table(engine, table)

            samples = [
                {"姓名": "张三", "部门": "技术部", "入职日期": "2023-01-15", "薪资": 15000, "是否在职": "是"},
                {"姓名": "李四", "部门": "市场部", "入职日期": "2022-06-01", "薪资": 12000, "是否在职": "是"},
                {"姓名": "王五", "部门": "人事部", "入职日期": "2024-03-20", "薪资": 10000, "是否在职": "是"},
                {"姓名": "赵六", "部门": "财务部", "入职日期": "2021-11-10", "薪资": 13000, "是否在职": "否"},
                {"姓名": "钱七", "部门": "技术部", "入职日期": "2023-08-05", "薪资": 18000, "是否在职": "是"},
            ]
            for data in samples:
                create_row(engine, table, values=data)
            print(f"[seed] 插入 {len(samples)} 条员工记录")

        tpl = db.query(ReportTemplate).filter_by(name="员工名册").first()
        if not tpl:
            tpl = ReportTemplate(
                name="员工名册",
                description="列出所有在职员工的基本信息",
                output_format="docx",
                template_content="# {{ table_name }}",
                parameters=[],
            )
            db.add(tpl)
            db.commit()
            print("[seed] 创建报告模板: 员工名册")

        print("[seed] 完成！可运行 cndb serve 启动服务后用 demo / demo1234 登录体验")
    finally:
        db.close()
