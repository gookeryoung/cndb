"""演示数据注入 — 幂等（drop_all 后重建，每次全新）.

数据源：
1. examples/datasets/<工作区名>/*.csv — 按文件夹名自动建工作区，CSV 自动推断字段建表导入
2. 硬编码业务表 — 部门表 + 员工表 + 报告模板 + 工作流，绑定到 datasets 创建的
   "某企业销售管理"工作区，与 CSV 数据共同构成完整销售场景
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData


def _get_datasets_dir() -> Path | None:
    """定位 examples/datasets 目录（优先源码仓库，找不到则返回 None 优雅降级）."""
    src_root = Path(__file__).resolve().parent.parent.parent
    candidate = src_root / "examples" / "datasets"
    if candidate.is_dir():
        return candidate
    return None


def _seed_datasets(db: Any, engine: Any, user: Any) -> tuple[int, dict[str, Any]]:
    """扫描 datasets 目录，按子文件夹建工作区、按 CSV 建表导入.

    Returns:
        (成功创建的数据表总数, 工作区名 -> Workspace 对象的映射)
    """
    from cndb.plugins.tables.transfer import create_table_from_csv
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember

    datasets_dir = _get_datasets_dir()
    if datasets_dir is None:
        print("[seed] examples/datasets 目录不存在，跳过 CSV 注入（wheel 安装版无此目录属正常）")
        return 0, {}

    table_count = 0
    ws_map: dict[str, Any] = {}
    for folder in sorted(datasets_dir.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        csv_files = sorted(folder.glob("*.csv"))
        if not csv_files:
            continue

        # 工作区名去掉 "工作区-" 前缀让显示更友好，同时保留原名做 key
        ws_name = folder.name
        if ws_name.startswith("工作区-"):
            ws_display = ws_name[len("工作区-") :]
        else:
            ws_display = ws_name

        ws = Workspace(name=ws_display, description=f"示例数据：{ws_display}")
        db.add(ws)
        db.commit()
        db.refresh(ws)
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
        db.commit()
        ws_map[ws_display] = ws
        print(f"[seed-CSV] 创建工作区: {ws_display} (id={ws.id})")

        for csv_path in csv_files:
            table_name = csv_path.stem
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            try:
                dt, ids = create_table_from_csv(engine, db, ws.id, table_name, csv_text)
                table_count += 1
                print(f"[seed-CSV] 建表: {ws_display}/{table_name} → {len(ids)} 行 (id={dt.id})")
            except Exception as exc:  # 单表失败不应阻断其它表
                print(f"[seed-CSV] 建表失败: {ws_display}/{table_name}: {exc}")

    return table_count, ws_map


def _seed_sales_tables(db: Any, engine: Any, ws: Any) -> int:
    """在"某企业销售管理"工作区下创建硬编码业务表（部门/员工/报告/工作流）.

    Returns:
        创建的数据表数量（部门表 + 员工表 = 2）.
    """
    from cndb.plugins.reports.models import ReportTemplate
    from cndb.plugins.tables.ddl import create_table
    from cndb.plugins.tables.models import DataField, DataTable
    from cndb.plugins.tables.records import create_row
    from cndb.plugins.workflows.models import Workflow, WorkflowEdge, WorkflowNode

    # 部门表（先建，员工表 link 字段要引用它）
    dept_tbl = DataTable(workspace_id=ws.id, name="部门表", description="公司部门", order=1)
    dept_tbl.ensure_db_name()
    db.add(dept_tbl)
    db.commit()
    db.refresh(dept_tbl)
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
    emp_tbl = DataTable(workspace_id=ws.id, name="员工表", description="公司员工信息", order=2)
    emp_tbl.ensure_db_name()
    db.add(emp_tbl)
    db.commit()
    db.refresh(emp_tbl)
    print(f"[seed] 创建数据表: 员工表 (id={emp_tbl.id})")

    field_specs: list[tuple[str, str, dict[str, Any], bool]] = [
        ("姓名", "text", {}, True),
        ("部门", "link", {"target_table_id": dept_tbl.id}, False),
        ("入职日期", "date", {}, False),
        ("薪资", "number", {}, False),
        ("是否在职", "select", {"options": ["是", "否"]}, False),
    ]
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
        {"姓名": "张三", "部门": [dept_rows["技术部"]], "入职日期": date(2023, 1, 15), "薪资": 15000, "是否在职": "是"},
        {"姓名": "李四", "部门": [dept_rows["市场部"]], "入职日期": date(2022, 6, 1), "薪资": 12000, "是否在职": "是"},
        {"姓名": "王五", "部门": [dept_rows["人事部"]], "入职日期": date(2024, 3, 20), "薪资": 10000, "是否在职": "是"},
        {
            "姓名": "赵六",
            "部门": [dept_rows["财务部"]],
            "入职日期": date(2021, 11, 10),
            "薪资": 13000,
            "是否在职": "否",
        },
        {"姓名": "钱七", "部门": [dept_rows["技术部"]], "入职日期": date(2023, 8, 5), "薪资": 18000, "是否在职": "是"},
    ]
    for data in samples:
        create_row(engine, emp_tbl, values=data, db=db)
    print("[seed] 插入 5 条员工记录")

    # 报告模板（绑定员工表）
    tpl = ReportTemplate(
        name="员工名册",
        description="列出所有在职员工的基本信息",
        table_id=emp_tbl.id,
        output_format="docx",
        template_content="# {{ table_name }}",
        parameters=[],
    )
    db.add(tpl)
    db.commit()
    print(f"[seed] 创建报告模板: 员工名册 (table_id={emp_tbl.id})")

    # 业务工作流 — 员工入职流程（3 节点 2 边，绑定部门表 + 员工表）
    wf = Workflow(
        workspace_id=ws.id,
        name="员工入职流程",
        description="从提交入职申请到完成登记的业务流程",
        order=0,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    print(f"[seed] 创建工作流: 员工入职流程 (id={wf.id})")

    n1 = WorkflowNode(
        workflow_id=wf.id, name="入职登记", table_id=emp_tbl.id, pos_x=60, pos_y=60, config={"default_view_id": None}
    )
    db.add(n1)
    db.commit()
    db.refresh(n1)

    n2 = WorkflowNode(
        workflow_id=wf.id, name="部门分配", table_id=dept_tbl.id, pos_x=300, pos_y=60, config={"default_view_id": None}
    )
    db.add(n2)
    db.commit()
    db.refresh(n2)

    n3 = WorkflowNode(
        workflow_id=wf.id, name="入职完成", table_id=None, pos_x=540, pos_y=60, config={"default_view_id": None}
    )
    db.add(n3)
    db.commit()
    db.refresh(n3)

    db.add(WorkflowEdge(workflow_id=wf.id, source_node_id=n1.id, target_node_id=n2.id, label="提交资料"))
    db.add(WorkflowEdge(workflow_id=wf.id, source_node_id=n2.id, target_node_id=n3.id, label="分配完成"))
    db.commit()
    print("[seed] 组装 3 节点 2 边: 入职登记 → 部门分配 → 入职完成")

    return 2


def seed(_args: argparse.Namespace) -> None:
    """向数据库注入演示数据（datasets CSV + 硬编码业务表）."""
    from cndb.core.database import SessionLocal, engine
    from cndb.models.base import Base
    from cndb.plugins.accounts.models import User

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        # 用户
        user = User(username="demo", email="demo@cndb.local", nickname="演示账号")
        user.set_password("demo1234")
        db.add(user)
        db.commit()
        db.refresh(user)
        print("[seed] 创建用户: demo / demo1234")

        # 先跑 datasets：每个子文件夹 → 工作区，每个 CSV → 数据表
        csv_count, ws_map = _seed_datasets(db, engine, user)

        # 硬编码业务表（部门表/员工表/报告模板/工作流）挂到 "某企业销售管理" 工作区
        extra = 0
        sales_ws = ws_map.get("某企业销售管理")
        if sales_ws is not None:
            print(f"[seed] 在工作区 '{sales_ws.name}' 下扩展部门/员工业务表")
            extra = _seed_sales_tables(db, engine, sales_ws)
        else:
            print("[seed] 未找到 '某企业销售管理' 工作区，跳过部门表/员工表注入")

        total = csv_count + extra
        print(f"[seed] 完成！共 {total} 张数据表。运行 uv run cndb serve 启动服务后用 demo / demo1234 登录")
    finally:
        db.close()
