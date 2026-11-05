"""质量检查流水线种子（pipelines/*.yaml）测试.

覆盖（需求卡片 0078）：
- 合法 YAML 编译落库：compiled IR 快照、created_by、表引用解析到真实表（C1/C3）
- 幂等：同 (workspace_id, name) 重复注入不重复建（C4）
- 坏 YAML / 未知动作 / 引用不存在的表：告警跳过，不阻断其它样例（C3/C2）
- datasets 目录缺失 / 无 pipelines 目录：返回 0 优雅降级（C4）
- 真实 examples 示例：全部可编译、表引用真实存在（C2）
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cndb.cli.seed.pipelines import _seed_pipelines

SALES_CSV = """订单号,销售额,日期
ORD1,100.5,2026-01-01
ORD2,88.0,2026-01-02
"""

GOOD_YAML = """\
name: 订单口径巡检
on:
  manual: true
jobs:
  口径:
    steps:
      - uses: table/null-rate
        with:
          table: 销售明细
          fields: [订单号, 销售额]
          max_rate: 0
        severity: error
      - uses: table/duplicates
        with:
          table: 销售明细
          fields: [订单号]
"""

BAD_YAML = """\
name: 坏定义
on:
  manual: true
jobs:
  坏:
    steps:
      - uses: table/不存在动作
"""


def _build_datasets_dir(tmp_path: Path, yamls: dict[str, str]) -> Path:
    """构建仅含「销售示例」workspace 的临时 datasets 目录."""
    ws_dir = tmp_path / "datasets" / "工作区-销售示例"
    (ws_dir / "pipelines").mkdir(parents=True)
    (ws_dir / "销售明细.csv").write_text(SALES_CSV, encoding="utf-8-sig")
    for filename, content in yamls.items():
        (ws_dir / "pipelines" / filename).write_text(content, encoding="utf-8")
    return tmp_path / "datasets"


@pytest.fixture
def pipeline_seed(db, db_engine, tmp_path):
    """端到端 fixture：建表 + 返回 (tables_map, ws_map, user, datasets_dir)."""
    from cndb.cli.seed import _seed_datasets
    from cndb.cli.seed import paths as seed_paths
    from cndb.plugins.accounts.models import User

    user = User(username="pl_seed", email="pl_seed@example.com", nickname="流水线种子测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    datasets_dir = _build_datasets_dir(tmp_path, {"good.yaml": GOOD_YAML})
    original = seed_paths._get_datasets_dir
    seed_paths._get_datasets_dir = lambda: datasets_dir
    try:
        _, ws_map, tables_map = _seed_datasets(db, db_engine, user)
        yield tables_map, ws_map, user, datasets_dir
    finally:
        seed_paths._get_datasets_dir = original


def test_seed_pipelines_compiles_and_persists(pipeline_seed, db):
    """合法 YAML 编译落库：content 原文、compiled IR 快照、创建人齐备."""
    from cndb.plugins.pipeline.models import PipelineWorkflow

    tables_map, ws_map, user, datasets_dir = pipeline_seed
    created = _seed_pipelines(db, user, ws_map, tables_map, datasets_dir)
    assert created == 1

    wf = db.query(PipelineWorkflow).filter(PipelineWorkflow.name == "订单口径巡检").one()
    assert wf.workspace_id == ws_map["销售示例"].id
    assert wf.content == GOOD_YAML
    assert wf.enabled is True
    assert wf.created_by_id == user.id
    assert wf.compiled["name"] == "订单口径巡检"
    steps = wf.compiled["jobs"][0]["steps"]
    assert [s["uses"] for s in steps] == ["table/null-rate", "table/duplicates"]
    assert steps[0]["with"]["table"] == "销售明细"
    assert steps[0]["severity"] == "error"


def test_seed_pipelines_idempotent(pipeline_seed, db):
    """幂等：同 (workspace_id, name) 重复注入只建一次."""
    tables_map, ws_map, user, datasets_dir = pipeline_seed
    assert _seed_pipelines(db, user, ws_map, tables_map, datasets_dir) == 1
    assert _seed_pipelines(db, user, ws_map, tables_map, datasets_dir) == 0
    from cndb.plugins.pipeline.models import PipelineWorkflow

    assert db.query(PipelineWorkflow).count() == 1


def test_seed_pipelines_bad_yaml_skipped(db, db_engine, tmp_path):
    """坏 YAML / 未知动作：编译失败告警跳过，不抛异常、不落库."""
    from cndb.cli.seed import _seed_datasets
    from cndb.cli.seed import paths as seed_paths
    from cndb.plugins.accounts.models import User
    from cndb.plugins.pipeline.models import PipelineWorkflow

    user = User(username="pl_bad", email="pl_bad@example.com", nickname="坏样例测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    datasets_dir = _build_datasets_dir(tmp_path, {"bad.yaml": BAD_YAML, "bad2.yaml": "::: 不是映射"})
    original = seed_paths._get_datasets_dir
    seed_paths._get_datasets_dir = lambda: datasets_dir
    try:
        _, ws_map, tables_map = _seed_datasets(db, db_engine, user)
        created = _seed_pipelines(db, user, ws_map, tables_map, datasets_dir)
    finally:
        seed_paths._get_datasets_dir = original

    assert created == 0
    assert db.query(PipelineWorkflow).count() == 0


def test_seed_pipelines_unknown_table_skipped(pipeline_seed, db):
    """表引用不存在：该样例跳过，不影响其它合法样例落库."""
    from cndb.plugins.pipeline.models import PipelineWorkflow

    tables_map, ws_map, user, datasets_dir = pipeline_seed
    missing_table = GOOD_YAML.replace("销售明细", "不存在的表")
    ws_dir = Path(datasets_dir) / "工作区-销售示例" / "pipelines"
    (ws_dir / "missing.yaml").write_text(missing_table, encoding="utf-8")

    created = _seed_pipelines(db, user, ws_map, tables_map, datasets_dir)
    assert created == 1  # 仅 good.yaml 落库
    names = {wf.name for wf in db.query(PipelineWorkflow).all()}
    assert names == {"订单口径巡检"}


def test_seed_pipelines_missing_dir_returns_zero(db):
    """datasets 目录缺失 → 返回 0，优雅降级."""
    assert _seed_pipelines(db, None, {}, {}, None) == 0


def test_seed_pipelines_no_pipeline_dir_returns_zero(db, db_engine, tmp_path):
    """工作区无 pipelines/ 目录 → 返回 0."""
    from cndb.cli.seed import _seed_datasets
    from cndb.cli.seed import paths as seed_paths
    from cndb.plugins.accounts.models import User

    user = User(username="pl_none", email="pl_none@example.com", nickname="无目录测试")
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
        _, ws_map, tables_map = _seed_datasets(db, db_engine, user)
        created = _seed_pipelines(db, user, ws_map, tables_map, datasets_dir)
    finally:
        seed_paths._get_datasets_dir = original
    assert created == 0


def test_real_pipeline_examples_are_valid(db, db_engine, tmp_path):
    """真实 examples 两个示例：编译通过、表引用真实存在于对应 CSV 表头、触发声明合法."""
    from cndb.cli.seed import paths as seed_paths
    from cndb.plugins.pipeline.services.dsl.parse import compile_workflow

    base = Path(__file__).resolve().parents[1] / "examples" / "datasets"
    ws_yamls = seed_paths._get_workspace_pipeline_yamls(base)
    assert set(ws_yamls) == {"某企业销售管理"}
    assert [p.name for p in ws_yamls["某企业销售管理"]] == ["工作区综合巡检.yaml", "销售数据质量巡检.yaml"]

    names: set[str] = set()
    for ws_name, yamls in ws_yamls.items():
        # 工作区下全部 CSV 表头 = 可引用字段的唯一真相源
        headers = {
            csv_path.stem: set(csv_path.read_text(encoding="utf-8-sig").splitlines()[0].split(","))
            for csv_path in (base / f"工作区-{ws_name}").glob("*.csv")
        }
        for path in yamls:
            ir = compile_workflow(path.read_text(encoding="utf-8-sig"))
            assert ir.name not in names, f"定义名跨示例重复：{ir.name}"
            names.add(ir.name)
            triggers = ir.triggers
            assert triggers.get("manual") is True or triggers.get("events") or triggers.get("schedule")
            if ir.name == "工作区综合巡检":
                # 该示例会出现在数据表域质量检查页：触发事件必须是表变更而不是文档保存
                assert triggers.get("events") == ["record.updated"]
            for job in ir.jobs:
                for step in job.steps:
                    table_name = step.params.get("table")
                    if table_name is not None:
                        assert table_name in headers, f"{ir.name} 引用了不存在的表 {table_name}"
                        used_fields = step.params.get("fields") or []
                        if used_fields != ["all"] and step.uses != "table/stale":
                            header = headers[table_name]
                            for field_name in used_fields:
                                assert field_name in header, f"{ir.name} 字段 {field_name} 不在 {table_name} 表头"
                    if step.uses == "table/stale":
                        assert step.params["field"] in headers[table_name]


def test_real_pipeline_example_compiled_is_json_friendly():
    """compiled 快照可 JSON 序列化（JSON 列落库口径）."""
    import json as _json

    from cndb.plugins.pipeline.services.dsl.parse import compile_workflow

    sample = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "datasets"
        / "工作区-某企业销售管理"
        / "pipelines"
        / "销售数据质量巡检.yaml"
    ).read_text(encoding="utf-8")
    ir = compile_workflow(sample)
    restored = _json.loads(_json.dumps(ir.to_dict(), ensure_ascii=False))
    assert restored["name"] == "销售数据质量巡检"
    assert yaml.safe_load(sample)["name"] == "销售数据质量巡检"
