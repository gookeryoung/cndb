# Bug: 切换到【按片区看板】【进行中看板】明显卡顿

> Status: FIXED
> Mode: (default)
> Severity: functional
> Author: user
> Last updated: 2026-10-07

## Symptom

某企业销售管理工作区「产品开发」表（500 行）切换到【按片区看板】【进行中看板】看板视图时明显卡顿。

## Expected

切换视图流畅渲染，主线程无明显长任务。

## Reproduction

- 命令 / 步骤：seed 后进入产品开发表，切换到任一看板视图（按片区看板分组后单列约 60-90 行）
- 测试位置：`frontend/src/pages/grid/views/KanbanView.test.tsx`（KanbanView 大数据量渲染性能）
- 复现稳定性：确定性（非时序），单次即稳定复现

## Hypotheses & diagnosis

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | 看板根容器无高度约束（仅 minHeight:300），列随内容生长 → 列内 overflowY 永不滚动、useVirtualizer 视口测量失效；叠加虚拟化阈值 100，单列 60-90 行全部走非虚拟分支全量挂载 | confirmed (root cause) | 代码核对：KanbanView 根容器 style vs GanttView/WbsView 根 `height: '100%'`；failing test 90 行单列挂载 90 张卡片（≥50 阈值断言 RED） |
| H2 | GridPage useCallback 依赖 useMutation 结果对象（每渲染新引用）→ KanbanCard memo 失效，每次重渲染全量重渲染所有卡片 | confirmed (放大器) | 代码核对：deps `[deleteRows, message]` / `[updateRow]`，useMutation 结果对象每渲染都是新对象 |

## Root cause

KanbanView 根容器缺少高度约束，`useVirtualizer` 依赖的列内滚动容器永不产生有效视口（视口=全量内容），而虚拟化阈值 100 又使真实数据分组后的列（60-90 行 < 100）全部走非虚拟分支；切换视图时同步全量挂载 500 张重型 antd 卡片（Tag/Tooltip/Progress），形成主线程长任务。GridPage 回调依赖不稳定使 memo 失效，进一步放大后续重渲染成本。

## Fix

- 改动文件：`frontend/src/pages/grid/views/KanbanView.tsx:736-748`（根容器 `flex: 1, minHeight: 300`）、`KanbanView.tsx:529-531`（阈值 100 → 30）、`KanbanView.tsx:618-621`（卡片列表 `minHeight: 0`）、`frontend/src/pages/grid/GridPage.tsx:446-457`（deps 改用 `deleteRows.mutate` / `updateRow.mutate`）
- 一句话改了什么：给看板高度约束使列内虚拟滚动生效 + 降低虚拟化阈值 + 回调引用稳定化

## Verification

- V-1: failing test（90 行单列）→ GREEN ✓（`pnpm vitest run KanbanView.test.tsx` 25 例全过）
- V-2: stash fix → test 重新 RED ✓（1 failed）；stash pop 恢复后 GREEN ✓
- V-3: grid 模块全部测试 31 文件 536 例 → all GREEN ✓
- V-4: `make check` → exit=0 ✓（后端 pytest + 前端 vitest 全量 86 文件 + 覆盖率双门槛 + lint）

## Regression test

- 路径：`frontend/src/pages/grid/views/KanbanView.test.tsx`（KanbanView 大数据量渲染性能）
- 名称：单列行数超过虚拟化阈值时启用虚拟滚动，不全量挂载所有卡片

## Pattern analysis

| 搜索方式 | 命中数 | 是否本次同类隐患 |
|---|---|---|
| `useCallback` deps 引用 mutation 结果对象（GridPage.tsx 全量） | 0（本次 2 处已修） | 否 |
| 视图组件根容器高度约束（GanttView/WbsView 均已 `height: '100%'`） | 0 | 否（仅 KanbanView 缺失，已修） |

## Open questions / Follow-ups

- make check 全量并发下偶发 EnvironmentTeardownError（matrixBoard.ts 在环境拆卸后完成动态加载，源自 GridPage.newRow.test.tsx 的 idle 预取），基线与本轮改动各跑多次仅偶发一次，与本修复无关；根治需给预取加卸载守卫，作为独立事项处理。
