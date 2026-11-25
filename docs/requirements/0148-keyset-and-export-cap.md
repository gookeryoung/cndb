# 需求卡片：keyset 翻页 + 可配导出上限

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0148（规划卡 `0141` 的 P2 项；S1）
- 来源 / 提出人：用户（会话 2026-11-24，「继续」）
- 日期：2026-11-24
- 关联 ADR：无独立 ADR（S1；沿用 ADR 0046 D8 深分页口径）

## 需求原句（逐字）

> 继续

对应 `docs/requirements/0141-table-robustness-roadmap.md` P2 表项：「keyset 分页 + 可配导出上限」。

## 可实施约束（C1..C7）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「keyset 翻页」 | `GET /records` 新增 `after` 游标（不透明 base64），游标 = 排序键值 + `id`；无排序时按 `id` 升序 | `routers/records.py`、`services/core/keyset.py` | 接口测试：逐页走完不重不漏 |
| C2 | 「与排序一致」 | 游标与 `sorts` 绑定，支持多字段与**混向**（逐列 ASC/DESC + id 兜底） | 同上 | 单测：混向排序游标结果 == offset 顺序 |
| C3 | 「NULL 不静默」 | 游标排序键出现 `NULL` → 400（SQLite 下"大于某个 NULL"无稳定语义），提示改用 offset 或加筛选 | 同上 | 单测：NULL 游标值 400 |
| C4 | 「不兼容路径明确拒绝」 | 含 lookup 字段的筛选 / 排序（内存求值路径）不支持 keyset → 400；不静默返回错页 | 同上 | 单测：`needs_post` + after 400 |
| C5 | 「游标健壮」 | 非法 base64 / 形状不符 / 超长（> 8 项）/ 长度与排序链不符 → 400 | 同上 | 单测：四类非法游标 |
| C6 | 「导出上限可配」 | `EXPORT_MAX_ROWS`（默认 500000，`0` = 不限制）；**先 COUNT 再取数**，超限时绝不把全表载入内存 | `core/config.py`、`routers/bulk_export.py` | 接口测试：超限 400 且提示配置项；`0` 不限 |
| C7 | （前端） | 导出弹窗文案改为真实上限（50 万）；**网格顺序翻页已接 keyset**（下一页用游标，跳页 / 改页大小 / 换筛选回退 offset 并清空游标栈） | `ExportPanel.tsx`、`GridPage.tsx`、`useGridData.ts`、`api/hooks.ts` | 前端单测 + 翻页回归 |

## 现状影响面

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 记录列表 | `records.list_rows`（新增 `after`） | `offset` 语义保留，游标与 offset 互斥（游标时忽略 offset） |
| 2 | 列表响应 | `RecordListResponse` | 新增 `next_cursor`（末页为 None） |
| 3 | 导出 | `routers/bulk_export.py` | 原硬编码 50 万改为配置项，并把校验提到取数之前 |
| 4 | 缓存 | `_cached_list` | 缓存键加入游标段，避免不同页命中同一缓存 |

## 未决问题

- [x] ① 游标是否可被伪造：游标内容只含排序键值，用它查询仍受行级权限 / 软删过滤约束，伪造只能改变起点，不泄露数据。
- [x] ② `total` 是否还返回：保留（COUNT 与游标无关）。
- [x] ③ 前端切换：网格顺序翻页已切 keyset；导出文案已修正。

## 卡点

- [x] 每条需求句都有 C 编号约束
- [x] 未决问题全部有结论
