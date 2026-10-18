"""科研项目管理「科研待办事项」数据集端到端测试.

覆盖：
- 科研待办事项 CSV 结构（9 列 × 16 行，含 7 行空责任人）
- 真实 datasets 目录解析：fields.json + views.json
- seed 流程：CSV 建表、课题关联字段、settings 应用、views 注入
- kanban 分组：按责任人分组时空值行进入「未分派」分组
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

# ── CSV 原文（与 examples/datasets/工作区-科研项目管理/科研待办事项.csv 一致） ────

TODO_CSV = """编号,类别,事项,创建时间,要求节点,完成日期,责任人,课题编号,备注
TB001,数据,完成多中心影像数据脱敏与入库,2026-09-15,2026-09-30,2026-09-28,毕思嘉,KT2024001,覆盖 3 家医院 1.2 万例
TB002,实验,补充小样本泛化实验,2026-09-18,2026-10-15,,毕思嘉,KT2024001,需覆盖 2 个外部中心
TB003,论文,完成分割模型论文初稿,2026-09-10,2026-10-31,2026-10-08,王建国,KT2024001,目标投 MICCAI 2027
TB004,经费,提交第三季度经费执行报告,2026-09-20,2026-10-10,,,KT2025002,附支出明细与凭证清单
TB005,实验,耐压封装样件送检,2026-09-12,2026-10-20,2026-10-16,卓明远,KT2025002,送第三方检测机构
TB006,沟通,协调海试船舶与作业窗口,2026-09-22,2026-10-12,,,KT2025002,需与海洋调查船队确认档期
TB007,评审,组织电堆集成工艺中期评审,2026-09-14,2026-10-09,2026-10-08,宋立群,KT2025010,评审材料含工艺路线对比
TB008,实验,双极板成型工艺参数复核,2026-09-23,2026-10-18,,,KT2025010,重点复核温度与压力曲线
TB009,归档,整理延期整改佐证材料,2026-09-08,2026-09-30,2026-09-29,石铭轩,KT2025010,按整改清单逐项归档
TB010,数据,建立样地基线数据库,2026-09-25,2026-11-15,,聂子涵,KT2026002,统一字段口径与采样编号
TB011,实验,完成秋季基线土壤采样,2026-09-19,2026-11-30,2026-11-20,常景行,KT2026002,共 48 个样点
TB012,评审,碳汇模型技术路线论证,2026-09-26,2026-11-10,,,KT2026002,邀请外部专家 5 人
TB013,经费,编制 2027 年度经费预算,2026-09-16,2026-10-25,2026-10-20,邱若谷,KT2026002,与任务书指标对齐
TB014,沟通,对接合作单位数据共享协议,2026-09-21,2026-10-30,,,KT2024001,涉及 2 家联合培养单位
TB015,论文,整理专利交底书,2026-09-27,2026-11-05,,,KT2024001,已受理 2 项
TB016,沟通,提交季度进展简报,2026-09-28,2026-10-20,,,KT2025002,按季报规范汇总进展
"""

EXPECTED_HEADER = ["编号", "类别", "事项", "创建时间", "要求节点", "完成日期", "责任人", "课题编号", "备注"]

# 责任人为空的行（空串 + 物理 NULL 统一视为空）
EMPTY_ASSIGNEE_IDS = {"TB004", "TB006", "TB008", "TB012", "TB014", "TB015", "TB016"}

# 非空责任人（看板分组去重）
EXPECTED_ASSIGNEES = {"毕思嘉", "王建国", "卓明远", "宋立群", "石铭轩", "聂子涵", "常景行", "邱若谷"}


def _build_datasets_dir(tmp_path: Path) -> Path:
    """在 tmp_path 下构建仅含科研项目管理 workspace 的临时 datasets 目录."""
    ws_dir = tmp_path / "datasets" / "工作区-科研项目管理"
    ws_dir.mkdir(parents=True)
    (ws_dir / "科研待办事项.csv").write_text(TODO_CSV, encoding="utf-8-sig")
    # 来源课题表：用于验证「关联课题」link + lookup 字段
    (ws_dir / "科研项目.csv").write_text(
        "课题编号,项目名称,项目状态\nKT2024001,医学影像分割算法研究,在研\nKT2025002,深海资源勘探关键技术装备,在研\n",
        encoding="utf-8-sig",
    )
    (ws_dir / "fields.json").write_text(
        json.dumps(
            {
                "settings": {
                    "科研待办事项": {
                        "编号": {"required": True, "unique": True},
                        "事项": {"required": True},
                    }
                },
                "link_lookups": [
                    {
                        "table": "科研待办事项",
                        "source_table": "科研项目",
                        "link_name": "关联课题",
                        "multiple": False,
                        "fields": ["项目名称", "项目状态"],
                        "match": {"local": "课题编号", "source": "课题编号"},
                    }
                ],
                "backfills": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (ws_dir / "views.json").write_text(
        json.dumps(
            {
                "科研待办事项": [
                    {
                        "name": "全部",
                        "view_type": "grid",
                        "sortings": [{"field_name": "要求节点", "direction": "asc"}],
                        "is_default": True,
                        "order": 0,
                    },
                    {
                        "name": "按责任人看板",
                        "view_type": "kanban",
                        "view_options": {
                            "group_field": "责任人",
                            "title_field": "事项",
                            "due_date_field": "要求节点",
                            "card_sort_field": "要求节点",
                            "card_sort_direction": "asc",
                            "ungrouped_label": "未分派",
                        },
                        "order": 1,
                    },
                    {
                        "name": "按类别看板",
                        "view_type": "kanban",
                        "view_options": {
                            "group_field": "类别",
                            "title_field": "事项",
                            "due_date_field": "要求节点",
                            "assignee_field": "责任人",
                            "card_sort_field": "要求节点",
                            "card_sort_direction": "asc",
                        },
                        "order": 2,
                    },
                    {
                        "name": "事项日历",
                        "view_type": "calendar",
                        "view_options": {
                            "start_field": "要求节点",
                            "title_field": "事项",
                            "group_field": "类别",
                        },
                        "order": 3,
                    },
                    {
                        "name": "待分派事项",
                        "view_type": "grid",
                        "filter_type": "AND",
                        "filters": [{"field_name": "责任人", "op": "=", "value": ""}],
                        "sortings": [{"field_name": "要求节点", "direction": "asc"}],
                        "order": 4,
                    },
                    {
                        "name": "未完成事项",
                        "view_type": "grid",
                        "filter_type": "AND",
                        "filters": [{"field_name": "完成日期", "op": "=", "value": ""}],
                        "sortings": [{"field_name": "要求节点", "direction": "asc"}],
                        "order": 5,
                    },
                    {
                        "name": "类别占比",
                        "view_type": "chart",
                        "view_options": {
                            "chart_type": "pie",
                            "dimension_field": "类别",
                            "measure_field": "编号",
                            "aggregation": "count",
                            "show_stats_panel": True,
                        },
                        "order": 6,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return tmp_path / "datasets"


# ── fixture：端到端 seed ──────────────────────────────────


@pytest.fixture
def project_todo_seed(db, db_engine, tmp_path):
    """端到端 fixture：建科研项目管理 workspace，跑 seed 到视图注入，返回 tables_map."""
    from cndb.cli.seed import (
        _apply_field_settings,
        _seed_datasets,
        _seed_views,
    )
    from cndb.plugins.accounts.models import User

    user = User(username="proj_todo", email="proj_todo@example.com", nickname="科研待办测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    datasets_dir = _build_datasets_dir(tmp_path)

    from cndb.cli.seed import paths as seed_paths

    original = seed_paths._get_datasets_dir
    seed_paths._get_datasets_dir = lambda: datasets_dir
    try:
        _, ws_map, tables_map = _seed_datasets(db, db_engine, user)
        # datasets 目录下 workspace 名是「科研项目管理」（剥掉「工作区-」前缀）
        assert "科研项目管理" in ws_map
        assert "科研项目管理" in tables_map

        _apply_field_settings(db, db_engine, tables_map, datasets_dir)
        _seed_views(db, user, tables_map, datasets_dir)

        db.commit()
        db.refresh(tables_map["科研项目管理"]["科研待办事项"])
        yield tables_map["科研项目管理"], user
    finally:
        seed_paths._get_datasets_dir = original


# ── 1. CSV 结构校验 ──────────────────────────────────────


def test_todo_csv_structure(tmp_path):
    """科研待办事项 CSV 基础结构：9 列 × 16 行，字段名符合预期，编号唯一."""
    ws_dir = tmp_path / "csv_check"
    ws_dir.mkdir()
    csv_path = ws_dir / "科研待办事项.csv"
    csv_path.write_text(TODO_CSV, encoding="utf-8-sig")

    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    assert header == EXPECTED_HEADER
    assert len(rows) == 16
    ids = [r[0] for r in rows]
    assert len(ids) == len(set(ids)), "编号应唯一"
    assert ids[0] == "TB001"
    assert ids[-1] == "TB016"


def test_todo_csv_empty_assignee_distribution(tmp_path):
    """CSV 中 7 行责任人为空，覆盖「空值进入未分组」的看板场景."""
    ws_dir = tmp_path / "csv_check2"
    ws_dir.mkdir()
    csv_path = ws_dir / "科研待办事项.csv"
    csv_path.write_text(TODO_CSV, encoding="utf-8-sig")

    with csv_path.open(encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))[1:]

    empty_ids = {r[0] for r in rows if not r[6].strip()}
    non_empty_ids = {r[0] for r in rows if r[6].strip()}
    assert len(empty_ids) == 7, f"空责任人应 7 行，实际 {len(empty_ids)}"
    assert len(non_empty_ids) == 9, f"非空责任人应 9 行，实际 {len(non_empty_ids)}"
    assert empty_ids == EMPTY_ASSIGNEE_IDS


# ── 2. 真实 datasets 目录解析 ────────────────────────────


def test_real_datasets_fields_json_has_todo_settings():
    """真实 datasets：科研项目管理 fields.json 包含科研待办事项 settings."""
    from cndb.cli.seed import _get_datasets_dir, _load_field_settings

    datasets_dir = _get_datasets_dir()
    if datasets_dir is None:
        pytest.skip("examples/datasets 目录不可用")

    cfg = _load_field_settings(datasets_dir)
    assert "科研项目管理" in cfg
    pm = cfg["科研项目管理"]
    assert "settings" in pm
    assert "科研待办事项" in pm["settings"]
    assert pm["settings"]["科研待办事项"]["编号"] == {"required": True, "unique": True}
    assert pm["settings"]["科研待办事项"]["事项"] == {"required": True}


def test_real_datasets_views_json_has_todo_views():
    """真实 datasets：科研项目管理 views.json 包含科研待办事项 7 个视图."""
    from cndb.cli.seed import _get_datasets_dir, _get_workspace_view_configs

    datasets_dir = _get_datasets_dir()
    if datasets_dir is None:
        pytest.skip("examples/datasets 目录不可用")

    configs = _get_workspace_view_configs(datasets_dir)
    pm_views = configs.get("科研项目管理")
    assert pm_views is not None
    todo_views = pm_views.get("科研待办事项")
    assert todo_views is not None, "views.json 应包含科研待办事项"
    assert len(todo_views) == 7, f"期望 7 个科研待办事项视图，实际 {len(todo_views)}"

    names = {v["name"] for v in todo_views}
    assert names == {
        "全部",
        "按责任人看板",
        "按类别看板",
        "事项日历",
        "待分派事项",
        "未完成事项",
        "类别占比",
    }

    assignee_kanban = next(v for v in todo_views if v["name"] == "按责任人看板")
    assert assignee_kanban["view_type"] == "kanban"
    opts = assignee_kanban["view_options"]
    assert opts["group_field"] == "责任人"
    assert opts["ungrouped_label"] == "未分派"


# ── 3. seed 端到端 ──────────────────────────────────────


def test_project_todo_csv_seeded(project_todo_seed):
    """科研待办事项 CSV 正确建表：9 个业务字段 + 关联课题 lookup 字段."""
    tables, _ = project_todo_seed
    todo_tbl = tables["科研待办事项"]
    assert todo_tbl is not None
    fields = {f.name: f for f in todo_tbl.fields if not f.trashed}
    assert set(EXPECTED_HEADER) <= set(fields.keys()), f"字段不匹配: {set(fields.keys())}"
    # fields.json 的 link_lookups 建出 link + 引用字段
    assert "关联课题" in fields
    assert fields["关联课题"].field_type == "link"
    assert "项目名称" in fields


def test_project_todo_settings(project_todo_seed):
    """fields.json settings 正确应用：编号 required+unique，事项 required."""
    tables, _ = project_todo_seed
    todo_tbl = tables["科研待办事项"]
    fields = {f.name: f for f in todo_tbl.fields if not f.trashed}
    assert fields["编号"].required is True
    assert fields["编号"].is_unique is True
    assert fields["事项"].required is True
    assert fields["事项"].is_unique is False


def test_project_todo_views_seeded(project_todo_seed, db):
    """科研待办事项 7 个视图全部注入成功，类型覆盖 grid / kanban / calendar / chart."""
    from cndb.plugins.tables.models import DataView

    tables, _ = project_todo_seed
    todo_tbl = tables["科研待办事项"]

    views = db.query(DataView).filter(DataView.table_id == todo_tbl.id).all()
    by_name = {v.name: v for v in views}
    assert len(by_name) == 7, (
        f"期望 7 个视图（首视图「全部」更新自动默认视图），实际 {len(by_name)}: {list(by_name.keys())}"
    )

    assert by_name["全部"].view_type == "grid"
    assert by_name["按责任人看板"].view_type == "kanban"
    assert by_name["按类别看板"].view_type == "kanban"
    assert by_name["事项日历"].view_type == "calendar"
    assert by_name["类别占比"].view_type == "chart"
    assert by_name["全部"].is_default is True

    # 按责任人看板的 view_options 引用正确字段
    assignee_kanban = by_name["按责任人看板"]
    assert assignee_kanban.view_options["group_field"] == "责任人"
    assert assignee_kanban.view_options["ungrouped_label"] == "未分派"


# ── 4. kanban API：空责任人行进入「未分派」 ──────────────────


def test_project_todo_kanban_ungrouped_empty_assignee(project_todo_seed, client, db, auth_headers):
    """按责任人看板分组时，空责任人行全部进入「未分派」分组."""
    # project_todo_seed fixture 已执行完整 seed 流程，直接查库即可
    # 让 auth_headers 里的 testuser 成为「科研项目管理」workspace 成员，否则读不到表
    from cndb.plugins.accounts.models import User
    from cndb.plugins.tables.models import DataTable, DataView
    from cndb.plugins.workspaces.models import WorkspaceMember

    testuser = db.query(User).filter(User.username == "testuser").first()
    assert testuser is not None

    todo_tbl = db.query(DataTable).filter_by(name="科研待办事项").first()
    assert todo_tbl is not None

    # 确保 testuser 在 workspace 里
    existing = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == todo_tbl.workspace_id, WorkspaceMember.user_id == testuser.id)
        .first()
    )
    if existing is None:
        db.add(WorkspaceMember(workspace_id=todo_tbl.workspace_id, user_id=testuser.id, role="owner"))
        db.commit()

    assignee_view = db.query(DataView).filter(DataView.table_id == todo_tbl.id, DataView.name == "按责任人看板").first()
    assert assignee_view is not None

    r = client.get(
        f"/api/v1/workspaces/{todo_tbl.workspace_id}/tables/{todo_tbl.id}/views/{assignee_view.id}/kanban",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # 分组结构：8 个实名人 + 「未分派」
    cols = body["columns"]
    assert "未分派" in cols, "空责任人行应进入「未分派」分组"

    # 空责任人行数量 = 7（CSV 里空 7 行）
    ungrouped_rows = cols["未分派"]
    assert len(ungrouped_rows) == 7, (
        f"「未分派」分组应有 7 行，实际 {len(ungrouped_rows)}: {[r['编号'] for r in ungrouped_rows]}"
    )
    ungrouped_ids = {r["编号"] for r in ungrouped_rows}
    assert ungrouped_ids == EMPTY_ASSIGNEE_IDS, f"「未分派」分组行编号应为 {EMPTY_ASSIGNEE_IDS}，实际 {ungrouped_ids}"

    # 总分组数：8 个责任人 + 「未分派」= 9
    assert len(cols) == 9, f"期望 9 个分组，实际 {len(cols)}: {list(cols.keys())}"

    actual_assignees = set(cols.keys()) - {"未分派"}
    assert actual_assignees == EXPECTED_ASSIGNEES

    for name, rows in cols.items():
        if name == "未分派":
            continue
        for row in rows:
            assert row["责任人"] == name, f"分组 {name} 内行的责任人应为 {name}，实际 {row['责任人']}"
