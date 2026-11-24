# 需求卡片：服务端聚合 / 分组

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0147（规划卡 `0141` 的 P2 项；S1）
- 来源 / 提出人：用户（会话 2026-11-24，「P1+P2」）
- 日期：2026-11-24
- 关联 ADR：无独立 ADR（S1；口径沿用 ADR 0046 读路径下推与 ADR 0004 行级权限）

## 需求原句（逐字）

> P1+P2

对应 `docs/requirements/0141-table-robustness-roadmap.md` P2 表项：「服务端聚合 / 分组」。

## 可实施约束（C1..C7）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「聚合」 | `POST /{wid}/tables/{tid}/records/aggregate`：`group_by[]` + `metrics[{field, agg}]`，`agg ∈ count / sum / avg / min / max / distinct` | `routers/records.py`、`services/core/records.py` | 接口测试：各聚合值正确 |
| C2 | 「过滤一致」 | 支持与列表同一份 `filters` + `filter_logic`；行级权限（读范围）与软删过滤无条件生效 | 同上 | 接口测试：范围外行不计入聚合 |
| C3 | 「下推」 | 物理列直接 `GROUP BY`/聚合下推 SQL；lookup / formula 等无物理列的字段作为 group_by / metric → 400（明确提示，不静默算错） | 同上 | 接口测试：lookup 字段 400 |
| C4 | 「排序与上限」 | `order_by` 支持按分组键或聚合结果排序；`limit` 默认 100、上限 1000；返回 `total_groups`（分页所需） | 同上 | 接口测试：排序 / limit / total_groups |
| C5 | 「空值分组」 | 分组键为 NULL 时归入 `null` 组并在结果中如实返回（不丢弃） | 同上 | 单测：含空值分组 |
| C6 | 「扫描上限」 | 复用 `TABLES_LOOKUP_SCAN_LIMIT` 之外的显式上限：聚合前先 `COUNT` 基础命中行数，超过 `AGGREGATE_MAX_ROWS`（默认 50 万）→ 400 提示收窄筛选 | 同上 | 单测：超限 400 |
| C7 | （前端） | 本期只交付接口；网格「本页 / 全表」聚合切换与画布 KPI 改造列为后续 | — | 记入「已知限制」 |

## 现状影响面

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 记录列表 | `records.list_rows` / `_build_query_plan` | 聚合复用同一 WHERE 构建（行权限 + 软删 + 业务过滤） |
| 2 | 画布 KPI | `dashboard_data.py` | 前端本地聚合，行数上限 2000；本期不改（后续可切到本接口） |
| 3 | 网格聚合条 | `gridAggregationBar.tsx` | 只统计选中行；本期不改 |

## 未决问题

- [x] ① 聚合口径：SQL 下推，数值列用 `SUM/AVG/MIN/MAX`，`count` 计非空，`distinct` 计数去重值。
- [x] ② 无物理列字段：明确 400（不让用户看到算错的结果）。
- [x] ③ 前端改造：本期不做。

## 卡点

- [x] 每条需求句都有 C 编号约束
- [x] 未决问题全部有结论
