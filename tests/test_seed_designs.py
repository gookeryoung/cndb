"""结构设计种子（designs/*.cnmd）测试（ADR 0079 P2）.

覆盖：
- 合法 .cnmd 编译落库：content 原文、compiled IR 快照、创建人、文件名即标题（D7 创建即 v1）
- 幂等：同 (workspace_id, title) 重复注入不重复建
- 坏 DSL / 空文件：告警跳过，不阻断其它样例
- datasets 目录缺失 / 无 designs 目录：返回 0 优雅降级
- 真实 examples 示例：全部可编译
"""

from __future__ import annotations

import json
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


def test_seed_designs_split_files(db, db_engine, tmp_path):
    """分文件种子（ADR 0086 §6）：parts/ 零件先建行，装配 use 引用 + 依赖闭包 + ref."""
    from cndb.cli.seed import _seed_datasets
    from cndb.cli.seed import paths as seed_paths
    from cndb.plugins.accounts.models import User
    from cndb.plugins.design.models import DesignDesign, DesignDesignref, DesignDesignVersion

    user = User(username="ds_split", email="ds_split@example.com", nickname="分文件种子测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    datasets_dir = tmp_path / "datasets"
    ws_dir = datasets_dir / "工作区-装配示例"
    (ws_dir / "designs" / "parts").mkdir(parents=True)
    (ws_dir / "designs" / "parts" / "轮毂.cnmd").write_text(
        "param d = 40\nparam w = 16\nrotate([90, 0, 0]) cyl(d = d, h = w)\n", encoding="utf-8"
    )
    (ws_dir / "designs" / "装配.cnmd").write_text('use "轮毂" as wheel_l\nuse "轮毂" as wheel_r\n', encoding="utf-8")
    original = seed_paths._get_datasets_dir
    seed_paths._get_datasets_dir = lambda: datasets_dir
    try:
        _, ws_map, _ = _seed_datasets(db, db_engine, user)
        created = _seed_designs(db, user, ws_map, datasets_dir)
    finally:
        seed_paths._get_datasets_dir = original

    assert created == 2
    part = db.query(DesignDesign).filter(DesignDesign.title == "轮毂").one()
    asm = db.query(DesignDesign).filter(DesignDesign.title == "装配").one()
    assert (part.kind, part.folder) == ("part", "parts")
    assert (asm.kind, asm.folder) == ("assembly", "")
    assert len(asm.dependencies) == 1, "同零件两实例合并为一份依赖闭包"
    assert asm.dependencies[0]["file_id"] == part.id
    version = db.query(DesignDesignVersion).filter(DesignDesignVersion.design_id == asm.id).one()
    assert version.dependencies == asm.dependencies, "版本快照与当前闭包一致"
    refs = db.query(DesignDesignref).filter(DesignDesignref.design_id == asm.id).all()
    assert [ref.target_design_id for ref in refs] == [part.id]


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
    """真实 examples 示例：全部可编译且产出顶层实例（分文件目录口径，ADR 0086 §6）."""
    from cndb.plugins.design.services.dsl.compile import compile_design
    from cndb.plugins.design.services.files import content_hash

    base = Path(__file__).resolve().parents[1] / "examples" / "datasets"
    from cndb.cli.seed import paths as seed_paths

    ws_cnmds = seed_paths._get_workspace_design_cnmds(base)
    # 设计示例集中在「机械设计示例」工作区（仅设计、无数据表）；其余工作区不带 designs/
    assert set(ws_cnmds) == {"机械设计示例"}
    entries = ws_cnmds["机械设计示例"]
    names = [(folder, p.name) for folder, p in entries]
    assert names == [
        ("", "L型支座.cnmd"),
        ("", "六轴机械臂.cnmd"),
        ("", "分文件装配示例.cnmd"),
        ("", "四轮小车.cnmd"),
        ("", "法兰板.cnmd"),
        ("", "离心风机叶轮.cnmd"),
        ("", "自动化立体仓库.cnmd"),
        ("", "行星减速器.cnmd"),
        ("parts", "底板.cnmd"),
        ("parts", "货架单元.cnmd"),
        ("parts", "轮毂.cnmd"),
    ]

    # 零件文件独立编译可过；装配文件按库内 file_key 解析（此处用标题即 key 的映射）
    part_sources: dict[str, str] = {}
    for folder, path in entries:
        content = path.read_text(encoding="utf-8-sig")
        if folder == "parts":
            result = compile_design(content, file_kind="part")
            assert result.ok, f"{path.name} 应可编译：{[d.message for d in result.diagnostics]}"
            part_sources[path.stem] = content

    def resolver(file_key: str):
        from cndb.plugins.design.services.dsl.compile import FileSource

        content = part_sources.get(file_key)
        if content is None:
            return None
        return FileSource(1, file_key, "part", content, 1, content_hash(content))

    for folder, path in entries:
        if folder != "":
            continue
        result = compile_design(path.read_text(encoding="utf-8-sig"), file_kind="assembly", resolver=resolver)
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
        / "工作区-机械设计示例"
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


def _designs_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "examples" / "datasets" / "工作区-机械设计示例" / "designs"


def _geom_count(node: dict) -> int:
    """几何 IR 子树图元计数（布尔 / 组件节点递归，图元为叶）."""
    return sum(_geom_count(child) for child in node["children"]) if "children" in node else 1


def _compile_example(title: str):
    """按真实种子口径编译示例（装配文件自动解析 parts/ 下的零件文件）."""
    from cndb.plugins.design.services.dsl.compile import FileSource, compile_design
    from cndb.plugins.design.services.files import content_hash

    designs = _designs_dir()
    parts = {p.stem: p.read_text(encoding="utf-8-sig") for p in (designs / "parts").glob("*.cnmd")}

    def resolver(file_key: str):
        content = parts.get(file_key)
        if content is None:
            return None
        return FileSource(1, file_key, "part", content, 1, content_hash(content))

    content = (designs / f"{title}.cnmd").read_text(encoding="utf-8-sig")
    return compile_design(content, file_kind="assembly", resolver=resolver)


def test_example_gear_reducer_covers_dsl_surface():
    """行星减速器示例：派生参数链 + 三角函数布齿 + 三级子装配 + 约束求解全绿."""
    result = _compile_example("行星减速器")
    assert result.ok, [d.message for d in result.diagnostics]
    ir = result.ir
    assert ir
    # 派生参数：r_carrier = m * n_sun / 2 + m * n_planet / 2（默认 m=2，8 / 12 齿）
    params = {item["name"]: item["value"] for item in ir["params"]}
    assert params["r_carrier"] == pytest.approx(20.0)
    assert params["r_ring"] == pytest.approx(18.0)
    # 约束全部消解成功（无 warning / error）
    assert [c["status"] for c in ir["constraints"]] == ["ok"] * len(ir["constraints"])
    assert len(ir["constraints"]) == 12
    # 大纲：系统 → 组件（carrier_asm 内嵌 planet_gear）→ 分组 → 零件
    roots = ir["outline"]["children"]
    assert [root["kind"] for root in roots] == ["system"]
    assert _outline_kinds(roots) == {"system", "assembly", "group", "part"}
    carrier = next(child for child in roots[0]["children"] if child.get("name") == "carrier_asm")
    nested = {child.get("name") for child in carrier["children"] if child["kind"] == "assembly"}
    assert "planet_gear" in nested
    # 规模：接近 100 个图元（比既有示例大一个量级）
    assert sum(_geom_count(node) for node in ir["nodes"]) >= 80


def test_example_impeller_uses_intersection_mirror_and_six_primitives():
    """离心风机叶轮示例：intersection 曲面 / mirror 镜像 / 六图元全覆盖."""
    result = _compile_example("离心风机叶轮")
    assert result.ok, [d.message for d in result.diagnostics]
    ir = result.ir
    assert ir
    primitives = set()
    ops = set()

    def walk(nodes):
        for node in nodes:
            if "children" in node:
                ops.add(node["op"])
                walk(node["children"])
            else:
                primitives.add(node["op"])
                for kind, _vector in (node.get("transform") or {}).get("ops", []):
                    ops.add(kind)

    walk(ir["nodes"])
    assert primitives == {"box", "cyl", "sphere", "cone", "torus", "tube"}
    assert {"union", "difference", "intersection", "mirror"} <= ops
    # 叶片圈 12 片 + 6 个约束组件 = 18 个顶层实例级别的大纲节点
    assert len(ir["outline"]["children"][0]["children"]) >= 12
    assert all(c["status"] == "ok" for c in ir["constraints"])


def test_example_asrs_reaches_budget_scale():
    """自动化立体仓库示例：分文件零件批量实例化，图元规模接近闭包预算上限."""
    result = _compile_example("自动化立体仓库")
    assert result.ok, [d.message for d in result.diagnostics]
    ir = result.ir
    assert ir
    total = sum(_geom_count(node) for node in ir["nodes"])
    # 84 个货位 × 15 图元 + 立柱 / 地脚 / 堆垛机 ≈ 1400 图元（预算上限 2000）
    assert 1200 <= total <= 2000
    # 单文件原文不大（阵列由循环展开生成），但 IR 规模显著
    assert len(json.dumps(ir)) > 300_000
    # 依赖闭包记录了被引用的零件文件（版本可复现，H20）
    assert [dep.file_key for dep in result.dependencies] == ["货架单元"]
    assert all(c["status"] == "ok" for c in ir["constraints"])
