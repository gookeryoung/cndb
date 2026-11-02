"""采集语义辅助 P3：rule_draft / item_summary / run_report / failure_diagnose（ADR 0085 §5）."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.plugins.acquisition.models import AcquisitionRound, AcquisitionRun, AcquisitionStrategy
from cndb.plugins.acquisition.services import ai as acquisition_ai
from cndb.plugins.acquisition.services.ai import (
    ACTION_FAILURE_DIAGNOSE,
    ACTION_ITEM_SUMMARY,
    ACTION_RULE_DRAFT,
    ACTION_RUN_REPORT,
    ItemSummary,
    RuleDraft,
    diagnose_run,
    draft_rules,
    sanitize_rule_draft,
    summarize_item,
    write_run_report,
)
from cndb.plugins.acquisition.services.runner import execute_strategy
from cndb.plugins.datasource.services.pipeline import PipelineOutcome
from cndb.plugins.llm.services.errors import LlmNotConfigured
from cndb.plugins.llm.services.gateway import LlmResult
from tests.test_acquisition_iteration import (
    _make_job,
    _make_table,
    _make_workspace,
    _table_strategy,
)

UTC = dt.UTC
NOW = dt.datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def _result(parsed: object, *, text: str = "", model: str = "test-model") -> LlmResult:
    return LlmResult(content=text or "…", parsed=parsed, model=model, usage={"total_tokens": 42}, run_id=7)


class TestSanitizeRuleDraft:
    def test_drops_out_of_whitelist_channels_and_targets(self) -> None:
        raw = {
            "scope": {
                "channels": ["job:1", "job:99", "rss:", "unknown:foo"],
                "query": "固态电池",
                "max_results_per_channel": 999,
            },
            "targets": [
                {"kind": "table", "table_id": 5, "match_keys": ["city"]},
                {"kind": "table", "table_id": 77},
                {"kind": "document", "parent_id": 3},
                {"kind": "document", "parent_id": 88},
            ],
            "iteration": {"max_rounds": 9, "expand": {"review": "manual"}, "budget": {"max_requests": 5000}},
            "filter_rule": {"must_have_keywords": ["固态", "固态", ""], "min_citations": -5, "api_key": "sk-xxx"},
            "notes": "仅猜了渠道",
        }
        draft = sanitize_rule_draft(
            raw,
            allowed_channels=["job:1", "rss:", "arxiv:"],
            allowed_table_ids=[5],
            allowed_folder_ids=[3],
        )
        assert draft["scope"]["channels"] == ["job:1", "rss:"]
        assert draft["scope"]["max_results_per_channel"] == 200
        assert draft["targets"] == [
            {"kind": "table", "table_id": 5, "match_keys": ["city"]},
            {"kind": "document", "parent_id": 3},
        ]
        assert draft["iteration"] == {"max_rounds": 5, "expand": {"review": "manual"}, "budget": {"max_requests": 1000}}
        assert draft["filter_rule"]["must_have_keywords"] == ["固态"]
        assert draft["filter_rule"]["min_citations"] == 0
        # 任何 Key 类字段都不会透传
        assert "api_key" not in draft["filter_rule"]
        assert "api_key" not in draft["scope"]

    def test_empty_input_gives_skeleton(self) -> None:
        draft = sanitize_rule_draft({}, allowed_channels=[], allowed_table_ids=[], allowed_folder_ids=[])
        assert draft == {
            "scope": {"channels": []},
            "filter_rule": {},
            "targets": [],
            "iteration": {},
            "notes": "",
        }


class TestRuleDraft:
    def test_success_returns_draft_and_meta(self, db, monkeypatch) -> None:
        ws, user = _make_workspace(db, "草案工作区")
        parsed = RuleDraft(
            scope={"channels": ["job:2"], "query": "{today} 固态电池"},
            filter_rule={"must_have_keywords": ["电解质"]},
            targets=[{"kind": "table", "table_id": 11, "match_keys": ["city"]}],
            iteration={"max_rounds": 2},
            notes="渠道来自既有任务",
        )
        calls: dict[str, object] = {}

        def fake_invoke(db_, user_, action, *, user_content, context=None, connection=None):
            calls["action"] = action.name
            calls["content"] = user_content
            return _result(parsed)

        monkeypatch.setattr(acquisition_ai, "invoke", fake_invoke)
        draft, meta = draft_rules(
            db,
            user,
            description="每天抓固态电池政策",
            allowed_channels=["job:2"],
            allowed_table_ids=[11],
            allowed_folder_ids=[],
            context_lines=["表 id=11 名称=政策"],
            workspace_id=ws.id,
        )

        assert calls["action"] == ACTION_RULE_DRAFT
        assert "每天抓固态电池政策" in str(calls["content"])
        assert draft["scope"]["channels"] == ["job:2"]
        assert draft["targets"] == [{"kind": "table", "table_id": 11, "match_keys": ["city"]}]
        assert meta["model"] == "test-model" and meta["run_id"] == 7 and meta["degraded"] == ""

    def test_degrade_when_not_configured(self, db, monkeypatch) -> None:
        ws, user = _make_workspace(db, "草案降级")

        def boom(*args, **kwargs):
            raise LlmNotConfigured("未配置")

        monkeypatch.setattr(acquisition_ai, "invoke", boom)
        draft, meta = draft_rules(
            db,
            user,
            description="抓点东西",
            allowed_channels=["job:1"],
            allowed_table_ids=[],
            allowed_folder_ids=[],
            workspace_id=ws.id,
        )
        assert draft["scope"]["channels"] == []
        assert meta["degraded"] == "LlmNotConfigured"

    def test_empty_description_skips_model(self, db) -> None:
        _ws, user = _make_workspace(db, "草案空描述")
        draft, meta = draft_rules(
            db,
            user,
            description="   ",
            allowed_channels=[],
            allowed_table_ids=[],
            allowed_folder_ids=[],
        )
        assert draft["targets"] == []
        assert meta["degraded"] == "empty_description"

    def test_action_registered(self) -> None:
        from cndb.plugins.llm.services.actions import get

        for name in (ACTION_RULE_DRAFT, ACTION_ITEM_SUMMARY, ACTION_RUN_REPORT, ACTION_FAILURE_DIAGNOSE):
            assert get(name) is not None, name


class TestItemSummary:
    def test_success_normalizes_tags(self, db, monkeypatch) -> None:
        _ws, user = _make_workspace(db, "摘要工作区")
        monkeypatch.setattr(
            acquisition_ai,
            "invoke",
            lambda *a, **k: _result(
                ItemSummary(summary="一句话摘要", tags=["固态", "固态", "电解质"], category="论文")
            ),
        )
        summary, meta = summarize_item(db, user, item={"title": "标题", "summary": "正文"})
        assert summary["summary"] == "一句话摘要"
        assert summary["tags"] == ["固态", "电解质"]
        assert summary["category"] == "论文"
        assert meta["model"] == "test-model"

    def test_degrade_falls_back_to_raw_summary(self, db, monkeypatch) -> None:
        _ws, user = _make_workspace(db, "摘要降级")

        def boom(*args, **kwargs):
            raise LlmNotConfigured("未配置")

        monkeypatch.setattr(acquisition_ai, "invoke", boom)
        summary, meta = summarize_item(db, user, item={"title": "标题", "summary": "原文摘要"})
        assert summary == {"summary": "原文摘要", "tags": [], "category": ""}
        assert meta["degraded"] == "LlmNotConfigured"

    def test_empty_item_skips_model(self, db) -> None:
        _ws, user = _make_workspace(db, "摘要空条目")
        summary, meta = summarize_item(db, user, item={})
        assert summary["summary"] == ""
        assert meta["degraded"] == "empty_item"


def _run(db: Session, strategy_id: int, **overrides: object) -> AcquisitionRun:
    run = AcquisitionRun(
        strategy_id=strategy_id,
        trigger="manual",
        status=str(overrides.get("status") or "success"),
        rule_snapshot={},
        round_count=int(overrides.get("round_count") or 1),
        fetched=int(overrides.get("fetched") or 0),
        inserted=int(overrides.get("inserted") or 0),
        updated=int(overrides.get("updated") or 0),
        detail=dict(overrides.get("detail") or {}),
        started_at=NOW,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


class TestRunReportAndDiagnose:
    def test_report_success(self, db, monkeypatch) -> None:
        ws, user = _make_workspace(db, "报告工作区")
        strategy = AcquisitionStrategy(
            workspace_id=ws.id,
            created_by_id=user.id,
            name="报告策略",
            scope={"channels": ["job:1"], "query": "x"},
            filter_rule={},
            targets=[],
            iteration={},
            llm={},
            schedule={},
        )
        db.add(strategy)
        db.commit()
        db.refresh(strategy)
        run = _run(db, strategy.id, fetched=5, inserted=3)

        monkeypatch.setattr(
            acquisition_ai,
            "invoke",
            lambda *a, **k: _result(None, text="本轮抓到 5 条，写入 3 条"),
        )
        text, meta = write_run_report(
            db,
            user,
            run=run,
            rounds=[{"round_no": 1, "query": "x", "new_items": 3, "stop_reason": "", "top_keywords": []}],
            workspace_id=ws.id,
        )
        assert text == "本轮抓到 5 条，写入 3 条"
        assert meta["model"] == "test-model"

    def test_report_degrade_returns_empty_text(self, db, monkeypatch) -> None:
        ws, user = _make_workspace(db, "报告降级")
        strategy = AcquisitionStrategy(
            workspace_id=ws.id,
            created_by_id=user.id,
            name="降级策略",
            scope={"channels": ["job:1"], "query": "x"},
            filter_rule={},
            targets=[],
            iteration={},
            llm={},
            schedule={},
        )
        db.add(strategy)
        db.commit()
        run = _run(db, strategy.id)

        def boom(*args, **kwargs):
            raise LlmNotConfigured("未配置")

        monkeypatch.setattr(acquisition_ai, "invoke", boom)
        text, meta = write_run_report(db, user, run=run, rounds=[], workspace_id=ws.id)
        assert text == ""
        assert meta["degraded"] == "LlmNotConfigured"

    def test_diagnose_fallback_explains_empty_filter(self, db) -> None:
        ws, _user = _make_workspace(db, "诊断降级")
        strategy = AcquisitionStrategy(
            workspace_id=ws.id,
            name="诊断策略",
            scope={"channels": ["job:1"], "query": "x"},
            filter_rule={},
            targets=[],
            iteration={},
            llm={},
            schedule={},
        )
        db.add(strategy)
        db.commit()
        db.refresh(strategy)
        run = _run(db, strategy.id, fetched=4, inserted=0)
        text, meta = diagnose_run(
            db,
            None,
            run=run,
            rounds=[{"round_no": 1, "stats": {"after_dedup": 4, "after_filter": 0}}],
        )
        assert "筛选" in text
        assert meta["degraded"] == "no_user"

    def test_diagnose_fallback_reports_channel_errors(self, db) -> None:
        ws, _user = _make_workspace(db, "诊断渠道")
        strategy = AcquisitionStrategy(
            workspace_id=ws.id,
            name="渠道策略",
            scope={"channels": ["job:1"], "query": "x"},
            filter_rule={},
            targets=[],
            iteration={},
            llm={},
            schedule={},
        )
        db.add(strategy)
        db.commit()
        db.refresh(strategy)
        run = _run(
            db,
            strategy.id,
            fetched=0,
            status="failed",
            detail={"channels": [{"channel": "rss:https://e.com/f.xml", "error": "404"}]},
        )
        text, _meta = diagnose_run(db, None, run=run, rounds=[])
        assert "rss:https://e.com/f.xml" in text

    def test_diagnose_success_text_truncated(self, db, monkeypatch) -> None:
        ws, user = _make_workspace(db, "诊断成功")
        strategy = AcquisitionStrategy(
            workspace_id=ws.id,
            created_by_id=user.id,
            name="诊断成功策略",
            scope={"channels": ["job:1"], "query": "x"},
            filter_rule={},
            targets=[],
            iteration={},
            llm={},
            schedule={},
        )
        db.add(strategy)
        db.commit()
        db.refresh(strategy)
        run = _run(db, strategy.id, fetched=1, inserted=1)
        monkeypatch.setattr(acquisition_ai, "invoke", lambda *a, **k: _result(None, text="诊" * 2000))
        text, meta = diagnose_run(db, user, run=run, rounds=[], workspace_id=ws.id)
        assert len(text) <= acquisition_ai.MAX_DIAGNOSE_CHARS
        assert meta["model"] == "test-model"


class TestRunnerLlmHooks:
    def _setup(self, db, engine, monkeypatch, payloads):
        ws, user = _make_workspace(db, "钩子工作区")
        table = _make_table(db, engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = _table_strategy(
            db,
            workspace_id=ws.id,
            table_id=table.id,
            job_id=job.id,
            iteration={"max_rounds": 2, "budget": {"max_requests": 10}},
            user_id=user.id,
        )
        strategy.llm = {"enabled": True, "actions": ["run_report"]}
        db.add(strategy)
        db.commit()

        calls = {"index": 0}

        def run_pipeline(spec, *, progress=None, on_batch=None, **kwargs):
            index = min(calls["index"], len(payloads) - 1)
            calls["index"] += 1
            return PipelineOutcome(rows=[dict(row) for row in payloads[index]], plans=1, succeeded=1, failures=[])

        monkeypatch.setattr("cndb.plugins.acquisition.services.runner.run_pipeline", run_pipeline)
        return ws, user, strategy

    def test_run_report_attached_to_detail(self, db, db_engine, monkeypatch) -> None:
        _ws, user, strategy = self._setup(db, db_engine, monkeypatch, [[{"city": "北京", "day": "2026-11-01"}]])
        monkeypatch.setattr(
            acquisition_ai,
            "write_run_report",
            lambda *a, **k: ("本轮写入 1 行", {"model": "test-model", "run_id": 9}),
        )

        execution = execute_strategy(db, strategy, user=user, now=NOW)

        assert execution.status == "success"
        run = db.execute(select(AcquisitionRun)).scalar_one()
        assert run.detail["report"]["text"] == "本轮写入 1 行"
        assert run.detail["report"]["model"] == "test-model"

    def test_run_report_skipped_when_action_not_enabled(self, db, db_engine, monkeypatch) -> None:
        _ws, user, strategy = self._setup(db, db_engine, monkeypatch, [[{"city": "北京", "day": "2026-11-01"}]])
        strategy.llm = {"enabled": True, "actions": ["keyword_refine"]}
        db.add(strategy)
        db.commit()
        called: list[bool] = []
        monkeypatch.setattr(
            acquisition_ai,
            "write_run_report",
            lambda *a, **k: called.append(True) or ("", {}),
        )

        execute_strategy(db, strategy, user=user, now=NOW)

        assert called == []

    def test_cancel_requested_stops_at_round_boundary(self, db, db_engine, monkeypatch) -> None:
        _ws, user, strategy = self._setup(
            db,
            db_engine,
            monkeypatch,
            [
                [{"city": "北京", "day": "2026-11-01"}],
                [{"city": "上海", "day": "2026-11-02"}],
            ],
        )
        rounds: list[int] = []

        def run_pipeline(spec, *, progress=None, on_batch=None, **kwargs):
            index = min(len(rounds), 1)
            rounds.append(index)
            if index == 0:  # 第一轮抓取期间请求取消
                run = db.execute(select(AcquisitionRun)).scalar_one()
                run.detail = {**dict(run.detail or {}), "cancel_requested": True}
                db.add(run)
                db.commit()
            return PipelineOutcome(
                rows=[{"city": f"城市{index}", "day": "2026-11-01"}], plans=1, succeeded=1, failures=[]
            )

        monkeypatch.setattr("cndb.plugins.acquisition.services.runner.run_pipeline", run_pipeline)
        monkeypatch.setattr(acquisition_ai, "write_run_report", lambda *a, **k: ("", {}))

        execution = execute_strategy(db, strategy, user=user, now=NOW)

        assert execution.status == "cancelled"
        run = db.execute(select(AcquisitionRun)).scalar_one()
        assert run.status == "cancelled"
        assert run.detail.get("cancelled_at_round") == 1
        assert db.execute(select(AcquisitionRound)).scalars().all()
