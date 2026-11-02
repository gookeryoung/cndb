"""acquisition P1：迭代（关键词 / 扩展 / 停止）+ 复核闸口 + 文档落点 + 模型降级."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.acquisition.models import (
    AcquisitionItem,
    AcquisitionRound,
    AcquisitionRun,
    AcquisitionStrategy,
)
from cndb.plugins.acquisition.services import ai as acquisition_ai
from cndb.plugins.acquisition.services.rules.expand import (
    apply_llm_decisions,
    apply_user_edit,
    build,
)
from cndb.plugins.acquisition.services.rules.keywords import extract_keywords
from cndb.plugins.acquisition.services.rules.stop import decide_stop
from cndb.plugins.acquisition.services.runner import StrategyBusyError, execute_strategy, resume_run
from cndb.plugins.datasource.models import DatasourceSyncJob
from cndb.plugins.datasource.services.pipeline import PipelineOutcome
from cndb.plugins.documents.models import Document, DocumentIssue
from cndb.plugins.documents.services.content import latest_version, update_content
from cndb.plugins.llm.services.errors import LlmNotConfigured
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

UTC = dt.UTC
NOW = dt.datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


# ── 纯函数：关键词 / 扩展 / 停止 ─────────────────────────


class TestExtractKeywords:
    def test_latin_and_cjk_bigrams(self) -> None:
        items = [
            {"title": "solid electrolyte interface", "summary": "sulfide electrolyte stability"},
            {"title": "硫化物固态电解质界面", "summary": "界面阻抗与电导率"},
        ]
        terms = [item["term"] for item in extract_keywords(items, top_n=10)]
        assert "electrolyte" in terms
        assert any(term in terms for term in ("固态", "界面", "电解"))

    def test_exclude_and_ordering_deterministic(self) -> None:
        items = [{"title": "alpha beta beta gamma"}]
        first = extract_keywords(items, 3)
        second = extract_keywords(items, 3)
        assert first == second
        assert first[0]["term"] == "beta"
        assert extract_keywords(items, 5, exclude=["beta"])[0]["term"] != "beta"

    def test_empty_corpus(self) -> None:
        assert extract_keywords([], 5) == []
        assert extract_keywords([{"title": "x"}], 0) == []


class TestExpand:
    def test_build_wraps_and_limits(self) -> None:
        query = build("固态电池", [{"term": "界面"}, {"term": "电导率"}, {"term": "固态"}], ())
        assert query.startswith("(固态电池) AND (")
        assert "界面" in query
        assert '"界面"' not in query  # 单词不加引号
        assert "固态" not in query.split("AND")[1]  # 基础词不重复

    def test_build_falls_back_when_same_as_previous(self) -> None:
        first = build("base", [{"term": "alpha"}], ())
        assert build("base", [{"term": "alpha"}], (), previous=first) == "base"

    def test_llm_decisions_only_touch_candidates(self) -> None:
        candidates = [{"term": "alpha", "count": 3, "df": 2}, {"term": "beta", "count": 1, "df": 1}]
        final, rejected = apply_llm_decisions(
            candidates,
            [
                {"term": "alpha", "action": "rename", "rename": "alphabet", "reason": "变体", "weight": 2},
                {"term": "beta", "action": "drop", "reason": "泛词"},
                {"term": "gamma", "action": "keep", "reason": "凭空造词"},
            ],
        )
        assert [item["term"] for item in final] == ["alphabet", "beta"]
        assert final[0]["source"] == "llm" and final[0]["original_term"] == "alpha"
        assert final[1]["dropped"] is True
        assert rejected == [{"term": "gamma", "reason": "候选集之外的词"}]

    def test_user_edit_marks_new_terms(self) -> None:
        existing = [{"term": "alpha", "count": 2, "df": 1, "source": "tf"}]
        final = apply_user_edit(existing, ["alpha", "delta"])
        by_term = {item["term"]: item for item in final}
        assert by_term["delta"]["source"] == "user"
        assert by_term["alpha"]["source"] == "user"
        assert apply_user_edit(existing, []) == existing


class TestStop:
    def test_priority_order(self) -> None:
        assert decide_stop(round_no=1, max_rounds=3, new_items=5, budget_exhausted=True) == "budget"
        assert decide_stop(round_no=3, max_rounds=3, new_items=5) == "max_rounds"
        assert decide_stop(round_no=1, max_rounds=3, new_items=0, consecutive_empty=1) == "empty_round"
        assert decide_stop(round_no=1, max_rounds=3, new_items=0) == "min_new"
        assert decide_stop(round_no=1, max_rounds=3, new_items=2) is None


# ── 夹层：工作区 / 用户 / 表 / 渠道 ─────────────────────


def _make_workspace(db: Session, name: str = "采集工作区") -> tuple[Workspace, User]:
    user = User(username=f"acq_{name}", nickname="ACQ")
    user.set_password("passw0rd")
    db.add(user)
    db.flush()
    ws = Workspace(name=name, created_by_id=user.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(ws)
    db.refresh(user)
    return ws, user


def _make_table(db: Session, engine, workspace_id: int) -> DataTable:
    table = DataTable(workspace_id=workspace_id, name=f"采集表{workspace_id}")
    table.ensure_db_name()
    db.add(table)
    db.commit()
    db.refresh(table)
    for order, name in enumerate(("city", "day", "temp")):
        field = DataField(table_id=table.id, name=name, field_type="text", order=order)
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(table)
    ddl.create_table(engine, table)
    return table


def _make_job(db: Session, workspace_id: int, table_id: int) -> DatasourceSyncJob:
    job = DatasourceSyncJob(
        workspace_id=workspace_id,
        name="政策源",
        provider="http_json",
        table_id=table_id,
        request_spec={"url_template": "https://api.example.com/p?q={query}"},
        parser="json",
        match_keys=["city", "day"],
        cursor={"strategy": "none"},
        schedule={"mode": "manual"},
        enabled=True,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _fetch_sequence(payloads: list[list[dict[str, object]]]):
    """按调用次数依次返回不同批次（模拟多轮扩展后的新结果）."""
    calls = {"index": 0}

    def fetch(_config: object) -> list[dict[str, object]]:
        index = min(calls["index"], len(payloads) - 1)
        calls["index"] += 1
        return [dict(row) for row in payloads[index]]

    return fetch


def _patch_pipeline(monkeypatch, payloads: list[list[dict[str, object]]]):
    """替换 runner 内的 run_pipeline（多轮下按批次返回）."""
    calls = {"index": 0}

    def run_pipeline(spec, *, progress=None, on_batch=None, **kwargs):
        index = min(calls["index"], len(payloads) - 1)
        calls["index"] += 1
        return PipelineOutcome(rows=[dict(row) for row in payloads[index]], plans=1, succeeded=1, failures=[])

    monkeypatch.setattr("cndb.plugins.acquisition.services.runner.run_pipeline", run_pipeline)
    return calls


def _table_strategy(
    db: Session,
    *,
    workspace_id: int,
    table_id: int,
    job_id: int,
    iteration: dict[str, object] | None = None,
    user_id: int | None = None,
) -> AcquisitionStrategy:
    strategy = AcquisitionStrategy(
        workspace_id=workspace_id,
        created_by_id=user_id,
        name="多轮采集",
        enabled=True,
        scope={"channels": [f"job:{job_id}"], "query": "固态电池", "max_results_per_channel": 50},
        filter_rule={},
        targets=[{"kind": "table", "table_id": table_id, "match_keys": ["city", "day"]}],
        iteration=iteration or {"max_rounds": 1, "budget": {"max_requests": 10}},
        llm={},
        schedule={"mode": "manual"},
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return strategy


# ── 多轮迭代 ─────────────────────────────────────


class TestMultiRound:
    def test_two_rounds_expand_query_and_record_history(self, db_engine, db, monkeypatch):
        ws, user = _make_workspace(db)
        table = _make_table(db, db_engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = _table_strategy(
            db,
            workspace_id=ws.id,
            table_id=table.id,
            job_id=job.id,
            iteration={"max_rounds": 2, "top_keywords_per_round": 3, "budget": {"max_requests": 10}},
            user_id=user.id,
        )
        _patch_pipeline(
            monkeypatch,
            [
                [{"city": "固态电解质界面研究", "day": "2026-11-01", "temp": "1"}],
                [{"city": "硫化物电导率提升", "day": "2026-11-02", "temp": "2"}],
            ],
        )

        execution = execute_strategy(db, strategy, user=user, now=NOW)

        assert execution.status == "success"
        assert execution.rounds == 2
        rounds = list(db.execute(select(AcquisitionRound).order_by(AcquisitionRound.round_no)).scalars())
        assert [row.round_no for row in rounds] == [1, 2]
        assert rounds[0].next_query.startswith("(固态电池) AND (")
        assert rounds[0].top_keywords and rounds[0].top_keywords[0]["source"] == "tf"
        assert rounds[1].stop_reason == "max_rounds"

    def test_empty_second_round_stops_early(self, db_engine, db, monkeypatch):
        ws, user = _make_workspace(db, "早停工作区")
        table = _make_table(db, db_engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = _table_strategy(
            db,
            workspace_id=ws.id,
            table_id=table.id,
            job_id=job.id,
            iteration={"max_rounds": 3, "budget": {"max_requests": 10}},
            user_id=user.id,
        )
        _patch_pipeline(monkeypatch, [[], []])

        execution = execute_strategy(db, strategy, user=user, now=NOW)

        assert execution.rounds == 1
        rounds = list(db.execute(select(AcquisitionRound)).scalars())
        assert rounds[0].stop_reason == "empty_round"
        assert execution.status == "success"  # 零新增属正常收敛

    def test_budget_across_rounds_marks_partial(self, db_engine, db, monkeypatch):
        ws, user = _make_workspace(db, "预算工作区")
        table = _make_table(db, db_engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = _table_strategy(
            db,
            workspace_id=ws.id,
            table_id=table.id,
            job_id=job.id,
            iteration={"max_rounds": 3, "budget": {"max_requests": 1}},
            user_id=user.id,
        )
        _patch_pipeline(monkeypatch, [[{"city": "北京", "day": "2026-11-01", "temp": "1"}]])

        execution = execute_strategy(db, strategy, user=user, now=NOW)

        assert execution.status == "partial"
        run = db.execute(select(AcquisitionRun)).scalar_one()
        assert run.budget_used["requests"] == 1
        assert run.detail["budget_exhausted"] is True


# ── 复核闸口（D14）───────────────────────────────


class TestReviewGate:
    def _manual_strategy(self, db, workspace_id, table_id, job_id, user_id):
        return _table_strategy(
            db,
            workspace_id=workspace_id,
            table_id=table_id,
            job_id=job_id,
            iteration={
                "max_rounds": 2,
                "top_keywords_per_round": 3,
                "expand": {"review": "manual"},
                "budget": {"max_requests": 10},
            },
            user_id=user_id,
        )

    def test_pauses_then_resumes_without_change(self, db_engine, db, monkeypatch):
        ws, user = _make_workspace(db, "复核工作区")
        table = _make_table(db, db_engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = self._manual_strategy(db, ws.id, table.id, job.id, user.id)
        _patch_pipeline(
            monkeypatch,
            [
                [{"city": "固态电解质界面研究", "day": "2026-11-01", "temp": "1"}],
                [{"city": "固态电解质界面研究二", "day": "2026-11-02", "temp": "2"}],
            ],
        )

        paused = execute_strategy(db, strategy, user=user, now=NOW)
        assert paused.status == "awaiting_review"
        run = db.execute(select(AcquisitionRun)).scalar_one()
        db.refresh(run)
        assert run.status == "awaiting_review"
        assert run.finished_at is None
        pending = db.execute(select(AcquisitionRound)).scalar_one()
        assert pending.review_state == "pending"
        db.refresh(strategy)
        assert strategy.lease_owner is None

        resumed = resume_run(db, run, user=user, now=NOW)
        assert resumed.status == "success"
        assert resumed.rounds == 2
        rows = list(db.execute(select(AcquisitionRound).order_by(AcquisitionRound.round_no)).scalars())
        assert rows[0].review_state == "confirmed"
        assert [row.round_no for row in rows] == [1, 2]

    def test_resume_with_user_keywords_marks_source_user(self, db_engine, db, monkeypatch):
        ws, user = _make_workspace(db, "复核调整工作区")
        table = _make_table(db, db_engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = self._manual_strategy(db, ws.id, table.id, job.id, user.id)
        _patch_pipeline(
            monkeypatch,
            [
                [{"city": "固态电解质界面研究", "day": "2026-11-01", "temp": "1"}],
                [{"city": "固态电解质界面研究二", "day": "2026-11-02", "temp": "2"}],
            ],
        )

        execute_strategy(db, strategy, user=user, now=NOW)
        run = db.execute(select(AcquisitionRun)).scalar_one()
        resumed = resume_run(db, run, user=user, keywords=["自定义词"], query="(固态电池) AND (自定义词)", now=NOW)

        assert resumed.status == "success"
        first_round = db.execute(select(AcquisitionRound).where(AcquisitionRound.round_no == 1)).scalar_one()
        assert any(item["source"] == "user" for item in first_round.top_keywords)
        assert first_round.next_query == "(固态电池) AND (自定义词)"

    def test_resume_rejects_run_not_awaiting(self, db_engine, db, monkeypatch):
        ws, user = _make_workspace(db, "非复核工作区")
        table = _make_table(db, db_engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = _table_strategy(db, workspace_id=ws.id, table_id=table.id, job_id=job.id, user_id=user.id)
        _patch_pipeline(monkeypatch, [[{"city": "北京", "day": "2026-11-01", "temp": "1"}]])
        execute_strategy(db, strategy, user=user, now=NOW)
        run = db.execute(select(AcquisitionRun)).scalar_one()

        from cndb.plugins.acquisition.services.rules.expr import RuleError

        with pytest.raises(RuleError):
            resume_run(db, run, user=user, now=NOW)


# ── 文档落点 ─────────────────────────────────────


def _doc_strategy(db: Session, *, workspace_id: int, job_id: int, user_id: int) -> AcquisitionStrategy:
    strategy = AcquisitionStrategy(
        workspace_id=workspace_id,
        created_by_id=user_id,
        name="文档采集",
        enabled=True,
        scope={"channels": [f"job:{job_id}"], "query": "固态电池", "max_results_per_channel": 20},
        filter_rule={},
        targets=[
            {
                "kind": "document",
                "parent_id": None,
                "title_template": "{title}",
                "body_template": "# {title}\n\n{summary}\n\n> 来源：{url}",
            }
        ],
        iteration={"max_rounds": 1, "budget": {"max_requests": 10}},
        llm={},
        schedule={"mode": "manual"},
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return strategy


class TestDocumentTarget:
    def _setup(self, db, engine, monkeypatch, rows: list[dict[str, object]]):
        ws, user = _make_workspace(db, f"文档工作区{len(rows)}")
        table = _make_table(db, engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = _doc_strategy(db, workspace_id=ws.id, job_id=job.id, user_id=user.id)
        _patch_pipeline(monkeypatch, [rows])
        return ws, user, strategy

    ROW = {"title": "固态电池进展", "summary": "界面研究", "url": "https://example.com/a"}

    def test_creates_document_and_ledger(self, db_engine, db, monkeypatch):
        ws, user, strategy = self._setup(db, db_engine, monkeypatch, [self.ROW])

        execution = execute_strategy(db, strategy, user=user, now=NOW)

        assert execution.status == "success"
        assert execution.report.docs_created == 1
        doc = db.execute(select(Document)).scalar_one()
        assert doc.title == "固态电池进展"
        assert doc.workspace_id == ws.id
        assert latest_version(db, doc.id).change_type == "auto_import"
        item = db.execute(select(AcquisitionItem)).scalar_one()
        assert item.target_kind == "document" and item.target_id == doc.id

    def test_same_content_creates_no_new_version(self, db_engine, db, monkeypatch):
        _ws, user, strategy = self._setup(db, db_engine, monkeypatch, [self.ROW])
        execute_strategy(db, strategy, user=user, now=NOW)
        doc = db.execute(select(Document)).scalar_one()
        version_before = latest_version(db, doc.id).version_number

        second = execute_strategy(db, strategy, user=user, now=NOW)

        assert second.status == "success"
        assert second.report.docs_created == 0
        assert latest_version(db, doc.id).version_number == version_before
        assert len(list(db.execute(select(Document)).scalars())) == 1

    def test_changed_content_updates_version(self, db_engine, db, monkeypatch):
        _ws, user, strategy = self._setup(db, db_engine, monkeypatch, [self.ROW])
        execute_strategy(db, strategy, user=user, now=NOW)
        doc = db.execute(select(Document)).scalar_one()
        version_before = latest_version(db, doc.id).version_number

        _patch_pipeline(monkeypatch, [[{**self.ROW, "summary": "界面研究（更新）"}]])
        execution = execute_strategy(db, strategy, user=user, now=NOW)

        assert execution.report.docs_updated == 1
        assert latest_version(db, doc.id).version_number == version_before + 1

    def test_human_edit_is_not_overwritten_and_issue_created(self, db_engine, db, monkeypatch):
        ws, user, strategy = self._setup(db, db_engine, monkeypatch, [self.ROW])
        execute_strategy(db, strategy, user=user, now=NOW)
        doc = db.execute(select(Document)).scalar_one()
        update_content(db, ws.id, doc.id, user, content="人工改过的正文", change_type="manual")
        version_before = latest_version(db, doc.id).version_number

        _patch_pipeline(monkeypatch, [[{**self.ROW, "summary": "自动更新内容"}]])
        execution = execute_strategy(db, strategy, user=user, now=NOW)

        assert execution.report.docs_skipped == 1
        assert latest_version(db, doc.id).version_number == version_before
        issue = db.execute(select(DocumentIssue)).scalar_one()
        assert issue.document_id == doc.id


# ── 模型参与与降级 ───────────────────────────────


class TestKeywordRefine:
    def test_action_registered(self) -> None:
        from cndb.plugins.llm.services import actions

        assert actions.get("acquisition.keyword_refine") is not None

    def test_degrade_when_not_configured(self, db, monkeypatch):
        ws, user = _make_workspace(db, "降级工作区")
        candidates = [{"term": "alpha", "count": 3, "df": 2}]

        def boom(*args, **kwargs):
            raise LlmNotConfigured("未配置")

        monkeypatch.setattr(acquisition_ai, "invoke", boom)
        final, rejected, meta = acquisition_ai.refine_keywords(
            db,
            user,
            candidates=candidates,
            base_query="base",
            workspace_id=ws.id,
        )

        assert [item["term"] for item in final] == ["alpha"]
        assert rejected == []
        assert meta["degraded"] == "LlmNotConfigured"

    def test_runner_degrades_without_user(self, db_engine, db, monkeypatch):
        ws, _user = _make_workspace(db, "无用户工作区")
        table = _make_table(db, db_engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = _table_strategy(
            db,
            workspace_id=ws.id,
            table_id=table.id,
            job_id=job.id,
            iteration={"max_rounds": 2, "expand": {"review": "llm"}, "budget": {"max_requests": 10}},
        )
        strategy.llm = {"enabled": True, "actions": ["keyword_refine"]}
        db.add(strategy)
        db.commit()

        _patch_pipeline(
            monkeypatch,
            [
                [{"city": "固态电解质界面研究", "day": "2026-11-01", "temp": "1"}],
                [{"city": "固态电解质界面研究二", "day": "2026-11-02", "temp": "2"}],
            ],
        )

        execution = execute_strategy(db, strategy, now=NOW)

        assert execution.status == "success"
        assert execution.llm.get("degraded") == "no_user"
        run = db.execute(select(AcquisitionRun)).scalar_one()
        assert run.detail["llm"]["degraded"] == "no_user"

    def test_busy_lease_blocks_resume(self, db_engine, db, monkeypatch):
        ws, user = _make_workspace(db, "租赁工作区")
        table = _make_table(db, db_engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = _table_strategy(
            db,
            workspace_id=ws.id,
            table_id=table.id,
            job_id=job.id,
            iteration={"max_rounds": 2, "expand": {"review": "manual"}, "budget": {"max_requests": 10}},
            user_id=user.id,
        )
        _patch_pipeline(
            monkeypatch,
            [
                [{"city": "固态电解质界面研究", "day": "2026-11-01", "temp": "1"}],
                [{"city": "固态电解质界面研究二", "day": "2026-11-02", "temp": "2"}],
            ],
        )
        execute_strategy(db, strategy, user=user, now=NOW)
        run = db.execute(select(AcquisitionRun)).scalar_one()
        strategy.lease_owner = "other"
        strategy.lease_until = NOW + dt.timedelta(minutes=5)
        db.add(strategy)
        db.commit()

        with pytest.raises(StrategyBusyError):
            resume_run(db, run, user=user, now=NOW)
