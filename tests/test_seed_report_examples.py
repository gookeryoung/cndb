"""seed 示例报告模板（REPORT_TEMPLATE_SPECS）单元测试.

覆盖：
- spec 定义一致性与 datasets 数据集引用有效性；
- _seed_report_templates 幂等创建；
- 5 组新增示例模板基于真实 datasets 数据的渲染断言（期望值独立重算）；
- _generate_sample_reports 端到端 docx 落盘。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cndb.cli.seed import (
    REPORT_TEMPLATE_SPECS,
    _generate_sample_reports,
    _get_datasets_dir,
    _seed_report_templates,
)

# 5 组新增示例涉及的数据集表（工作区显示名 -> 表名列表，对应仓库 examples/datasets/*.csv）
REQUIRED_TABLES: dict[str, list[str]] = {
    "某企业销售管理": ["电商销售", "产品开发"],
    "项目管理": ["WBS任务分解"],
    "某地区数据": ["气温天气"],
    "低质量数据": ["19-特殊值杂项", "17-数字格式大全"],
}


def _non_empty(records: list[dict[str, Any]], field: str) -> int:
    """与 reports._stats 的 non_empty 同口径：None 与空串视为空."""
    return sum(1 for r in records if r.get(field) is not None and r.get(field) != "")


def _num_sum(records: list[dict[str, Any]], field: str) -> float:
    """对可解析数值字段求和（跳过空值/非数值），与 _coerce_numeric 口径一致."""
    total = 0.0
    for r in records:
        v = r.get(field)
        if v is None or v == "":
            continue
        try:
            total += float(v)
        except (TypeError, ValueError):
            continue
    return total


@pytest.fixture
def seed_env(db, db_engine):
    """按 REQUIRED_TABLES 从真实 datasets CSV 建表并 seed 全部示例模板.

    Returns:
        (tables_map, user)：与 seed 主流程一致的数据结构。
    """
    from cndb.plugins.accounts.models import User
    from cndb.plugins.tables.services.transfer import create_table_from_csv
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember

    datasets_dir = _get_datasets_dir()
    if datasets_dir is None:
        pytest.skip("examples/datasets 目录不可用（wheel 安装环境）")

    user = User(username="seedreport", email="seedreport@test.local", nickname="示例报告测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    tables_map: dict[str, dict[str, Any]] = {}
    for ws_name, table_names in REQUIRED_TABLES.items():
        ws = Workspace(name=ws_name, description=f"示例报告测试：{ws_name}")
        db.add(ws)
        db.commit()
        db.refresh(ws)
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
        db.commit()
        tables_map[ws_name] = {}
        for tname in table_names:
            csv_path = datasets_dir / f"工作区-{ws_name}" / f"{tname}.csv"
            if not csv_path.is_file():
                pytest.skip(f"数据集缺失: {csv_path}")
            dt, _ids = create_table_from_csv(
                db_engine, db, ws.id, tname, csv_path.read_text(encoding="utf-8-sig"), owner_id=user.id
            )
            tables_map[ws_name][tname] = dt

    _seed_report_templates(db, tables_map)
    return tables_map, user


def _render_spec(db, user, tables_map: dict[str, dict[str, Any]], spec_name: str) -> tuple[dict[str, Any], str]:
    """用生产渲染路径（_jinja_env + _render_with_timeout）渲染指定模板.

    Returns:
        (渲染上下文, 渲染后文本)。
    """
    from cndb.plugins.reports.models import ReportTemplate
    from cndb.plugins.reports.routers.reports import _jinja_env, _load_table_records, _render_with_timeout
    from cndb.plugins.tables.models import DataTable

    spec = next(s for s in REPORT_TEMPLATE_SPECS if s["name"] == spec_name)
    main_tbl = tables_map[spec["workspace"]][spec["table"]]
    tpl = (
        db.query(ReportTemplate).filter(ReportTemplate.table_id == main_tbl.id, ReportTemplate.name == spec_name).one()
    )
    _, records = _load_table_records(db, main_tbl.id, user)
    records_by_table: dict[str, list[dict[str, Any]]] = {}
    for etid in tpl.extra_table_ids:
        etable = db.get(DataTable, etid)
        assert etable is not None
        _, erecords = _load_table_records(db, etid, user)
        records_by_table[etable.name] = erecords
    ctx: dict[str, Any] = {
        "records": records,
        "table_name": main_tbl.name,
        "params": {},
        "records_by_table": records_by_table,
        "generated_at": "2026-09-24 12:00",
    }
    rendered = _render_with_timeout(_jinja_env.from_string(tpl.template_content), ctx)
    return ctx, rendered


# ── spec 定义与数据集引用 ──────────────────────────────


def test_spec_definitions_unique_and_compilable():
    """6 组 spec 名称唯一，模板内容均可通过沙箱环境编译（语法校验）。"""
    from cndb.plugins.reports.routers.reports import _jinja_env

    names = [s["name"] for s in REPORT_TEMPLATE_SPECS]
    assert len(names) == 6
    assert len(set(names)) == len(names)
    for spec in REPORT_TEMPLATE_SPECS:
        assert spec["content"].strip(), f"{spec['name']} 模板内容为空"
        _jinja_env.from_string(spec["content"])  # 语法错误会抛 TemplateSyntaxError


def test_specs_reference_existing_dataset_tables():
    """每个 spec 引用的主表/额外表都必须在 datasets 目录中存在对应 CSV."""
    datasets_dir = _get_datasets_dir()
    if datasets_dir is None:
        pytest.skip("examples/datasets 目录不可用（wheel 安装环境）")
    for spec in REPORT_TEMPLATE_SPECS:
        folder = datasets_dir / f"工作区-{spec['workspace']}"
        assert folder.is_dir(), f"缺少工作区目录 {folder}"
        assert (folder / f"{spec['table']}.csv").is_file(), f"{spec['name']} 主表 CSV 缺失"
        for extra in spec["extra_tables"]:
            assert (folder / f"{extra}.csv").is_file(), f"{spec['name']} 额外表 CSV 缺失"


# ── seed 幂等 ─────────────────────────────────────────


def test_seed_report_templates_idempotent(seed_env, db):
    """重复执行 _seed_report_templates 不会产生重复模板。"""
    from cndb.plugins.reports.models import ReportTemplate

    tables_map, _user = seed_env
    assert db.query(ReportTemplate).count() == 5  # 科研模板因工作区缺失跳过
    _seed_report_templates(db, tables_map)
    assert db.query(ReportTemplate).count() == 5
    names = {t.name for t in db.query(ReportTemplate).all()}
    assert names == {s["name"] for s in REPORT_TEMPLATE_SPECS} - {"科研项目季度汇报"}


# ── 5 组示例模板渲染断言 ────────────────────────────────


def test_render_ecommerce_monthly(seed_env, db):
    """电商销售月报：销售额合计与订单总数与数据独立重算一致。"""
    tables_map, user = seed_env
    ctx, text = _render_spec(db, user, tables_map, "电商销售月报")
    records = ctx["records"]
    assert records, "电商销售表应有数据"
    expected_total = round(_num_sum(records, "销售额"), 2)
    assert f"| 销售额合计（元） | {expected_total} |" in text
    assert f"| 订单总数 | {len(records)} |" in text
    # 分组行存在：首个商品类别出现且其分组销售额正确
    first_cat = records[0]["商品类别"]
    cat_sum = round(_num_sum([r for r in records if r["商品类别"] == first_cat], "销售额"), 2)
    assert f"| {first_cat} |" in text
    assert f"{cat_sum}" in text


def test_render_product_delivery(seed_env, db):
    """产品开发交付进度报告：已交付数（non_empty 口径）与合同总额正确。"""
    tables_map, user = seed_env
    ctx, text = _render_spec(db, user, tables_map, "产品开发交付进度报告")
    records = ctx["records"]
    delivered = _non_empty(records, "实际交付日期")
    assert f"| 已交付项目数 | {delivered} |" in text
    assert f"| 未交付项目数 | {len(records) - delivered} |" in text
    expected_total = round(_num_sum(records, "合同金额_万元"), 2)
    assert f"| 合同总额（万元） | {expected_total} |" in text
    assert "---PAGE---" in text  # 分页标记保留给 docx 渲染器处理


def test_render_wbs_weekly(seed_env, db):
    """WBS 任务进度周报：顶层任务数（ROOT）与总工期正确。"""
    tables_map, user = seed_env
    ctx, text = _render_spec(db, user, tables_map, "WBS任务进度周报")
    records = ctx["records"]
    root_count = sum(1 for r in records if r.get("父任务ID") == "ROOT")
    assert f"| 顶层任务数 | {root_count} |" in text
    expected_days = float(_num_sum(records, "工期_天"))
    assert f"| 总工期（天） | {expected_days} |" in text


def test_render_city_weather(seed_env, db):
    """城市气温天气月报：全局极值与分城市最低温（嵌套分组匹配）正确。"""
    tables_map, user = seed_env
    ctx, text = _render_spec(db, user, tables_map, "城市气温天气月报")
    records = ctx["records"]
    expected_max = max(float(r["最高温_℃"]) for r in records if r.get("最高温_℃") not in (None, ""))
    expected_min = min(float(r["最低温_℃"]) for r in records if r.get("最低温_℃") not in (None, ""))
    assert f"| 全局最高气温（℃） | {expected_max} |" in text
    assert f"| 全局最低气温（℃） | {expected_min} |" in text
    # 分城市行：首个城市的最低气温经 selectattr 匹配后渲染
    first_city = records[0]["城市"]
    city_lows = [
        float(r["最低温_℃"]) for r in records if r.get("城市") == first_city and r.get("最低温_℃") not in (None, "")
    ]
    assert f"| {first_city} |" in text
    assert f"{min(city_lows)}" in text


def test_render_data_quality(seed_env, db):
    """数据质量体检报告：字段非空计数与附加表（数字格式大全）检查正确。"""
    tables_map, user = seed_env
    ctx, text = _render_spec(db, user, tables_map, "数据质量体检报告")
    records = ctx["records"]
    assert f"| 邮箱 | {_non_empty(records, '邮箱')} |" in text
    assert "100.0%" in text  # 邮箱/手机号等字段在数据集中无空值，完整率应为 100%
    expected_mix = round(_num_sum(records, "混合数值"), 2)
    assert f"混合数值合计：{expected_mix}" in text
    extra_records = ctx["records_by_table"]["17-数字格式大全"]
    assert f"| 十五位长号 | {_non_empty(extra_records, '十五位长号')} |" in text


# ── 端到端 docx 生成 ───────────────────────────────────


def test_generate_sample_reports_writes_docx(seed_env, db, tmp_path: Path):
    """_generate_sample_reports 为全部示例模板落盘 docx，且文档含标题与表格。"""
    from docx import Document

    tables_map, user = seed_env
    out_dir = tmp_path / "datasets"
    for ws_name in REQUIRED_TABLES:
        (out_dir / f"工作区-{ws_name}").mkdir(parents=True)

    _generate_sample_reports(db, tables_map, user, out_dir)

    files = sorted(out_dir.rglob("*-示例报告.docx"))
    expected_names = {f"{s['name']}-示例报告.docx" for s in REPORT_TEMPLATE_SPECS} - {"科研项目季度汇报-示例报告.docx"}
    assert {f.name for f in files} == expected_names
    for f in files:
        assert f.stat().st_size > 1000, f"{f.name} 体积异常"
        doc = Document(str(f))
        assert any(p.style.name.startswith("Heading") for p in doc.paragraphs), f"{f.name} 缺少标题"
        assert doc.tables, f"{f.name} 缺少表格"
