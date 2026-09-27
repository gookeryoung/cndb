# 表/页面切换加载态与过渡设计

来源需求：切换数据表或页面时出现短暂不正常页面状态（旧表行配新表列、空态闪现、纯文字加载页跳动）。本文件记录消除异常状态与切换过渡的落地设计。

## 问题清单

1. 切表时 `useTableRecords` 无 placeholderData：请求期间行数据为空，旧表行已清空而新表列未到，出现"空表/空态闪现"；或缓存残留旧表行配新表列。
2. `GridTableSection` 的 `isLoading` 只接收表元数据（`useTable`）的加载态，行数据加载不遮罩，行未到时闪现「这张表还没有数据」空态。
3. `GridPage` 主内容区加载占位为纯文字，页面级 `PageFallback` 为 50vh 居中文字（且硬编码 `#9ca3af`），切换时高度跳变。
4. `GridPage` 内部局部状态（列宽预览等）跨表残留一帧。
5. 页面/视图硬切无过渡，感知突兀。
6. 侧边栏点击切表后才发起表详情请求，冷启动白屏时间长。

## 接口定义

### useTableRecords（[api/hooks.ts](f:/Dev/cndb/frontend/src/api/hooks.ts)）

- 签名不变：`useTableRecords(wid, tid, mode, params)`。
- 新增 `placeholderData` 回调（React Query v5 双参形式）：
  `(prev, prevQuery) => prevQuery?.queryKey[1] === tableKey ? prev : undefined`
  - `queryKey[1]` 即 `${wid}/${tid}`（tableKey）。
  - 同表（翻页 / 改筛选 / 改排序 / 切 mode / 切视图）保留上一份行数据，请求中 `isFetching=true`。
  - 跨表（tableKey 变化）返回 `undefined`，走正常 loading，杜绝旧表行配新表列。
- 返回值透传 `isFetching`。

### useGridData（[useGridData.ts](f:/Dev/cndb/frontend/src/pages/grid/useGridData.ts)）

- 返回值新增 `isFetching`（来自 `useTableRecords`），其余字段不变。

### GridPage

- `GridTableSection` 的 `isLoading` prop 改传行数据加载态：`isFetching`（表元数据加载态只用于主内容骨架屏判断）。
- 主内容容器（`gridAreaRef` 所在 div）加 `key={tableKey}`：切表整块重挂载，清空内部局部状态。
- 主内容加载分支：表元数据 `isLoading` 时渲染表形状骨架（`TableSkeleton`，本地组件），替换纯文字。
- `TableSkeleton` 列数对齐：组件接收可选 `columnCount`（估计列数，`columnCount || 6` 兜底）；GridPage 以 ref 记录最近一次已加载表的可见字段数（`hidden` 不计入，useEffect 随 `gridFields` 同步），切表元数据未到时骨架按该参考渲染，冷启动无参考退化 6 列。
- `ViewFallback`：由居中文字改为与主内容同形状的占位（flex:1 + 骨架条）。
- 挂载后空闲预取四个非 grid 视图 chunk（`requestIdleCallback`，不支持时 `setTimeout` 退化，卸载时取消）。

### MainLayout / TablesList hover 预取

- 新增 `prefetchTable(tid)`：`queryClient.prefetchQuery({ queryKey: ['table', \`${wid}/${tid}\`], queryFn: () => tableApi.get(wid, tid), staleTime: 60_000 })`，与 `useTable` 的 queryKey 一致。
- MainLayout 侧边栏 Menu item label 包 `span onMouseEnter` 触发；TablesList 用 `Table onRow.onMouseEnter` 触发。

## 数据模型

无后端改动，无 schema 迁移。仅前端行为约定：

| 查询 | staleTime（main.tsx 既有） | placeholderData |
| --- | --- | --- |
| `['table', tableKey]` | 60s | 无 |
| `['table-records', tableKey, ...]` | 10s | 同 tableKey 保留上一份 |

## 算法与流程

- 切表时序：URL 变化 → `useTable`/`useTableRecords` 新 tableKey 查询启动 → `placeholderData` 判定 tableKey 不同返回 undefined → 主内容渲染骨架（元数据未到）或 spinner（行未到）→ 数据到达渲染。
- 同表翻页/筛选时序：queryKey 变化 → placeholderData 返回上一份数据立即渲染 → 后台请求 → `isFetching` 驱动 Table loading 遮罩 → 数据到达刷新。
- 动画触发：`MainLayout` 的 `Content` 以 `location.pathname` 为 key 并挂 `cn-page-enter`，路由切换（含切表）整块重挂载重放淡入；同表切视图（query 参数变化）不重挂载，视图组件切换由 GridPage 内部条件渲染自然完成。
- 视图 chunk 预取：GridPage 挂载后 `requestIdleCallback` 内 `void import('./views/KanbanView')` 等（bundler 对动态 import 有缓存，已加载时为 no-op）。

## 异常处理

- `requestIdleCallback` 不存在（Safari 旧版 / jsdom）：退化为 `setTimeout(cb, 200)`；卸载时 `cancelIdleCallback` / `clearTimeout` 对应清理。
- `prefers-reduced-motion: reduce`：`cn-page-enter` 动画禁用（加入 index.css 既有 reduce 块）。
- 预取失败静默（prefetchQuery 内部吞错），不弹提示。
- 视图 store 的旧表状态残留由「主内容 key 重挂载 + placeholderData 跨表判空」双保险兜底。

## 样式约束

- 新增 `@keyframes cn-page-enter`（opacity 0→1，180ms ease-out）与 `.cn-page-enter` 类，颜色一律 `var(--cn-*)` token，禁止硬编码。
- 骨架占位色用 `var(--cn-border)` / `var(--cn-bg-page)` 等既有 token。

## 验收标准

- [x] 同表翻页/筛选/切视图时行数据无清空闪现，Table 出现 loading 遮罩。
- [x] 切表时旧行数据不出现在新表列下（placeholderData 跨表判空）。
- [x] 主内容区、PageFallback、ViewFallback 均为骨架/同形状占位，无高度跳动，无硬编码颜色。
- [x] 切表时主内容整块重挂载（局部状态清零）。
- [x] 路由切换有淡入过渡，reduce-motion 下禁用。
- [x] 侧边栏/表列表 hover 预取表详情；进入 GridPage 后空闲预取视图 chunk。
- [x] 配套测试：placeholderData 同表保留/跨表清空两分支。
- [x] make check 全绿。
