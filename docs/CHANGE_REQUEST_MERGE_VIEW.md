# 修改申请：「同行合并视图 + 批量审批 + 冲突处理」方案

> 状态：已实现（M1-M4 全部落地） · 日期：2026-10-19
> 范围：数据表修改申请（`src/cndb/plugins/change_requests/`、`frontend/src/pages/changeRequests/`）
> 关联：`docs/adr/0001-table-edit-approval-change-request.md`、`CONTEXT.md`「修改申请 / 双轨制写入」
> 实现对照：
> - 后端：[schemas.py](file:///workspace/src/cndb/plugins/change_requests/schemas.py)（`RowMergePayload`）、[services.py](file:///workspace/src/cndb/plugins/change_requests/services.py)（`detect_row_conflicts` / `_group_requests_by_row` / `merge_row_requests`）、[change_requests.py](file:///workspace/src/cndb/plugins/change_requests/routers/change_requests.py)（`group_by=row` + `POST .../rows/{row_id}/merge`）
> - 前端：[ChangeRequestsPage.tsx](file:///workspace/frontend/src/pages/changeRequests/ChangeRequestsPage.tsx)（同行合并视图 + 批量审批）、[ChangeRequestRowMergePage.tsx](file:///workspace/frontend/src/pages/changeRequests/ChangeRequestRowMergePage.tsx)（冲突处理页）、[useGridData.ts](file:///workspace/frontend/src/pages/grid/useGridData.ts)（`usePendingChanges` 走聚合端点）
> - 测试：`tests/test_change_requests_merge_view.py`、`frontend/src/pages/changeRequests/*.test.tsx`

---

## 1. 背景与现状

现有能力（以代码为准）：

- 列表页 [ChangeRequestsPage.tsx](file:///workspace/frontend/src/pages/changeRequests/ChangeRequestsPage.tsx)：扁平 `List`，scope 段控（`open/merged/all/mine`）；排序由后端 `ChangeRequest.id.desc()` 决定；仅展示 `conflicts_count`（与其他 open 申请共享的行数，已去重）。
- 详情页 [ChangeRequestDetailPage.tsx](file:///workspace/frontend/src/pages/changeRequests/ChangeRequestDetailPage.tsx)：单申请维度，逐 item `apply/skip` 后调 `POST /{id}/merge`；后端原子落库，任一校验失败整体 409 并保持 `open`（[services.py](file:///workspace/src/cndb/plugins/change_requests/services.py#L268-L342)）。
- 现有两类「冲突」信号：
  - `stale`：他人合并了同行后置位（行级，[`_mark_others_stale`](file:///workspace/src/cndb/plugins/change_requests/services.py#L491-L508)）；
  - `field_conflicts`：`current[field] != base[field]` 的字段级基准漂移，详情接口实时计算（[`get_request_detail`](file:///workspace/src/cndb/plugins/change_requests/services.py#L198-L247)）。
- 行级「编辑中标识」由 [usePendingChanges](file:///workspace/frontend/src/pages/grid/useGridData.ts#L54-L83) 实现：客户端先 `list(open)` 再逐条 `get` 详情（N+1），聚合 `row_id → 申请`。

问题：

1. 同一数据行的多个申请在列表中被拆散，无法一眼看清「这一行有哪些待审变更、是否互相打架」；
2. 审批者需逐个进入详情页逐项处理，同行多申请重复操作；
3. **尚无**「多个 open 申请对同一行同一字段写入不同值」的交汇冲突检测，也没有集中的冲突发现与解决入口。

---

## 2. 需求

| # | 需求 | 落点 |
|---|---|---|
| R1 | 合并查看同行数据申请 | 列表页按 `row_id` 聚合的「行组」视图 |
| R2 | 按时间倒序查看 | 组间按组内最新 `created_at` 倒序；组内按 `created_at` 倒序 |
| R3 | 同行允许合并审批多项 | 行组内多选 → 批量 merge（一次审批多份申请） |
| R4 | 提供冲突处理页面 | 行组冲突字段可视化 + 逐字段裁决后批量落库 |

---

## 3. 术语与冲突模型

- **同行（row）**：同一 `ChangeItem.row_id`。注意 `op=create` 的项 `row_id` 为空，**不参与按行分组**，归入「新增行申请」区。
- **三方（three-way）**：`base` = 申请 `base_values` 快照；`ours` = 行 `current_values`；`theirs` = 申请 `values`。
- 冲突分类：
  - **基准漂移（drift）**：`current[field] != base[field]`，即现有详情 `field_conflicts`（字段级）。
  - **交汇冲突（cross conflict）**：同一行、同一字段被 ≥2 个 open 申请写入且目标值不等；或 `delete` 与其他 `update`/`delete` 互斥（行级 op 冲突）。
  - **行缺失（row_missing）**：目标行已被删除。
- **行组冲突态**：`has_conflict`（存在交汇冲突或 delete 互斥）、`has_drift`（存在基准漂移）。

---

## 4. merge 工具最佳实践映射

参考 git / Pull Request 的合并模型，逐条落到本方案：

| merge / PR 概念 | 本方案对应 |
|---|---|
| three-way merge（base / ours / theirs） | `base_values` / `current_values` / `values` |
| fast-forward / auto-merge（无重叠自动合并） | 无冲突字段自动 apply（单一写者，或写入值一致） |
| conflict detection | 交汇冲突检测（同字段多写者不同值、delete 互斥） |
| conflict resolution（ours / theirs / manual） | 冲突处理页逐字段裁决：采用某申请值 / 保留当前值 |
| merge commit + 审计 | 批量 merge 向各申请写 `merge` 动作流水（含批次备注） |
| PR batch / squash merge | 行组内多申请一次性 merge |
| 合并使他人 base 失效 | 落库后同行其余 open 申请置 `stale`（复用 `_mark_others_stale`） |
| merge-base 复检（乐观并发） | 落库前 `_normalize_values` 预校验，失败整体 409 回滚 |
| 线性化应用顺序 | 非冲突项按 `created_at` 升序应用，`delete` 最后 |

核心策略：**无冲突自动合并，有冲突必须显式裁决**，绝不静默覆盖他人已提交的值。

---

## 5. 后端方案

### 5.1 列表契约扩展（向后兼容）

- `ChangeRequest` item 新增可选字段：`row_ids: number[]`（去重）、`fields: string[]`、`item_count: number`。
- `GET /{wid}/tables/{tid}/change-requests` 新增可选查询参 `group_by=row`：
  - 缺省（不传）：维持扁平 `items`，**旧契约不变**；
  - `group_by=row`：返回分组结构（见 5.2）。

### 5.2 分组响应

```json
{
  "groups": [
    {
      "row_id": 12,
      "row_values": {"名称": "甲", "数量": 1},
      "row_missing": false,
      "requests": [
        {"id": 51, "title": "修改行 #12", "created_at": "2026-10-19T09:00:00",
         "stale": false, "row_ids": [12], "fields": ["数量"], "item_count": 1}
      ],
      "conflict_fields": ["数量"],
      "drift_fields": ["名称"],
      "has_conflict": true,
      "has_drift": true,
      "latest_created_at": "2026-10-19T09:00:00"
    }
  ],
  "ungrouped": [{"id": 60, "title": "新增行", "row_ids": []}],
  "total": 5,
  "write_mode": "change_request"
}
```

排序：`groups` 按 `latest_created_at` 倒序；组内 `requests` 按 `created_at` 倒序。

### 5.3 批量合并端点

```
POST /{wid}/tables/{tid}/change-requests/rows/{row_id}/merge

{
  "request_ids": [51, 53],
  "resolutions": {
    "数量": {"strategy": "item", "item_id": 120},
    "名称": {"strategy": "current"}
  },
  "comment": "批量批准"
}

→ 200 {
  "applied": 2, "skipped": 0,
  "merged_request_ids": [51, 53],
  "requests": [ { ...ChangeRequestDetail } ]
}
```

语义：

- 权限：仅 owner/editor（复用 `_require_reviewer`）。
- 校验：所有 `request_ids` 必须为 `open` 且**均引用 `row_id`**（含 create 项的申请一律 400）；否则 409。
- 应用：按 `created_at` 升序对每份申请的 items apply；`delete` 最后。
- 冲突字段必须由 `resolutions` 显式裁决，**缺省 → 409**（避免隐式覆盖）；`strategy=current` 跳过写入该字段，`strategy=item` 采用指定 item 的值。
- 原子性：任一 `_normalize_values` 失败 → 整体 409 回滚，全部保持 `open`。
- 成功：各申请置 `merged` 并写 `merge` 动作流水；复用 `_mark_others_stale`。
- 详情页原 `POST /{request_id}/merge` **保留不动**（单申请兼容）。

### 5.4 冲突检测服务

在 `services.py`（或新增 `conflicts.py`）实现：

- `detect_row_conflicts(db, table, row_id, *, open_items) -> dict`
  - 输入：该行全部 open 申请的 items；
  - 输出：`fields`（字段 → 各写者 `(request_id, item_id, value)`）、`conflict_fields`（同字段多写者值不等）、`row_op_conflict`（delete 互斥）、`drift_fields`、`row_missing`。
- 复用 `rec.get_row`、`_normalize_values`；`create` 项排除。

### 5.5 行级聚合（替换前端 N+1）

`group_by=row` 一次返回 `row_id → 行组`，覆盖 [usePendingChanges](file:///workspace/frontend/src/pages/grid/useGridData.ts#L61-L82) 的需求，消除逐条 `get` 详情的 N+1。

---

## 6. 前端方案

### 6.1 列表页（`ChangeRequestsPage.tsx`）

- 视图切换（`Segmented`）：**同行合并（默认）** / 平铺。
- 同行合并视图：
  - 行组卡片：标题 = 行标识（`#{row_id}` + 主字段/首列值）；右侧徽标 = 申请数、`冲突`、`基准漂移`。
  - 组内申请按 `created_at` 倒序；复用现有标题 + 提交人 + 时间 + `stale` / `conflicts_count` 标记。
  - 组排序按 `latest_created_at` 倒序（R2）。
  - reviewer 可见复选框 + 「批量审批」按钮：无冲突 → 确认后直接批量 merge；有冲突 → 跳转冲突处理页（6.2）。
  - `ungrouped`（新增行申请）单列一区。
- 保留 scope 段控与 `write_mode` 横幅；`merged` / `closed` 视图维持平铺（历史留痕）。
- 查询：`useQuery(['change-requests', wid, tid, scope, 'row'])`，走 `group_by=row`。

### 6.2 冲突处理页（新增）

- 路由：`/w/:wid/tables/:tid/change-requests/rows/:rowId/merge`（在 `App.tsx` 注册）。
- 布局：
  1. 行摘要：当前值表（ours）；
  2. 待合并申请列表（theirs）：每份申请的 items 摘要；
  3. 冲突字段裁决表：`字段 | 当前值 | 各申请目标值 | 选择`（radio：采用第 N 份 / 保留当前值）；
  4. 非冲突字段只读汇总（auto-merge 预览）；
  5. 备注 + 「执行批量合并」。
- 快捷操作：全部采用最新提交 / 全部保留当前。
- 提交调 5.3 端点；成功后回列表并失效相关缓存。

### 6.3 API 与类型

- `api/changeRequests.ts` 新增：`listGrouped(wid, tid, scope)`、`mergeRow(wid, tid, rowId, payload)`。
- `api/types/change-requests.ts` 新增：`ChangeRowGroup`、`CRRowMergePayload`、`CRConflictField`、`CRResolution`。

### 6.4 缓存失效

批量 merge 后失效：`['change-requests', wid, tid]`、`['pending-changes', ${wid}/${tid}]`、`['table-records', ${wid}/${tid}]`、行组详情。

---

## 7. 边界与错误处理

| 场景 | 处理 |
|---|---|
| 选中申请含 `create` 项（无 `row_id`） | 行组端点拒绝（400） |
| 冲突字段未裁决 | 409，提示「请先处理冲突字段」 |
| 行在批量 merge 期间被删 | 行级冲突，需显式选择「执行删除 / 保留」 |
| 落库校验失败 | 整体 409 回滚，全部保持 `open` |
| 申请非 `open` | 409 |
| 非 reviewer | 403 |

---

## 8. 测试计划（TDD）

后端（新增 `tests/test_change_requests_merge_view.py`，并扩充 `tests/test_change_requests_api.py`）：

- 分组：同一 `row_id` 多申请聚为一组；`create` 归 `ungrouped`；组内/组间时间倒序。
- 冲突检测：同字段不同值 → `conflict`；同值 → 无冲突；`delete` 互斥 → `row_op_conflict`；漂移 → `drift_fields`。
- 批量 merge：无冲突应用；带 `resolutions` 应用；`strategy=current` 保留；未裁决 409；原子性（一失败全 open）；权限 403；`stale` 传染。

前端（vitest）：

- `ChangeRequestsPage`：行组渲染、时间倒序、批量选择与按钮态、冲突跳转。
- 冲突处理页：裁决表渲染、提交载荷、成功后回跳。
- `usePendingChanges` 改走聚合端点（若采用 5.5）。

---

## 9. 兼容与迁移

- 列表旧响应字段不变，新增字段为可选，旧前端不受影响。
- 单申请 merge 端点保留，详情页不受影响。
- `usePendingChanges` 切换到聚合端点前保持兼容（先并存后收敛）。

---

## 10. 里程碑

- **M1 后端**：列表契约扩展 + `group_by=row` + 冲突检测 + 批量 merge（含测试）。
- **M2 前端列表**：分组视图 + 批量审批。
- **M3 冲突处理页**。
- **M4 收尾**：`usePendingChanges` 收敛、文档（`CONTEXT.md` / `docs/adr`）更新。

---

## 11. 风险与取舍

- **隐式覆盖 vs 显式裁决**：采用「无冲突自动、冲突必须显式」策略，宁多一步也不静默覆盖他人值。
- **批量语义**：跨多申请时明确「按申请逐项 + 冲突字段覆盖裁决」，不做隐式 last-writer-wins（避免歧义）。
- **create 无行归属**：只能按申请维度批量，不做行分组。
- **性能**：分组在服务端一次完成，替换前端 N+1；行组规模受 scope 限制，可控。
