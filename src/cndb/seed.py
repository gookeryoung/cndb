"""演示数据注入 — 幂等（drop_all 后重建，每次全新）.

数据源：
1. examples/datasets/<工作区名>/*.csv — 按文件夹名自动建工作区，CSV 自动推断字段建表导入
2. examples/datasets/<工作区名>/views.json — 每个工作区独立的视图种子配置，按 表名 -> 视图列表 组织
3. 硬编码业务表 — 部门表 + 员工表 + 报告模板 + 工作流，绑定到 datasets 创建的
   "某企业销售管理"工作区，与 CSV 数据共同构成完整销售场景
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData


def _get_datasets_dir() -> Path | None:
    """定位 datasets 目录（包内优先，fallback 仓库根，均找不到则返回 None 优雅降级）.

    搜索顺序：
    1. 包内 cndb/datasets/ —— wheel 安装版，由 hatch force-include 打包
    2. 仓库根 examples/datasets/ —— 源码开发版
    """
    pkg_datasets = Path(__file__).resolve().parent / "datasets"
    if pkg_datasets.is_dir():
        return pkg_datasets
    src_root = Path(__file__).resolve().parent.parent.parent
    candidate = src_root / "examples" / "datasets"
    if candidate.is_dir():
        return candidate
    return None


def _get_workspace_view_configs(datasets_dir: Path) -> dict[str, dict[str, Any]]:
    """扫描每个工作区文件夹下的 views.json.

    Returns:
        工作区显示名 -> 视图配置（表名 -> 视图列表）的映射.
    """
    result: dict[str, dict[str, Any]] = {}
    for folder in sorted(datasets_dir.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        views_path = folder / "views.json"
        if not views_path.is_file():
            continue
        # 工作区名做同样的 "工作区-" 前缀剥离
        ws_name = folder.name
        if ws_name.startswith("工作区-"):
            ws_display = ws_name[len("工作区-") :]
        else:
            ws_display = ws_name
        try:
            result[ws_display] = json.loads(views_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[seed-视图] {folder.name}/views.json 解析失败: {exc}")
    return result


def _seed_datasets(db: Any, engine: Any, user: Any) -> tuple[int, dict[str, Any], dict[str, dict[str, Any]]]:
    """扫描 datasets 目录，按子文件夹建工作区、按 CSV 建表导入.

    Returns:
        (成功创建的数据表总数, 工作区名 -> Workspace 对象映射, 工作区名 -> 表名 -> DataTable 映射)
    """
    from cndb.plugins.tables.transfer import create_table_from_csv
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember

    datasets_dir = _get_datasets_dir()
    if datasets_dir is None:
        print("[seed] examples/datasets 目录不存在，跳过 CSV 注入（wheel 安装版无此目录属正常）")
        return 0, {}, {}

    table_count = 0
    ws_map: dict[str, Any] = {}
    tables_map: dict[str, dict[str, Any]] = {}
    for folder in sorted(datasets_dir.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        csv_files = sorted(folder.glob("*.csv"))
        if not csv_files:
            continue

        # 工作区名去掉 "工作区-" 前缀让显示更友好
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
        tables_map[ws_display] = {}
        print(f"[seed-CSV] 创建工作区: {ws_display} (id={ws.id})")

        for csv_path in csv_files:
            table_name = csv_path.stem
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            try:
                dt, ids = create_table_from_csv(engine, db, ws.id, table_name, csv_text)
                table_count += 1
                tables_map[ws_display][table_name] = dt
                print(f"[seed-CSV] 建表: {ws_display}/{table_name} → {len(ids)} 行 (id={dt.id})")
            except Exception as exc:  # 单表失败不应阻断其它表
                print(f"[seed-CSV] 建表失败: {ws_display}/{table_name}: {exc}")

    return table_count, ws_map, tables_map


def _seed_sales_tables(db: Any, engine: Any, ws: Any) -> tuple[int, dict[str, Any]]:
    """在"某企业销售管理"工作区下创建硬编码业务表（部门/员工/报告/工作流）.

    Returns:
        (创建的数据表数量, 表名 -> DataTable 映射)
    """
    from cndb.plugins.reports.models import ReportTemplate
    from cndb.plugins.tables.ddl import create_table
    from cndb.plugins.tables.models import DataField, DataTable
    from cndb.plugins.tables.records import create_row
    from cndb.plugins.workflows.models import Workflow, WorkflowEdge, WorkflowNode

    extra_tables: dict[str, Any] = {}

    # 部门表（先建，员工表 link 字段要引用它）
    dept_tbl = DataTable(workspace_id=ws.id, name="部门表", description="公司部门", order=1)
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
    emp_tbl = DataTable(workspace_id=ws.id, name="员工表", description="公司员工信息", order=2)
    emp_tbl.ensure_db_name()
    db.add(emp_tbl)
    db.commit()
    db.refresh(emp_tbl)
    extra_tables["员工表"] = emp_tbl
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

    return 2, extra_tables


def _validate_view_fields(vc: dict[str, Any], valid_fields: set[str], ws_name: str, table_name: str) -> bool:
    """校验单个视图配置里引用的所有 field_name 是否在目标表存在.

    Returns:
        True 表示通过，False 表示校验失败并已打印错误信息.
    """
    view_name = vc.get("name", "")
    for f in vc.get("filters", []):
        if f.get("field_name") not in valid_fields:
            print(
                f"[seed-视图] 跳过: {ws_name}/{table_name} 视图'{view_name}' "
                f"的 filter field_name='{f.get('field_name')}' 不存在"
            )
            return False
    for s in vc.get("sortings", []):
        if s.get("field_name") not in valid_fields:
            print(
                f"[seed-视图] 跳过: {ws_name}/{table_name} 视图'{view_name}' "
                f"的 sorting field_name='{s.get('field_name')}' 不存在"
            )
            return False
    # kanban 的 group_field / calendar 的 start_field / gallery 的 title_field 等
    vo = vc.get("view_options", {})
    for opt_key in (
        "group_field",
        "start_field",
        "end_field",
        "title_field",
        "image_field",
        "subtitle_field",
        "tag_field",
    ):
        opt_val = vo.get(opt_key)
        if opt_val and opt_val not in valid_fields:
            print(
                f"[seed-视图] 跳过: {ws_name}/{table_name} 视图'{view_name}' "
                f"的 view_options.{opt_key}='{opt_val}' 不存在"
            )
            return False
    # meta_fields 是字符串数组，每项都需校验
    for mf in vo.get("meta_fields") or []:
        if mf not in valid_fields:
            print(
                f"[seed-视图] 跳过: {ws_name}/{table_name} 视图'{view_name}' "
                f"的 view_options.meta_fields 包含不存在的字段 '{mf}'"
            )
            return False
    return True


def _seed_views(db: Any, user: Any, tables_map: dict[str, dict[str, Any]], datasets_dir: Path | None) -> int:
    """按各工作区文件夹下的 views.json 为每张表创建典型视图."""
    from cndb.plugins.tables.models import DataView

    if datasets_dir is None:
        print("[seed-视图] examples/datasets 目录不存在，跳过视图注入")
        return 0

    ws_configs = _get_workspace_view_configs(datasets_dir)
    if not ws_configs:
        print("[seed-视图] 未发现任何 views.json，跳过视图注入")
        return 0

    created = 0
    for ws_name, tables in ws_configs.items():
        ws_tables = tables_map.get(ws_name)
        if not ws_tables:
            print(f"[seed-视图] 配置中的工作区 '{ws_name}' 不存在，跳过")
            continue
        for table_name, view_list in tables.items():
            if table_name.startswith("_"):
                continue  # 跳过 _comment 等元数据键
            dt = ws_tables.get(table_name)
            if dt is None:
                print(f"[seed-视图] 配置中的表 '{ws_name}/{table_name}' 不存在，跳过")
                continue
            valid_fields = {f.name for f in dt.fields}
            for idx, vc in enumerate(view_list):
                try:
                    if not _validate_view_fields(vc, valid_fields, ws_name, table_name):
                        continue
                    dv = DataView(
                        table_id=dt.id,
                        owner_id=user.id,
                        name=vc["name"],
                        view_type=vc.get("view_type", "grid"),
                        filter_type=vc.get("filter_type", "AND"),
                        filters=vc.get("filters", []),
                        sortings=vc.get("sortings", []),
                        field_options=vc.get("field_options", {}),
                        field_order=vc.get("field_order", []),
                        view_options=vc.get("view_options", {}),
                        is_default=vc.get("is_default", False),
                        order=vc.get("order", idx),
                    )
                    db.add(dv)
                    db.flush()
                    created += 1
                    print(f"[seed-视图] {ws_name}/{table_name} → {dv.name} ({dv.view_type})")
                except Exception as exc:  # 单视图失败不阻断其它
                    print(f"[seed-视图] 跳过: {ws_name}/{table_name} / {vc.get('name', '<无>')}: {exc}")

    db.commit()
    return created


def seed(_args: argparse.Namespace) -> None:
    """向数据库注入演示数据（datasets CSV + 硬编码业务表 + 视图种子）."""
    from cndb.core.database import SessionLocal, engine
    from cndb.core.plugin_registry import plugin_registry
    from cndb.models.base import Base
    from cndb.plugins.accounts.models import User

    # 触发所有插件 register_models，确保 Base.metadata 完整注册
    plugin_registry.discover_and_load()

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

        # 1) datasets CSV：每个子文件夹 → 工作区，每个 CSV → 数据表
        csv_count, ws_map, tables_map = _seed_datasets(db, engine, user)

        # 2) 硬编码业务表挂到 "某企业销售管理" 工作区
        extra = 0
        sales_ws = ws_map.get("某企业销售管理")
        if sales_ws is not None:
            print(f"[seed] 在工作区 '{sales_ws.name}' 下扩展部门/员工业务表")
            extra, extra_tables = _seed_sales_tables(db, engine, sales_ws)
            tables_map.setdefault("某企业销售管理", {}).update(extra_tables)
        else:
            print("[seed] 未找到 '某企业销售管理' 工作区，跳过部门表/员工表注入")

        # 3) 视图种子（依赖所有表已就绪，扫描每个工作区文件夹下的 views.json）
        datasets_dir = _get_datasets_dir()
        view_count = _seed_views(db, user, tables_map, datasets_dir)

        total = csv_count + extra
        print(
            f"[seed] 完成！共 {total} 张数据表、{view_count} 个视图。"
            "运行 uv run cndb serve 启动服务后用 demo / demo1234 登录"
        )
    finally:
        db.close()
