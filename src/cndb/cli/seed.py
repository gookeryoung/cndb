"""演示数据注入 — 幂等（drop_all 后重建，每次全新）.

数据源：
1. examples/datasets/<工作区名>/*.csv — 按文件夹名自动建工作区，CSV 自动推断字段建表导入
2. examples/datasets/<工作区名>/views.json — 每个工作区独立的视图种子配置，按 表名 -> 视图列表 组织
3. examples/datasets/<工作区名>/fields.json — 每个工作区独立的字段设置种子：必填/唯一约束、
   关联（link）+ 引用（lookup）示例字段，用于演示字段设置能力
4. 硬编码业务表 — 部门表 + 员工表 + 报告模板 + 工作流，绑定到 datasets 创建的
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
    # 本文件位于 src/cndb/cli/seed.py，向上四级才是仓库根（移入 cli 包后层级 +1）
    src_root = Path(__file__).resolve().parents[3]
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
    """扫描 datasets 目录，按子文件夹建工作区、按 CSV 建表导入 + 按 api_config.json 建表.

    Returns:
        (成功创建的数据表总数, 工作区名 -> Workspace 对象映射, 工作区名 -> 表名 -> DataTable 映射)
    """
    from cndb.plugins.tables.services.importing.api_config_loader import (
        ApiConfigError,
        build_fetch_config,
        load_api_config_file,
    )
    from cndb.plugins.tables.services.transfer import create_table_from_csv, ingest_from_api
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember

    datasets_dir = _get_datasets_dir()
    if datasets_dir is None:
        print("[seed] examples/datasets 目录不存在，跳过 CSV 注入（wheel 安装版无此目录属正常）")
        return 0, {}, {}

    table_count = 0
    ws_map: dict[str, Any] = {}
    tables_map: dict[str, dict[str, Any]] = {}

    # "某企业销售管理"（硬编码业务表宿主）固定最先创建 → 稳定占据 ws id=1，
    # 供 e2e 等场景对工作区 id 做稳定假设；其余工作区保持名称排序。
    def _sales_first(p: Path) -> tuple[bool, str]:
        """排序键：某企业销售管理优先，其余按文件夹名升序."""
        return (p.name != "工作区-某企业销售管理", p.name)

    folders = sorted(datasets_dir.iterdir(), key=_sales_first)
    for folder in folders:
        if not folder.is_dir() or folder.name.startswith("."):
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
        print(f"[seed] 创建工作区: {ws_display} (id={ws.id})")

        # ── CSV 建表 ──
        csv_files = sorted(folder.glob("*.csv"))
        for csv_path in csv_files:
            table_name = csv_path.stem
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            try:
                dt, _ids = create_table_from_csv(engine, db, ws.id, table_name, csv_text, owner_id=user.id)
                table_count += 1
                tables_map[ws_display][table_name] = dt
                print(f"[seed-CSV] 建表: {ws_display}/{table_name} → (id={dt.id})")
            except Exception as exc:  # 单表失败不应阻断其它表
                print(f"[seed-CSV] 建表失败: {ws_display}/{table_name}: {exc}")

        # ── API 配置建表 ──
        api_config_path = folder / "api_config.json"
        if api_config_path.is_file():
            try:
                table_defs = load_api_config_file(api_config_path)
            except ApiConfigError as exc:
                print(f"[seed-API] 配置文件解析失败 {api_config_path.name}: {exc}")
                continue

            for table_def in table_defs:
                tbl_name = table_def["table_name"]
                fetch_cfg = build_fetch_config(table_def)
                try:
                    dt, ids, _columns = ingest_from_api(
                        engine,
                        db,
                        ws.id,
                        tbl_name,
                        api_url=fetch_cfg.url,
                        method=fetch_cfg.method,
                        headers=fetch_cfg.headers,
                        params=fetch_cfg.params,
                        body=fetch_cfg.body,
                        data_path=fetch_cfg.data_path,
                        timeout=fetch_cfg.timeout,
                        response_handler=fetch_cfg.response_handler,
                        encoding=fetch_cfg.encoding,
                        query_interval=fetch_cfg.query_interval,
                        owner_id=user.id,
                    )
                    table_count += 1
                    tables_map[ws_display][tbl_name] = dt
                    print(
                        f"[seed-API] 建表: {ws_display}/{tbl_name} "
                        f"(handler={fetch_cfg.response_handler}, "
                        f"interval={fetch_cfg.query_interval:.0f}s, "
                        f"{len(ids)} 行, id={dt.id})"
                    )
                except Exception as exc:
                    print(f"[seed-API] 建表失败: {ws_display}/{tbl_name}: {exc}")

        # ── 跨表字段引入（表已就绪后执行，避免源表不存在） ──
        _apply_field_import_rules(db, engine, ws_display, tables_map)

    return table_count, ws_map, tables_map


# ── 字段引入规则 ──────────────────────────────────────


def _apply_field_import_rules(db: Any, engine: Any, ws_name: str, tables_map: dict[str, dict[str, Any]]) -> None:
    """按预定义规则在同一工作区内把源表字段克隆到目标表.

    设计意图：
    - CSV 建表天然是"先建主体表再建关联子表"，子表往往需要知道主表的某个状态/标签字段；
    - 这里用 field_ops.clone_fields_between_tables 把字段 schema 从主表克隆到子表，
      让子表可以独立存储（不依赖 link 字段和 lookup 计算）；
    - 失败不阻断其它规则执行（单条规则失败只打印）。
    """
    from cndb.plugins.tables.services.fields import field_ops as _fo

    rules: dict[str, list[tuple[str, str, list[str]]]] = {
        # 项目进展表 / 科研经费表 都需要从 科研项目 表知道项目状态和立项年份
        "科研项目管理": [
            # (目标表, 源表, 要引入的字段名列表)
            ("项目进展", "科研项目", ["项目状态", "立项年份"]),
            ("科研经费", "科研项目", ["项目状态", "项目类别"]),
            ("课题负责人", "科研项目", ["项目状态"]),
        ],
    }

    ws_rules = rules.get(ws_name)
    if not ws_rules:
        return

    ws_tables = tables_map.get(ws_name, {})
    for dst_name, src_name, field_names in ws_rules:
        dst = ws_tables.get(dst_name)
        src = ws_tables.get(src_name)
        if dst is None or src is None:
            print(f"[seed-字段引入] {ws_name}: 表缺失（{src_name}->{dst_name}），跳过")
            continue
        try:
            created, skipped = _fo.clone_fields_between_tables(
                engine, db, src, dst, field_names=field_names, skip_conflicts=True
            )
            if created or skipped:
                print(f"[seed-字段引入] {ws_name}: {src_name} → {dst_name} (成功 {len(created)}, 跳过 {len(skipped)})")
        except Exception as exc:
            print(f"[seed-字段引入] {ws_name}: {src_name} → {dst_name} 失败: {exc}")


def _load_field_settings(datasets_dir: Path | None) -> dict[str, dict[str, Any]]:
    """读取每个工作区文件夹下的 fields.json 字段设置种子配置.

    配置结构（均可缺省，解析失败仅告警跳过）::

        {
          "settings": {"表名": {"字段名": {"required": true, "unique": true}}},
          "link_lookups": [
            {"table": "目标表", "source_table": "源表", "fields": ["源字段名"],
             "link_name": "关联课题", "multiple": false}
          ]
        }

    Returns:
        工作区显示名 -> fields.json 解析结果的映射.
    """
    result: dict[str, dict[str, Any]] = {}
    if datasets_dir is None or not datasets_dir.is_dir():
        return result
    for folder in sorted(datasets_dir.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        fields_path = folder / "fields.json"
        if not fields_path.is_file():
            continue
        ws_name = folder.name
        ws_display = ws_name[len("工作区-") :] if ws_name.startswith("工作区-") else ws_name
        try:
            cfg = json.loads(fields_path.read_text(encoding="utf-8-sig"))
            if not isinstance(cfg, dict):
                raise ValueError("顶层必须是对象")
            result[ws_display] = cfg
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            print(f"[seed-字段设置] {folder.name}/fields.json 解析失败: {exc}")
    return result


def _apply_field_settings(
    db: Any, engine: Any, tables_map: dict[str, dict[str, Any]], datasets_dir: Path | None
) -> None:
    """按 fields.json 为数据集表补充字段设置示例：必填/唯一约束 + 关联/引用字段.

    - settings：直接改写 DataField.required / is_unique 标志（仅对已存在字段生效）；
    - link_lookups：复用 field_ops.import_fields_as_lookup 建实时关联（link + lookup），
      单行业务表通过 multiple=False 演示单选关联；
    - 幂等：重复执行时 settings 重设标志，link 复用、同名 lookup 跳过；
    - 单表/单条失败仅打印，不阻断其它工作区。
    """
    from cndb.plugins.tables.services.fields import field_ops as _fo

    ws_configs = _load_field_settings(datasets_dir)
    if not ws_configs:
        return

    for ws_display, cfg in ws_configs.items():
        ws_tables = tables_map.get(ws_display, {})

        # 1) 必填 / 唯一约束设置
        for tbl_name, field_cfgs in (cfg.get("settings") or {}).items():
            tbl = ws_tables.get(tbl_name)
            if tbl is None:
                print(f"[seed-字段设置] {ws_display}: 表 '{tbl_name}' 不存在，跳过设置")
                continue
            field_by_name = {f.name: f for f in tbl.fields if not f.trashed}
            for fname, flags in field_cfgs.items():
                field = field_by_name.get(fname)
                if field is None:
                    print(f"[seed-字段设置] {ws_display}/{tbl_name}: 字段 '{fname}' 不存在，跳过")
                    continue
                if "required" in flags:
                    field.required = bool(flags["required"])
                if "unique" in flags:
                    field.is_unique = bool(flags["unique"])
                db.commit()
            print(f"[seed-字段设置] {ws_display}/{tbl_name}: 应用必填/唯一设置 {len(field_cfgs)} 项")

        # 2) 关联 + 引用示例字段
        for rule in cfg.get("link_lookups") or []:
            dst = ws_tables.get(rule.get("table", ""))
            src = ws_tables.get(rule.get("source_table", ""))
            src_field_names = rule.get("fields") or []
            if dst is None or src is None:
                print(
                    f"[seed-字段设置] {ws_display}: 关联规则表缺失"
                    f"（{rule.get('source_table')} -> {rule.get('table')}），跳过"
                )
                continue
            src_fields = [f for f in src.active_fields() if f.name in src_field_names]
            if not src_fields:
                print(f"[seed-字段设置] {ws_display}: 源字段 {src_field_names} 均不存在，跳过")
                continue
            try:
                created, skipped = _fo.import_fields_as_lookup(
                    engine,
                    db,
                    src,
                    dst,
                    src_fields,
                    link_name=rule.get("link_name"),
                    link_multiple=bool(rule.get("multiple", True)),
                )
                print(
                    f"[seed-字段设置] {ws_display}: {src.name} → {dst.name} 关联引入"
                    f"（新建 {len(created)}, 跳过 {len(skipped)}）"
                )
            except Exception as exc:
                print(f"[seed-字段设置] {ws_display}: {src.name} → {dst.name} 关联引入失败: {exc}")


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
        ("工号", "text", {}, True),
        ("姓名", "text", {}, True),
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


def _generate_sample_reports(
    db: Any, tables_map: dict[str, dict[str, Any]], owner: Any, datasets_dir: Path | None
) -> None:
    """渲染 REPORT_TEMPLATE_SPECS 中的全部示例模板，按模板输出格式（docx/xlsx/pdf）落盘到对应工作区数据集目录.

    复用渲染端点的沙箱环境 / 统计函数 / docx 渲染器，端到端验证模板可渲染；
    固定文件名（不带时间戳，避免 git 反复变更），每次 seed 覆盖重写。
    渲染失败仅告警不中断 seed（模板/数据问题不应阻塞演示数据注入）。
    """
    import datetime as dt

    from cndb.plugins.reports.models import ReportTemplate
    from cndb.plugins.reports.routers.reports import (
        _FORMAT_RENDERERS,
        _jinja_env,
        _load_table_records,
        _render_with_timeout,
    )
    from cndb.plugins.tables.models import DataTable

    if datasets_dir is None:
        print("[seed-示例报告] 跳过：datasets 目录不可用")
        return

    for spec in REPORT_TEMPLATE_SPECS:
        ws_tables = tables_map.get(spec["workspace"]) or {}
        main_tbl = ws_tables.get(spec["table"])
        if main_tbl is None:
            print(f"[seed-示例报告] 跳过：未找到 {spec['workspace']}/{spec['table']}（{spec['name']}）")
            continue
        tpl = (
            db.query(ReportTemplate)
            .filter(ReportTemplate.table_id == main_tbl.id, ReportTemplate.name == spec["name"])
            .first()
        )
        if tpl is None:
            print(f"[seed-示例报告] 跳过：模板未创建（{spec['name']}）")
            continue

        # 构建渲染上下文（与渲染端点 render_report 一致：主表 + extra 表 + generated_at）
        table, records = _load_table_records(db, main_tbl.id, owner)
        records_by_table: dict[str, list[dict[str, Any]]] = {}
        for etid in tpl.extra_table_ids:
            etable = db.get(DataTable, etid)
            if etable is None:
                continue
            _, erecords = _load_table_records(db, etid, owner)
            records_by_table[etable.name] = erecords
        ctx: dict[str, Any] = {
            "records": records,
            "table_name": table.name,
            "params": {},
            "records_by_table": records_by_table,
            "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        try:
            jinja_tmpl = _jinja_env.from_string(tpl.template_content)
            rendered = _render_with_timeout(jinja_tmpl, ctx)
            renderer = _FORMAT_RENDERERS.get(tpl.output_format)
            if renderer is None:
                print(f"[seed-示例报告] 跳过：不支持的输出格式 {tpl.output_format}（{spec['name']}）")
                continue
            file_bytes = renderer(rendered, ctx)
        except Exception as exc:  # 模板/数据问题不应阻塞 seed
            print(f"[seed-示例报告] {spec['name']} 渲染失败（请检查模板与数据集字段匹配）: {exc}")
            continue

        out_dir = datasets_dir / f"工作区-{spec['workspace']}"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{spec['name']}-示例报告.{tpl.output_format}"
            out_path.write_bytes(file_bytes)
        except OSError as exc:
            print(f"[seed-示例报告] 写入失败（{spec['name']}）: {exc}")
            continue
        print(f"[seed-示例报告] 生成: {out_path} ({len(file_bytes)} bytes)")


# ── 示例报告模板定义 ────────────────────────────────────
# 8 组典型示例（含既有科研项目季度汇报），覆盖 datasets 各工作区的代表性场景，
# 并在输出格式（docx/xlsx/pdf/html）、主题风格、参数化、跨工作区引用上保持配置多样性。
# 所有模板统一遵循"标题 → 摘要 → 数据统计 → 结论与建议"的正文结构：
# 摘要与各节分析段落均为数据驱动叙述（基于 stats/group_stats/set 计算插值），落款前附结论与建议。
# 1. 科研项目季度汇报 —— 跨表引用 + selectattr 匹配分组（科研项目管理，docx/business）
# 2. 电商销售月报 —— 单表分组聚合（某企业销售管理/电商销售，xlsx 数据导出）
# 3. 产品开发交付进度报告 —— non_empty 空值统计 + 分页（某企业销售管理/产品开发，docx/modern）
# 4. WBS 任务进度周报 —— selectattr 过滤 + 多维统计（项目管理，docx/engineering）
# 5. 城市气温天气月报 —— min/max 极值 + 嵌套分组 + 城市参数明细（某地区数据，pdf/academic）
# 6. 数据质量体检报告 —— 脏数据完整性边界 + 跨工作区抽检（低质量数据，docx/academic）
# 7. 日常待办任务清单 —— 任务状态/优先级/类型多维统计 + 高优先级明细（某企业销售管理/日常待办，html/modern）
# 8. 营销活动效果报告 —— 预算/线索/转化率聚合 + 渠道分组 + 活动明细（某企业销售管理/营销活动，html/business）
REPORT_TEMPLATE_SPECS: list[dict[str, Any]] = [
    {
        "workspace": "科研项目管理",
        "table": "科研项目",
        "extra_tables": ["科研经费", "项目进展", "课题负责人"],
        "name": "科研项目季度汇报",
        "description": "汇总科研项目概览、按类别/状态分组统计、经费拨付、研究进展与负责人名录",
        "output_format": "docx",
        "theme": "business",
        "content": (
            "# 科研项目季度汇报\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "{% set total_funding = stats(records, '经费总额_万元').sum %}\n"
            "{% set ongoing = records | selectattr('项目状态', 'equalto', '在研') | list | length %}\n"
            "本季度共梳理科研课题 {{ records | length }} 项，其中在研 {{ ongoing }} 项；经费总额合计 {{ total_funding | round(2) }} 万元，平均单课题经费 {{ stats(records, '经费总额_万元').avg | round(2) }} 万元。\n"
            "{% set cat_stats = group_stats(records, '项目类别', '经费总额_万元') %}\n"
            "{% if cat_stats %}\n"
            "{% set top_cat = cat_stats | sort(attribute='sum', reverse=true) | first %}\n"
            "经费主要投向「{{ top_cat.key }}」方向（{{ top_cat.count }} 项课题，合计 {{ top_cat.sum | round(2) }} 万元），经费结构详见下文分项统计。\n"
            "{% endif %}\n"
            "\n"
            "## 一、项目概览\n"
            "\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 项目总数 | {{ records | length }} |\n"
            "| 在研项目数 | {{ records | selectattr('项目状态', 'equalto', '在研') | list | length }} |\n"
            "| 有进展记录的课题数 | {{ stats(records_by_table['项目进展'], '课题编号').non_empty }} |\n"
            "| 经费总额（万元） | {{ stats(records, '经费总额_万元').sum | round(2) }} |\n"
            "| 经费平均值（万元） | {{ stats(records, '经费总额_万元').avg | round(2) }} |\n"
            "\n"
            "## 二、按项目类别统计\n"
            "\n"
            "| 项目类别 | 数量 | 经费合计（万元） |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '项目类别', '经费总额_万元') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum | round(2) }} |\n"
            "{% endfor %}"
            "\n"
            "{% if cat_stats %}"
            "从类别结构看，「{{ top_cat.key }}」以 {{ top_cat.count }} 项课题、{{ top_cat.sum | round(2) }} 万元经费居各方向首位；建议后续保持重点方向的资源倾斜，并关注薄弱类别的培育。\n"
            "{% endif %}"
            "\n"
            "## 三、按项目状态统计\n"
            "\n"
            "| 项目状态 | 数量 | 经费合计（万元） |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '项目状态', '经费总额_万元') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum | round(2) }} |\n"
            "{% endfor %}"
            "\n"
            "已登记结题日期的课题 {{ stats(records, '结题日期').non_empty }} 项，其余课题仍在推进中；建议对照计划周期跟踪各课题里程碑，对明显滞后的课题提前协调资源。\n"
            "\n"
            "## 四、经费拨付汇总\n"
            "\n"
            "{% if records_by_table['科研经费'] %}"
            "| 预算科目 | 预算金额（万元） | 已拨金额（万元） | 拨付率 |\n"
            "| --- | --- | --- | --- |\n"
            "{% for g in group_stats(records_by_table['科研经费'], '预算科目', '预算金额_万元') %}"
            "{% set g2 = group_stats(records_by_table['科研经费'], '预算科目', '已拨金额_万元') %}"
            "{% set matched = g2 | selectattr('key', 'equalto', g.key) | list %}"
            "{% set disbursed = matched[0].sum if matched else 0 %}"
            "| {{ g.key }} | {{ g.sum | round(2) }} | {{ disbursed | round(2) }} | {{ '%.1f%%' | format(disbursed / g.sum * 100) if g.sum > 0 else 'N/A' }} |\n"
            "{% endfor %}"
            "\n"
            "经费状态统计：\n"
            "{% for g in group_stats(records_by_table['科研经费'], '经费状态', '已拨金额_万元') %}"
            "- **{{ g.key }}**：{{ g.count }} 笔，已拨 {{ g.sum | round(2) }} 万元\n"
            "{% endfor %}"
            "{% set fund_all = records_by_table['科研经费'] %}"
            "拨付进度方面，已拨金额合计 {{ stats(fund_all, '已拨金额_万元').sum | round(2) }} 万元，占预算合计 {{ stats(fund_all, '预算金额_万元').sum | round(2) }} 万元的 {{ '%.1f%%' | format(stats(fund_all, '已拨金额_万元').sum / stats(fund_all, '预算金额_万元').sum * 100) if stats(fund_all, '预算金额_万元').sum else 'N/A' }}；未拨付部分建议按科目逐项核对堵点，避免影响课题支出。\n"
            "{% endif %}"
            "\n"
            "## 五、研究进展汇总\n"
            "\n"
            "{% if records_by_table['项目进展'] %}"
            "| 进展阶段 | 条目数 | 平均进度 |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records_by_table['项目进展'], '进展阶段', '进度百分比') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.avg | round(1) }}% |\n"
            "{% endfor %}"
            "\n"
            "按季度分布：\n"
            "{% for g in group_stats(records_by_table['项目进展'], '报告季度', '进度百分比') %}"
            "- **{{ g.key }}**：{{ g.count }} 条进展记录\n"
            "{% endfor %}"
            "本季度进展记录共 {{ records_by_table['项目进展'] | length }} 条，平均进度 {{ stats(records_by_table['项目进展'], '进度百分比').avg | round(1) }}%；对平均进度明显偏低的阶段建议安排专项督导，并在下一季度跟踪整改效果。\n"
            "{% endif %}"
            "\n"
            "## 六、负责人名录\n"
            "\n"
            "{% if records_by_table['课题负责人'] %}"
            "| 姓名 | 职称 | 是否 PI | 研究方向 |\n"
            "| --- | --- | --- | --- |\n"
            "{% for r in records_by_table['课题负责人'] %}"
            "| {{ r['姓名'] }} | {{ r['职称'] }} | {{ '是' if r['是否PI'] else '否' }} | {{ r['研究方向'] }} |\n"
            "{% endfor %}"
            "{% endif %}"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 经费管理：对照拨付率梳理未拨付科目，优先保障设备费与人员费等刚性支出，确保课题执行不受资金影响。\n"
            "2. 进度督导：对进度滞后的在研课题建立月度跟踪机制，必要时调整阶段计划并同步至项目进展表。\n"
            "3. 成果规划：临近结题的课题应提前规划论文、专利、软件著作权等成果形式，避免结题前集中补齐材料。\n"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
    {
        "workspace": "某企业销售管理",
        "table": "电商销售",
        "extra_tables": [],
        "name": "电商销售月报",
        "description": "按商品类别与支付方式分组汇总销售额、客单价与评分（xlsx 数据导出）",
        "output_format": "xlsx",
        "content": (
            "# 电商销售月报\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "{% set sales_sum = stats(records, '销售额').sum %}\n"
            "本期共录入 {{ records | length }} 笔订单，销售额合计 {{ sales_sum | round(2) }} 元，平均客单价 {{ stats(records, '销售额').avg | round(2) }} 元，平均评分 {{ stats(records, '评分').avg | round(1) }} 分。\n"
            "{% set cat_stats = group_stats(records, '商品类别', '销售额') %}\n"
            "{% if cat_stats %}\n"
            "{% set top_cat = cat_stats | sort(attribute='sum', reverse=true) | first %}\n"
            "「{{ top_cat.key }}」为销售额最高类目（{{ top_cat.count }} 笔订单，合计 {{ top_cat.sum | round(2) }} 元），类目贡献详见第二节。\n"
            "{% endif %}\n"
            "\n"
            "## 一、销售概览\n"
            "\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 订单总数 | {{ records | length }} |\n"
            "| 销售额合计（元） | {{ stats(records, '销售额').sum | round(2) }} |\n"
            "| 平均客单价（元） | {{ stats(records, '销售额').avg | round(2) }} |\n"
            "| 平均评分 | {{ stats(records, '评分').avg | round(1) }} |\n"
            "| 商品类别数 | {{ group_stats(records, '商品类别', '销售额') | length }} |\n"
            "\n"
            "## 二、按商品类别汇总\n"
            "\n"
            "| 商品类别 | 订单数 | 销售额（元） |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '商品类别', '销售额') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum | round(2) }} |\n"
            "{% endfor %}"
            "\n"
            "类目销售额集中度较高，头部类目贡献了主要业绩；建议结合库存与毛利数据评估促销资源投放结构，避免过度依赖单一类目。\n"
            "\n"
            "## 三、按支付方式汇总\n"
            "\n"
            "| 支付方式 | 订单数 | 销售额（元） |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '支付方式', '销售额') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum | round(2) }} |\n"
            "{% endfor %}"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 类目运营：对销售额最高的类目维持当前投入，同时为第二梯队类目设计组合促销，提升整体抗波动能力。\n"
            "2. 支付体验：关注各支付方式的订单分布变化，若单一渠道占比持续上升，建议评估其手续费成本与结算周期。\n"
            "3. 客单价提升：可通过满减、套装组合等方式拉升平均客单价，并持续跟踪评分反馈定位体验短板。\n"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
    {
        "workspace": "某企业销售管理",
        "table": "产品开发",
        "extra_tables": [],
        "name": "产品开发交付进度报告",
        "description": "项目交付状态概览（含未交付空值统计）、按状态与片区分组汇总",
        "output_format": "docx",
        "theme": "modern",
        "content": (
            "# 产品开发交付进度报告\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "{% set delivered = stats(records, '实际交付日期').non_empty %}\n"
            "本期共跟踪项目 {{ records | length }} 个，已交付 {{ delivered }} 个、未交付 {{ records | length - delivered }} 个，整体平均进度 {{ stats(records, '进度百分比').avg | round(1) }}%；合同总额合计 {{ stats(records, '合同金额_万元').sum | round(2) }} 万元。\n"
            "{% set doing = records | selectattr('项目状态', 'equalto', '进行中') | list %}\n"
            "进行中项目 {{ doing | length }} 个，是下一阶段交付管理的主要对象，风险项与资源需求详见下文分析。\n"
            "\n"
            "## 一、项目概览\n"
            "\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 项目总数 | {{ records | length }} |\n"
            "| 已交付项目数 | {{ stats(records, '实际交付日期').non_empty }} |\n"
            "| 未交付项目数 | {{ records | length - stats(records, '实际交付日期').non_empty }} |\n"
            "| 合同总额（万元） | {{ stats(records, '合同金额_万元').sum | round(2) }} |\n"
            "| 平均进度 | {{ stats(records, '进度百分比').avg | round(1) }}% |\n"
            "\n"
            "## 二、按项目状态统计\n"
            "\n"
            "| 项目状态 | 项目数 | 平均进度 |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '项目状态', '进度百分比') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.avg | round(1) }}% |\n"
            "{% endfor %}"
            "\n"
            "对进行中且进度偏低的项目，应结合备注列的原因说明逐项确认恢复时间；涉及客户方变更的项目建议升级沟通并固化变更流程，避免逾期交付。\n"
            "\n"
            "## 三、按片区汇总\n"
            "\n"
            "| 片区 | 项目数 | 合同金额（万元） |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '片区', '合同金额_万元') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum | round(2) }} |\n"
            "{% endfor %}"
            "\n"
            "片区维度上，合同金额与项目数量分布并不均衡；资源投入应向项目集中、交付压力大的片区倾斜。\n"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 交付风险：对未交付且进度低于 50% 的项目建立风险清单，明确责任人与恢复计划，每周更新状态。\n"
            "2. 客户协同：备注中涉及客户需求变更或组织调整的项目，建议升级至客户高层沟通，并固化变更流程。\n"
            "3. 资源调配：结合片区合同金额与项目阶段分布动态调整实施人力，优先保障临近计划交付日期的项目。\n"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
    {
        "workspace": "项目管理",
        "table": "WBS任务分解",
        "extra_tables": [],
        "name": "WBS任务进度周报",
        "description": "顶层/子任务结构概览，按任务状态与优先级多维统计进度与工期",
        "output_format": "docx",
        "theme": "engineering",
        "content": (
            "# WBS 任务进度周报\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "{% set root_tasks = records | selectattr('父任务ID', 'equalto', 'ROOT') | list %}\n"
            "{% set done_count = records | selectattr('任务状态', 'equalto', '已完成') | list | length %}\n"
            "本期跟踪 WBS 任务共 {{ records | length }} 项，其中顶层任务 {{ root_tasks | length }} 项；总工期 {{ stats(records, '工期_天').sum }} 天，整体平均进度 {{ stats(records, '进度百分比').avg | round(1) }}%。\n"
            "已完成任务 {{ done_count }} 项，完成率 {{ '%.1f%%' | format(done_count / records | length * 100) if records else 'N/A' }}；进度结构详见下文分组统计。\n"
            "\n"
            "## 一、任务概览\n"
            "\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 任务总数 | {{ records | length }} |\n"
            "| 顶层任务数 | {{ records | selectattr('父任务ID', 'equalto', 'ROOT') | list | length }} |\n"
            "| 总工期（天） | {{ stats(records, '工期_天').sum }} |\n"
            "| 平均进度 | {{ stats(records, '进度百分比').avg | round(1) }}% |\n"
            "\n"
            "## 二、按任务状态统计\n"
            "\n"
            "| 任务状态 | 任务数 | 平均进度 |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '任务状态', '进度百分比') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.avg | round(1) }}% |\n"
            "{% endfor %}"
            "\n"
            "建议对进行中任务按周核对进度偏差；对尚未启动的任务确认前置条件与依赖关系是否就绪，避免关键路径出现断点。\n"
            "\n"
            "## 三、按优先级统计\n"
            "\n"
            "| 优先级 | 任务数 | 工期合计（天） |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '优先级', '工期_天') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum }} |\n"
            "{% endfor %}"
            "\n"
            "高优先级任务的工期占比直接影响关键路径；建议将资源优先投向高优先级与长工期任务，降低整体延期风险。\n"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 关键路径：围绕高优先级顶层任务复核关键路径，工期偏差超过一周的任务需说明原因并给出赶工方案。\n"
            "2. 任务闭环：已完成任务及时归档经验，进行中任务保持周度进度刷新，避免进度数据失真。\n"
            "3. 依赖管理：跨任务依赖较多时，在周例会上对齐上下游交付物，减少等待与返工。\n"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
    {
        "workspace": "某地区数据",
        "table": "气温天气",
        "extra_tables": [],
        "name": "城市气温天气月报",
        "description": "全局极值与分城市最高/最低气温、平均湿度嵌套分组统计，附城市明细",
        "output_format": "pdf",
        "theme": "academic",
        "parameters": [
            {"name": "城市", "type": "string", "default": "全部", "required": False, "label": "明细筛选城市"}
        ],
        "content": (
            "# 城市气温天气月报\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "{% set city_groups = group_stats(records, '城市', '最高温_℃') %}\n"
            "本月共收录 {{ records | length }} 条城市气温观测记录，覆盖 {{ city_groups | length }} 个城市；全局最高气温 {{ stats(records, '最高温_℃').max }}℃，最低气温 {{ stats(records, '最低温_℃').min }}℃，平均湿度 {{ stats(records, '湿度_%').avg | round(1) }}%。\n"
            "{% if city_groups %}\n"
            "{% set hot_city = city_groups | rejectattr('max', 'none') | sort(attribute='max', reverse=true) | first %}\n"
            "{% set cold_city = city_groups | rejectattr('min', 'none') | sort(attribute='min') | first %}\n"
            "分城市看，「{{ hot_city.key }}」观测到全月最高气温 {{ hot_city.max }}℃，「{{ cold_city.key }}」最低气温低至 {{ cold_city.min }}℃；城市间差异详见第二节。\n"
            "{% endif %}\n"
            "\n"
            "## 一、总体概况\n"
            "\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 记录条数 | {{ records | length }} |\n"
            "| 覆盖城市数 | {{ group_stats(records, '城市', '最高温_℃') | length }} |\n"
            "| 全局最高气温（℃） | {{ stats(records, '最高温_℃').max }} |\n"
            "| 全局最低气温（℃） | {{ stats(records, '最低温_℃').min }} |\n"
            "| 平均湿度（%） | {{ stats(records, '湿度_%').avg | round(1) }} |\n"
            "\n"
            "## 二、分城市统计\n"
            "\n"
            "| 城市 | 记录数 | 最高气温（℃） | 最低气温（℃） | 平均湿度（%） |\n"
            "| --- | --- | --- | --- | --- |\n"
            "{% for g in group_stats(records, '城市', '最高温_℃') %}"
            "{% set g_low = group_stats(records, '城市', '最低温_℃') | selectattr('key', 'equalto', g.key) | list %}"
            "{% set g_hum = group_stats(records, '城市', '湿度_%') | selectattr('key', 'equalto', g.key) | list %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.max }} | {{ g_low[0].min if g_low else 'N/A' }} | {{ g_hum[0].avg | round(1) if g_hum else 'N/A' }} |\n"
            "{% endfor %}"
            "\n"
            "城市间气温与湿度差异显著，跨区域业务安排（物流、出行、用能）应参考城市级数据而非全局均值；对极值城市建议补充风速与湿度交叉分析。\n"
            "\n"
            "## 三、天气类型分布\n"
            "\n"
            "| 天气 | 天数 |\n"
            "| --- | --- |\n"
            "{% for g in group_stats(records, '天气', '最高温_℃') %}"
            "| {{ g.key }} | {{ g.count }} |\n"
            "{% endfor %}"
            "\n"
            "天气类型统计可与气温极值交叉验证：极端天气对应日期的观测值建议复核原始记录，确保月度统计口径一致。\n"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 极值监测：全月气温极值均可在附录明细中定位到具体日期，建议对极值日记录做原始数据复核。\n"
            "2. 城市对比：分城市温差显著，区域运营决策应基于城市级统计，避免全局均值掩盖局部特征。\n"
            "3. 数据质量：发现单日观测值异常偏高或偏低时，应回溯原始记录并在下期报告中标注修正情况。\n"
            "\n"
            "## 附录：城市明细（前 10 条）\n"
            "\n"
            "{% set city = params.get('城市', '全部') %}\n"
            "{% if city == '全部' %}{% set scoped = records %}"
            "{% else %}{% set scoped = records | selectattr('城市', 'equalto', city) | list %}{% endif %}\n"
            "统计范围：{{ city }}\n"
            "\n"
            "| 城市 | 天气 | 最高温_℃ | 最低温_℃ | 湿度_% |\n"
            "| --- | --- | --- | --- | --- |\n"
            "{% for r in scoped[:10] %}"
            "| {{ r['城市'] }} | {{ r['天气'] }} | {{ r['最高温_℃'] }} | {{ r['最低温_℃'] }} | {{ r['湿度_%'] }} |\n"
            "{% endfor %}"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
    {
        "workspace": "低质量数据",
        "table": "19-特殊值杂项",
        "extra_tables": ["17-数字格式大全"],
        "name": "数据质量体检报告",
        "description": "按字段统计非空条数与完整率，覆盖 JSON/长号等特殊值、跨工作区抽检与多表附加检查",
        "output_format": "docx",
        "theme": "academic",
        "cross_workspace_tables": [("某地区数据", "气温天气")],
        "content": (
            "# 数据质量体检报告\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "本次体检覆盖主表「特殊值杂项」（{{ records | length }} 条记录）与附加表「数字格式大全」，并对跨工作区表「气温天气」进行了抽检；重点核查 JSON、邮箱、手机号、长文本与混合数值等字段的完整率。\n"
            "总体来看，邮箱、手机号等结构化字段完整率保持在较高水平，空值主要集中于文本类可选字段；完整率明细与改进建议见下文。\n"
            "\n"
            "## 一、主表完整性检查（特殊值杂项）\n"
            "\n"
            "| 字段 | 非空条数 | 记录总数 | 完整率 |\n"
            "| --- | --- | --- | --- |\n"
            "{% for f in ['JSON对象', '邮箱', '手机号', '客户备注', '混合数值'] %}"
            "{% set s = stats(records, f) %}"
            "| {{ f }} | {{ s.non_empty }} | {{ records | length }} | {{ '%.1f%%' | format(s.non_empty / records | length * 100) if records else 'N/A' }} |\n"
            "{% endfor %}"
            "\n"
            "混合数值合计：{{ stats(records, '混合数值').sum | round(2) }}\n"
            "\n"
            "从完整率分布看，结构化字段（邮箱/手机号）完整率普遍高于自由文本字段，符合录入习惯特征；空值集中的字段建议在表单层面区分必填与选填，减少无意义空值。\n"
            "\n"
            "## 二、附加表完整性检查（数字格式大全）\n"
            "\n"
            "{% if records_by_table['17-数字格式大全'] %}"
            "{% set extra_records = records_by_table['17-数字格式大全'] %}"
            "| 字段 | 非空条数 | 记录总数 |\n"
            "| --- | --- | --- |\n"
            "{% for f in ['千分位整数', '科学计数法', '前导零编号', '十五位长号'] %}"
            "{% set s = stats(extra_records, f) %}"
            "| {{ f }} | {{ s.non_empty }} | {{ extra_records | length }} |\n"
            "{% endfor %}"
            "数字格式类字段完整率良好，说明导入端对千分位、科学计数法等格式的解析稳定；后续新增格式时应同步补充本节检查项。\n"
            "{% else %}附加表无数据{% endif %}\n"
            "\n"
            "## 三、跨工作区抽检（某地区数据/气温天气）\n"
            "\n"
            "{% if records_by_table['气温天气'] %}"
            "{% set wx = records_by_table['气温天气'] %}"
            "| 字段 | 非空条数 | 记录总数 | 完整率 |\n"
            "| --- | --- | --- | --- |\n"
            "{% for f in ['城市', '天气', '最高温_℃', '最低温_℃'] %}"
            "{% set s = stats(wx, f) %}"
            "| {{ f }} | {{ s.non_empty }} | {{ wx | length }} | {{ '%.1f%%' | format(s.non_empty / wx | length * 100) if wx else 'N/A' }} |\n"
            "{% endfor %}"
            "跨工作区抽检与主表使用同一套统计口径，结果可直接比较；若抽检完整率明显低于主表，应优先排查导入映射环节。\n"
            "{% else %}跨工作区数据不可用{% endif %}\n"
            "\n"
            "## 四、检查说明\n"
            "\n"
            "- 完整率 100% 表示该字段全部记录非空；\n"
            "- 非空计数按原始值统计（None 与空串视为空），与前端报表统计口径一致；\n"
            "- 数字格式类字段仅检查存在性，不校验格式合法性。\n"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 完整率治理：对完整率低于 100% 的字段建立补录清单，明确责任人与时限，避免长期积累。\n"
            "2. 录入规范：在表单与导入模板中区分必填与选填字段，并对邮箱、手机号等结构化字段开启格式校验。\n"
            "3. 巡检机制：将本报告纳入数据治理例行巡检，按周生成并跟踪完整率变化趋势。\n"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
    {
        "workspace": "某企业销售管理",
        "table": "日常待办",
        "extra_tables": [],
        "name": "日常待办任务清单",
        "description": "按状态/优先级/类型多维统计销售团队待办任务，附高优先级任务明细（html 输出）",
        "output_format": "html",
        "theme": "modern",
        "content": (
            "# 日常待办任务清单\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "{% set done_count = records | selectattr('状态', 'equalto', '已完成') | list | length %}\n"
            "本期清单共 {{ records | length }} 项任务，其中已完成 {{ done_count }} 项、进行中 {{ records | selectattr('状态', 'equalto', '进行中') | list | length }} 项、待办 {{ records | selectattr('状态', 'equalto', '待办') | list | length }} 项、已取消 {{ records | selectattr('状态', 'equalto', '已取消') | list | length }} 项，整体完成率 {{ '%.1f%%' | format(done_count / records | length * 100) if records else 'N/A' }}。\n"
            "高优先级任务共 {{ records | selectattr('优先级', 'equalto', '高') | list | length }} 项，是本期资源投入的重点，明细见第四节。\n"
            "\n"
            "## 一、任务概览\n"
            "\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 任务总数 | {{ records | length }} |\n"
            "| 已完成 | {{ records | selectattr('状态', 'equalto', '已完成') | list | length }} |\n"
            "| 进行中 | {{ records | selectattr('状态', 'equalto', '进行中') | list | length }} |\n"
            "| 待办 | {{ records | selectattr('状态', 'equalto', '待办') | list | length }} |\n"
            "| 已取消 | {{ records | selectattr('状态', 'equalto', '已取消') | list | length }} |\n"
            "| 高优先级任务数 | {{ records | selectattr('优先级', 'equalto', '高') | list | length }} |\n"
            "\n"
            "## 二、按优先级统计\n"
            "\n"
            "| 优先级 | 任务数 | 占比 |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '优先级', '优先级') %}"
            "| {{ g.key }} | {{ g.count }} | {{ '%.1f%%' | format(g.count / records | length * 100) if records else 'N/A' }} |\n"
            "{% endfor %}"
            "\n"
            "优先级分布反映了团队精力投放结构；若高优先级占比持续偏高，建议评估任务分级标准是否过松，避免「全都紧急」导致优先级失效。\n"
            "\n"
            "## 三、按任务类型统计\n"
            "\n"
            "| 任务类型 | 任务数 | 已完成数 |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '待办类型', '优先级') %}"
            "{% set done = records | selectattr('待办类型', 'equalto', g.key) | selectattr('状态', 'equalto', '已完成') | list | length %}"
            "| {{ g.key }} | {{ g.count }} | {{ done }} |\n"
            "{% endfor %}"
            "\n"
            "任务类型的完成率差异能暴露流程堵点：完成率明显偏低的类型通常是资源或依赖不足的环节，应优先安排对接与跟进。\n"
            "\n"
            "## 四、高优先级任务明细\n"
            "\n"
            "{% set high = records | selectattr('优先级', 'equalto', '高') | list %}\n"
            "| 待办编号 | 待办标题 | 待办类型 | 状态 | 截止日期 | 备注 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "{% for r in high %}"
            "| {{ r['待办编号'] }} | {{ r['待办标题'] }} | {{ r['待办类型'] }} | {{ r['状态'] }} | {{ r['截止日期'] }} | {{ r['备注'] or '-' }} |\n"
            "{% endfor %}"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 重点保障：高优先级任务按截止日期倒排计划，明确每日跟进人，避免临近截止集中突击。\n"
            "2. 状态维护：任务完成后及时更新状态与完成日期，保持清单与实际进展一致，便于复盘。\n"
            "3. 类型均衡：对完成率偏低的任务类型复盘原因（依赖、资源或流程），必要时拆分为更小的可执行任务。\n"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
    {
        "workspace": "某企业销售管理",
        "table": "营销活动",
        "extra_tables": [],
        "name": "营销活动效果报告",
        "description": "汇总营销活动预算/线索/转化率，按渠道与状态分组，附重点活动明细（html 输出）",
        "output_format": "html",
        "theme": "business",
        "content": (
            "# 营销活动效果报告\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "{% set budget_sum = stats(records, '预算_元').sum %}\n"
            "{% set spend_sum = stats(records, '实际花费_元').sum %}\n"
            "{% set leads_sum = stats(records, '线索数').sum %}\n"
            "本期共复盘营销活动 {{ records | length }} 场（其中重点活动 {{ records | selectattr('是否重点', 'equalto', '是') | list | length }} 场），预算合计 {{ budget_sum | round(0) | int }} 元、实际花费 {{ spend_sum | round(0) | int }} 元，预算执行率 {{ '%.1f%%' | format(spend_sum / budget_sum * 100) if budget_sum else 'N/A' }}；累计获取线索 {{ leads_sum | round(0) | int }} 条，平均转化率 {{ stats(records, '转化率_%').avg | round(2) }}%。\n"
            "{% if leads_sum %}\n"
            "平均单线索成本约 {{ (spend_sum / leads_sum) | round(2) }} 元，可结合各渠道转化率评估投放结构的优化空间。\n"
            "{% endif %}\n"
            "\n"
            "## 一、总体效果概览\n"
            "\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 活动总数 | {{ records | length }} |\n"
            "| 重点活动数 | {{ records | selectattr('是否重点', 'equalto', '是') | list | length }} |\n"
            "| 预算合计（元） | {{ stats(records, '预算_元').sum | round(0) | int }} |\n"
            "| 实际花费合计（元） | {{ stats(records, '实际花费_元').sum | round(0) | int }} |\n"
            "| 线索总数 | {{ stats(records, '线索数').sum | round(0) | int }} |\n"
            "| 平均转化率（%） | {{ stats(records, '转化率_%').avg | round(2) }} |\n"
            "\n"
            "## 二、按渠道类型统计\n"
            "\n"
            "| 渠道类型 | 活动数 | 预算合计（元） | 线索合计 |\n"
            "| --- | --- | --- | --- |\n"
            "{% for g in group_stats(records, '渠道类型', '预算_元') %}"
            "{% set gl = group_stats(records, '渠道类型', '线索数') | selectattr('key', 'equalto', g.key) | list %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum | round(0) | int }} | {{ gl[0].sum | int if gl else 0 }} |\n"
            "{% endfor %}"
            "\n"
            "渠道评估应同时看线索量与单线索成本：线索量大的渠道若成本同步走高，需关注线索质量；小渠道转化率突出时可考虑加大测试预算。\n"
            "\n"
            "## 三、按活动状态统计\n"
            "\n"
            "| 活动状态 | 活动数 | 预算合计（元） |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '活动状态', '预算_元') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum | round(0) | int }} |\n"
            "{% endfor %}"
            "\n"
            "进行中与已排期的活动需按周同步进展，避免预算沉淀在低效活动上；已结束活动应及时沉淀复盘结论并归档素材。\n"
            "\n"
            "## 四、重点活动明细\n"
            "\n"
            "{% set key_acts = records | selectattr('是否重点', 'equalto', '是') | list %}\n"
            "| 活动编号 | 活动名称 | 渠道类型 | 负责人 | 联系邮箱 | 活动页面 | 预算（元） | 线索数 | 转化率（%） |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "{% for r in key_acts %}"
            "| {{ r['活动编号'] }} | {{ r['活动名称'] }} | {{ r['渠道类型'] }} | {{ r['负责人'] }} "
            "| {{ r['负责人邮箱'] }} | {{ r['活动页面'] }} | {{ r['预算_元'] }} | {{ r['线索数'] }} | {{ r['转化率_%'] }} |\n"
            "{% endfor %}"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 投放结构：以单线索成本与转化率双指标评估各渠道，向「低成本、高转化」渠道倾斜预算，收缩长期低效渠道。\n"
            "2. 活动复盘：已结束活动在两周内完成复盘并归档素材，沉淀可复用的活动模板与话术。\n"
            "3. 线索承接：高线索量活动应提前准备销售承接方案，明确响应时限，避免线索流失。\n"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
]


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
    # kanban 的 group_field / calendar 的 start_field / kanban/gantt/wbs 的 title_field 等
    vo = vc.get("view_options", {})
    for opt_key in (
        "group_field",
        "start_field",
        "end_field",
        "title_field",
        "start_date_field",
        "end_date_field",
        "actual_end_field",
        "progress_field",
        "assignee_field",
    ):
        opt_val = vo.get(opt_key)
        if opt_val and opt_val not in valid_fields:
            print(
                f"[seed-视图] 跳过: {ws_name}/{table_name} 视图'{view_name}' "
                f"的 view_options.{opt_key}='{opt_val}' 不存在"
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
                    dv_payload = {
                        "table_id": dt.id,
                        "owner_id": user.id,
                        "name": vc["name"],
                        "view_type": vc.get("view_type", "grid"),
                        "filter_type": vc.get("filter_type", "AND"),
                        "filters": vc.get("filters", []),
                        "sortings": vc.get("sortings", []),
                        "field_options": vc.get("field_options", {}),
                        "field_order": vc.get("field_order", []),
                        "view_options": vc.get("view_options", {}),
                        "is_default": vc.get("is_default", False),
                        "order": vc.get("order", idx),
                    }
                    # 同名视图已存在则用配置更新（自动生成的「全部」默认视图需要被丰富化）
                    existing = (
                        db.query(DataView).filter(DataView.table_id == dt.id, DataView.name == vc["name"]).first()
                    )
                    if existing is not None:
                        for key, value in dv_payload.items():
                            setattr(existing, key, value)
                        db.flush()
                        print(
                            f"[seed-视图] 更新已存在: {ws_name}/{table_name} → {dv_payload['name']} ({dv_payload['view_type']})"
                        )
                        continue
                    dv = DataView(**dv_payload)
                    db.add(dv)
                    db.flush()
                    created += 1
                    print(f"[seed-视图] {ws_name}/{table_name} → {dv.name} ({dv.view_type})")
                except Exception as exc:  # 单视图失败不阻断其它
                    db.rollback()
                    print(f"[seed-视图] 跳过: {ws_name}/{table_name} / {vc.get('name', '<无>')}: {exc}")

    db.commit()
    return created


def seed(_args: argparse.Namespace) -> None:
    """向数据库注入演示数据（datasets CSV + 硬编码业务表 + 视图种子 + 三员演示账号）."""
    from cndb.core.database import SessionLocal, engine
    from cndb.core.plugin_registry import plugin_registry
    from cndb.models.base import Base
    from cndb.plugins.accounts.models import User, UserRole

    # 触发所有插件 register_models，确保 Base.metadata 完整注册
    plugin_registry.discover_and_load()

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    # 补写 alembic_version（seed 自行建表绕过了迁移），避免 serve 启动时
    # ensure_db_migrated 误判为"半迁移库"而重放建表迁移报 table already exists
    from cndb.core.migrations import stamp_head

    stamp_head()
    db = SessionLocal()
    try:
        # 用户 —— 三员账号（GB/T 22239 等级保护模型）+ 1 个普通用户示例
        # 系统管理员（同时是超级管理员，用于首次安装时的初始管理员）
        admin = User(
            username="admin",
            email="admin@example.com",
            nickname="系统管理员",
            role=UserRole.SYSTEM_ADMIN.value,
            is_superuser=True,
        )
        admin.set_password("admin1234")
        db.add(admin)
        db.commit()
        db.refresh(admin)
        print("[seed] 创建用户: admin / admin1234  (角色: 系统管理员 + 超级管理员)")

        # 安全管理员
        sec_admin = User(
            username="sec_admin",
            email="sec_admin@example.com",
            nickname="安全管理员",
            role=UserRole.SECURITY_ADMIN.value,
        )
        sec_admin.set_password("sec1234")
        db.add(sec_admin)
        db.commit()
        db.refresh(sec_admin)
        print("[seed] 创建用户: sec_admin / sec1234  (角色: 安全管理员)")

        # 审计管理员
        audit_admin = User(
            username="audit_admin",
            email="audit_admin@example.com",
            nickname="审计管理员",
            role=UserRole.AUDIT_ADMIN.value,
        )
        audit_admin.set_password("audit1234")
        db.add(audit_admin)
        db.commit()
        db.refresh(audit_admin)
        print("[seed] 创建用户: audit_admin / audit1234  (角色: 审计管理员)")

        # 普通用户（示例）
        demo = User(
            username="demo",
            email="demo@example.com",
            nickname="演示用户",
            role=UserRole.USER.value,
        )
        demo.set_password("demo1234")
        db.add(demo)
        db.commit()
        db.refresh(demo)
        print("[seed] 创建用户: demo / demo1234  (角色: 普通用户)")

        # 用 admin 作为后续数据的所有者（超级管理员最合理）
        owner = admin

        # 1) datasets CSV：每个子文件夹 → 工作区，每个 CSV → 数据表
        csv_count, ws_map, tables_map = _seed_datasets(db, engine, owner)

        # 2) 硬编码业务表挂到 "某企业销售管理" 工作区
        extra = 0
        sales_ws = ws_map.get("某企业销售管理")
        if sales_ws is not None:
            print(f"[seed] 在工作区 '{sales_ws.name}' 下扩展部门/员工业务表")
            extra, extra_tables = _seed_sales_tables(db, engine, sales_ws, owner_id=owner.id)
            tables_map.setdefault("某企业销售管理", {}).update(extra_tables)
        else:
            print("[seed] 未找到 '某企业销售管理' 工作区，跳过部门表/员工表注入")

        # 2b) 字段设置种子（依赖所有表已就绪，含硬编码业务表；扫描每个工作区文件夹下的 fields.json）
        datasets_dir = _get_datasets_dir()
        _apply_field_settings(db, engine, tables_map, datasets_dir)

        # 3) 视图种子（依赖所有表已就绪，扫描每个工作区文件夹下的 views.json）
        view_count = _seed_views(db, owner, tables_map, datasets_dir)

        # 4) 报告模板种子（幂等：按工作区+模板名查重，已存在跳过）
        _seed_report_templates(db, tables_map)

        # 4b) 示例报告生成：渲染"科研项目季度汇报"落盘到数据集目录
        _generate_sample_reports(db, tables_map, owner, datasets_dir)

        # 5) 为"某企业销售管理"工作区添加其他演示成员，使表权限设置能看到可添加的候选成员
        from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole

        sales_ws = ws_map.get("某企业销售管理")
        if sales_ws is not None:
            extra_members = [
                (sec_admin, WorkspaceRole.ADMIN, "安全管理员"),
                (audit_admin, WorkspaceRole.EDITOR, "审计管理员"),
                (demo, WorkspaceRole.VIEWER, "演示用户"),
            ]
            for u, role, label in extra_members:
                db.add(WorkspaceMember(workspace_id=sales_ws.id, user_id=u.id, role=role))
                print(f"[seed] 添加工作区成员: {label} → {sales_ws.name} ({role.value})")
            db.commit()

        total = csv_count + extra
        print(
            f"[seed] 完成！共 {total} 张数据表、{view_count} 个视图、4 个演示账号（三员 + 普通用户）。"
            "\n登录账号："
            "\n  系统管理员: admin / admin1234"
            "\n  安全管理员: sec_admin / sec1234"
            "\n  审计管理员: audit_admin / audit1234"
            "\n  普通用户:   demo / demo1234"
        )
    finally:
        db.close()
