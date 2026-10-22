"""ADR 0019 P1：llm_prompt 空表自动建表 / 自动补字段 / 自动幂等键测试.

覆盖：

- 目标表留空 → 按任务名自动建表（含默认视图「全部」），首轮 inserted、次轮 updated 不重复；
- 已有空表（无字段 / 无数据行）→ 同步时自动新增字段；
- 已有数据表 → 不自动加字段；
- 无唯一列 → 不推断幂等键，仍按纯追加落表；
- 非 llm_prompt provider → 不自动建表（行为保持不变）；
- 幂等键推断算法单测（单列唯一加权 / 全空列过滤 / 2-3 列组合 / 无解）。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from cndb.core.crypto import encrypt_secrets
from cndb.plugins.datasource.models import DatasourceSession, DatasourceSyncJob
from cndb.plugins.datasource.services.auto_table import (
    candidate_names,
    ensure_job_table,
    infer_match_keys,
)
from cndb.plugins.datasource.services.runner import execute_job
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.importing.api_fetch import FetchConfig

UTC = dt.UTC
NOW = dt.datetime(2024, 7, 1, 9, 0, tzinfo=UTC)


def _fetch(rows: list[dict[str, Any]]):
    def fetch(_config: FetchConfig) -> list[dict[str, Any]]:
        return rows

    return fetch


def _make_llm_job(
    db: Session,
    *,
    name: str = "天气同步",
    table_id: int | None = None,
    match_keys: list[str] | None = None,
) -> DatasourceSyncJob:
    """建一个大模型提示词任务：带 api_key 的凭证会话（provider 运行必需）."""
    session = DatasourceSession(
        workspace_id=1,
        name="LLM",
        headers={},
        secrets=encrypt_secrets({"api_key": "sk-test"}),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    job = DatasourceSyncJob(
        workspace_id=1,
        name=name,
        provider="llm_prompt",
        table_id=table_id,
        request_spec={
            "url_template": "https://llm.example.com/v1",
            "prompt": {"system": "你是数据助手", "user_template": "生成 {today} 的天气摘要"},
            "llm": {"model": "model-a", "temperature": 0.2},
        },
        parser="json",
        entrant_param=None,
        entrant_keys=[],
        match_keys=list(match_keys or []),
        field_mapping={},
        session_id=session.id,
        cursor={"strategy": "none"},
        schedule={"mode": "manual"},
        enabled=True,
        last_status="",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _make_table(db: Session, engine: Any, name: str, fields: list[tuple[str, str]]) -> DataTable:
    table = DataTable(workspace_id=1, name=name)
    table.ensure_db_name()
    db.add(table)
    db.commit()
    db.refresh(table)
    for order, (field_name, field_type) in enumerate(fields):
        field = DataField(table_id=table.id, name=field_name, field_type=field_type, order=order)
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(table)
    ddl.create_table(engine, table)
    return table


def _field_names(table: DataTable) -> set[str]:
    return {field.name for field in table.active_fields()}


class TestAutoCreateTable:
    def test_first_run_creates_table_then_second_run_updates(self, db: Session, db_engine):
        job = _make_llm_job(db)
        rows = [
            {"date": "2024-07-01", "city": "北京", "temp": "33"},
            {"date": "2024-07-02", "city": "上海", "temp": "30"},
        ]
        first = execute_job(db, job, fetch=_fetch(rows), now=NOW)

        assert first.run.status == "success"
        assert (first.run.fetched, first.run.inserted, first.run.updated) == (2, 2, 0)
        db.refresh(job)
        assert job.table_id is not None
        table = db.get(DataTable, job.table_id)
        assert table is not None
        assert table.name == "天气同步"
        assert {"date", "city", "temp"} <= _field_names(table)
        # 默认视图「全部」随建表一起生成
        assert any(view.name == "全部" for view in table.views)
        # 留痕：自动新增字段 + 自动推断的幂等键
        assert set(first.run.detail["auto_fields"]) >= {"date", "city", "temp"}
        assert first.run.detail["auto_match_keys"] == ["date"]
        assert job.match_keys == ["date"]  # 回填并持久化，后续运行沿用

        second_rows = [
            {"date": "2024-07-01", "city": "北京", "temp": "35"},
            {"date": "2024-07-02", "city": "上海", "temp": "31"},
        ]
        second = execute_job(db, job, fetch=_fetch(second_rows), now=NOW)
        assert (second.run.inserted, second.run.updated) == (0, 2)
        assert second.run.detail["auto_fields"] == []  # 已有数据行 → 不再补字段
        assert second.run.detail["auto_match_keys"] == ["date"]

    def test_same_name_table_is_reused_not_recreated(self, db: Session, db_engine):
        job = _make_llm_job(db)
        table = _make_table(db, db_engine, "天气同步", [("date", "text")])
        rows = [{"date": "2024-07-01", "city": "北京"}]

        execution = execute_job(db, job, fetch=_fetch(rows), now=NOW)

        assert execution.run.status == "success"
        db.refresh(job)
        assert job.table_id == table.id
        assert db.query(DataTable).filter(DataTable.name == "天气同步").count() == 1
        # 复用的空表也允许补字段（无数据行）
        assert {"date", "city"} <= _field_names(db.get(DataTable, table.id))


class TestExistingTable:
    def test_empty_table_gets_fields_added(self, db: Session, db_engine):
        table = _make_table(db, db_engine, "空天气表", [("date", "text")])
        job = _make_llm_job(db, table_id=table.id)
        rows = [{"date": "2024-07-01", "city": "北京", "temp": "33"}]

        execution = execute_job(db, job, fetch=_fetch(rows), now=NOW)

        assert execution.run.status == "success"
        assert (execution.run.inserted, execution.run.fetched) == (1, 1)
        assert {"date", "city", "temp"} <= _field_names(db.get(DataTable, table.id))
        assert set(execution.run.detail["auto_fields"]) >= {"city", "temp"}

    def test_table_with_rows_does_not_add_fields(self, db: Session, db_engine):
        table = _make_table(db, db_engine, "有数据天气表", [("city", "text"), ("day", "text")])
        job = _make_llm_job(db, table_id=table.id)
        # 预置一行已有数据 → 不是空表
        from cndb.plugins.datasource.services.write import upsert_rows

        upsert_rows(db_engine, db, table, [{"city": "北京", "day": "2024-06-30"}])

        execution = execute_job(
            db,
            job,
            fetch=_fetch([{"city": "上海", "day": "2024-07-01", "temp": "30"}]),
            now=NOW,
        )

        assert execution.run.status == "success"
        assert execution.run.detail["auto_fields"] == []
        assert _field_names(db.get(DataTable, table.id)) == {"city", "day"}

    def test_no_unique_key_still_appends(self, db: Session, db_engine):
        job = _make_llm_job(db)
        rows = [
            {"城市": "北京", "状态": "晴"},
            {"城市": "北京", "状态": "晴"},
        ]
        execution = execute_job(db, job, fetch=_fetch(rows), now=NOW)

        assert execution.run.status == "success"
        assert (execution.run.fetched, execution.run.inserted) == (2, 2)
        assert execution.run.detail["auto_match_keys"] == []
        db.refresh(job)
        assert job.match_keys == []  # 无唯一组合 → 保持纯追加
        assert {"城市", "状态"} <= _field_names(db.get(DataTable, job.table_id))


class TestNonLlmProviderUnchanged:
    def test_http_json_does_not_auto_create_table(self, db: Session, db_engine):
        job = DatasourceSyncJob(
            workspace_id=1,
            name="普通 HTTP 同步",
            provider="http_json",
            table_id=None,
            request_spec={"url_template": "https://api.example.com/x"},
            parser="json",
            cursor={"strategy": "none"},
            schedule={"mode": "manual"},
            enabled=True,
            last_status="",
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        execution = execute_job(db, job, fetch=_fetch([{"city": "北京"}]), now=NOW)

        assert execution.run.status == "success"
        assert execution.run.fetched == 1
        assert execution.run.detail["auto_fields"] == []
        assert execution.run.detail["auto_match_keys"] == []
        db.refresh(job)
        assert job.table_id is None
        assert db.query(DataTable).count() == 0


class TestEnsureJobTable:
    def test_idempotent_and_backfills_job(self, db: Session, db_engine):
        job = _make_llm_job(db, name="幂等建表")
        first = ensure_job_table(db, job)
        second = ensure_job_table(db, job)

        assert first.id == second.id
        assert db.query(DataTable).filter(DataTable.name == "幂等建表").count() == 1
        db.refresh(job)
        assert job.table_id == first.id
        assert ddl.table_exists(db_engine, first.db_table_name)


class TestInferMatchKeys:
    def test_single_unique_weighted_by_name(self):
        rows = [
            {"date": "2024-07-01", "value": "a"},
            {"date": "2024-07-02", "value": "b"},
        ]
        # 两列都唯一 → 名称像键的 date 优先
        assert infer_match_keys(rows, ["date", "value"]) == ["date"]

    def test_chinese_field_names_are_weighted_as_keys(self):
        """中文键名同样参与「像键」加权（大模型默认输出中文字段，2026-10-23）."""
        rows = [
            {"日期": "2026-10-22", "摘要": "a"},
            {"日期": "2026-10-23", "摘要": "b"},
        ]
        # 两列都唯一 → 名称像键的「日期」优先
        assert infer_match_keys(rows, ["日期", "摘要"]) == ["日期"]

    def test_chinese_three_column_combination(self):
        """无单列 / 两列唯一时，中文三列组合仍能推断出来."""
        rows = [
            {"日期": "1", "地区": "1", "标题": "1"},
            {"日期": "1", "地区": "1", "标题": "2"},
            {"日期": "1", "地区": "2", "标题": "1"},
            {"日期": "2", "地区": "1", "标题": "1"},
        ]
        # 组合内顺序按「像键」权重排（日期 / 标题 命中中文提示词片段，排在 地区 之前）
        assert sorted(infer_match_keys(rows, ["日期", "地区", "标题"])) == sorted(["日期", "地区", "标题"])

    def test_all_empty_column_is_ignored(self):
        rows = [
            {"date": "", "code": "sh600519"},
            {"date": "  ", "code": "sh000001"},
        ]
        assert infer_match_keys(rows, ["date", "code"]) == ["code"]

    def test_two_column_combination_when_no_single_unique(self):
        rows = [
            {"city": "北京", "day": "2024-07-01"},
            {"city": "北京", "day": "2024-07-02"},
            {"city": "上海", "day": "2024-07-01"},
        ]
        assert infer_match_keys(rows, ["city", "day"]) == ["city", "day"]

    def test_returns_empty_when_no_unique_combination(self):
        rows = [
            {"city": "北京", "weather": "晴"},
            {"city": "北京", "weather": "晴"},
        ]
        assert infer_match_keys(rows, ["city", "weather"]) == []

    def test_three_column_combination_when_no_pair_unique(self):
        rows = [
            {"date": "1", "city": "1", "category": "1"},
            {"date": "1", "city": "1", "category": "2"},
            {"date": "1", "city": "2", "category": "1"},
            {"date": "2", "city": "1", "category": "1"},
        ]
        # 任意两列组合都有重复，只有三列组合在全部行上唯一
        assert infer_match_keys(rows, ["date", "city", "category"]) == ["date", "city", "category"]

    def test_empty_inputs_return_empty(self):
        assert infer_match_keys([], ["date"]) == []
        assert infer_match_keys([{"date": "2024-07-01"}], []) == []
        assert infer_match_keys([{"date": ""}, {"date": " "}], ["date"]) == []

    def test_candidate_names_intersect_fields(self):
        rows = [{"date": "2024-07-01", "extra": 1}]
        assert candidate_names(rows, ["date", "city"]) == ["date"]
        assert candidate_names(rows, []) == ["date", "extra"]
