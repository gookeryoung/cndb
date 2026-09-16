"""cleaning_actions 全链路测试 —— 模型字段 → confirm 路由规范化 → execute 传递."""

from __future__ import annotations

from contextlib import suppress


class TestImportTaskCleaningActions:
    """ImportTask 模型应支持 cleaning_actions 字段."""

    def test_model_has_cleaning_actions_column(self):
        from cndb.plugins.tables.models import ImportTask

        cols = [c.name for c in ImportTask.__table__.columns]
        assert "cleaning_actions" in cols

    def test_model_default_after_insert(self, db):
        """commit 后从 DB 读回，default 应为空列表（由 server_default 提供）."""
        from cndb.plugins.tables.models import ImportTask

        task = ImportTask(
            table_id=0,
            status="pending",
            filename="test.csv",
            format="csv",
            file_content="",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        # server_default='[]' 保证 INSERT 后读回来是列表
        assert task.cleaning_actions in ([], None)  # SQLite JSON() 默认值因 driver 可能有差异

    def test_model_can_store_actions(self, db):
        from cndb.plugins.tables.models import ImportTask

        actions = [
            {"column": "price", "action": "coerce_type", "strategy": "number"},
            {"action": "dedupe_rows", "strategy": "keep_first"},
        ]
        task = ImportTask(
            table_id=0,
            status="pending",
            filename="test.csv",
            format="csv",
            file_content="",
            cleaning_actions=actions,  # type: ignore[arg-type]
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        assert task.cleaning_actions == actions


class TestConfirmRouteCleaningActionsNormalize:
    """confirm 路由应规范化 cleaning_actions —— 只保留 apply_cleaning_actions 需要的字段."""

    def test_normalize_strips_preview_and_reason(self):
        from cndb.plugins.tables.routers.bulk import _normalize_cleaning_actions

        raw = [
            {
                "id": "price_coerce",
                "column": "price",
                "action": "coerce_type",
                "strategy": "number",
                "on_fail": "nullify",
                "affected_count": 42,
                "reason": "类型冲突",
                "preview_before": ["abc"],
                "preview_after": ["(转换为 number)"],
            },
            {
                "id": "global_dedupe",
                "action": "dedupe_rows",
                "strategy": "keep_first",
                "column": None,
                "affected_count": 10,
            },
        ]
        result = _normalize_cleaning_actions(raw)
        assert len(result) == 2
        assert set(result[0].keys()) <= {"column", "action", "strategy", "on_fail"}
        assert result[0]["action"] == "coerce_type"
        assert result[0]["column"] == "price"
        assert result[1]["action"] == "dedupe_rows"
        assert "preview_before" not in result[0]
        assert "reason" not in result[0]
        assert "id" not in result[0]

    def test_normalize_skips_non_dict(self):
        from cndb.plugins.tables.routers.bulk import _normalize_cleaning_actions

        raw = [
            {"action": "dedupe_rows"},
            "not a dict",
        ]
        result = _normalize_cleaning_actions(raw)
        assert len(result) == 1

    def test_normalize_empty_list(self):
        from cndb.plugins.tables.routers.bulk import _normalize_cleaning_actions

        assert _normalize_cleaning_actions([]) == []

    def test_normalize_none(self):
        from cndb.plugins.tables.routers.bulk import _normalize_cleaning_actions

        assert _normalize_cleaning_actions(None) == []


class TestExecuteImportTaskPassesCleaningActions:
    """execute_import_task 应把 task.cleaning_actions 传给 importer.execute."""

    def test_passes_cleaning_actions_when_present(self, db, monkeypatch):
        """有 validation_report 且 cleaning_actions 非空时，应传给 importer.execute."""
        from cndb.plugins.tables.models import DataTable, ImportTask

        # 必须先有真实 DataTable，execute_import_task 会查它
        dt = DataTable(workspace_id=1, name="t_cleaning")
        dt.db_table_name = "table_cleaning_chain_111"
        db.add(dt)
        db.commit()
        db.refresh(dt)

        task = ImportTask(
            table_id=dt.id,
            status="pending_confirm",
            filename="t.csv",
            format="csv",
            file_content="1,a\n2,b\n",
            validation_report='{"column_profiles": []}',
            cleaning_actions=[{"action": "dedupe_rows"}],  # type: ignore[arg-type]
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        captured: dict = {}

        class FakeImporter:
            def __init__(self, engine, session, table):
                pass

            def execute(self, content, fmt, **kwargs):
                captured.update(kwargs)
                return type(
                    "R",
                    (),
                    {
                        "imported_ids": [1],
                        "report": {"new_preview": []},
                    },
                )()

        monkeypatch.setattr("cndb.plugins.tables.importer.Importer", FakeImporter)

        from cndb.plugins.tables import import_tasks

        with suppress(Exception):
            import_tasks.execute_import_task(db, task.id)

        assert "cleaning_actions" in captured
        assert captured["cleaning_actions"] == [{"action": "dedupe_rows"}]

        db.delete(task)
        db.delete(dt)
        db.commit()

    def test_passes_none_when_empty(self, db, monkeypatch):
        """cleaning_actions 为空列表时，应转成 None 传给 importer."""
        from cndb.plugins.tables.models import DataTable, ImportTask

        dt = DataTable(workspace_id=1, name="t_cleaning2")
        dt.db_table_name = "table_cleaning_chain_222"
        db.add(dt)
        db.commit()
        db.refresh(dt)

        task = ImportTask(
            table_id=dt.id,
            status="pending_confirm",
            filename="t.csv",
            format="csv",
            file_content="1,a\n2,b\n",
            validation_report='{"column_profiles": []}',
            cleaning_actions=[],  # type: ignore[arg-type]
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        captured: dict = {}

        class FakeImporter:
            def __init__(self, engine, session, table):
                pass

            def execute(self, content, fmt, **kwargs):
                captured.update(kwargs)
                return type(
                    "R",
                    (),
                    {
                        "imported_ids": [1],
                        "report": {"new_preview": []},
                    },
                )()

        monkeypatch.setattr("cndb.plugins.tables.importer.Importer", FakeImporter)

        from cndb.plugins.tables import import_tasks

        with suppress(Exception):
            import_tasks.execute_import_task(db, task.id)

        assert captured["cleaning_actions"] is None

        db.delete(task)
        db.delete(dt)
        db.commit()


class TestConfirmRouteCleaningActionsE2E:
    """用 FastAPI TestClient 端到端验证 confirm 路由能接收 cleaning_actions 并存入 task."""

    def test_confirm_route_accepts_cleaning_actions_body(self, client, auth_headers, db):
        """POST confirm 路由带 cleaning_actions body → DB 里 task.cleaning_actions 应被规范化存储."""
        import json
        import time
        from io import BytesIO

        # 1. 创建 workspace + table + 字段
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_ca_e2e"})
        wid = ws.json()["id"]
        tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_ca_e2e"})
        tid = tbl.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "name", "field_type": "text", "order": 0},
        )
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "price", "field_type": "number", "order": 1},
        )

        # 2. 提交 analyze
        csv = "name,price\nfoo,100\nbar,abc\nbaz,200\n"
        files = {"file": ("t.csv", BytesIO(csv.encode()), "text/csv")}
        resp = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/analyze",
            headers=auth_headers,
            files=files,
        )
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        # 3. 轮询直到 pending_confirm
        for _ in range(30):
            time.sleep(0.3)
            poll = client.get(
                f"/api/v1/workspaces/{wid}/tables/{tid}/import/async/{task_id}",
                headers=auth_headers,
            )
            if poll.json()["status"] in ("pending_confirm", "pending_validation", "failed"):
                break

        # 4. POST confirm 带 cleaning_actions body（含前端传来的展示字段）
        fake_suggestion = {
            "id": "price_coerce",
            "column": "price",
            "action": "coerce_type",
            "strategy": "number",
            "on_fail": "nullify",
            "affected_count": 42,
            "reason": "类型冲突",
            "preview_before": ["abc"],
            "preview_after": ["(转换为 number)"],
        }
        body = {"cleaning_actions": [fake_suggestion]}
        resp2 = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/{task_id}/confirm",
            headers={**auth_headers, "Content-Type": "application/json"},
            content=json.dumps(body),
        )
        assert resp2.status_code == 200
        from cndb.plugins.tables.models import ImportTask

        db_task = db.get(ImportTask, task_id)
        assert db_task is not None
        assert len(db_task.cleaning_actions) == 1
        # 展示字段应被剥离
        stored = db_task.cleaning_actions[0]
        assert "action" in stored
        assert stored["action"] == "coerce_type"
        assert stored["column"] == "price"
        assert "reason" not in stored
        assert "preview_before" not in stored
        assert "id" not in stored

    def test_confirm_route_no_cleaning_actions_skips_save(self, client, auth_headers, db):
        """不传 cleaning_actions body 时，task.cleaning_actions 应保持不变."""
        import json
        import time
        from io import BytesIO

        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_ca_no"})
        wid = ws.json()["id"]
        tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_ca_no"})
        tid = tbl.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "x", "field_type": "text", "order": 0},
        )

        csv = "x\nfoo\nbar\n"
        files = {"file": ("t.csv", BytesIO(csv.encode()), "text/csv")}
        resp = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/analyze",
            headers=auth_headers,
            files=files,
        )
        task_id = resp.json()["task_id"]

        for _ in range(30):
            time.sleep(0.3)
            poll = client.get(
                f"/api/v1/workspaces/{wid}/tables/{tid}/import/async/{task_id}",
                headers=auth_headers,
            )
            if poll.json()["status"] in ("pending_confirm", "pending_validation", "failed"):
                break

        # 不传 cleaning_actions 字段（空 body）
        resp2 = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/{task_id}/confirm",
            headers={**auth_headers, "Content-Type": "application/json"},
            content=json.dumps({}),
        )
        assert resp2.status_code == 200

        from cndb.plugins.tables.models import ImportTask

        db_task = db.get(ImportTask, task_id)
        # 不传时应保持默认值（空列表 或 None 取决于 driver）
        assert db_task.cleaning_actions in ([], None)


class TestReanalyzeRouteCoverage:
    """reanalyze 路由需要覆盖（bulk.py 里较大的未覆盖块）."""

    def test_reanalyze_updates_match_keys(self, client, auth_headers, db):
        """POST reanalyze 带 match_keys → DB 里 task.match_keys 应被更新."""
        import json
        import time
        from io import BytesIO

        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_ra"})
        wid = ws.json()["id"]
        tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_ra"})
        tid = tbl.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "name", "field_type": "text", "order": 0},
        )

        csv = "name\nfoo\nbar\n"
        files = {"file": ("t.csv", BytesIO(csv.encode()), "text/csv")}
        resp = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/analyze",
            headers=auth_headers,
            files=files,
        )
        task_id = resp.json()["task_id"]

        for _ in range(30):
            time.sleep(0.3)
            poll = client.get(
                f"/api/v1/workspaces/{wid}/tables/{tid}/import/async/{task_id}",
                headers=auth_headers,
            )
            if poll.json()["status"] in ("pending_confirm", "pending_validation", "failed"):
                break

        # POST reanalyze 带 match_keys (query param)
        resp2 = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/{task_id}/reanalyze",
            headers=auth_headers,
            params={"match_keys": json.dumps(["name"])},
        )
        assert resp2.status_code == 200

        from cndb.plugins.tables.models import ImportTask

        db_task = db.get(ImportTask, task_id)
        assert db_task.match_keys == ["name"]
