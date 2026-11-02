"""结构设计种子（designs/*.cnmd）测试（ADR 0079 P2）.

覆盖：
- 合法 .cnmd 编译落库：content 原文、compiled IR 快照、创建人、文件名即标题（D7 创建即 v1）
- 幂等：同 (workspace_id, title) 重复注入不重复建
- 坏 DSL / 空文件：告警跳过，不阻断其它样例
- datasets 目录缺失 / 无 designs 目录：返回 0 优雅降级
- 真实 examples 示例：全部可编译
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cndb.cli.seed.designs import _seed_designs

SALES_CSV = """订单号,销售额,日期
ORD1,100.5,2026-01-01
ORD2,88.0,2026-01-02
"""

GOOD_CNMD = """\
param width = 80

module plate(w, h, t) {
  difference {
    box(size = [w, h, t])
    translate([w / 2, h / 2, -1]) {
      cyl(d = 8, h = t + 2)
    }
  }
}

plate(width, 40, 12)
"""

BAD_CNMD = "box(size = [1, 2, -3])\n"


def _build_datasets_dir(tmp_path: Path, cnmds: dict[str, str]) -> Path:
    """构建仅含「销售示例」workspace 的临时 datasets 目录."""
    ws_dir = tmp_path / "datasets" / "工作区-销售示例"
    (ws_dir / "designs").mkdir(parents=True)
    (ws_dir / "销售明细.csv").write_text(SALES_CSV, encoding="utf-8-sig")
    for filename, content in cnmds.items():
        (ws_dir / "designs" / filename).write_text(content, encoding="utf-8")
    return tmp_path / "datasets"


@pytest.fixture
def design_seed(db, db_engine, tmp_path):
    """端到端 fixture：建工作区 + 返回 (ws_map, user, datasets_dir)."""
    from cndb.cli.seed import _seed_datasets
    from cndb.cli.seed import paths as seed_paths
    from cndb.plugins.accounts.models import User

    user = User(username="ds_seed", email="ds_seed@example.com", nickname="设计种子测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    datasets_dir = _build_datasets_dir(tmp_path, {"法兰板.cnmd": GOOD_CNMD})
    original = seed_paths._get_datasets_dir
    seed_paths._get_datasets_dir = lambda: datasets_dir
    try:
        _, ws_map, _ = _seed_datasets(db, db_engine, user)
        yield ws_map, user, datasets_dir
    finally:
        seed_paths._get_datasets_dir = original


def test_seed_designs_compiles_and_persists(design_seed, db):
    """合法 .cnmd 编译落库：content 原文、compiled IR、创建人、创建即 v1."""
    from cndb.plugins.design.models import DesignDesign, DesignDesignVersion

    ws_map, user, datasets_dir = design_seed
    created = _seed_designs(db, user, ws_map, datasets_dir)
    assert created == 1

    design = db.query(DesignDesign).filter(DesignDesign.title == "法兰板").one()
    assert design.workspace_id == ws_map["销售示例"].id
    assert design.content == GOOD_CNMD
    assert design.compiled["nodes"], "IR 快照随落库"
    assert design.created_by_id == user.id
    version = db.query(DesignDesignVersion).filter(DesignDesignVersion.design_id == design.id).one()
    assert version.version_number == 1, "创建即 v1（ADR 0079 D7）"
    assert version.content == GOOD_CNMD


def test_seed_designs_idempotent(design_seed, db):
    """幂等：同 (workspace_id, title) 重复注入只建一次."""
    from cndb.plugins.design.models import DesignDesign

    ws_map, user, datasets_dir = design_seed
    assert _seed_designs(db, user, ws_map, datasets_dir) == 1
    assert _seed_designs(db, user, ws_map, datasets_dir) == 0
    assert db.query(DesignDesign).count() == 1


def test_seed_designs_bad_dsl_skipped(db, db_engine, tmp_path):
    """坏 DSL：编译失败告警跳过，不抛异常、不落库，不阻断同目录其它样例."""
    from cndb.cli.seed import _seed_datasets
    from cndb.cli.seed import paths as seed_paths
    from cndb.plugins.accounts.models import User
    from cndb.plugins.design.models import DesignDesign

    user = User(username="ds_bad", email="ds_bad@example.com", nickname="坏样例测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    datasets_dir = _build_datasets_dir(tmp_path, {"坏设计.cnmd": BAD_CNMD, "法兰板.cnmd": GOOD_CNMD})
    original = seed_paths._get_datasets_dir
    seed_paths._get_datasets_dir = lambda: datasets_dir
    try:
        _, ws_map, _ = _seed_datasets(db, db_engine, user)
        created = _seed_designs(db, user, ws_map, datasets_dir)
    finally:
        seed_paths._get_datasets_dir = original

    assert created == 1  # 仅法兰板落库
    titles = {d.title for d in db.query(DesignDesign).all()}
    assert titles == {"法兰板"}


def test_seed_designs_missing_dir_returns_zero(db):
    """datasets 目录缺失 → 返回 0，优雅降级."""
    assert _seed_designs(db, None, {}, None) == 0


def test_seed_designs_no_design_dir_returns_zero(db, db_engine, tmp_path):
    """工作区无 designs/ 目录 → 返回 0."""
    from cndb.cli.seed import _seed_datasets
    from cndb.cli.seed import paths as seed_paths
    from cndb.plugins.accounts.models import User

    user = User(username="ds_none", email="ds_none@example.com", nickname="无目录测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    datasets_dir = tmp_path / "datasets"
    ws_dir = datasets_dir / "工作区-空示例"
    ws_dir.mkdir(parents=True)
    (ws_dir / "任意.csv").write_text("a,b\n1,2\n", encoding="utf-8-sig")
    original = seed_paths._get_datasets_dir
    seed_paths._get_datasets_dir = lambda: datasets_dir
    try:
        _, ws_map, _ = _seed_datasets(db, db_engine, user)
        created = _seed_designs(db, user, ws_map, datasets_dir)
    finally:
        seed_paths._get_datasets_dir = original
    assert created == 0


def test_real_design_examples_are_valid():
    """真实 examples 示例：全部可编译且产出顶层实例."""
    from cndb.plugins.design.services.dsl.compile import compile_design

    base = Path(__file__).resolve().parents[1] / "examples" / "datasets"
    from cndb.cli.seed import paths as seed_paths

    ws_cnmds = seed_paths._get_workspace_design_cnmds(base)
    assert set(ws_cnmds) == {"某企业销售管理"}
    assert [p.name for p in ws_cnmds["某企业销售管理"]] == [
        "L型支座.cnmd",
        "六轴机械臂.cnmd",
        "四轮小车.cnmd",
        "法兰板.cnmd",
    ]

    for path in ws_cnmds["某企业销售管理"]:
        result = compile_design(path.read_text(encoding="utf-8-sig"))
        assert result.ok, f"{path.name} 应可编译：{[d.message for d in result.diagnostics]}"
        assert result.ir and result.ir["nodes"], f"{path.name} 应有顶层实例"


def _outline_kinds(nodes: list[dict]) -> set[str]:
    """递归收集大纲节点 kind（组件可嵌套，系统 / 分组 / 零件均覆盖）."""
    kinds: set[str] = set()
    for node in nodes:
        kinds.add(node["kind"])
        kinds |= _outline_kinds(node.get("children", []))
    return kinds


def test_real_complex_system_example_outline():
    """复杂系统级装配示例：两个系统根 + 系统 / 组件 / 分组 / 零件四级层级."""
    from cndb.plugins.design.services.dsl.compile import compile_design

    path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "datasets"
        / "工作区-某企业销售管理"
        / "designs"
        / "六轴机械臂.cnmd"
    )
    result = compile_design(path.read_text(encoding="utf-8-sig"))
    assert result.ok
    assert result.ir
    roots = result.ir["outline"]["children"]
    assert [root["kind"] for root in roots] == ["system", "system"]
    assert {root["name"] for root in roots} == {"robot_cell", "fixture"}
    assert _outline_kinds(roots) == {"system", "assembly", "group", "part"}

    # 子装配嵌套：forearm 为组件，其下再挂 link / joint 组件
    robot = next(root for root in roots if root["name"] == "robot_cell")
    forearm = next(child for child in robot["children"] if child["kind"] == "assembly" and child["name"] == "forearm")
    nested = {child["name"] for child in forearm["children"] if child["kind"] == "assembly"}
    assert {"link", "joint"} <= nested
