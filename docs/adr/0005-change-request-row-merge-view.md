# ADR 0005: 修改申请同行合并视图与冲突裁决

Status: Accepted（M1-M3 已落地；M4 代码已交付，缺聚合端点的前端用例）
Date: 2026-10-19
Related: `src/cndb/plugins/change_requests/services.py`、`src/cndb/plugins/change_requests/routers/change_requests.py`、`src/cndb/plugins/change_requests/schemas.py`、`frontend/src/pages/changeRequests/ChangeRequestsPage.tsx`、`frontend/src/pages/changeRequests/ChangeRequestRowMergePage.tsx`、`frontend/src/pages/grid/useGridData.ts`；术语见 `CONTEXT.md`「修改申请 / 双轨制写入 / 编辑中标识」
需求卡片: 无卡片（需求直接立项，原文见「口径」）

## 口径（需求 → 设计落点）

需求原文：**「合并查看同行的数据申请」「按时间倒序查看」「同行允许合并审批多项修改」「提供冲突处理页面」**（本 ADR 无需求卡片，原文与 C 编号就地维护）

| C # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 合并查看同行数据申请 | `GET .../change-requests?group_by=row` 按 `row_id` 聚合成行组；`op=create` 无行归属，归 `ungrouped` |
| C2 | 按时间倒序查看 | 组间按组内 `latest_created_at` 倒序；组内 `requests` 按 `created_at` 倒序 |
| C3 | 同行允许合并审批多项修改 | `POST .../change-requests/rows/{row_id}/merge`：行组内多选 → 一次审批多份申请，按 `created_at` 升序逐份 apply、`delete` 最后 |
| C4 | 提供冲突处理页面 | 独立路由 `/w/:wid/tables/:tid/change-requests/rows/:rowId/merge`，冲突字段逐字段裁决（采用指定申请值 / 保留当前值）后批量落库 |

决策结论只在「决策记录」写一次；本节与正文不再罗列。

## Context

决策时（2026-10-19）修改申请只支持**单申请维度**审批，现状逐条核对：

| # | 现状 | 位置 | 影响 | 对应约束 |
|---|---|---|---|---|
| 1 | 列表页为扁平 `List`，scope 段控 `open/merged/all/mine`，排序由 `ChangeRequest.id.desc()` 决定，只展示 `conflicts_count`（共享行的申请数，已去重） | `frontend/src/pages/changeRequests/ChangeRequestsPage.tsx` | 同一行的多份申请在列表中被拆散，看不出「这一行有哪些待审变更、是否互相打架」 | C1、C2 |
| 2 | 详情页逐 item `apply/skip` 后 `POST /{id}/merge`；后端原子落库，任一校验失败整体 409 并保持 `open` | `src/cndb/plugins/change_requests/services.py` | 审批者需逐个进详情页，同行多申请重复操作 | C3 |
| 3 | 仅有两类「冲突」信号：`stale`（同行他人合并后置位，行级）与 `field_conflicts`（`current[field] != base[field]`，字段级基准漂移，详情接口实时计算） | `src/cndb/plugins/change_requests/services.py` | **没有**「同一行同一字段被多个 open 申请写入不同值」的交汇冲突检测，也没有集中的冲突发现 / 解决入口 | C4 |
| 4 | 行级「编辑中标识」由客户端先 `list(open)` 再逐条 `get` 详情（N+1），聚合 `row_id → 申请` | `frontend/src/pages/grid/useGridData.ts` | 申请量随行数放大时请求数线性增长 | C1 |

**核心缺陷（需求要补的）**：现模型只有「单申请 vs 当前行」的两方比对，无法表达**多份 open 申请对同一字段的目标值相互冲突**，因而既无法安全批量审批，也无法在落库前让人显式裁决。

设计目标（不变量）：

- **I1 无冲突自动合并**：字段只有单一写者、或全部写者目标值一致时，无需人工干预即 apply。
- **I2 冲突必须显式裁决**：存在交汇冲突的字段，`resolutions` 缺省即 409，**绝不静默覆盖**他人已提交的值（不做 last-writer-wins）。
- **I3 原子性**：批量 merge 任一 `_normalize_values` 校验失败 → 整体 409 回滚，全部申请保持 `open`。
- **I4 旧契约不变**：不传 `group_by` 仍返回扁平 `items`；单申请 `POST /{id}/merge` 保留可用。
- **I5 基准失效传染**：落库后同行其余 open 申请置 `stale`，需 `update-base` 刷新后才能继续。

## Decision

### 1. 术语与冲突模型

- **同行（row）**：同一 `ChangeItem.row_id`；`op=create` 的项 `row_id` 为空，不参与行分组。
- **三方（three-way）**：`base` = 申请 `base_values` 快照；`ours` = 行 `current_values`；`theirs` = 申请 `values`。
- **冲突分类**：基准漂移 `drift`（`current[field] != base[field]`，字段级）；交汇冲突 `cross conflict`（同行同字段被 ≥2 开放申请写入且值不等，或 `delete` 与其他 `update`/`delete` 互斥）；行缺失 `row_missing`（目标行已删除）。
- **行组冲突态**：`has_conflict`（存在交汇冲突或 delete 互斥）、`has_drift`（存在基准漂移）。

### 2. 判定算法（唯一入口）

`detect_row_conflicts(items, current) -> dict`（`services.py`），输入该行全部 open 申请的 items，输出 `fields`（字段 → 各写者 `(request_id, item_id, value)`）、`conflict_fields`、`row_op_conflict`、`drift_fields`、`row_missing`；`create` 项排除，复用 `rec.get_row` / `_normalize_values`。分组接口与批量 merge 共用该入口，禁止各写一份判定。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{wid}/tables/{tid}/change-requests` | 新增可选查询参 `group_by`（取值 `flat` 或 `row`，缺省 `flat`）；item 新增可选 `row_ids` / `fields` / `item_count` |
| `GET`（`group_by=row`） | 返回 `groups[]`（`row_id` / `row_values` / `row_missing` / `requests[]` / `conflict_fields` / `drift_fields` / `has_conflict` / `has_drift` / `latest_created_at`）+ `ungrouped[]` + `total` + `write_mode` |
| `POST /{wid}/tables/{tid}/change-requests/rows/{row_id}/merge` | 新增：`request_ids` + `resolutions`（每个冲突字段一项：`strategy` 取 `item` 或 `current`，`item_id` 指向采用的申请项）+ `row_action`（delete 互斥裁决）+ `comment`，返回 `applied` / `skipped` / `merged_request_ids` / `requests[]` |
| `POST /{wid}/tables/{tid}/change-requests/{id}/merge` | 保留不动（单申请兼容） |

### 4. 边界与例外

1. 选中申请含 `create` 项（无 `row_id`）→ 行组端点 400；`create` 只能按申请维度批量。
2. 冲突字段未裁决 → 409（提示「请先处理冲突字段」）；`strategy=current` 跳过该字段写入。
3. 行在批量 merge 期间被删 → 行级冲突，须经 `row_action` 显式选择「执行删除 / 保留」。
4. 申请非 `open` → 409；非 reviewer → 403（复用 `_require_reviewer`）。
5. 应用顺序线性化：非冲突项按 `created_at` 升序，`delete` 最后。

### 5. 迁移

无（纯读模型 + 新端点，无新表 / 新列，存量数据零迁移）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 列表页 | `frontend/src/pages/changeRequests/ChangeRequestsPage.tsx` | 视图段控「同行合并（默认）/ 平铺」；行组卡片（行标识 + 申请数 / 冲突 / 基准漂移徽标）；组内倒序；reviewer 复选框 + 批量审批（有冲突跳裁决页）；`ungrouped` 单列一区；`merged` / `closed` 维持平铺 |
| 冲突处理页 | `frontend/src/pages/changeRequests/ChangeRequestRowMergePage.tsx` | 行摘要（ours）→ 申请 items（theirs）→ 冲突字段裁决表（radio：采用第 N 份 / 保留当前）→ 非冲突字段只读汇总 → 备注 + 执行合并；快捷「全部采用最新提交 / 全部保留当前」 |
| API 封装 | `frontend/src/api/changeRequests.ts` | `listGrouped`、`mergeRow` |
| 类型 | `frontend/src/api/types/change-requests.ts` | `ChangeRowGroup`、`CRRowMergePayload`、`CRConflictField`、`CRResolution` |
| 行级标识 | `frontend/src/pages/grid/useGridData.ts` | `usePendingChanges` 改走 `listGrouped` 聚合端点，消除逐条 `get` 的 N+1 |

缓存失效：`['change-requests', wid, tid]`、`['pending-changes', wid/tid]`、`['table-records', wid/tid]` 与行组详情。

### 7. 测试清单

**判定层（单测）**：分组归类（同 `row_id` 聚合 / `create` 归 `ungrouped` / 组内组间倒序）；冲突检测（同字段不同值 → conflict、同值 → 无冲突、delete 互斥 → `row_op_conflict`、漂移 → `drift_fields`）。

**接口层**：批量 merge 无冲突应用；带 `resolutions` 应用；`strategy=current` 保留；未裁决 409；原子性（一失败全 open）；权限 403；`stale` 传染。

**e2e（前端）**：`ChangeRequestsPage`（行组渲染 / 时间倒序 / 批量选择与按钮态 / 冲突跳转）、`ChangeRequestRowMergePage`（裁决表渲染 / 提交载荷 / 成功回跳）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **M1** | 列表契约扩展 + `group_by=row` + 冲突检测 + 批量 merge 端点（含测试） | 中 |
| **M2** | 前端列表分组视图 + 批量审批 | 中 |
| **M3** | 冲突处理页 | 中 |
| **M4** | `usePendingChanges` 收敛到聚合端点 + 文档同步 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 冲突策略 | 无冲突自动合并，冲突必须显式裁决 | 静默覆盖他人提交值不可追溯、不可申诉 | last-writer-wins（歧义且丢数据） | `services.py#merge_row_requests` |
| D2 | 列表契约形态 | 追加可选参 `group_by=row`，缺省保持扁平 | 旧前端零改动；`merged`/`closed` 仍需平铺留痕 | 直接改成分组响应（破坏兼容） | `routers/change_requests.py` |
| D3 | 批量语义 | 按申请逐项 apply + 冲突字段覆盖裁决，一次审批多份 | 与 git/PR 的 merge commit + 显式 conflict resolution 同构 | 行级整体覆盖（丢失申请粒度） | `services.py#merge_row_requests` |
| D4 | `create` 项归属 | 不参与行分组，归 `ungrouped` | 新行无 `row_id`，与既有行无冲突可比 | 伪造行 ID 归组（语义错误） | `services.py#list_requests` |
| D5 | 行级标识数据源 | `group_by=row` 一次返回行组 | 一次请求替代 N+1，服务端已完成冲突计算 | 保留前端逐条 `get`（随申请量线性退化） | `frontend/src/pages/grid/useGridData.ts` |
| D6 | 单申请端点 | 保留不动 | 详情页与旧调用方兼容 | 让行组端点取代单申请端点（无收益、破坏兼容） | `routers/change_requests.py#merge_request` |

## Consequences

- **正向**：同行变更一屏可见（含冲突标记）；批量审批替代逐份进详情；冲突在落库前被显式暴露，审计流水（`merge` 动作含批次备注）可追；行级标识请求数由 O(n) 降为 O(1)。
- **负向**：`list_requests(group_by=row)` 需为每组现算冲突，组数与 open 申请量同阶，scope 未收敛时有额外读放大；前端多一个页面与一套类型。
- **风险与缓解**：冲突字段判定依赖 `_normalize_values` 口径，字段类型校验变化会同步影响裁决合法性 → 判定与落库共用同一校验函数；`row_action` 为 delete 互斥新增的必填裁决项，旧客户端不会调用该端点，无兼容风险。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 谁能改这一行（写范围） | `row_access.py` + `tables_rowpermission` | 目标行在写范围内直编，可看不可改写为修改申请 | ADR 0004 |
| 多份申请如何合并落库 | `change_requests` 行组 + 批量 merge（本 ADR） | 冲突字段必须显式裁决，不静默覆盖 | ADR 0005 |
| 文档侧同类机制 | `documents_change_request` | 文档级申请按整篇 `proposed_content` 合并，无行分组 | ADR 0005（口径之外，独立实现） |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| M1 后端契约 + 分组 + 冲突检测 + 批量 merge | 已落地 | `src/cndb/plugins/change_requests/services.py`、`src/cndb/plugins/change_requests/routers/change_requests.py`、`src/cndb/plugins/change_requests/schemas.py` | `tests/test_change_requests_merge_view.py`、`tests/test_change_requests_api.py` | `22d5ed58` |
| M2 前端列表分组视图 + 批量审批 | 已落地 | `frontend/src/pages/changeRequests/ChangeRequestsPage.tsx`、`frontend/src/api/changeRequests.ts` | `frontend/src/pages/changeRequests/ChangeRequestsPage.test.tsx` | `22d5ed58` |
| M3 冲突处理页 | 已落地 | `frontend/src/pages/changeRequests/ChangeRequestRowMergePage.tsx` | `frontend/src/pages/changeRequests/ChangeRequestRowMergePage.test.tsx` | `22d5ed58` |
| M4 `usePendingChanges` 收敛 + 文档同步 | 进行中 | `frontend/src/pages/grid/useGridData.ts` | `frontend/src/pages/changeRequests/ChangeRequestsPage.test.tsx`（聚合端点本身尚无独立用例） | `22d5ed58` |

> M1-M3 有代码落点与专属测试文件；M4 的代码已上线（`usePendingChanges` 走 `listGrouped`），但缺一个直接断言「聚合端点替代 N+1」的前端用例，故标「进行中」，补测后转「已落地」。

## 交接（会话结束更新）

- 当前阶段：M1-M3 已落地；M4 代码已交付，待补聚合端点前端用例
- 已完成：后端分组与冲突检测、行组批量 merge、前端分组视图、冲突裁决页、`usePendingChanges` 聚合收敛（代码）
- 下一步：补 `usePendingChanges` 断言 `listGrouped` 被调用且不再逐条 `get` 的用例（`frontend/src/pages/grid/`），通过后把 M4 转「已落地」
- 已知坑：`create` 项不能进行组；冲突字段必须带 `resolutions`，否则 409；delete 互斥需 `row_action` 显式裁决；落库后同行其余 open 申请被置 `stale`，需 `update-base` 刷新
- 最近一次全绿：`make flow` 通过（2026-10-20，本地工作区）
