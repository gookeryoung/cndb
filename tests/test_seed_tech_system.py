"""科研项目管理「技术体系」数据集与「技术脉络」树视图测试.

覆盖：
- 真实 CSV：6 列 × 43 行，技术编号唯一、父子引用完整、无环、层级语义一致
- 真实 datasets 目录：fields.json 设置与 views.json 双视图配置
- seed 流程：CSV 建表、select 推断、settings 应用、tree 视图配置落库
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = PROJECT_ROOT / "examples" / "datasets"
WORKSPACE_DIR = DATASETS_DIR / "工作区-科研项目管理"
CSV_PATH = WORKSPACE_DIR / "技术体系.csv"

EXPECTED_HEADER = ["技术编号", "父技术编号", "技术名称", "技术方向", "技术层级", "成熟度"]
EXPECTED_ROW_COUNT = 43
EXPECTED_DIRECTIONS = {"人工智能", "先进制造", "新能源", "新材料", "生物医药", "信息技术"}
EXPECTED_LEVELS = {"领域", "方向", "技术", "专项"}
EXPECTED_MATURITY = {"探索期", "培育期", "成长期", "成熟期"}
LEVEL_DEPTH = {"领域": 1, "方向": 2, "技术": 3, "专项": 4}

TREE_VIEW_OPTIONS = {
    "parent_field": "父技术编号",
    "title_field": "技术名称",
    "status_field": "成熟度",
    "show_numbering": False,
    "expand_all": True,
}


def _load_rows() -> list[dict[str, str]]:
    if not CSV_PATH.exists():
        pytest.skip(f"{CSV_PATH} 不可用")
    with CSV_PATH.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _parents(rows: list[dict[str, str]]) -> dict[str, str]:
    return {row["技术编号"]: row["父技术编号"] for row in rows}


def _depth(node_id: str, parents: dict[str, str]) -> int:
    depth = 1
    current = node_id
    while parents[current] != "ROOT":
        current = parents[current]
        depth += 1
    return depth


# ── 1. 真实 CSV 结构与层级完整性 ──────────────────────────


def test_tech_system_csv_structure():
    """表头逐字一致、行数 43、技术编号与技术名称唯一."""
    rows = _load_rows()
    assert list(rows[0].keys()) == EXPECTED_HEADER, f"表头不匹配: {list(rows[0].keys())}"
    assert len(rows) == EXPECTED_ROW_COUNT

    ids = [row["技术编号"] for row in rows]
    assert len(ids) == len(set(ids)), "技术编号应唯一"
    names = [row["技术名称"] for row in rows]
    assert len(names) == len(set(names)), "技术名称应唯一"


def test_tech_system_parent_references_complete():
    """父引用只能指向同表技术编号或 ROOT，且根节点为 6 个技术方向."""
    rows = _load_rows()
    parents = _parents(rows)

    roots = [node_id for node_id, parent in parents.items() if parent == "ROOT"]
    assert len(roots) == 6, f"根节点应 6 个，实际 {len(roots)}: {roots}"

    for node_id, parent in parents.items():
        assert parent == "ROOT" or parent in parents, f"{node_id} 的父节点 {parent} 不存在"


def test_tech_system_no_cycle_and_reachable_from_root():
    """所有节点从根可达且不形成循环."""
    rows = _load_rows()
    parents = _parents(rows)

    for node_id in parents:
        seen: set[str] = set()
        current = node_id
        while current != "ROOT":
            assert current not in seen, f"检测到循环引用: {node_id}"
            seen.add(current)
            current = parents[current]


def test_tech_system_dimension_and_level_semantics():
    """方向 / 层级 / 成熟度取值固定，层级深度与父子关系一致，最深 4 层."""
    rows = _load_rows()
    parents = _parents(rows)

    assert {row["技术方向"] for row in rows} == EXPECTED_DIRECTIONS
    assert {row["技术层级"] for row in rows} == EXPECTED_LEVELS
    assert {row["成熟度"] for row in rows} == EXPECTED_MATURITY

    max_depth = 0
    for row in rows:
        depth = _depth(row["技术编号"], parents)
        assert depth == LEVEL_DEPTH[row["技术层级"]], f"{row['技术编号']} 层级 {row['技术层级']} 与深度 {depth} 不一致"
        max_depth = max(max_depth, depth)
    assert max_depth == 4


# ── 2. 真实 datasets 目录配置 ────────────────────────────


def test_real_datasets_fields_json_has_tech_system_settings():
    """真实 datasets：技术体系 settings 为技术编号 required+unique、技术名称 required."""
    from cndb.cli.seed import _get_datasets_dir, _load_field_settings

    datasets_dir = _get_datasets_dir()
    if datasets_dir is None:
        pytest.skip("examples/datasets 目录不可用")

    cfg = _load_field_settings(datasets_dir)
    settings = cfg["科研项目管理"]["settings"]["技术体系"]
    assert settings["技术编号"] == {"required": True, "unique": True}
    assert settings["技术名称"] == {"required": True}


def test_real_datasets_views_json_has_tech_system_views():
    """真实 datasets：技术体系含默认 grid「全部」与 tree「技术脉络」."""
    from cndb.cli.seed import _get_datasets_dir, _get_workspace_view_configs

    datasets_dir = _get_datasets_dir()
    if datasets_dir is None:
        pytest.skip("examples/datasets 目录不可用")

    configs = _get_workspace_view_configs(datasets_dir)
    views = configs["科研项目管理"]["技术体系"]
    assert len(views) == 2, f"期望 2 个技术体系视图，实际 {len(views)}"

    by_name = {v["name"]: v for v in views}
    assert set(by_name) == {"全部", "技术脉络"}
    assert by_name["全部"]["view_type"] == "grid"
    assert by_name["全部"]["is_default"] is True
    assert by_name["技术脉络"]["view_type"] == "tree"
    assert by_name["技术脉络"]["view_options"] == TREE_VIEW_OPTIONS
    assert by_name["技术脉络"]["sortings"] == [{"field_name": "技术编号", "direction": "asc"}]


# ── 3. seed 端到端 ──────────────────────────────────────


def _build_datasets_dir(tmp_path: Path) -> Path:
    """构建仅含技术体系表的临时 datasets 目录（只带新表 settings / views）."""
    ws_dir = tmp_path / "datasets" / "工作区-科研项目管理"
    ws_dir.mkdir(parents=True)
    ws_dir.joinpath("技术体系.csv").write_text(CSV_PATH.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    ws_dir.joinpath("fields.json").write_text(
        json.dumps(
            {
                "settings": {
                    "技术体系": {
                        "技术编号": {"required": True, "unique": True},
                        "技术名称": {"required": True},
                    }
                },
                "link_lookups": [],
                "backfills": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ws_dir.joinpath("views.json").write_text(
        json.dumps(
            {
                "技术体系": [
                    {
                        "name": "全部",
                        "view_type": "grid",
                        "sortings": [{"field_name": "技术编号", "direction": "asc"}],
                        "is_default": True,
                        "order": 0,
                    },
                    {
                        "name": "技术脉络",
                        "view_type": "tree",
                        "sortings": [{"field_name": "技术编号", "direction": "asc"}],
                        "view_options": dict(TREE_VIEW_OPTIONS),
                        "order": 1,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return tmp_path / "datasets"


@pytest.fixture
def tech_system_seed(db, db_engine, tmp_path):
    """端到端 fixture：建科研项目管理 workspace，seed 技术体系并注入视图."""
    from cndb.cli.seed import _apply_field_settings, _seed_datasets, _seed_views
    from cndb.cli.seed import paths as seed_paths
    from cndb.plugins.accounts.models import User

    user = User(username="tech_system", email="tech_system@example.com", nickname="技术体系测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    datasets_dir = _build_datasets_dir(tmp_path)

    original = seed_paths._get_datasets_dir
    seed_paths._get_datasets_dir = lambda: datasets_dir
    try:
        _, ws_map, tables_map = _seed_datasets(db, db_engine, user)
        assert "科研项目管理" in ws_map
        assert "技术体系" in tables_map["科研项目管理"]

        _apply_field_settings(db, db_engine, tables_map, datasets_dir)
        _seed_views(db, user, tables_map, datasets_dir)
        db.commit()
        db.refresh(tables_map["科研项目管理"]["技术体系"])
        yield tables_map["科研项目管理"]
    finally:
        seed_paths._get_datasets_dir = original


def test_project_tech_system_csv_seeded(tech_system_seed, db):
    """CSV 建成 6 列 × 43 行；低基数列提升 select."""
    from cndb.plugins.tables.services.core import records as rec

    tables = tech_system_seed
    tbl = tables["技术体系"]
    fields = {f.name: f for f in tbl.fields if not f.trashed}
    assert set(fields) == set(EXPECTED_HEADER)

    for name in ("技术方向", "技术层级", "成熟度"):
        assert fields[name].field_type == "select", f"{name} 应为 select，实际 {fields[name].field_type}"
    for name in ("技术编号", "父技术编号", "技术名称"):
        assert fields[name].field_type == "text", f"{name} 应为 text，实际 {fields[name].field_type}"

    rows, total = rec.list_rows(db.get_bind(), tbl, limit=None, db=db)
    assert total == EXPECTED_ROW_COUNT
    assert {row["技术方向"] for row in rows} == EXPECTED_DIRECTIONS
    parents = {row["技术编号"]: row["父技术编号"] for row in rows}
    assert len([node for node, parent in parents.items() if parent == "ROOT"]) == 6


def test_project_tech_system_settings(tech_system_seed):
    """fields.json settings 正确应用：技术编号 required+unique，技术名称 required."""
    tables = tech_system_seed
    fields = {f.name: f for f in tables["技术体系"].fields if not f.trashed}
    assert fields["技术编号"].required is True
    assert fields["技术编号"].is_unique is True
    assert fields["技术名称"].required is True
    assert fields["技术名称"].is_unique is False


def test_project_tech_system_views_seeded(tech_system_seed, db):
    """全部 + 技术脉络 两个视图注入成功，tree 配置与种子一致."""
    from cndb.plugins.tables.models import DataView

    tables = tech_system_seed
    tbl = tables["技术体系"]
    views = db.query(DataView).filter(DataView.table_id == tbl.id).all()
    by_name = {v.name: v for v in views}
    assert set(by_name) == {"全部", "技术脉络"}
    assert by_name["全部"].view_type == "grid"
    assert by_name["全部"].is_default is True
    assert by_name["技术脉络"].view_type == "tree"
    assert by_name["技术脉络"].view_options == TREE_VIEW_OPTIONS
