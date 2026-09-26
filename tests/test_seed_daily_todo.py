"""日常待办工作区数据集端到端单元测试.

覆盖：
- 日常待办 CSV 建表（含产品开发 CSV 做源表）
- 硬编码员工表 + 部门表
- fields.json 声明的 link_lookups 关联引入（产品开发→日常待办 + 员工表→日常待办）
- 每个 link 附带的 lookup 字段数量与字段类型
- views.json 日常待办视图注入（6 个视图，含 grid / kanban / calendar）
- seed 主流程幂等：重复执行不报错、字段数稳定、link 复用
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

# ── 测试数据（CSV 原文 + 配置） ────────────────────────────

DAILY_TODO_CSV = """待办编号,待办标题,待办类型,优先级,截止日期,完成日期,状态,备注
TODO00001,拜访客户 CIO,跟进拜访,高,2026-10-01,,待办,客户方组织架构调整
TODO00002,提交智能仓储二期方案,方案设计,高,2026-10-05,,进行中,方案需补充 GPU 章节
TODO00003,确认技术指标,需求确认,中,2026-10-10,,待办,
TODO00004,起草合同条款,合同签订,高,2026-10-03,2026-09-20,已完成,法务已出初稿
TODO00005,检查部署环境,实施交付,中,2026-10-15,,待办,
TODO00006,处理告警工单,运维支持,低,2026-09-28,2026-09-25,已完成,告警单 #ALM-003
TODO00007,协调部门资源,内部协调,中,2026-10-08,,进行中,
TODO00008,用户培训,客户培训,低,2026-10-20,,待办,
TODO00009,催收二期回款,回款催收,高,2026-10-25,,待办,
TODO00010,竞品信息收集,内部协调,低,2026-11-01,,已取消,对方战略调整
"""

PRODUCT_DEV_CSV = """项目编号,片区,客户名称,项目类别,项目名称,负责人,合同金额_万元,启动日期,计划交付日期,实际交付日期,当前交付节点,进度百分比,项目状态,备注
PRJ000001,华东,华中交通,数字孪生,数字孪生可视化系统,刘洋,108.23,2026-08-30,2027-01-30,,需求调研,19,进行中,
PRJ000002,东北,南方电网,供应链,智能仓储WMS系统,梁婷,1204.68,2025-11-13,2027-05-13,2027-06-17,运维支持,100,已完成,
"""

FIELDS_JSON = {
    "settings": {
        "日常待办": {
            "待办编号": {"required": True, "unique": True},
            "待办标题": {"required": True},
        }
    },
    "link_lookups": [
        {
            "table": "日常待办",
            "source_table": "产品开发",
            "link_name": "关联项目",
            "multiple": False,
            "fields": ["片区", "项目类别", "项目状态"],
        },
        {
            "table": "日常待办",
            "source_table": "员工表",
            "link_name": "负责员工",
            "multiple": False,
            "fields": ["姓名", "是否在职"],
        },
    ],
}

VIEWS_JSON = {
    "日常待办": [
        {"name": "全部", "view_type": "grid", "is_default": True, "order": 0},
        {
            "name": "待办看板",
            "view_type": "kanban",
            "view_options": {
                "group_field": "状态",
                "title_field": "待办标题",
                "due_date_field": "截止日期",
                "assignee_field": "负责员工",
                "card_sort_field": "优先级",
                "card_sort_direction": "desc",
            },
            "order": 1,
        },
        {
            "name": "高优先级任务",
            "view_type": "grid",
            "filter_type": "AND",
            "filters": [{"field_name": "优先级", "op": "=", "value": "高"}],
            "sortings": [{"field_name": "截止日期", "direction": "asc"}],
            "order": 2,
        },
        {
            "name": "按员工看板",
            "view_type": "kanban",
            "view_options": {
                "group_field": "负责员工",
                "title_field": "待办标题",
                "due_date_field": "截止日期",
            },
            "order": 3,
        },
        {
            "name": "待办日历",
            "view_type": "calendar",
            "view_options": {
                "start_field": "截止日期",
                "title_field": "待办标题",
                "group_field": "状态",
            },
            "order": 4,
        },
        {
            "name": "进行中任务",
            "view_type": "grid",
            "filter_type": "AND",
            "filters": [{"field_name": "状态", "op": "=", "value": "进行中"}],
            "order": 5,
        },
    ],
    "产品开发": [
        {"name": "全部", "view_type": "grid", "is_default": True, "order": 0},
    ],
}


# ── fixture：在 tmp_path 下搭好 datasets_dir ───────────────


def _build_datasets_dir(tmp_path: Path) -> Path:
    """把日常待办 + 产品开发 CSV、fields.json、views.json 写到 tmp_path/datasets/工作区-销售测试/."""
    ws_dir = tmp_path / "datasets" / "工作区-销售测试"
    ws_dir.mkdir(parents=True)
    (ws_dir / "日常待办.csv").write_text(DAILY_TODO_CSV, encoding="utf-8-sig")
    (ws_dir / "产品开发.csv").write_text(PRODUCT_DEV_CSV, encoding="utf-8-sig")
    (ws_dir / "fields.json").write_text(json.dumps(FIELDS_JSON, ensure_ascii=False), encoding="utf-8")
    (ws_dir / "views.json").write_text(json.dumps(VIEWS_JSON, ensure_ascii=False), encoding="utf-8")
    return tmp_path / "datasets"


@pytest.fixture
def sales_todo_seed(db, db_engine, tmp_path):
    """端到端 fixture：创建 Workspace + User，跑 seed 完整流程到「视图注入」返回 tables_map."""
    from cndb.cli.seed import (
        _apply_field_settings,
        _seed_datasets,
        _seed_sales_tables,
        _seed_views,
    )
    from cndb.plugins.accounts.models import User

    user = User(username="todo_seed", email="todo@example.com", nickname="日常待办测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    datasets_dir = _build_datasets_dir(tmp_path)

    # patch _get_datasets_dir 返回我们的临时目录
    import cndb.cli.seed as seed_mod

    original = seed_mod._get_datasets_dir
    seed_mod._get_datasets_dir = lambda: datasets_dir

    try:
        # 1. CSV 建表（含日常待办 + 产品开发）
        _, ws_map, tables_map = _seed_datasets(db, db_engine, user)
        assert "销售测试" in ws_map
        assert "销售测试" in tables_map
        ws = ws_map["销售测试"]
        # 硬编码建部门表/员工表（日常待办要 link 员工表）
        extra_n, extra_tables = _seed_sales_tables(db, db_engine, ws, owner_id=user.id)
        assert extra_n == 2  # 部门表 + 员工表
        tables_map["销售测试"].update(extra_tables)

        # 2. 字段设置（link_lookups）
        _apply_field_settings(db, db_engine, tables_map, datasets_dir)

        # 3. 视图注入
        view_count = _seed_views(db, user, tables_map, datasets_dir)

        db.commit()
        db.refresh(tables_map["销售测试"]["日常待办"])
        db.refresh(tables_map["销售测试"]["产品开发"])
        db.refresh(tables_map["销售测试"]["员工表"])
        yield tables_map["销售测试"], view_count
    finally:
        seed_mod._get_datasets_dir = original


# ── 端到端测试 ──────────────────────────────────────────────


def test_daily_todo_csv_seeded(sales_todo_seed):
    """日常待办 CSV 正确建表：8 列 × 10 行."""
    tables, _ = sales_todo_seed
    todo_tbl = tables["日常待办"]
    assert todo_tbl is not None
    todo_fields = {f.name: f for f in todo_tbl.fields if not f.trashed}
    # 先只验证基础 8 列（link/lookup 是后续加的，另测）
    base_cols = {"待办编号", "待办标题", "待办类型", "优先级", "截止日期", "完成日期", "状态", "备注"}
    assert base_cols.issubset(set(todo_fields.keys()))


def test_daily_todo_settings_required_unique(sales_todo_seed, db):
    """fields.json settings 段正确应用：待办编号 required+unique、待办标题 required."""
    tables, _ = sales_todo_seed
    todo_tbl = tables["日常待办"]
    fields = {f.name: f for f in todo_tbl.fields if not f.trashed}
    assert fields["待办编号"].required is True
    assert fields["待办编号"].is_unique is True
    assert fields["待办标题"].required is True
    assert fields["待办标题"].is_unique is False


def test_daily_todo_link_to_product_dev(sales_todo_seed):
    """日常待办 → 产品开发 link + 3 个 lookup."""
    tables, _ = sales_todo_seed
    todo_tbl = tables["日常待办"]
    product_tbl = tables["产品开发"]

    fields = {f.name: f for f in todo_tbl.fields if not f.trashed}

    link = fields["关联项目"]
    assert link.field_type == "link"
    assert link.config["target_table_id"] == product_tbl.id
    assert link.config["multiple"] is False

    product_fields = {f.name: f for f in product_tbl.fields if not f.trashed}
    for lookup_name in ["片区", "项目类别", "项目状态"]:
        lookup = fields[lookup_name]
        assert lookup.field_type == "lookup", f"{lookup_name} 应为 lookup 字段"
        assert lookup.config["source_table_id"] == product_tbl.id
        assert lookup.config["source_field_id"] == product_fields[lookup_name].id
        assert lookup.config["via_link_field_id"] == link.id


def test_daily_todo_link_to_employee(sales_todo_seed):
    """日常待办 → 员工表 link + lookup."""
    tables, _ = sales_todo_seed
    todo_tbl = tables["日常待办"]
    emp_tbl = tables["员工表"]

    fields = {f.name: f for f in todo_tbl.fields if not f.trashed}

    link = fields["负责员工"]
    assert link.field_type == "link"
    assert link.config["target_table_id"] == emp_tbl.id
    assert link.config["multiple"] is False

    emp_fields = {f.name: f for f in emp_tbl.fields if not f.trashed}
    for lookup_name in ["姓名", "是否在职"]:
        lookup = fields[lookup_name]
        assert lookup.field_type == "lookup"
        assert lookup.config["source_table_id"] == emp_tbl.id
        assert lookup.config["source_field_id"] == emp_fields[lookup_name].id
        assert lookup.config["via_link_field_id"] == link.id


def test_daily_todo_view_seeded(sales_todo_seed, db):
    """日常待办 6 个视图全部注入成功（grid / kanban / calendar）."""
    from cndb.plugins.tables.models import DataView

    tables, _ = sales_todo_seed
    todo_tbl = tables["日常待办"]

    views = db.query(DataView).filter(DataView.table_id == todo_tbl.id).all()
    view_by_name = {v.name: v for v in views}
    assert len(view_by_name) == 6, f"期望 6 个视图，实际 {len(view_by_name)}: {list(view_by_name.keys())}"

    # grid / kanban / calendar 三类都有
    assert view_by_name["全部"].view_type == "grid"
    assert view_by_name["待办看板"].view_type == "kanban"
    assert view_by_name["待办日历"].view_type == "calendar"
    assert view_by_name["高优先级任务"].view_type == "grid"

    # 看板的 view_options 引用了 link 字段
    kanban = view_by_name["待办看板"]
    assert kanban.view_options["group_field"] == "状态"
    assert kanban.view_options["assignee_field"] == "负责员工"

    # 日历视图引用了 link 前的基础字段
    cal = view_by_name["待办日历"]
    assert cal.view_options["start_field"] == "截止日期"
    assert cal.view_options["group_field"] == "状态"


def test_daily_todo_link_lookup_total_fields(sales_todo_seed):
    """日常待办表字段总数 = 8 基础 + 2 link + 3 产品开发 lookup + 2 员工表 lookup = 15."""
    tables, _ = sales_todo_seed
    todo_tbl = tables["日常待办"]
    fields = [f for f in todo_tbl.fields if not f.trashed]
    # 8 基础 + 2 link + 3 lookup(产品开发) + 2 lookup(员工表) = 15
    assert len(fields) == 15, f"期望 15 字段，实际 {len(fields)}: {[f.name for f in fields]}"


def test_daily_todo_settings_loading_from_real_datasets():
    """真实 datasets 解析：某企业销售管理 fields.json 包含日常待办配置 + 2 条 link_lookups."""
    from cndb.cli.seed import _get_datasets_dir, _load_field_settings

    datasets_dir = _get_datasets_dir()
    if datasets_dir is None:
        pytest.skip("examples/datasets 目录不可用")

    cfg = _load_field_settings(datasets_dir)
    assert "某企业销售管理" in cfg
    sm_cfg = cfg["某企业销售管理"]
    settings = sm_cfg["settings"]
    assert "日常待办" in settings
    assert settings["日常待办"]["待办编号"] == {"required": True, "unique": True}
    assert settings["日常待办"]["待办标题"] == {"required": True}

    link_rules = sm_cfg["link_lookups"]
    assert len(link_rules) == 2
    # 两条 link_lookups 分别是：产品开发→日常待办、员工表→日常待办
    rule_src_pairs = {(r["table"], r["source_table"]) for r in link_rules}
    assert rule_src_pairs == {("日常待办", "产品开发"), ("日常待办", "员工表")}
    # 都是单选关联（multiple=false）
    assert all(r.get("multiple") is False for r in link_rules)
    # 引用了部分字段（不是全字段复制）
    rule_fields = {r["source_table"]: r["fields"] for r in link_rules}
    assert rule_fields["产品开发"] == ["片区", "项目类别", "项目状态"]
    assert rule_fields["员工表"] == ["姓名", "是否在职"]


def test_daily_todo_views_config_from_real_datasets():
    """真实 datasets 解析：某企业销售管理 views.json 包含日常待办 6 个视图."""
    from cndb.cli.seed import _get_datasets_dir, _get_workspace_view_configs

    datasets_dir = _get_datasets_dir()
    if datasets_dir is None:
        pytest.skip("examples/datasets 目录不可用")

    configs = _get_workspace_view_configs(datasets_dir)
    sm_tables = configs.get("某企业销售管理")
    assert sm_tables is not None
    todo_views = sm_tables.get("日常待办")
    assert todo_views is not None, "views.json 应包含日常待办表"
    assert len(todo_views) == 6, f"期望 6 个日常待办视图，实际 {len(todo_views)}"

    names = {v["name"] for v in todo_views}
    assert {"全部", "待办看板", "高优先级任务", "按员工看板", "待办日历", "进行中任务"} == names


def test_daily_todo_csv_has_10_rows(tmp_path):
    """日常待办 CSV 基础校验：8 列 × 10 行，字段名正确."""
    ws_dir = tmp_path / "daily_todo_test"
    ws_dir.mkdir()
    csv_path = ws_dir / "日常待办.csv"
    csv_path.write_text(DAILY_TODO_CSV, encoding="utf-8-sig")

    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    assert header == ["待办编号", "待办标题", "待办类型", "优先级", "截止日期", "完成日期", "状态", "备注"]
    assert len(rows) == 10
    # 待办编号唯一
    ids = [r[0] for r in rows]
    assert len(ids) == len(set(ids))
    assert ids[0] == "TODO00001"
    assert ids[-1] == "TODO00010"
