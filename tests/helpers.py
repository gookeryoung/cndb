"""测试共享工具."""

from __future__ import annotations


def wait_import_settled(client, url, headers, timeout: float = 10) -> dict:
    """等 import 后台线程结束后单次查询任务状态.

    用 join_background_threads 做确定性等待，替代固定 sleep 轮询；
    返回任务 JSON（调用方自行断言状态）。
    """
    from cndb.plugins.tables.import_tasks import join_background_threads

    join_background_threads(timeout=timeout)
    resp = client.get(url, headers=headers)
    assert resp.status_code == 200, f"查询任务失败: {resp.status_code} {resp.text[:200]}"
    return resp.json()
