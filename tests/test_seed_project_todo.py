"""项目管理工作区「待办事项」数据集端到端测试.

覆盖：
- 待办事项 CSV 结构（8 列 × 15 行，含约半数空责任人）
- 真实 datasets 目录解析：fields.json + views.json
- seed 流程：CSV 建表、settings 应用、views 注入
- kanban 分组：按责任人分组时空值行进入「未分派」分组
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

# ── CSV 原文（与 examples/datasets/工作区-项目管理/待办事项.csv 一致） ────

TODO_CSV = """编号,类别,事项,创建时间,要求节点,完成日期,责任人,备注
TB001,需求,整理客户访谈纪要,2026-09-15,2026-09-30,,刘洋,覆盖 3 家重点客户，输出需求清单
TB002,设计,评审新版原型,2026-09-18,2026-09-28,,李明,UI 需兼顾移动端适配
TB003,开发,搭建 CI 流水线,2026-09-10,2026-09-25,2026-09-24,王强,已完成，包含 lint/test/typecheck 三阶段
TB004,开发,统一 API 返回结构,2026-09-20,2026-10-10,,,按 v2 规范改造，涉及 6 个 router
TB005,测试,编写冒烟测试用例,2026-09-12,2026-09-22,2026-09-20,陈静,覆盖核心流程 15 条
TB006,部署,准备灰度环境,2026-09-22,2026-10-05,,,申请 2 台云主机 + SSL 证书
TB007,文档,更新 README 与 API 说明,2026-09-14,2026-09-26,2026-09-25,赵磊,新增 Docker 部署章节
TB008,沟通,同步客户月度进展,2026-09-23,2026-09-30,,,华中交通 + 南方电网各一场
TB009,运维,巡检生产数据库慢查询,2026-09-08,2026-09-18,2026-09-17,周磊,发现 3 条需加索引
TB010,需求,梳理权限矩阵 V2,2026-09-25,2026-10-12,,,新增视图级 + 字段级权限
TB011,开发,重构表格字段元数据,2026-09-19,2026-10-08,2026-10-06,王强,迁移完成，兼容旧视图配置
TB012,测试,回归测试多租户隔离,2026-09-26,2026-10-14,,,重点验证跨工作区数据泄露
TB013,设计,输出数据字典,2026-09-16,2026-09-29,2026-09-27,李明,覆盖 8 张核心表全部字段
TB014,部署,备份策略演练,2026-09-21,2026-10-03,,,全量 + 增量恢复演练各一次
TB015,沟通,启动会准备,2026-09-27,2026-10-06,,,议程、材料、会议室协调
"""

EXPECTED_HEADER = ["编号", "类别", "事项", "创建时间", "要求节点", "完成日期", "责任人", "备注"]

# 责任人为空的行（空串 + 物理 NULL 统一视为空）
EMPTY_ASSIGNEE_IDS = {"TB004", "TB006", "TB008", "TB010", "TB012", "TB014", "TB015"}


def _build_datasets_dir(tmp_path: Path) -> Path:
    """在 tmp_path 下构建仅含项目管理 workspace 的临时 datasets 目录."""
    ws_dir = tmp_path / "datasets" / "工作区-项目管理"
    ws_dir.mkdir(parents=True)
    (ws_dir / "待办事项.csv").write_text(TODO_CSV, encoding="utf-8-sig")
    # 同时放一份最小 WBS 任务分解表，让 workspace 被 seed 时不会因缺 CSV 目录空跑
    (ws_dir / "WBS任务分解.csv").write_text("任务ID,任务名称,负责人\nROOT,根任务,\n", encoding="utf-8-sig")
    (ws_dir / "fields.json").write_text(
        json.dumps(
            {
                "settings": {
                    "待办事项": {
                        "编号": {"required": True, "unique": True},
                        "事项": {"required": True},
                    }
                },
                "link_lookups": [],
                "backfills": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (ws_dir / "views.json").write_text(
        json.dumps(
            {
                "待办事项": [
                    {
                        "name": "全部事项",
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
    """端到端 fixture：建项目管理 workspace，跑 seed 到视图注入，返回 tables_map."""
    from cndb.cli.seed import (
        _apply_field_settings,
        _seed_datasets,
        _seed_views,
    )
    from cndb.plugins.accounts.models import User

    user = User(username="proj_todo", email="proj_todo@example.com", nickname="项目待办测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    datasets_dir = _build_datasets_dir(tmp_path)

    import cndb.cli.seed as seed_mod

    original = seed_mod._get_datasets_dir
    seed_mod._get_datasets_dir = lambda: datasets_dir
    try:
        _, ws_map, tables_map = _seed_datasets(db, db_engine, user)
        # datasets 目录下 workspace 名是「项目管理」（剥掉「工作区-」前缀）
        assert "项目管理" in ws_map
        assert "项目管理" in tables_map

        _apply_field_settings(db, db_engine, tables_map, datasets_dir)
        _seed_views(db, user, tables_map, datasets_dir)

        db.commit()
        db.refresh(tables_map["项目管理"]["待办事项"])
        yield tables_map["项目管理"], user
    finally:
        seed_mod._get_datasets_dir = original


# ── 1. CSV 结构校验 ──────────────────────────────────────


def test_todo_csv_structure(tmp_path):
    """待办事项 CSV 基础结构：8 列 × 15 行，字段名符合预期，编号唯一."""
    ws_dir = tmp_path / "csv_check"
    ws_dir.mkdir()
    csv_path = ws_dir / "待办事项.csv"
    csv_path.write_text(TODO_CSV, encoding="utf-8-sig")

    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    assert header == EXPECTED_HEADER
    assert len(rows) == 15
    ids = [r[0] for r in rows]
    assert len(ids) == len(set(ids)), "编号应唯一"
    assert ids[0] == "TB001"
    assert ids[-1] == "TB015"


def test_todo_csv_empty_assignee_distribution(tmp_path):
    """CSV 中约半数行责任人为空，覆盖「空值进入未分组」的看板场景."""
    ws_dir = tmp_path / "csv_check2"
    ws_dir.mkdir()
    csv_path = ws_dir / "待办事项.csv"
    csv_path.write_text(TODO_CSV, encoding="utf-8-sig")

    with csv_path.open(encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))[1:]

    empty_ids = {r[0] for r in rows if not r[6].strip()}
    non_empty_ids = {r[0] for r in rows if r[6].strip()}
    # CSV 中实际分布：空 7 行（TB004/6/8/10/12/14/15），非空 8 行
    assert len(empty_ids) == 7, f"空责任人应 7 行，实际 {len(empty_ids)}"
    assert len(non_empty_ids) == 8, f"非空责任人应 8 行，实际 {len(non_empty_ids)}"
    assert empty_ids == EMPTY_ASSIGNEE_IDS


# ── 2. 真实 datasets 目录解析 ────────────────────────────


def test_real_datasets_fields_json_has_todo_settings():
    """真实 datasets：项目管理 fields.json 包含待办事项 settings."""
    from cndb.cli.seed import _get_datasets_dir, _load_field_settings

    datasets_dir = _get_datasets_dir()
    if datasets_dir is None:
        pytest.skip("examples/datasets 目录不可用")

    cfg = _load_field_settings(datasets_dir)
    assert "项目管理" in cfg
    pm = cfg["项目管理"]
    assert "settings" in pm
    assert "待办事项" in pm["settings"]
    assert pm["settings"]["待办事项"]["编号"] == {"required": True, "unique": True}
    assert pm["settings"]["待办事项"]["事项"] == {"required": True}


def test_real_datasets_views_json_has_todo_views():
    """真实 datasets：项目管理 views.json 包含待办事项 6 个视图."""
    from cndb.cli.seed import _get_datasets_dir, _get_workspace_view_configs

    datasets_dir = _get_datasets_dir()
    if datasets_dir is None:
        pytest.skip("examples/datasets 目录不可用")

    configs = _get_workspace_view_configs(datasets_dir)
    pm_views = configs.get("项目管理")
    assert pm_views is not None
    todo_views = pm_views.get("待办事项")
    assert todo_views is not None, "views.json 应包含待办事项"
    assert len(todo_views) == 7, f"期望 7 个待办事项视图，实际 {len(todo_views)}"

    names = {v["name"] for v in todo_views}
    assert names == {
        "全部事项",
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
    """待办事项 CSV 正确建表：8 列."""
    tables, _ = project_todo_seed
    todo_tbl = tables["待办事项"]
    assert todo_tbl is not None
    fields = {f.name: f for f in todo_tbl.fields if not f.trashed}
    assert set(fields.keys()) == set(EXPECTED_HEADER), f"字段不匹配: {set(fields.keys())}"


def test_project_todo_settings(project_todo_seed):
    """fields.json settings 正确应用：编号 required+unique，事项 required."""
    tables, _ = project_todo_seed
    todo_tbl = tables["待办事项"]
    fields = {f.name: f for f in todo_tbl.fields if not f.trashed}
    assert fields["编号"].required is True
    assert fields["编号"].is_unique is True
    assert fields["事项"].required is True
    assert fields["事项"].is_unique is False


def test_project_todo_views_seeded(project_todo_seed, db):
    """待办事项 6 个视图全部注入成功，类型覆盖 grid / kanban / calendar."""
    from cndb.plugins.tables.models import DataView

    tables, _ = project_todo_seed
    todo_tbl = tables["待办事项"]

    views = db.query(DataView).filter(DataView.table_id == todo_tbl.id).all()
    by_name = {v.name: v for v in views}
    assert len(by_name) == 7, f"期望 7 个视图（含自动创建的默认「全部」），实际 {len(by_name)}: {list(by_name.keys())}"

    assert by_name["全部事项"].view_type == "grid"
    assert by_name["按责任人看板"].view_type == "kanban"
    assert by_name["按类别看板"].view_type == "kanban"
    assert by_name["事项日历"].view_type == "calendar"
    assert "全部" in by_name, "CSV 建表应自动创建默认「全部」视图"
    assert by_name["全部事项"].is_default is True

    # 按责任人看板的 view_options 引用正确字段
    assignee_kanban = by_name["按责任人看板"]
    assert assignee_kanban.view_options["group_field"] == "责任人"
    assert assignee_kanban.view_options["ungrouped_label"] == "未分派"


# ── 4. kanban API：空责任人行进入「未分派」 ──────────────────


def test_project_todo_kanban_ungrouped_empty_assignee(project_todo_seed, client, db, auth_headers):
    """按责任人看板分组时，空责任人行全部进入「未分派」分组."""
    # project_todo_seed fixture 已执行完整 seed 流程，直接查库即可
    # 让 auth_headers 里的 testuser 成为「项目管理」workspace 成员，否则读不到表
    from cndb.plugins.accounts.models import User
    from cndb.plugins.tables.models import DataTable, DataView
    from cndb.plugins.workspaces.models import WorkspaceMember

    testuser = db.query(User).filter(User.username == "testuser").first()
    assert testuser is not None

    todo_tbl = db.query(DataTable).filter_by(name="待办事项").first()
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

    # 分组结构：6 个实名人 + 「未分派」
    cols = body["columns"]
    assert "未分派" in cols, "空责任人行应进入「未分派」分组"

    # 空责任人行数量 = 7（CSV 里空 7 行）
    ungrouped_rows = cols["未分派"]
    assert len(ungrouped_rows) == 7, (
        f"「未分派」分组应有 7 行，实际 {len(ungrouped_rows)}: {[r['编号'] for r in ungrouped_rows]}"
    )
    ungrouped_ids = {r["编号"] for r in ungrouped_rows}
    assert ungrouped_ids == EMPTY_ASSIGNEE_IDS, f"「未分派」分组行编号应为 {EMPTY_ASSIGNEE_IDS}，实际 {ungrouped_ids}"

    # 总分组数：6 个责任人 + 「未分派」= 7
    assert len(cols) == 7, f"期望 7 个分组，实际 {len(cols)}: {list(cols.keys())}"

    # 非空责任人分组共 6 个，每个分组内责任人姓名一致
    expected_assignees = {"刘洋", "李明", "王强", "陈静", "赵磊", "周磊"}
    actual_assignees = set(cols.keys()) - {"未分派"}
    assert actual_assignees == expected_assignees

    for name, rows in cols.items():
        if name == "未分派":
            continue
        for row in rows:
            assert row["责任人"] == name, f"分组 {name} 内行的责任人应为 {name}，实际 {row['责任人']}"
