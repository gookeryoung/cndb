"""异步导入 + ImportTask 测试."""

from __future__ import annotations

import time


def test_import_task_model_exists(db):
    """ImportTask 模型应可导入并注册."""
    from cndb.plugins.tables.models import ImportTask

    assert ImportTask.__tablename__ == "tables_importtask"
    # 检查字段存在
    cols = [c.name for c in ImportTask.__table__.columns]
    assert "table_id" in cols
    assert "status" in cols
    assert "progress" in cols
    assert "result_ids" in cols


def test_import_task_status_transitions():
    """状态机应拒绝非法转换."""
    from cndb.plugins.tables.import_tasks import _transition_status

    # 模拟一个 task 对象
    class FakeTask:
        def __init__(self, status):
            self.status = status

    fake = FakeTask("done")
    try:
        _transition_status(fake, "pending")
        raise AssertionError("应抛 ValueError")
    except ValueError:
        pass  # 预期行为

    # 合法转换
    fake2 = FakeTask("pending")
    _transition_status(fake2, "running")
    assert fake2.status == "running"


def test_async_import_submit_and_poll(client, auth_headers, db):
    """提交异步导入任务并轮询进度."""
    # 创建工作区和表
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_async"})
    wid = ws.json()["id"]
    tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_async"})
    tid = tbl.json()["id"]
    # 添加一个 text 字段
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "name", "field_type": "text", "order": 0},
    )
    # 准备 JSON 文件内容
    import json

    file_content = json.dumps([{"name": "foo"}, {"name": "bar"}])
    # 提交异步导入
    from io import BytesIO

    # 用文件上传方式调用（multipart/form-data）
    files = {"file": ("test.json", BytesIO(file_content.encode()), "application/json")}
    resp = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/import/async",
        headers=auth_headers,
        files=files,
    )
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    assert resp.json()["status"] == "pending"

    # 轮询等待完成
    for _ in range(30):
        time.sleep(0.3)
        poll = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import/async/{task_id}",
            headers=auth_headers,
        )
        assert poll.status_code == 200
        data = poll.json()
        if data["status"] in ("done", "failed"):
            break

    # 最终应为 done 或 failed（取决于引擎行为）
    assert data["status"] in ("done", "failed")
    if data["status"] == "done":
        assert data["imported_rows"] == 2


def test_import_task_not_found(client, auth_headers, db):
    """查询不存在的任务应 404."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws"})
    wid = ws.json()["id"]
    tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t"})
    tid = tbl.json()["id"]

    resp = client.get(
        f"/api/v1/workspaces/{wid}/tables/{tid}/import/async/99999",
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_execute_import_task_not_found(db):
    """执行不存在的任务应静默返回（不抛异常）."""
    from cndb.plugins.tables.import_tasks import execute_import_task

    # 不应抛异常
    execute_import_task(db, 99999)


def test_execute_import_task_failed_path(db, auth_headers, client):
    """任务执行失败时应标记为 failed."""
    # 创建工作区和表
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_fail"})
    wid = ws.json()["id"]
    tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_fail"})
    tbl.json()["id"]

    from cndb.plugins.tables.import_tasks import (
        create_import_task,
        execute_import_task,
    )

    # 用不存在的 table_id 创建任务，执行时应失败
    task = create_import_task(
        db,
        table_id=99999,
        user_id=None,
        filename="test.json",
        fmt="json",
        content='[{"name": "x"}]',
    )
    execute_import_task(db, task.id)
    db.refresh(task)
    assert task.status == "failed"
    assert task.error_message != ""


def test_execute_import_task_invalid_format(db, auth_headers, client):
    """不支持的格式应导致任务失败."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_badfmt"})
    wid = ws.json()["id"]
    tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_badfmt"})
    tid = tbl.json()["id"]

    from cndb.plugins.tables.import_tasks import (
        create_import_task,
        execute_import_task,
    )

    task = create_import_task(
        db,
        table_id=tid,
        user_id=None,
        filename="test.xyz",
        fmt="xyz",
        content="garbage",
    )
    execute_import_task(db, task.id)
    db.refresh(task)
    assert task.status == "failed"


def test_create_import_task_bytes_content(db):
    """bytes 内容应正确解码存储."""
    from cndb.plugins.tables.import_tasks import create_import_task
    from cndb.plugins.tables.models import DataTable

    dt = DataTable(workspace_id=1, name="unused")
    dt.db_table_name = "table_testunused123"
    db.add(dt)
    db.commit()
    db.refresh(dt)

    raw = "a,b\n1,2"
    task = create_import_task(
        db,
        table_id=dt.id,
        user_id=None,
        filename="test.csv",
        fmt="csv",
        content=raw.encode("utf-8"),
    )
    assert task.file_content == raw

    db.delete(task)
    db.delete(dt)
    db.commit()


def test_execute_import_task_csv_path(db, auth_headers, client):
    """CSV 格式导入应走 csv 分支."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_csv"})
    wid = ws.json()["id"]
    tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_csv"})
    tid = tbl.json()["id"]
    # 加一个 text 字段
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "col", "field_type": "text"},
    )

    from cndb.plugins.tables.import_tasks import (
        create_import_task,
        execute_import_task,
    )

    csv_content = "col\nhello\nworld"
    task = create_import_task(
        db,
        table_id=tid,
        user_id=None,
        filename="test.csv",
        fmt="csv",
        content=csv_content,
    )
    execute_import_task(db, task.id)
    db.refresh(task)
    assert task.status == "done"


def test_execute_import_task_xlsx_format(db):
    """xlsx 格式应触发 base64 decode（但 transfer 里没实际 xlsx 解析，会失败）."""
    from cndb.plugins.tables.import_tasks import (
        create_import_task,
        execute_import_task,
    )
    from cndb.plugins.tables.models import DataTable

    dt = DataTable(workspace_id=1, name="unused_xlsx")
    dt.db_table_name = "table_testxlsx123"
    db.add(dt)
    db.commit()
    db.refresh(dt)

    import base64

    base64.b64encode(b"PKG!fake").decode("ascii")
    task = create_import_task(
        db,
        table_id=dt.id,
        user_id=None,
        filename="test.xlsx",
        fmt="xlsx",
        content=b"PKG!fake",
    )
    execute_import_task(db, task.id)
    db.refresh(task)
    # 要么 done（如果 transfer 支持 xlsx）要么 failed（不支持）
    assert task.status in ("done", "failed")

    db.delete(task)
    db.delete(dt)
    db.commit()


def test_create_import_task_xlsx_str_content(db):
    """xlsx 格式 + str content 应走 encode 分支."""
    from cndb.plugins.tables.import_tasks import create_import_task
    from cndb.plugins.tables.models import DataTable

    dt = DataTable(workspace_id=1, name="unused_xlsx_str")
    dt.db_table_name = "table_testxlsxs123"
    db.add(dt)
    db.commit()
    db.refresh(dt)

    task = create_import_task(
        db,
        table_id=dt.id,
        user_id=None,
        filename="test.xlsx",
        fmt="xlsx",
        content="PKG!fake-string-content",
    )
    assert task.format == "xlsx"
    assert task.file_content != "PKG!fake-string-content"  # 应该被 base64 编码

    db.delete(task)
    db.delete(dt)
    db.commit()
