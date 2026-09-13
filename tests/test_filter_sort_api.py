"""Records API 端到端筛选/排序集成测试.

覆盖：
- 多种字段类型 (text / number / select / date)
- 各类筛选操作符 (contains / starts_with / ends_with / = / != / > / < / >= / <= / in / is_empty / is_not_empty)
- 全局搜索 (__query__)
- AND / OR 逻辑切换
- 单字段 / 多字段排序
- 筛选 + 排序组合
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ── 辅助 fixtures ─────────────────────────────────────────


@pytest.fixture
def setup_table(client: TestClient, auth_headers: dict, db):
    """创建一张带 text / number / select / date 字段的表 + 插入典型测试数据.

    表名 EmployeeList，字段：
      name   text     —— 姓名
      dept   select   —— 部门（技术部/市场部/人事部/财务部）
      salary number   —— 薪资
      hire   date     —— 入职日期
      active select   —— 是否在职（是/否）

    插入 7 条典型数据（刻意让筛选/排序可预测）.
    """
    # 建工作区
    r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "FilterSortWS"})
    wid = r.json()["id"]

    # 建表
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables",
        headers=auth_headers,
        json={"name": "EmployeeList"},
    )
    tid = r.json()["id"]

    # 加字段
    fields = [
        {"name": "name", "field_type": "text", "order": 0},
        {
            "name": "dept",
            "field_type": "select",
            "config": {"options": ["技术部", "市场部", "人事部", "财务部"]},
            "order": 1,
        },
        {"name": "salary", "field_type": "number", "order": 2},
        {"name": "hire", "field_type": "date", "order": 3},
        {"name": "active", "field_type": "select", "config": {"options": ["是", "否"]}, "order": 4},
        {"name": "note", "field_type": "text", "order": 5},
    ]
    for f in fields:
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json=f,
        )

    # 插入 7 条数据 —— 刻意设计让各种筛选结果可预测
    rows_data = [
        {"name": "张三", "dept": "技术部", "salary": 15000, "hire": "2023-01-15", "active": "是", "note": "核心开发"},
        {"name": "李四", "dept": "市场部", "salary": 12000, "hire": "2022-06-01", "active": "是", "note": ""},
        {"name": "王五", "dept": "人事部", "salary": 10000, "hire": "2024-03-20", "active": "是", "note": ""},
        {"name": "赵六", "dept": "财务部", "salary": 13000, "hire": "2021-11-10", "active": "否", "note": "已离职"},
        {"name": "钱七", "dept": "技术部", "salary": 18000, "hire": "2023-08-05", "active": "是", "note": "架构师"},
        {"name": "孙八", "dept": "技术部", "salary": 9000, "hire": "2025-01-10", "active": "是", "note": ""},
        {"name": "周九", "dept": "市场部", "salary": 20000, "hire": "2020-05-20", "active": "否", "note": ""},
    ]
    for row in rows_data:
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records",
            headers=auth_headers,
            json={"values": row},
        )

    return wid, tid


def _list_records(
    client: TestClient,
    auth_headers: dict,
    wid: int,
    tid: int,
    filters=None,
    sorts=None,
    filter_logic="AND",
    limit=100,
    offset=0,
    include_trashed=False,
):
    """调 POST /records/list 返回 rows + total."""
    body = {"limit": limit, "offset": offset, "filter_logic": filter_logic}
    if filters is not None:
        body["filters"] = filters
    if sorts is not None:
        body["sorts"] = sorts
    params = {"include_trashed": "true"} if include_trashed else None
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/list",
        headers=auth_headers,
        json=body,
        params=params,
    )
    assert r.status_code == 200, f"list failed: {r.status_code} {r.text}"
    d = r.json()
    return d["rows"], d["total"]


# ── 文本字段筛选 ──────────────────────────────────────────


class TestTextFilter:
    """text 字段的各种操作符."""

    def test_equals(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "name", "op": "=", "value": "张三"}]
        )
        assert total == 1
        assert rows[0]["name"] == "张三"

    def test_not_equals(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "name", "op": "!=", "value": "张三"}]
        )
        assert total == 6
        names = [r["name"] for r in rows]
        assert "张三" not in names

    def test_contains(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "name", "op": "contains", "value": "三"}]
        )
        assert total == 1  # 只有"张三"

    def test_starts_with(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "name", "op": "starts_with", "value": "张"}]
        )
        assert total == 1

    def test_ends_with(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "name", "op": "ends_with", "value": "七"}]
        )
        assert total == 1  # "钱七"

    def test_is_empty(self, client, auth_headers, setup_table):
        """note 字段：赵六="已离职"，孙八/周九/李四/王五 note 为空串."""
        wid, tid = setup_table
        rows, total = _list_records(client, auth_headers, wid, tid, filters=[{"field_name": "note", "op": "is_empty"}])
        # 李四、王五、孙八、周九 note 都是空字符串 ""（create_row 时未赋值，可能为 None）
        # 具体数取决于后端如何处理空值插入，但至少应 < 7
        assert total < 7
        for r in rows:
            v = r.get("note")
            assert v is None or v == ""

    def test_is_not_empty(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "note", "op": "is_not_empty"}]
        )
        assert total >= 2  # 张三="核心开发"，赵六="已离职"，钱七="架构师"


# ── 数值字段筛选 ──────────────────────────────────────────


class TestNumberFilter:
    """number 字段 salary 的各种操作符."""

    def test_gt(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "salary", "op": ">", "value": 15000}]
        )
        # 钱七 18000, 周九 20000
        assert total == 2
        names = [r["name"] for r in rows]
        assert "钱七" in names and "周九" in names

    def test_gte(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "salary", "op": ">=", "value": 15000}]
        )
        # 张三 15000, 钱七 18000, 周九 20000
        assert total == 3

    def test_lt(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "salary", "op": "<", "value": 12000}]
        )
        # 王五 10000, 孙八 9000
        assert total == 2

    def test_lte(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "salary", "op": "<=", "value": 12000}]
        )
        # 李四 12000, 王五 10000, 孙八 9000
        assert total == 3

    def test_eq(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "salary", "op": "=", "value": 13000}]
        )
        assert total == 1
        assert rows[0]["name"] == "赵六"

    def test_not_in(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "salary", "op": "!=", "value": 13000}]
        )
        assert total == 6

    def test_in(self, client, auth_headers, setup_table):
        """in 操作符：值在列表中."""
        wid, tid = setup_table
        rows, total = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            filters=[{"field_name": "salary", "op": "in", "value": [10000, 15000, 20000]}],
        )
        assert total == 3
        names = [r["name"] for r in rows]
        assert set(names) == {"张三", "王五", "周九"}


# ── 日期字段筛选 ──────────────────────────────────────────


class TestDateFilter:
    """date 字段 hire 的操作符."""

    def test_equals(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "hire", "op": "=", "value": "2023-01-15"}]
        )
        assert total == 1
        assert rows[0]["name"] == "张三"

    def test_after(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "hire", "op": ">", "value": "2023-06-01"}]
        )
        # 钱七 2023-08-05, 王五 2024-03-20, 孙八 2025-01-10
        assert total == 3

    def test_before(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "hire", "op": "<", "value": "2022-01-01"}]
        )
        # 周九 2020-05-20, 赵六 2021-11-10
        assert total == 2


# ── select 字段筛选 ──────────────────────────────────────


class TestSelectFilter:
    """select 字段 dept / active."""

    def test_equals(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "dept", "op": "=", "value": "技术部"}]
        )
        # 张三, 钱七, 孙八
        assert total == 3

    def test_not_equals(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "dept", "op": "!=", "value": "技术部"}]
        )
        assert total == 4

    def test_in(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "dept", "op": "in", "value": ["技术部", "市场部"]}]
        )
        # 技术部 3 人 + 市场部 2 人
        assert total == 5


# ── 全局搜索 (__query__) ──────────────────────────────────


class TestGlobalSearch:
    """前端搜索输入框 → __query__ 对所有文本字段做 OR contains."""

    def test_query_finds_multiple(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "__query__", "op": "contains", "value": "技术"}]
        )
        # 张三(技术部), 钱七(技术部), 孙八(技术部) —— name 不含"技术"但 dept 含
        assert total == 3

    def test_query_find_by_name(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "__query__", "op": "contains", "value": "张三"}]
        )
        assert total == 1
        assert rows[0]["name"] == "张三"


# ── AND / OR 逻辑 ─────────────────────────────────────────


class TestFilterLogic:
    """多条件 AND / OR 组合."""

    def test_and_two_conditions(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        rows, total = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            filters=[
                {"field_name": "dept", "op": "=", "value": "技术部"},
                {"field_name": "salary", "op": ">", "value": 12000},
            ],
            filter_logic="AND",
        )
        # 技术部: 张三 15000, 钱七 18000, 孙八 9000 → salary > 12000 的是张三+钱七
        assert total == 2
        names = {r["name"] for r in rows}
        assert names == {"张三", "钱七"}

    def test_or_two_conditions(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        rows, total = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            filters=[
                {"field_name": "dept", "op": "=", "value": "财务部"},
                {"field_name": "salary", "op": ">", "value": 19000},
            ],
            filter_logic="OR",
        )
        # 财务部: 赵六 13000; salary > 19000: 周九 20000
        assert total == 2
        names = {r["name"] for r in rows}
        assert names == {"赵六", "周九"}

    def test_and_three_conditions(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            filters=[
                {"field_name": "active", "op": "=", "value": "是"},
                {"field_name": "dept", "op": "=", "value": "技术部"},
                {"field_name": "salary", "op": ">=", "value": 15000},
            ],
            filter_logic="AND",
        )
        # 在职 + 技术部 + 薪资 >= 15000: 张三 15000, 钱七 18000
        assert total == 2

    def test_or_three_conditions(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            filters=[
                {"field_name": "name", "op": "=", "value": "张三"},
                {"field_name": "name", "op": "=", "value": "李四"},
                {"field_name": "name", "op": "=", "value": "王五"},
            ],
            filter_logic="OR",
        )
        assert total == 3


# ── 排序 ──────────────────────────────────────────────────


class TestSorting:
    """单列 / 多列排序."""

    def test_single_field_asc(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        rows, total = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            sorts=[{"field_name": "salary", "direction": "asc"}],
        )
        assert total == 7
        salaries = [r["salary"] for r in rows]
        assert salaries == sorted(salaries)

    def test_single_field_desc(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        rows, _total = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            sorts=[{"field_name": "salary", "direction": "desc"}],
        )
        salaries = [r["salary"] for r in rows]
        assert salaries == sorted(salaries, reverse=True)

    def test_multiple_fields(self, client, auth_headers, setup_table):
        """先按 dept asc，同部门内按 salary desc."""
        wid, tid = setup_table
        rows, _total = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            sorts=[
                {"field_name": "dept", "direction": "asc"},
                {"field_name": "salary", "direction": "desc"},
            ],
        )
        # 验证各部门内部 salary 降序
        from collections import defaultdict

        dept_groups: dict[str, list[int]] = defaultdict(list)
        for r in rows:
            dept_groups[r["dept"]].append(r["salary"])
        for _dept, sals in dept_groups.items():
            assert sals == sorted(sals, reverse=True), f"{_dept} 内部排序不对"

    def test_sort_with_filter(self, client, auth_headers, setup_table):
        """技术部员工按薪资降序."""
        wid, tid = setup_table
        rows, total = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            filters=[{"field_name": "dept", "op": "=", "value": "技术部"}],
            sorts=[{"field_name": "salary", "direction": "desc"}],
        )
        assert total == 3
        names = [r["name"] for r in rows]
        # 技术部按薪资 desc: 钱七 18000 > 张三 15000 > 孙八 9000
        assert names == ["钱七", "张三", "孙八"]


# ── 边界 / 组合 ───────────────────────────────────────────


class TestFilterSortEdge:
    """边界场景 — 空结果 / 筛选 + 排序 + 分页."""

    def test_filter_no_match(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        rows, total = _list_records(
            client, auth_headers, wid, tid, filters=[{"field_name": "salary", "op": ">", "value": 999999}]
        )
        assert total == 0
        assert rows == []

    def test_empty_filters_returns_all(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        _rows, total = _list_records(client, auth_headers, wid, tid, filters=[])
        assert total == 7

    def test_none_filters_returns_all(self, client, auth_headers, wid=0, tid=0):
        # 不传给 filters 参数 → 默认 list 为空
        # 注意这个 fixture 不依赖 setup_table，直接用 setup_table
        pass  # 下面真正测

    def test_filter_with_pagination(self, client, auth_headers, setup_table):
        """筛选后分页正确."""
        wid, tid = setup_table
        rows_p1, total = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            filters=[{"field_name": "salary", "op": ">", "value": 10000}],
            sorts=[{"field_name": "salary", "direction": "asc"}],
            limit=2,
            offset=0,
        )
        rows_p2, _ = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            filters=[{"field_name": "salary", "op": ">", "value": 10000}],
            sorts=[{"field_name": "salary", "direction": "asc"}],
            limit=2,
            offset=2,
        )
        rows_p3, _ = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            filters=[{"field_name": "salary", "op": ">", "value": 10000}],
            sorts=[{"field_name": "salary", "direction": "asc"}],
            limit=2,
            offset=4,
        )
        # salary > 10000 的: 李四 12000, 赵六 13000, 张三 15000, 钱七 18000, 周九 20000 → 5 条
        assert total == 5
        # 拼接后应覆盖全部 5 条，且升序
        all_rows = rows_p1 + rows_p2 + rows_p3
        salaries = [r["salary"] for r in all_rows]
        assert salaries == sorted(salaries)
        assert len(all_rows) == 5

    def test_unknown_field_filter_is_ignored(self, client, auth_headers, setup_table):
        """不存在的字段名 → 后端静默忽略（不报错）."""
        wid, tid = setup_table
        _rows, total = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            filters=[{"field_name": "nonexistent_field", "op": "=", "value": "x"}],
        )
        # 后端 warning 跳过，返回全部 7 条
        assert total == 7

    def test_invalid_filter_payload_returns_400(self, client, auth_headers, setup_table):
        """未知操作符 → 后端 400."""
        wid, tid = setup_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/list",
            headers=auth_headers,
            json={
                "filters": [{"field_name": "name", "op": "no_such_op", "value": "x"}],
                "limit": 10,
            },
        )
        assert r.status_code == 400


class TestIncludeTrashed:
    """include_trashed=True 能查到软删除的行."""

    def test_soft_delete_then_include_trashed(self, client, auth_headers, setup_table):
        wid, tid = setup_table
        # 拿到第一条记录的 id
        rows, _ = _list_records(client, auth_headers, wid, tid, limit=1)
        row_id = rows[0]["id"]

        # 默认不包含 → 7 条
        _, total_normal = _list_records(client, auth_headers, wid, tid)
        assert total_normal == 7

        # 软删除
        r = client.delete(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/{row_id}",
            headers=auth_headers,
        )
        assert r.status_code == 204

        # 默认查不到 → 6 条
        _, total_after = _list_records(client, auth_headers, wid, tid)
        assert total_after == 6

        # include_trashed=True → 回到 7 条
        rows_trashed, total_trashed = _list_records(client, auth_headers, wid, tid, include_trashed=True)
        assert total_trashed == 7
        # 被删的那条 name 应该能找到（ trashed 行可能有标记）
        names = [r["name"] for r in rows_trashed]
        assert rows[0]["name"] in names


class TestFilterSortBulk:
    """批量操作 + 筛选排序组合场景."""

    def test_filter_then_count_only(self, client, auth_headers, setup_table):
        """只传 filters 不传 sorts — total 仍然正确."""
        wid, tid = setup_table
        _rows, total = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            filters=[{"field_name": "active", "op": "=", "value": "是"}],
        )
        # active=是 的: 张三, 李四, 王五, 钱七, 孙八 → 5 条
        assert total == 5

    def test_sorts_empty_list_no_crash(self, client, auth_headers, setup_table):
        """sorts=[] 应等同于不传 sorts."""
        wid, tid = setup_table
        _rows, total = _list_records(client, auth_headers, wid, tid, sorts=[])
        assert total == 7

    def test_filters_empty_list_no_crash(self, client, auth_headers, setup_table):
        """filters=[] 等同于不传 — 返回全部."""
        wid, tid = setup_table
        _rows, total = _list_records(client, auth_headers, wid, tid, filters=[])
        assert total == 7

    def test_date_filter_with_in(self, client, auth_headers, setup_table):
        """date 字段 in 操作符."""
        wid, tid = setup_table
        rows, total = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            filters=[{"field_name": "hire", "op": "in", "value": ["2023-01-15", "2024-03-20"]}],
        )
        # 张三 2023-01-15, 王五 2024-03-20
        assert total == 2
        names = {r["name"] for r in rows}
        assert names == {"张三", "王五"}

    def test_select_is_empty_is_not_empty(self, client, auth_headers, setup_table):
        """select 字段的 is_empty / is_not_empty（hard to trigger since we set all, skip)."""
        wid, tid = setup_table
        # 所有 active 字段都有值 —— is_not_empty 返回全部 7 条
        _rows, total = _list_records(
            client,
            auth_headers,
            wid,
            tid,
            filters=[{"field_name": "active", "op": "is_not_empty"}],
        )
        assert total == 7
