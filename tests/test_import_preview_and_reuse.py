"""preview=False 与归一值复用的等价性（ADR 0040 D5）."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.importing.importer import Importer

FIELDS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("代码", "text", {}),
    ("日期", "date", {}),
    ("收盘", "float", {"decimals": 2}),
    ("来源", "select", {"options": [{"label": "腾讯前复权", "value": "腾讯前复权"}]}),
    ("更新时间", "datetime", {"auto_fill": "on_update"}),
)


def _make_table(db: Session, engine: Any, name: str) -> DataTable:
    table = DataTable(workspace_id=1, name=name)
    table.ensure_db_name()
    db.add(table)
    db.commit()
    db.refresh(table)
    for order, (field_name, field_type, config) in enumerate(FIELDS):
        field = DataField(table_id=table.id, name=field_name, field_type=field_type, config=config, order=order)
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(table)
    ddl.create_table(engine, table)
    return table


def _seed(db: Session, engine: Any, table: DataTable) -> list[int]:
    return rec.bulk_create(
        engine,
        table,
        [
            {"代码": "sh600519", "日期": "2026-10-23", "收盘": 1500.0, "来源": "腾讯前复权"},
            {"代码": "sz000001", "日期": "2026-10-23", "收盘": 11.0, "来源": "腾讯前复权"},
        ],
        db=db,
    )


def _incoming() -> list[dict[str, Any]]:
    """2 行更新（1 有变化、1 无变化）+ 2 行新增 + 1 行校验失败."""
    return [
        {"代码": "sh600519", "日期": "2026-10-23", "收盘": 1510.0, "来源": "腾讯前复权"},
        {"代码": "sz000001", "日期": "2026-10-23", "收盘": 11.0, "来源": "腾讯前复权"},
        {"代码": "sh601318", "日期": "2026-10-24", "收盘": 48.5, "来源": "腾讯前复权"},
        {"代码": "sz300750", "日期": "2026-10-24", "收盘": 180.2, "来源": "腾讯前复权"},
        {"代码": "sh600036", "日期": "2026-10-24", "收盘": "无成交", "来源": "腾讯前复权"},
    ]


def _run(db: Session, engine: Any, table: DataTable, *, preview: bool) -> tuple[Any, Any]:
    importer = Importer(engine, db, table, partial=True)
    analysis = importer.analyze("", rows=_incoming(), match_keys=["代码", "日期"], light=True, preview=preview)
    result = importer.execute(analysis=analysis, match_keys=["代码", "日期"], sync_options=False, preview=preview)
    return analysis, result


def _db_col(table: DataTable, name: str) -> str:
    return next(field.db_column_name for field in table.active_fields() if field.name == name)


def _rows(db: Session, engine: Any, table: DataTable) -> dict[str, dict[str, Any]]:
    return {row["代码"]: row for row in rec.list_rows(engine, table, db=db, limit=100)[0]}


def test_preview_false_keeps_write_result_identical(db: Session, db_engine: Any) -> None:
    """关闭预览不改变 upsert 分类、计数与落库行内容."""
    left = _make_table(db, db_engine, "PREVIEW_ON")
    right = _make_table(db, db_engine, "PREVIEW_OFF")
    _seed(db, db_engine, left)
    _seed(db, db_engine, right)

    analysis_on, result_on = _run(db, db_engine, left, preview=True)
    analysis_off, result_off = _run(db, db_engine, right, preview=False)

    for key in ("new_count", "update_count", "multi_key_conflicts"):
        assert analysis_off.upsert_result[key] == analysis_on.upsert_result[key]
    assert analysis_off.upsert_result["new_preview"] == []
    assert analysis_off.upsert_result["update_preview"] == []
    assert analysis_off.upsert_result["update_changed_count"] == 0
    assert analysis_on.upsert_result["new_preview"] and analysis_on.upsert_result["update_preview"]

    assert result_off.report["actually_created"] == result_on.report["actually_created"] == 2
    assert result_off.report["actually_updated"] == result_on.report["actually_updated"] == 2
    assert result_off.report["error_count"] == result_on.report["error_count"] == 1

    rows_on = _rows(db, db_engine, left)
    rows_off = _rows(db, db_engine, right)
    assert rows_on.keys() == rows_off.keys()
    for code in rows_on:
        for name in ("日期", "收盘", "来源"):
            assert rows_off[code][name] == rows_on[code][name], (code, name)
        # on_update 时间戳两轮各取当前时间：只需确认被填充（复用路径不能漏掉自动填充）
        assert rows_off[code]["更新时间"] is not None
        assert rows_on[code]["更新时间"] is not None


def test_preview_false_skips_old_row_fetch_and_diffs(db: Session, db_engine: Any, monkeypatch: Any) -> None:
    """preview=False 不查旧行、不算字段 diff，且 update 行携带校验产出的归一值."""
    table = _make_table(db, db_engine, "PREVIEW_SPY")
    _seed(db, db_engine, table)
    calls: dict[str, int] = {"fetch": 0, "diffs": 0}

    def spy_fetch(self: Importer, _row_ids: list[int]) -> dict[int, dict[str, Any]]:
        calls["fetch"] += 1
        return {}

    def spy_diffs(_old: Any, _new: Any, _keys: Any) -> dict[str, Any]:
        calls["diffs"] += 1
        return {}

    monkeypatch.setattr(Importer, "_fetch_old_rows_by_ids", spy_fetch)
    monkeypatch.setattr(Importer, "_build_field_diffs", staticmethod(spy_diffs))

    analysis, _result = _run(db, db_engine, table, preview=False)
    assert calls == {"fetch": 0, "diffs": 0}
    update_rows = analysis.upsert_result["update_rows"]
    assert update_rows and all("normalized" in item for item in update_rows)
    assert _db_col(table, "收盘") in update_rows[0]["normalized"]


def test_reuse_normalized_matches_legacy_normalize(db: Session, db_engine: Any) -> None:
    """记录层归一复用与旧路径逐格校验结果一致（含空值清空与数字类型）."""
    legacy = _make_table(db, db_engine, "REUSE_LEGACY")
    reused = _make_table(db, db_engine, "REUSE_FAST")
    ids_legacy = _seed(db, db_engine, legacy)
    ids_reused = _seed(db, db_engine, reused)

    payloads = [
        {"收盘": "1600.5", "来源": "腾讯前复权"},
        {"收盘": None, "来源": "腾讯前复权"},
    ]
    plan = rec._build_normalize_plan(reused, for_update=True)
    legacy_updates = [{"row_id": row_id, "values": values} for row_id, values in zip(ids_legacy, payloads, strict=True)]
    reused_updates = []
    for row_id, values in zip(ids_reused, payloads, strict=True):
        normalized, _links = rec._normalize_row_with_plan(plan, values, for_update=True)
        reused_updates.append({"row_id": row_id, "values": values, "normalized": normalized})

    assert rec.bulk_update_rows(db_engine, legacy, legacy_updates, db=db) == 2
    assert rec.bulk_update_rows(db_engine, reused, reused_updates, db=db, reuse_normalized=True) == 2

    rows_legacy = _rows(db, db_engine, legacy)
    rows_reused = _rows(db, db_engine, reused)
    for code in rows_legacy:
        for name in ("收盘", "来源"):
            assert rows_reused[code][name] == rows_legacy[code][name], (code, name)
    assert rows_reused["sh600519"]["收盘"] == 1600.5
    assert rows_reused["sz000001"]["收盘"] is None


def test_reuse_normalized_falls_back_for_unvalidated_fields(db: Session, db_engine: Any) -> None:
    """复用只覆盖已归一字段；未产出的字段仍按原语义校验（空串 → 清空）."""
    table = _make_table(db, db_engine, "REUSE_FALLBACK")
    ids = _seed(db, db_engine, table)
    plan = rec._build_normalize_plan(table, for_update=True)
    values = {"收盘": None, "来源": "腾讯前复权"}
    normalized, _links = rec._normalize_row_with_plan(plan, values, for_update=True)
    # 去掉「来源」的归一结果，模拟校验层未产出该字段：写入仍须落库正确值
    partial = {key: value for key, value in normalized.items() if key != _db_col(table, "来源")}
    assert (
        rec.bulk_update_rows(
            db_engine,
            table,
            [{"row_id": ids[0], "values": values, "normalized": partial}],
            db=db,
            reuse_normalized=True,
        )
        == 1
    )
    row = rec.get_row(db_engine, table, ids[0], db=db)
    assert row is not None
    assert row["收盘"] is None
    assert row["来源"] == "腾讯前复权"
    assert isinstance(row["更新时间"], dt.datetime)
