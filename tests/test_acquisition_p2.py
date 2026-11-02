"""采集策略 P2：渠道扩展（rss/sitemap/学术）+ 策略级调度（ADR 0085 P2）."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.plugins.acquisition.models import AcquisitionRun
from cndb.plugins.acquisition.services.channels import (
    build_channel_specs,
    parse_channel_ref,
    preset_request,
)
from cndb.plugins.acquisition.services.rules.expr import RuleError
from cndb.plugins.acquisition.services.scheduler import due_strategies, tick
from cndb.plugins.datasource.providers.base import ProviderError
from cndb.plugins.datasource.providers.feeds import (
    AcademicProvider,
    RssAtomProvider,
    parse_feed,
    parse_sitemap,
)
from cndb.plugins.datasource.services.pipeline import PipelineOutcome
from tests.test_acquisition_iteration import (
    _make_job,
    _make_table,
    _make_workspace,
    _table_strategy,
)

UTC = dt.UTC
NOW = dt.datetime(2026, 11, 2, 9, 0, tzinfo=UTC)

RSS_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <title>示例订阅</title>
  <item>
    <title>固态电池新进展</title>
    <link>https://example.com/posts/1</link>
    <description>&lt;p&gt;硫化物电解质界面研究&lt;/p&gt;</description>
    <pubDate>Mon, 02 Nov 2026 08:00:00 +0800</pubDate>
    <author>张三</author>
  </item>
  <item><title>无链接条目</title><guid>https://example.com/2</guid></item>
</channel></rss>
"""

ATOM_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>arXiv Query</title>
  <entry>
    <title>Solid electrolyte interphase</title>
    <link href="http://arxiv.org/abs/2601.00001v1" rel="alternate"/>
    <summary>We study the interface.</summary>
    <published>2026-11-01T10:00:00Z</published>
    <author><name>A. Researcher</name></author>
  </entry>
</feed>
"""

SITEMAP_XML = """<?xml version="1.0" encoding="utf-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/blog/solid-electrolyte</loc><lastmod>2026-11-01</lastmod></url>
</urlset>
"""


# ── provider：解析 ────────────────────────────────


class TestRssAtomProvider:
    def test_rss_items_normalized(self) -> None:
        rows = RssAtomProvider().parse(RSS_XML, job=None)  # type: ignore[arg-type]
        assert rows[0]["title"] == "固态电池新进展"
        assert rows[0]["url"] == "https://example.com/posts/1"
        assert rows[0]["summary"] == "硫化物电解质界面研究"
        assert rows[0]["published_at"].startswith("2026-11-02T00:00:00")
        assert rows[0]["authors"] == "张三"
        assert rows[1]["url"] == "https://example.com/2"

    def test_atom_items_normalized(self) -> None:
        rows = parse_feed(ATOM_XML)
        assert rows == [
            {
                "title": "Solid electrolyte interphase",
                "url": "http://arxiv.org/abs/2601.00001v1",
                "summary": "We study the interface.",
                "published_at": "2026-11-01T10:00:00+00:00",
                "authors": "A. Researcher",
            }
        ]

    def test_bad_xml_rejected(self) -> None:
        with pytest.raises(ProviderError):
            parse_feed("<rss>")

    def test_unknown_root_rejected(self) -> None:
        with pytest.raises(ProviderError, match="无法识别"):
            parse_feed("<html><body/></html>")


class TestAcademicProvider:
    def test_openalex_json(self) -> None:
        payload = {
            "results": [
                {
                    "display_name": "Solid electrolyte",
                    "doi": "https://doi.org/10.1/abc",
                    "publication_date": "2026-10-01",
                    "primary_location": {"landing_page_url": "https://example.org/p"},
                    "authorships": [{"author": {"display_name": "Li"}}, {"author": {"display_name": "Wang"}}],
                }
            ]
        }
        rows = AcademicProvider().parse(json.dumps(payload), job=_job())
        assert rows[0]["title"] == "Solid electrolyte"
        assert rows[0]["url"] == "https://example.org/p"
        assert rows[0]["doi"].endswith("10.1/abc")
        assert rows[0]["authors"] == "Li, Wang"

    def test_crossref_json(self) -> None:
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Sulfide electrolytes"],
                        "DOI": "10.2/xyz",
                        "URL": "https://doi.org/10.2/xyz",
                        "abstract": "<jats:p>interface stability</jats:p>",
                        "issued": {"date-parts": [[2026, 9, 15]]},
                        "author": [{"given": "Anna", "family": "K"}],
                    }
                ]
            }
        }
        rows = AcademicProvider().parse(json.dumps(payload), job=_job())
        assert rows[0]["title"] == "Sulfide electrolytes"
        assert rows[0]["summary"] == "interface stability"
        assert rows[0]["published_at"].startswith("2026-09-15")
        assert rows[0]["authors"] == "Anna K"

    def test_arxiv_atom(self) -> None:
        rows = AcademicProvider().parse(ATOM_XML, job=_job())
        assert rows[0]["title"] == "Solid electrolyte interphase"

    def test_no_array_rejected(self) -> None:
        with pytest.raises(ProviderError, match="结果数组"):
            AcademicProvider().parse(json.dumps({"ok": True}), job=_job())

    def test_non_json_text_rejected(self) -> None:
        with pytest.raises(ProviderError):
            AcademicProvider().parse("not-json", job=_job())


class TestSitemapProvider:
    def test_urlset_rows(self) -> None:
        rows = parse_sitemap(SITEMAP_XML)
        assert rows == [
            {
                "title": "solid electrolyte",
                "url": "https://example.com/blog/solid-electrolyte",
                "published_at": "2026-11-01T00:00:00",
                "type": "url",
            }
        ]

    def test_sitemap_index_rejected(self) -> None:
        with pytest.raises(ProviderError, match="sitemap 索引"):
            parse_sitemap("<sitemapindex><sitemap><loc>https://e.com/a.xml</loc></sitemap></sitemapindex>")

    def test_unknown_root_rejected(self) -> None:
        with pytest.raises(ProviderError, match="无法识别"):
            parse_sitemap("<rss/>")


def _job():
    from cndb.plugins.datasource.providers.base import RequestSpec, SyncJobSpec

    return SyncJobSpec(request=RequestSpec(url_template="https://api.example.com", data_path=None))


# ── 渠道简写 ─────────────────────────────────────


class TestChannelPresets:
    def test_parse_presets(self) -> None:
        assert parse_channel_ref("rss:https://e.com/f.xml") == ("preset", ("rss", "https://e.com/f.xml"))
        assert parse_channel_ref("arxiv:") == ("preset", ("arxiv", ""))
        assert parse_channel_ref("openalex:固态电池") == ("preset", ("openalex", "固态电池"))

    def test_unknown_prefix_rejected(self) -> None:
        with pytest.raises(RuleError, match="渠道引用非法"):
            parse_channel_ref("ftp://e.com/a")

    def test_rss_requires_http_url(self) -> None:
        with pytest.raises(RuleError, match="http/https"):
            preset_request("rss", "e.com/f.xml", "q")

    def test_academic_uses_round_query_when_empty(self) -> None:
        payload = preset_request("arxiv", "", "固态 电解质")
        assert payload["provider"] == "academic"
        assert payload["request_spec"]["params_template"]["search_query"] == "all:固态 电解质"

    def test_academic_keeps_explicit_term(self) -> None:
        payload = preset_request("openalex", "thin film", "固态")
        assert payload["request_spec"]["params_template"]["search"] == "thin film"
        assert payload["request_spec"]["data_path"] == "results"

    def test_build_specs_from_presets(self, db: Session) -> None:
        specs, errors = build_channel_specs(
            db,
            workspace_id=1,
            scope={"channels": ["rss:https://e.com/f.xml", "crossref:", "sitemap:https://e.com/s.xml"]},
            query="固态电池",
            today="2026-11-02",
        )
        assert errors == []
        assert [spec.provider for spec in specs] == ["rss_atom", "academic", "sitemap"]
        assert specs[0].spec.request.url_template == "https://e.com/f.xml"
        assert specs[1].spec.request.params_template["query"] == "固态电池"
        assert specs[2].channel.startswith("sitemap:")


# ── 调度 ───────────────────────────────────────


def _strategy_with_schedule(db: Session, workspace_id: int, table_id: int, job_id: int, **schedule: object):
    strategy = _table_strategy(
        db,
        workspace_id=workspace_id,
        table_id=table_id,
        job_id=job_id,
        iteration={"max_rounds": 1, "budget": {"max_requests": 10}},
    )
    strategy.schedule = schedule or {"mode": "manual"}
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return strategy


def _patch_pipeline(monkeypatch, payloads: list[list[dict[str, object]]]) -> None:
    calls = {"index": 0}

    def run_pipeline(spec, *, progress=None, on_batch=None, **kwargs):
        index = min(calls["index"], len(payloads) - 1)
        calls["index"] += 1
        return PipelineOutcome(rows=[dict(row) for row in payloads[index]], plans=1, succeeded=1, failures=[])

    monkeypatch.setattr("cndb.plugins.acquisition.services.runner.run_pipeline", run_pipeline)


ROW = {"city": "北京", "day": "2026-11-01", "temp": "1"}


class TestDueStrategies:
    def _setup(self, db, engine):
        ws, user = _make_workspace(db, "调度工作区")
        table = _make_table(db, engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        return ws, user, table, job

    def test_disabled_and_manual_not_due(self, db_engine, db) -> None:
        ws, _user, table, job = self._setup(db, db_engine)
        manual = _strategy_with_schedule(db, ws.id, table.id, job.id, mode="manual")
        off = _strategy_with_schedule(db, ws.id, table.id, job.id, mode="interval", seconds=60)
        off.enabled = False
        db.add(off)
        db.commit()

        due = due_strategies(db, now=NOW)
        assert [item.id for item in due] == []
        assert manual.id not in [item.id for item in due]

    def test_interval_due_after_elapsed(self, db_engine, db) -> None:
        ws, _user, table, job = self._setup(db, db_engine)
        strategy = _strategy_with_schedule(db, ws.id, table.id, job.id, mode="interval", seconds=3600)
        strategy.last_run_at = NOW - dt.timedelta(hours=2)
        db.add(strategy)
        db.commit()

        assert [item.id for item in due_strategies(db, now=NOW)] == [strategy.id]

    def test_invalid_schedule_skipped(self, db_engine, db) -> None:
        ws, _user, table, job = self._setup(db, db_engine)
        strategy = _strategy_with_schedule(db, ws.id, table.id, job.id, mode="cron", expr="not a cron")
        assert due_strategies(db, now=NOW) == []
        assert strategy.id  # 仅确认构造成功

    def test_lease_held_not_due(self, db_engine, db) -> None:
        ws, _user, table, job = self._setup(db, db_engine)
        strategy = _strategy_with_schedule(db, ws.id, table.id, job.id, mode="interval", seconds=60)
        strategy.lease_owner = "other:1"
        strategy.lease_until = NOW + dt.timedelta(minutes=5)
        db.add(strategy)
        db.commit()

        assert due_strategies(db, now=NOW) == []


class TestTick:
    def _setup(self, db, engine, monkeypatch, schedule=None):
        ws, user = _make_workspace(db, "tick 工作区")
        table = _make_table(db, engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        strategy = _strategy_with_schedule(
            db,
            ws.id,
            table.id,
            job.id,
            **(schedule or {"mode": "interval", "seconds": 60}),
        )
        _patch_pipeline(monkeypatch, [[ROW]])
        return ws, user, table, job, strategy

    def test_tick_executes_due_strategy(self, db_engine, db, monkeypatch) -> None:
        _ws, _user, _table, _job, strategy = self._setup(db, db_engine, monkeypatch)

        report = tick(db, now=NOW)

        assert report.examined == 1
        assert report.executed == 1 and report.succeeded == 1
        assert report.strategy_ids == [strategy.id]
        run = db.execute(select(AcquisitionRun)).scalar_one()
        assert run.trigger == "scheduler"
        assert run.status == "success"

    def test_tick_skips_pending_review(self, db_engine, db, monkeypatch) -> None:
        _ws, _user, _table, _job, strategy = self._setup(db, db_engine, monkeypatch)
        db.add(
            AcquisitionRun(
                strategy_id=strategy.id,
                trigger="manual",
                status="awaiting_review",
                rule_snapshot={},
                started_at=NOW - dt.timedelta(minutes=5),
            )
        )
        db.commit()

        report = tick(db, now=NOW)

        assert report.skipped_pending == 1
        assert report.executed == 0

    def test_tick_skips_leased(self, db_engine, db, monkeypatch) -> None:
        _ws, _user, _table, _job, strategy = self._setup(db, db_engine, monkeypatch)
        strategy.lease_owner = "other:1"
        strategy.lease_until = NOW + dt.timedelta(minutes=5)
        db.add(strategy)
        db.commit()

        report = tick(db, now=NOW)

        assert report.examined == 0
        assert report.executed == 0

    def test_tick_resumes_expired_review(self, db_engine, db, monkeypatch) -> None:
        from cndb.plugins.acquisition.models import AcquisitionRound, ReviewState

        _ws, _user, _table, _job, strategy = self._setup(db, db_engine, monkeypatch)
        run = AcquisitionRun(
            strategy_id=strategy.id,
            trigger="manual",
            status="awaiting_review",
            rule_snapshot={},
            started_at=NOW - dt.timedelta(days=4),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        db.add(
            AcquisitionRound(
                run_id=run.id,
                round_no=1,
                query="固态电池",
                next_query="固态电池",
                review_state=ReviewState.PENDING.value,
                created_at=NOW - dt.timedelta(days=4),
            )
        )
        db.commit()

        report = tick(db, now=NOW)

        assert report.resumed_timeout == 1
        refreshed = db.get(AcquisitionRun, run.id)
        assert refreshed is not None
        assert refreshed.status != "awaiting_review"
        assert refreshed.detail.get("review_timeout") is True

    def test_tick_by_strategy_id_ignores_schedule(self, db_engine, db, monkeypatch) -> None:
        _ws, _user, _table, _job, strategy = self._setup(db, db_engine, monkeypatch, {"mode": "manual"})

        report = tick(db, now=NOW, strategy_id=strategy.id)

        assert report.executed == 1
        assert report.strategy_ids == [strategy.id]

    def test_tick_limit_respected(self, db_engine, db, monkeypatch) -> None:
        ws, _user, table, job, first = self._setup(db, db_engine, monkeypatch)
        _strategy_with_schedule(db, ws.id, table.id, job.id, mode="interval", seconds=60)

        report = tick(db, now=NOW, limit=1)

        assert report.examined == 1
        assert report.strategy_ids == [first.id]

    def test_tick_limit_zero_does_nothing(self, db_engine, db, monkeypatch) -> None:
        self._setup(db, db_engine, monkeypatch)

        report = tick(db, now=NOW, limit=0)

        assert report.examined == 0
        assert report.executed == 0


# ── 渠道引用的容错分支（label / mapping / 错误声明） ──────────────


class TestChannelRefEdges:
    def test_channel_label_variants(self) -> None:
        from cndb.plugins.acquisition.services.channels import channel_label

        assert channel_label("job:12", 1) == "job:12"
        assert channel_label({"job": 3}, 2) == "job:3"
        assert channel_label({"provider": "http_json"}, 3) == "http_json"
        assert channel_label({}, 4) == "channel-4"
        assert channel_label(None, 5) == "channel-5"
        assert channel_label("   ", 6) == "channel-6"

    def test_mapping_refs(self) -> None:
        assert parse_channel_ref({"job": "7"}) == ("job", 7)
        assert parse_channel_ref({"provider": "http_json", "request_spec": {}}) == (
            "inline",
            {"provider": "http_json", "request_spec": {}},
        )

    def test_invalid_mapping_refs(self) -> None:
        with pytest.raises(RuleError, match="job 编号非法"):
            parse_channel_ref({"job": "abc"})
        with pytest.raises(RuleError, match="缺少 job 或 provider"):
            parse_channel_ref({"other": 1})
        with pytest.raises(RuleError, match="类型非法"):
            parse_channel_ref(42)
        with pytest.raises(RuleError, match="job 编号必须是整数"):
            parse_channel_ref("job:abc")

    def test_unknown_preset_kind(self) -> None:
        with pytest.raises(RuleError, match="未知渠道简写"):
            preset_request("nope", "", "q")

    def test_with_query_injects_variable_only_when_present(self) -> None:
        from cndb.plugins.acquisition.services.channels import _with_query

        spec = _job()
        assert _with_query(spec, "") is spec
        injected = _with_query(spec, "固态电池")
        assert injected.extra_variables["query"] == "固态电池"

    def test_build_specs_collects_per_channel_errors(self, db: Session) -> None:
        specs, errors = build_channel_specs(
            db,
            workspace_id=999,
            scope={"channels": ["job:424242", {"provider": "http_json"}]},
            query="q",
            today="2026-11-02",
        )
        assert specs == []
        assert any("同步任务不存在" in item["error"] for item in errors)

    def test_build_specs_rejects_foreign_job(self, db: Session, db_engine) -> None:
        ws, _user = _make_workspace(db, "渠道归属")
        table = _make_table(db, db_engine, ws.id)
        job = _make_job(db, ws.id, table.id)
        specs, errors = build_channel_specs(
            db,
            workspace_id=ws.id + 1000,
            scope={"channels": [f"job:{job.id}"]},
            query="q",
            today="2026-11-02",
        )
        assert specs == []
        assert "不属于当前工作区" in errors[0]["error"]
