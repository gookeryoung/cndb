"""seed 字段设置种子（fields.json）单元测试.

覆盖：
- _load_field_settings：解析真实 datasets 配置 / 顶层非对象 / 目录缺失；
- _apply_field_settings：必填/唯一标志应用、关联引入（link+lookup）、
  match 行关联回填、backfills 物理列数据回填、缺表/缺字段优雅跳过、
  重复执行幂等；
- import_fields_as_lookup 的 link_name / link_multiple 参数。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cndb.cli.seed import _apply_field_settings, _get_datasets_dir, _load_field_settings


@pytest.fixture
def seed_env(db, db_engine):
    """建两张演示表（课题表 + 负责人表）并插入少量行，返回 tables_map.

    使用真实 CSV 建表服务，保证字段元数据与 seed 主流程一致。
    """
    from cndb.plugins.accounts.models import User
    from cndb.plugins.tables.services.core.records import create_row
    from cndb.plugins.tables.services.transfer import create_table_from_csv
    from cndb.plugins.workspaces.models import Workspace

    user = User(username="fieldcfg", email="fieldcfg@example.com", nickname="字段配置测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    ws = Workspace(name="字段配置测试", description="fields.json 种子测试")
    db.add(ws)
    db.commit()
    db.refresh(ws)

    topic_csv = "课题编号,项目名称,立项年份\nKT001,课题一,2023\nKT002,课题二,2024\n"
    owner_csv = "负责人编号,姓名,课题编号\nFZR001,张三,KT001\nFZR002,李四,KT002\n"
    topic_tbl, _ = create_table_from_csv(db_engine, db, ws.id, "课题表", topic_csv, owner_id=user.id)
    owner_tbl, _ = create_table_from_csv(db_engine, db, ws.id, "负责人表", owner_csv, owner_id=user.id)
    for no, name in [("KT001", "课题一"), ("KT002", "课题二")]:
        create_row(db_engine, topic_tbl, values={"课题编号": no, "项目名称": name})

    # 键 "演示" 对应 datasets/工作区-演示/ 文件夹剥前缀后的工作区显示名
    return {"演示": {"课题表": topic_tbl, "负责人表": owner_tbl}}


def _write_fields_json(tmp_path: Path, payload: dict) -> Path:
    """把 payload 写成 datasets/工作区-演示/fields.json，返回 datasets 目录."""
    ws_dir = tmp_path / "datasets" / "工作区-演示"
    ws_dir.mkdir(parents=True)
    (ws_dir / "fields.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return tmp_path / "datasets"


def test_load_field_settings_from_real_datasets():
    """真实 datasets 目录中的 fields.json 可被解析且结构合法."""
    datasets_dir = _get_datasets_dir()
    if datasets_dir is None:
        pytest.skip("examples/datasets 目录不可用（wheel 安装环境）")

    result = _load_field_settings(datasets_dir)
    assert "科研项目管理" in result, "科研工作区应包含 fields.json 字段设置种子"
    cfg = result["科研项目管理"]
    assert "settings" in cfg and "link_lookups" in cfg
    # 唯一示例字段存在且同时声明 required + unique
    topic_cfg = cfg["settings"]["科研项目"]["课题编号"]
    assert topic_cfg == {"required": True, "unique": True}
    # 关联引入规则引用真实表名，且声明 match（行关联回填）
    for rule in cfg["link_lookups"]:
        assert rule["table"] in {"课题负责人", "项目进展", "科研经费"}
        assert rule["source_table"] == "科研项目"
        assert rule.get("multiple") is False
        assert rule.get("match") == {"local": "课题编号", "source": "课题编号"}
    # backfills 覆盖全部克隆字段的数据回填
    backfills = cfg.get("backfills") or []
    backfill_map = {r["table"]: r for r in backfills}
    assert backfill_map["课题负责人"]["fields"] == ["项目状态"]
    assert backfill_map["项目进展"]["fields"] == ["项目状态", "立项年份"]
    assert backfill_map["科研经费"]["fields"] == ["项目状态", "项目类别"]
    for rule in backfills:
        assert rule["match"] == {"local": "课题编号", "source": "课题编号"}


def test_load_field_settings_invalid_top_level(tmp_path):
    """顶层非对象时解析失败，返回结果中不含该工作区且不抛异常."""
    ws_dir = tmp_path / "datasets" / "工作区-坏配置"
    ws_dir.mkdir(parents=True)
    (ws_dir / "fields.json").write_text('["not", "an", "object"]', encoding="utf-8")

    result = _load_field_settings(tmp_path / "datasets")
    assert result == {}


def test_load_field_settings_missing_dir():
    """datasets 目录不可用时返回空映射."""
    assert _load_field_settings(None) == {}
    assert _load_field_settings(Path("Z:/不存在的目录")) == {}


def test_apply_settings_required_unique(seed_env, db, db_engine, tmp_path):
    """settings 段正确改写 DataField.required / is_unique 标志."""
    datasets_dir = _write_fields_json(
        tmp_path,
        {"settings": {"课题表": {"课题编号": {"required": True, "unique": True}, "项目名称": {"required": True}}}},
    )
    _apply_field_settings(db, db_engine, seed_env, datasets_dir)

    topic_tbl = seed_env["演示"]["课题表"]
    fields = {f.name: f for f in topic_tbl.fields if not f.trashed}
    assert fields["课题编号"].required is True
    assert fields["课题编号"].is_unique is True
    assert fields["项目名称"].required is True
    assert fields["项目名称"].is_unique is False


def test_apply_settings_missing_table_and_field(seed_env, db, db_engine, tmp_path):
    """缺表/缺字段时优雅跳过，不抛异常且不影响其它设置."""
    datasets_dir = _write_fields_json(
        tmp_path,
        {
            "settings": {
                "不存在表": {"字段": {"required": True}},
                "课题表": {"不存在字段": {"required": True}, "课题编号": {"required": True}},
            }
        },
    )
    _apply_field_settings(db, db_engine, seed_env, datasets_dir)

    topic_tbl = seed_env["演示"]["课题表"]
    fields = {f.name: f for f in topic_tbl.fields if not f.trashed}
    assert fields["课题编号"].required is True


def test_apply_link_lookups_creates_link_and_lookup(seed_env, db, db_engine, tmp_path):
    """link_lookups 段创建单选关联字段 + 引用字段，值可实时解析."""
    datasets_dir = _write_fields_json(
        tmp_path,
        {
            "link_lookups": [
                {
                    "table": "负责人表",
                    "source_table": "课题表",
                    "link_name": "关联课题",
                    "multiple": False,
                    "fields": ["项目名称", "立项年份"],
                }
            ]
        },
    )
    _apply_field_settings(db, db_engine, seed_env, datasets_dir)

    owner_tbl = seed_env["演示"]["负责人表"]
    fields = {f.name: f for f in owner_tbl.fields if not f.trashed}
    link = fields["关联课题"]
    assert link.field_type == "link"
    assert link.config["target_table_id"] == seed_env["演示"]["课题表"].id
    assert link.config["multiple"] is False

    topic_fields = {f.name: f for f in seed_env["演示"]["课题表"].fields if not f.trashed}
    for name in ["项目名称", "立项年份"]:
        lookup = fields[name]
        assert lookup.field_type == "lookup"
        assert lookup.config["source_table_id"] == seed_env["演示"]["课题表"].id
        assert lookup.config["source_field_id"] == topic_fields[name].id
        assert lookup.config["via_link_field_id"] == link.id


def test_apply_link_lookups_idempotent(seed_env, db, db_engine, tmp_path):
    """重复执行时 link 复用、同名 lookup 跳过，字段数不再增长."""
    payload = {
        "link_lookups": [
            {
                "table": "负责人表",
                "source_table": "课题表",
                "link_name": "关联课题",
                "multiple": False,
                "fields": ["项目名称"],
            }
        ]
    }
    datasets_dir = _write_fields_json(tmp_path, payload)
    owner_tbl = seed_env["演示"]["负责人表"]

    _apply_field_settings(db, db_engine, seed_env, datasets_dir)
    db.refresh(owner_tbl)
    count_after_first = len([f for f in owner_tbl.fields if not f.trashed])

    _apply_field_settings(db, db_engine, seed_env, datasets_dir)
    db.refresh(owner_tbl)
    count_after_second = len([f for f in owner_tbl.fields if not f.trashed])

    assert count_after_first == count_after_second
    names = [f.name for f in owner_tbl.fields if not f.trashed]
    assert names.count("关联课题") == 1
    assert names.count("项目名称") == 1


def test_apply_link_lookups_missing_table(seed_env, db, db_engine, tmp_path):
    """关联规则引用不存在表时优雅跳过."""
    datasets_dir = _write_fields_json(
        tmp_path,
        {
            "link_lookups": [
                {"table": "不存在表", "source_table": "课题表", "fields": ["项目名称"]},
                {"table": "负责人表", "source_table": "不存在表", "fields": ["项目名称"]},
            ]
        },
    )
    _apply_field_settings(db, db_engine, seed_env, datasets_dir)  # 不抛异常即通过

    owner_tbl = seed_env["演示"]["负责人表"]
    names = [f.name for f in owner_tbl.fields if not f.trashed]
    assert "项目名称" not in names


def test_apply_link_lookups_match_backfills_links(seed_env, db, db_engine, tmp_path):
    """link_lookups 声明 match 时按本地/源匹配列回填行关联，lookup 可实时解析."""
    datasets_dir = _write_fields_json(
        tmp_path,
        {
            "link_lookups": [
                {
                    "table": "负责人表",
                    "source_table": "课题表",
                    "link_name": "关联课题",
                    "multiple": False,
                    "fields": ["项目名称", "立项年份"],
                    "match": {"local": "课题编号", "source": "课题编号"},
                }
            ]
        },
    )
    _apply_field_settings(db, db_engine, seed_env, datasets_dir)

    from cndb.plugins.tables.services.core.links import load_links
    from cndb.plugins.tables.services.core.lookups import attach_lookup_values

    topic_tbl = seed_env["演示"]["课题表"]
    owner_tbl = seed_env["演示"]["负责人表"]
    owner_rows = [
        {"id": r["id"], "课题编号": r["课题编号"]} for r in db_engine_connect_rows(db_engine, owner_tbl, ["课题编号"])
    ]
    topic_ids_by_code = {r["课题编号"]: r["id"] for r in db_engine_connect_rows(db_engine, topic_tbl, ["课题编号"])}
    links = load_links(
        db_engine,
        next(f for f in owner_tbl.active_fields() if f.field_type == "link"),
        [r["id"] for r in owner_rows],
    )
    for row in owner_rows:
        expected = topic_ids_by_code[row["课题编号"]]
        assert links.get(row["id"]) == [expected], f"行 {row['id']} 关联应回填为课题 {expected}"

    # lookup 实时解析：负责人行应拿到对应课题的项目名称
    enriched = attach_lookup_values(db_engine, owner_tbl, [dict(r) for r in owner_rows], db=db)
    names = {
        r["课题编号"]: r["项目名称"] for r in db_engine_connect_rows(db_engine, topic_tbl, ["课题编号", "项目名称"])
    }
    for r in enriched:
        assert r["项目名称"] == names[r["课题编号"]]


def test_apply_backfills_value_fields(seed_env, db, db_engine, tmp_path):
    """backfills 段按匹配列把源表字段值写入目标表克隆物理列."""
    from cndb.plugins.tables.services.fields.field_ops import clone_fields_between_tables

    topic_tbl = seed_env["演示"]["课题表"]
    owner_tbl = seed_env["演示"]["负责人表"]
    # 模拟 _apply_field_import_rules：克隆字段结构（无数据）
    clone_fields_between_tables(db_engine, db, topic_tbl, owner_tbl, field_names=["立项年份"])

    datasets_dir = _write_fields_json(
        tmp_path,
        {
            "backfills": [
                {
                    "table": "负责人表",
                    "source_table": "课题表",
                    "fields": ["立项年份"],
                    "match": {"local": "课题编号", "source": "课题编号"},
                }
            ]
        },
    )
    _apply_field_settings(db, db_engine, seed_env, datasets_dir)

    year_by_code = {
        r["课题编号"]: r["立项年份"] for r in db_engine_connect_rows(db_engine, topic_tbl, ["课题编号", "立项年份"])
    }
    for r in db_engine_connect_rows(db_engine, owner_tbl, ["课题编号", "立项年份"]):
        assert r["立项年份"] == year_by_code[r["课题编号"]], (
            f"行课题 {r['课题编号']} 的立项年份应回填为 {year_by_code[r['课题编号']]}"
        )


def test_apply_backfills_idempotent_and_unmatched_skipped(seed_env, db, db_engine, tmp_path):
    """重复回填结果一致；匹配不上的行保持原值不被清空."""
    from cndb.plugins.tables.services.fields.field_ops import clone_fields_between_tables

    topic_tbl = seed_env["演示"]["课题表"]
    owner_tbl = seed_env["演示"]["负责人表"]
    clone_fields_between_tables(db_engine, db, topic_tbl, owner_tbl, field_names=["立项年份"])

    datasets_dir = _write_fields_json(
        tmp_path,
        {
            "backfills": [
                {
                    "table": "负责人表",
                    "source_table": "课题表",
                    "fields": ["立项年份"],
                    "match": {"local": "课题编号", "source": "课题编号"},
                }
            ]
        },
    )
    _apply_field_settings(db, db_engine, seed_env, datasets_dir)
    rows_first = db_engine_connect_rows(db_engine, owner_tbl, ["负责人编号", "课题编号", "立项年份"])

    _apply_field_settings(db, db_engine, seed_env, datasets_dir)
    rows_second = db_engine_connect_rows(db_engine, owner_tbl, ["负责人编号", "课题编号", "立项年份"])
    assert rows_first == rows_second


def test_backfill_rows_by_match_missing_columns(seed_env, db, db_engine):
    """匹配列不存在时返回 0 且不抛异常."""
    from cndb.cli.seed import _backfill_rows_by_match

    topic_tbl = seed_env["演示"]["课题表"]
    owner_tbl = seed_env["演示"]["负责人表"]
    assert _backfill_rows_by_match(db_engine, db, owner_tbl, topic_tbl, "不存在列", "课题编号") == 0
    assert _backfill_rows_by_match(db_engine, db, owner_tbl, topic_tbl, "课题编号", "不存在列") == 0


def db_engine_connect_rows(engine: Any, table: Any, col_names: list[str]) -> list[dict[str, Any]]:
    """按字段名读取物理表全部行（测试辅助，返回 {字段名: 值} 含 id）."""
    from sqlalchemy import select

    from cndb.cli.seed import _get_sa_table_by_name

    sa_tbl = _get_sa_table_by_name(engine, table.db_table_name)
    cols = {f.name: f.db_column_name for f in table.active_fields()}
    with engine.connect() as conn:
        rows = conn.execute(select(sa_tbl.c.id, *[sa_tbl.c[cols[n]] for n in col_names])).all()
    result = []
    for r in rows:
        mapping = dict(r._mapping)
        item: dict[str, Any] = {"id": mapping["id"]}
        for name in col_names:
            item[name] = mapping[cols[name]]
        result.append(item)
    return result
