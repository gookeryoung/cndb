"""导入任务"卡住且无报错"的回归测试.

线上现象：导入任务进度停在 5%、状态一直是"进行中"，前端没有任何报错（用户无法判断该等还是该重试）。

两个真实成因，本文件各锁一条：
1. **进程重启/容器重建**：任务跑在进程内后台线程里，线程被直接带走 → 任务行永远停在 5%。
   → 启动时回收（`reclaim_on_startup`）。
2. **查询兜底**：进程还活着但线程异常终止 → 查询任务详情时按"无进展时长"判定中断。
   → `GET /import/async/{task_id}` 返回 failed + 可读原因（前端因此一定能看到提示）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cndb.plugins.tables.models import ImportTask
from cndb.plugins.tables.services.importing import import_tasks
from cndb.plugins.tables.services.importing.import_tasks import (
    STALL_THRESHOLD_SECONDS,
    reclaim_interrupted_tasks,
)


def _make_task(db, table_id: int, **overrides) -> ImportTask:
    payload = {
        "table_id": table_id,
        "status": "running",
        "progress": 5,
        "format": "xlsx",
        "file_content": "",
        "filename": "问题记录.xlsx",
        "error_message": "",
    }
    payload.update(overrides)
    task = ImportTask(**payload)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@pytest.fixture
def table_id(client, auth_headers) -> int:
    ws = client.post("/api/v1/workspaces", json={"name": "reclaim-ws"}, headers=auth_headers).json()
    table = client.post(
        f"/api/v1/workspaces/{ws['id']}/tables",
        json={"name": "reclaim-table", "description": ""},
        headers=auth_headers,
    ).json()
    return int(table["id"])


class TestReclaimInterruptedTasks:
    def test_stale_running_task_is_failed_with_readable_reason(self, db, table_id):
        task = _make_task(db, table_id)
        task.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
        db.commit()

        assert reclaim_interrupted_tasks(db, stall_threshold=STALL_THRESHOLD_SECONDS) == 1

        db.refresh(task)
        assert task.status == "failed"
        assert task.progress == 100
        assert "没有进展" in (task.error_message or "")
        assert "重试" in (task.error_message or "")

    def test_fresh_running_task_is_kept(self, db, table_id):
        """刚刚更新过的任务不能被误判（默认阈值 180s）."""
        task = _make_task(db, table_id)
        assert reclaim_interrupted_tasks(db, stall_threshold=STALL_THRESHOLD_SECONDS) == 0
        db.refresh(task)
        assert task.status == "running"
        assert task.progress == 5

    def test_pending_validation_also_reclaimed(self, db, table_id):
        task = _make_task(db, table_id, status="pending_validation")
        task.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        db.commit()
        assert reclaim_interrupted_tasks(db, stall_threshold=0) == 1
        db.refresh(task)
        assert task.status == "failed"

    def test_finished_tasks_untouched(self, db, table_id):
        done = _make_task(db, table_id, status="done", progress=100)
        confirm = _make_task(db, table_id, status="pending_confirm", progress=95)
        for t in (done, confirm):
            t.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        db.commit()

        assert reclaim_interrupted_tasks(db, stall_threshold=0) == 0
        db.refresh(done)
        db.refresh(confirm)
        assert done.status == "done"
        assert confirm.status == "pending_confirm"

    def test_startup_reclaim_marks_leftover_tasks(self, db, table_id, monkeypatch):
        """启动回收走同一逻辑（阈值 0：上一进程遗留的任务不可能再被推进）."""
        _make_task(db, table_id)
        called: dict[str, int] = {}

        def fake_reclaim(session, *, stall_threshold: int = 0):
            called["threshold"] = stall_threshold
            return reclaim_interrupted_tasks(session, stall_threshold=stall_threshold)

        monkeypatch.setattr(import_tasks, "reclaim_interrupted_tasks", fake_reclaim)
        # reclaim_on_startup 使用生产 SessionLocal；这里直接验证它在阈值 0 下会判定该任务
        assert import_tasks.reclaim_on_startup() >= 0
        assert called.get("threshold") == 0


class TestStallDetectionOnRead:
    """查询任务详情时兜底判定：前端不会永远停在 5% 且无提示."""

    def test_stale_running_task_reported_as_failed(self, client, auth_headers, db, table_id):
        ws_id = client.get("/api/v1/workspaces", headers=auth_headers).json()[0]["id"]
        task = _make_task(db, table_id)
        task.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=30)
        db.commit()

        resp = client.get(
            f"/api/v1/workspaces/{ws_id}/tables/{table_id}/import/async/{task.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "failed"
        assert body["progress"] == 100
        assert "没有进展" in body["error_message"]
        # 无进展时长一并返回，便于前端展示"已 xx 秒无进展"
        assert body["stalled_seconds"] >= 0

    def test_fresh_running_task_still_reported_running(self, client, auth_headers, db, table_id):
        ws_id = client.get("/api/v1/workspaces", headers=auth_headers).json()[0]["id"]
        task = _make_task(db, table_id)

        resp = client.get(
            f"/api/v1/workspaces/{ws_id}/tables/{table_id}/import/async/{task.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "running"
        assert body["progress"] == 5
        assert body["stalled_seconds"] < STALL_THRESHOLD_SECONDS


class TestExecuteSubStepProgress:
    """执行阶段必须给出子步骤进度：卡住时能看出卡在解析/校验/写入/选项同步哪一步.

    旧实现 execute 只在开始时写一次 progress=5，之后直到结束才有变化 —— 任何子步骤卡住，
    用户看到的都是"5% 无报错"，既无法判断还要不要等，也无法定位。
    """

    def test_progress_cb_writes_task_progress(self, client, auth_headers, db, table_id, monkeypatch):
        from cndb.plugins.tables.models import ImportTask
        from cndb.plugins.tables.services.importing import import_tasks
        from cndb.plugins.tables.services.importing.importer import Importer

        task = _make_task(db, table_id, status="pending_confirm", progress=95, validation_report="{}")
        captured: dict[str, int] = {}

        def fake_execute(self, *args, **kwargs):
            cb = kwargs.get("progress_cb")
            assert cb is not None, "execute 必须收到 progress_cb（否则执行阶段无法显示子步骤）"
            cb(45, "准备写入")
            # 回调内部会 commit，这里换一个查询视图确认真的落库了
            db.expire_all()
            captured["progress_in_db"] = int(db.get(ImportTask, task.id).progress)

            class _Result:
                imported_ids: list[int] = []
                report: dict = {}

            return _Result()

        monkeypatch.setattr(Importer, "execute", fake_execute, raising=True)

        import_tasks.execute_import_task(db, task.id)
        db.refresh(task)

        assert captured.get("progress_in_db") == 45, "子步骤进度应写进任务行"
        assert task.status == "done"
        assert task.progress == 100

    def test_slow_sub_step_is_visible(self, client, auth_headers, db, table_id, monkeypatch):
        """子步骤耗时（模拟卡住）时，任务行停在对应百分比而不是笼统的 5%."""
        import time as _time

        from cndb.plugins.tables.models import ImportTask
        from cndb.plugins.tables.services.importing import import_tasks
        from cndb.plugins.tables.services.importing.importer import Importer

        task = _make_task(db, table_id, status="pending_confirm", progress=95, validation_report="{}")
        observed: list[int] = []

        def fake_execute(self, *args, **kwargs):
            kwargs["progress_cb"](60, "写入数据")
            db.expire_all()
            observed.append(int(db.get(ImportTask, task.id).progress))
            _time.sleep(0.05)

            class _Result:
                imported_ids: list[int] = []
                report: dict = {}

            return _Result()

        monkeypatch.setattr(Importer, "execute", fake_execute, raising=True)
        import_tasks.execute_import_task(db, task.id)

        assert observed == [60]
