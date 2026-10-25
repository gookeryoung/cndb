"""轻量落表模式等价性（ADR 0035 D2）：默认链路 vs 数据源同步链路.

核心不变量 I2：同一输入批次，``light=True`` 与默认模式的写入行集合、
``actually_created`` / ``actually_updated`` / ``error_count`` 完全一致；
轻量模式只跳过报告类产物（列画像 / 参考列推荐 / 清洗建议 / 全表选项同步）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.importing import importer as importer_module
from cndb.plugins.tables.services.importing.importer import Importer

REPORT_ONLY_KEYS = ("column_profiles", "data_quality_summary", "match_key_recommendations", "cleaning_suggestions")


def _make_table(session: Session, engine, name: str) -> DataTable:
    table = DataTable(workspace_id=1, name=name)
    table.ensure_db_name()
    session.add(table)
    session.commit()
    session.refresh(table)
    for order, (field_name, field_type, config) in enumerate(
        (
            ("代码", "text", {}),
            ("日期", "date", {}),
            ("收盘", "float", {"decimals": 2}),
            ("来源", "select", {"options": [{"label": "腾讯前复权", "value": "腾讯前复权"}]}),
        )
    ):
        field = DataField(table_id=table.id, name=field_name, field_type=field_type, config=config, order=order)
        field.ensure_db_name()
        session.add(field)
    session.commit()
    session.refresh(table)
    ddl.create_table(engine, table)
    return table


def _seed(session: Session, engine, table: DataTable) -> None:
    rec.bulk_create(
        engine,
        table,
        [
            {"代码": "sh600519", "日期": "2026-10-23", "收盘": 1500.0, "来源": "腾讯前复权"},
            {"代码": "sz000001", "日期": "2026-10-23", "收盘": 11.0, "来源": "腾讯前复权"},
        ],
        db=session,
    )


def _incoming_rows() -> list[dict[str, Any]]:
    """混合批次：2 行更新（其中 1 行无变化）+ 2 行新增 + 1 行收盘非数字（error）.

    选项字段的非法值不在此列：批内 prefill 会先把新值补进 options（既有语义），
    既覆盖「新标的代码入选」场景，也让轻量模式不必依赖全表选项同步。
    """
    return [
        {"代码": "sh600519", "日期": "2026-10-23", "收盘": 1510.0, "来源": "腾讯前复权"},
        {"代码": "sz000001", "日期": "2026-10-23", "收盘": 11.0, "来源": "腾讯前复权"},
        {"代码": "sh601318", "日期": "2026-10-24", "收盘": 48.5, "来源": "腾讯前复权"},
        {"代码": "sz300750", "日期": "2026-10-24", "收盘": 180.2, "来源": "腾讯前复权"},
        {"代码": "sh600036", "日期": "2026-10-24", "收盘": "无成交", "来源": "腾讯前复权"},
    ]


def _run(session: Session, engine, table: DataTable, *, light: bool) -> Any:
    importer = Importer(engine, session, table, partial=True)
    analysis = importer.analyze("", rows=_incoming_rows(), match_keys=["代码", "日期"], light=light)
    result = importer.execute(analysis=analysis, match_keys=["代码", "日期"], sync_options=not light)
    return analysis, result


def _table_snapshot(engine, table: DataTable) -> list[dict[str, Any]]:
    sa_table = rec._get_sa_table(engine, table)
    columns = {f.name: sa_table.c[f.db_column_name].label(f.name) for f in table.active_fields()}
    with engine.connect() as conn:
        rows = conn.execute(select(*columns.values())).mappings().all()
    return sorted(({name: row[name] for name in columns} for row in rows), key=lambda r: (r["代码"], r["日期"]))


class TestLightModeEquivalence:
    def test_write_result_and_rows_identical(self, db_engine, db):
        """I2：默认与轻量模式写入行集合、计数、错误行完全一致."""
        table_default = _make_table(db, db_engine, "默认导入表")
        table_light = _make_table(db, db_engine, "同步落表")
        _seed(db, db_engine, table_default)
        _seed(db, db_engine, table_light)

        analysis_default, result_default = _run(db, db_engine, table_default, light=False)
        analysis_light, result_light = _run(db, db_engine, table_light, light=True)

        assert result_light.report["actually_created"] == result_default.report["actually_created"] == 2
        assert result_light.report["actually_updated"] == result_default.report["actually_updated"] == 2
        assert result_light.report["error_count"] == result_default.report["error_count"] == 1
        assert len(result_light.failed_results) == len(result_default.failed_results) == 1
        assert _table_snapshot(db_engine, table_light) == _table_snapshot(db_engine, table_default)
        assert analysis_light.report["skipped_columns"] == analysis_default.report["skipped_columns"]
        assert analysis_light.report["valid_count"] == analysis_default.report["valid_count"]

    def test_light_report_shape_keeps_keys_but_skips_heavy_sections(self, db_engine, db):
        """轻量报告键集合不变，画像 / 推荐 / 清洗建议为空."""
        table = _make_table(db, db_engine, "同步落表")
        _seed(db, db_engine, table)
        analysis, _result = _run(db, db_engine, table, light=True)
        for key in REPORT_ONLY_KEYS:
            assert analysis.report[key] in ([], {}), key
        # 校验与匹配结果照常产出
        assert analysis.report["error_count"] == 1
        assert analysis.report["update_count"] == 2
        assert analysis.report["planned_columns"] == []

    def test_light_skips_full_table_options_sync(self, db_engine, db, monkeypatch):
        """sync_options=False 不调用全表选项同步；默认模式仍调用一次."""
        calls: list[str] = []

        def _spy(_db: Any, _table: DataTable) -> list[str]:
            calls.append("sync")
            return []

        monkeypatch.setattr(
            "cndb.plugins.tables.services.fields.field_ops.sync_select_options_from_table",
            _spy,
        )
        table = _make_table(db, db_engine, "同步落表")
        _seed(db, db_engine, table)
        _run(db, db_engine, table, light=True)
        assert calls == []

        table_default = _make_table(db, db_engine, "默认导入表")
        _seed(db, db_engine, table_default)
        _run(db, db_engine, table_default, light=False)
        assert calls == ["sync"]

    def test_light_skips_profile_and_recommendation(self, db_engine, db, monkeypatch):
        """轻量模式不计算列画像 / 参考列推荐（报告类产物对同步无人消费）."""
        called: list[str] = []

        def _profile(*_args: Any, **_kwargs: Any) -> Any:
            called.append("profile")
            return [], {}

        def _recommend(*_args: Any, **_kwargs: Any) -> Any:
            called.append("recommend")
            return []

        monkeypatch.setattr(importer_module, "profile_columns", _profile)
        monkeypatch.setattr(importer_module, "recommend_match_keys", _recommend)

        table = _make_table(db, db_engine, "同步落表")
        _seed(db, db_engine, table)
        _run(db, db_engine, table, light=True)
        assert called == []

        table_default = _make_table(db, db_engine, "默认导入表")
        _seed(db, db_engine, table_default)
        _run(db, db_engine, table_default, light=False)
        assert called == ["profile", "recommend"]

    def test_light_still_writes_new_select_options_from_batch(self, db_engine, db):
        """轻量模式仍做批内选项预填充：新值写入后不会在下批被判非法."""
        table = _make_table(db, db_engine, "同步落表")
        _seed(db, db_engine, table)
        importer = Importer(db_engine, db, table, partial=True)
        importer.analyze("", rows=_incoming_rows(), match_keys=["代码", "日期"], light=True)
        importer.execute(analysis=importer.analyze("", rows=_incoming_rows(), match_keys=["代码", "日期"], light=True))

        source_field = next(f for f in table.active_fields() if f.name == "来源")
        labels = {item["label"] for item in source_field.config.get("options", [])}
        assert "腾讯前复权" in labels

        count = db.execute(select(func.count()).select_from(rec._get_sa_table(db_engine, table))).scalar()
        assert count == 4
