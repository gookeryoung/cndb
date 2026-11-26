"""文档 FTS 索引一致性校验 + trigram 中文检索（需求 0170 / 0171）.

覆盖：
- verify_fts_index：正常库一致、人为删行→missing、插孤儿→orphan、改标题→mismatch、
  trigram 影子表漂移能被检出；默认开关与 workspace 过滤；
- 中文 trigram 通道：≥3 字符长词走索引（LIKE 通道候选收窄）、2 字短词仍 LIKE 兜底、
  命中集合只增不减、写路径同步维护两表、重建后两表一致。
"""

from __future__ import annotations

from sqlalchemy import text

API = "/api/v1/workspaces/{wid}/documents"


def _ws(client, auth_headers, name: str) -> int:
    r = client.post("/api/v1/workspaces", json={"name": name}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create(client, api: str, auth, title: str, content: str = "正文") -> dict:
    r = client.post(api, json={"title": title, "content": content}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


class TestFtsConsistency:
    def test_healthy_library_reports_consistent(self, client, db, auth_headers):
        from cndb.plugins.documents.services.search import verify_fts_index

        wid = _ws(client, auth_headers, "fts-ok")
        _create(client, API.format(wid=wid), auth_headers, "销售管理总览", "经营数据")

        db.expire_all()
        report = verify_fts_index(db)
        assert report.consistent is True
        assert report.as_dict()["counts"] == {"missing": 0, "orphan": 0, "mismatch": 0}

    def test_detects_missing_fts_row(self, client, db, auth_headers):
        from cndb.plugins.documents.services.search import verify_fts_index

        wid = _ws(client, auth_headers, "fts-miss")
        doc = _create(client, API.format(wid=wid), auth_headers, "待索引文档", "正文")

        db.execute(text("DELETE FROM documents_fts WHERE rowid = :id"), {"id": doc["id"]})
        db.commit()
        report = verify_fts_index(db)
        assert doc["id"] in report.missing
        assert report.consistent is False

    def test_detects_title_mismatch(self, client, db, auth_headers):
        from cndb.plugins.documents.services.search import verify_fts_index

        wid = _ws(client, auth_headers, "fts-mis")
        doc = _create(client, API.format(wid=wid), auth_headers, "原标题", "正文")

        db.execute(text("UPDATE documents_fts SET title = '被篡改' WHERE rowid = :id"), {"id": doc["id"]})
        db.commit()
        assert doc["id"] in verify_fts_index(db).mismatch

    def test_detects_orphan_index_row(self, client, db, auth_headers):
        from cndb.plugins.documents.services.search import verify_fts_index

        wid = _ws(client, auth_headers, "fts-orphan")
        _create(client, API.format(wid=wid), auth_headers, "正常文档", "正文")
        db.execute(
            text(
                "INSERT INTO documents_fts(rowid, title, content, summary, author) "
                "VALUES (999999, '孤儿', '正文', '', '')"
            )
        )
        db.commit()
        assert 999999 in verify_fts_index(db).orphan

    def test_detects_trigram_drift(self, client, db, auth_headers):
        from cndb.plugins.documents.services.search import verify_fts_index

        wid = _ws(client, auth_headers, "fts-tri-drift")
        doc = _create(client, API.format(wid=wid), auth_headers, "销售管理总览", "经营数据")
        db.execute(text("UPDATE documents_fts_tri SET content = '' WHERE rowid = :id"), {"id": doc["id"]})
        db.commit()
        assert doc["id"] in verify_fts_index(db).missing

    def test_workspace_filter(self, client, db, auth_headers):
        from cndb.plugins.documents.services.search import verify_fts_index

        wid1 = _ws(client, auth_headers, "fts-w1")
        wid2 = _ws(client, auth_headers, "fts-w2")
        d1 = _create(client, API.format(wid=wid1), auth_headers, "文档一", "正文")
        _create(client, API.format(wid=wid2), auth_headers, "文档二", "正文")
        db.execute(text("DELETE FROM documents_fts WHERE rowid = :id"), {"id": d1["id"]})
        db.commit()

        assert verify_fts_index(db, workspace_id=wid2).consistent is True
        assert d1["id"] in verify_fts_index(db, workspace_id=wid1).missing

    def test_rebuild_repairs_and_keeps_both_tables(self, client, db, auth_headers):
        from cndb.plugins.documents.services.search import rebuild_fts_index, verify_fts_index

        wid = _ws(client, auth_headers, "fts-rebuild")
        doc = _create(client, API.format(wid=wid), auth_headers, "销售管理总览", "经营数据正文")
        for table in ("documents_fts", "documents_fts_tri"):
            db.execute(text(f"UPDATE {table} SET content = '' WHERE rowid = :id"), {"id": doc["id"]})
        db.commit()

        count = rebuild_fts_index(db)
        assert count >= 1
        assert verify_fts_index(db).consistent is True

    def test_report_has_no_content(self, client, db, auth_headers):
        """H38：报告只含 id / 计数，不携带正文."""
        from cndb.plugins.documents.services.search import verify_fts_index

        wid = _ws(client, auth_headers, "fts-no-content")
        _create(client, API.format(wid=wid), auth_headers, "敏感标题文档", "机密正文内容")
        payload = verify_fts_index(db).as_dict()
        assert "机密正文内容" not in str(payload)
        assert set(payload) == {"consistent", "missing", "orphan", "mismatch", "counts"}


class TestTrigramSearch:
    def test_long_cjk_term_matches(self, client, auth_headers):
        wid = _ws(client, auth_headers, "tri-long")
        api = API.format(wid=wid)
        _create(client, api, auth_headers, "销售管理总览", "本工作区承载经营数据")
        r = client.get(f"{api}/search", params={"q": "销售管理"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_short_cjk_term_still_falls_back_to_like(self, client, auth_headers):
        """2 字中文无法被 trigram 命中，必须保留 LIKE 兜底."""
        wid = _ws(client, auth_headers, "tri-short")
        api = API.format(wid=wid)
        _create(client, api, auth_headers, "销售管理总览", "正文")
        r = client.get(f"{api}/search", params={"q": "销售"}, headers=auth_headers)
        assert r.json()["total"] == 1

    def test_middle_substring_of_long_term_matches(self, client, auth_headers):
        wid = _ws(client, auth_headers, "tri-mid")
        api = API.format(wid=wid)
        _create(client, api, auth_headers, "销售管理总览", "正文")
        # 2 字中间子串走 LIKE 兜底
        assert client.get(f"{api}/search", params={"q": "售管"}, headers=auth_headers).json()["total"] == 1
        # 3 字中间子串走 trigram 收窄
        assert client.get(f"{api}/search", params={"q": "售管理"}, headers=auth_headers).json()["total"] == 1

    def test_trigram_candidate_narrows_without_losing_hits(self, client, auth_headers):
        """trigram 候选收窄后，完整 query 的多词 AND 语义仍生效."""
        wid = _ws(client, auth_headers, "tri-and")
        api = API.format(wid=wid)
        _create(client, api, auth_headers, "销售管理总览", "包含协同关键词")
        _create(client, api, auth_headers, "销售管理周报", "只有其他内容")
        # 「协同」仅第一篇正文含；trigram 候选收窄后 AND 语义仍生效
        assert client.get(f"{api}/search", params={"q": "销售管理 协同"}, headers=auth_headers).json()["total"] == 1

    def test_write_path_syncs_both_tables(self, client, db, auth_headers):
        wid = _ws(client, auth_headers, "tri-sync")
        api = API.format(wid=wid)
        doc = _create(client, api, auth_headers, "销售管理总览", "初始内容")
        for table in ("documents_fts", "documents_fts_tri"):
            row = db.execute(text(f"SELECT content FROM {table} WHERE rowid = :id"), {"id": doc["id"]}).scalar_one()
            assert "初始内容" in row
        client.put(f"{api}/{doc['id']}/content", json={"content": "更新后的销售管理内容"}, headers=auth_headers)
        for table in ("documents_fts", "documents_fts_tri"):
            row = db.execute(text(f"SELECT content FROM {table} WHERE rowid = :id"), {"id": doc["id"]}).scalar_one()
            assert "更新后" in row

    def test_soft_delete_clears_both_tables(self, client, db, auth_headers):
        wid = _ws(client, auth_headers, "tri-del")
        api = API.format(wid=wid)
        doc = _create(client, api, auth_headers, "销售管理总览", "正文")
        assert client.delete(f"{api}/{doc['id']}", headers=auth_headers).status_code == 200
        for table in ("documents_fts", "documents_fts_tri"):
            row = db.execute(text(f"SELECT content FROM {table} WHERE rowid = :id"), {"id": doc["id"]}).scalar_one()
            assert row == ""

    def test_latin_channel_unchanged(self, client, auth_headers):
        wid = _ws(client, auth_headers, "tri-latin")
        api = API.format(wid=wid)
        _create(client, api, auth_headers, "FastAPI 指南", "FastAPI 是最流行的 Web 框架")
        data = client.get(f"{api}/search", params={"q": "FastAPI"}, headers=auth_headers).json()
        assert data["total"] == 1
        assert "<mark>" in data["items"][0]["title_hit"]


class TestFtsRefresher:
    def test_disabled_start_and_running_state(self, monkeypatch):
        from cndb.core import fts_refresh
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "FTS_VERIFY_ENABLED", False)
        refresher = fts_refresh._FtsRefresher(interval_seconds=0, startup_delay_seconds=0)
        assert refresher.start() is False
        assert refresher.running is False

    def test_thread_runs_once_and_stops(self, monkeypatch):
        from cndb.core import fts_refresh
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "FTS_VERIFY_ENABLED", True)
        refresher = fts_refresh._FtsRefresher(interval_seconds=0, startup_delay_seconds=0)
        calls: list[int] = []

        def _verify() -> dict:
            calls.append(1)
            return {"consistent": True}

        monkeypatch.setattr(refresher, "verify_once", _verify)
        assert refresher.start() is True
        thread = refresher._thread
        assert thread is not None
        thread.join(timeout=5)
        assert calls == [1]
        assert refresher.running is False
        refresher.stop()

    def test_verify_once_repairs_drift(self, monkeypatch, client, auth_headers, db):
        from cndb.core import database as core_db
        from cndb.core import fts_refresh
        from cndb.core.config import settings

        wid = _ws(client, auth_headers, "fts-refresher")
        api = API.format(wid=wid)
        doc = _create(client, api, auth_headers, "自愈文档", "正文")
        db.execute(text("DELETE FROM documents_fts WHERE rowid = :id"), {"id": doc["id"]})
        db.commit()
        monkeypatch.setattr(settings, "FTS_VERIFY_ENABLED", True)
        monkeypatch.setattr(core_db, "SessionLocal", lambda: db)

        refresher = fts_refresh._FtsRefresher(interval_seconds=0, startup_delay_seconds=0)
        payload = refresher.verify_once()
        assert payload["consistent"] is False
        assert payload["rebuilt"] >= 1
        assert payload["counts"]["missing"] >= 0
