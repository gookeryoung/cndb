# 前端库引入评估与设计方案

> Status: DRAFT
> Author: AI
> Last updated: 2026-09-18

## Background

项目 `cndb` 前端（`frontend/`）基于 React 18.3.1 + TypeScript + Vite + Ant Design 5。当前已引入 `@tanstack/react-query` 和 `zustand`，但 `zustand` 实际未使用。用户提出评估以下五个库是否能进一步提升设计健壮性和性能：

1. `react-window` / `@tanstack/react-virtual` — 列表虚拟化
2. `@tanstack/react-query` — 服务端状态管理
3. `zustand` — 客户端状态管理
4. `react-hook-form` — 表单管理
5. React Compiler（React 19）— 编译器级渲染优化

本文档逐项评估现状、收益、成本与优先级，供用户决策。

## 现状速览

| 维度 | 现状 | 痛点 |
|------|------|------|
| 网格视图 | AntD Table + 服务端分页（offset/limit） | 已有分页，虚拟化收益有限 |
| 非网格视图（看板/画廊/日历/甘特/WBS） | 全量拉取（上限 5000 行）后 `.map()` 全量渲染 DOM | 大数据量下渲染卡顿、内存占用高 |
| 数据获取 | `@tanstack/react-query` v5，已广泛使用 | 缺乐观更新、缺 query 自定义 hooks、缺预取 |
| 客户端状态 | React Context（Auth、TableSettings）+ 大量 `useState` | GridPage 单组件 20+ useState，状态管理臃肿 |
| 表单 | AntD Form（13 处）+ 部分手动 useState（RowDetailDrawer、CreateEditViewForm） | AntD Form 已够用；手动表单缺统一校验 |
| React 版本 | 18.3.1 | React Compiler 需升级到 19 |

---

## 1. react-window / @tanstack/react-virtual

### 现状

- **网格视图（Grid）**：使用 AntD Table + 服务端分页，默认每页 25/50/100/200 行。已有分页机制，单页 DOM 节点可控，虚拟化收益有限。
- **非网格视图**：在 `GridPage.tsx` 第 341-343 行，非 grid 模式强制 `VIEW_FETCH_ALL_LIMIT = 5000`，一次性拉取全部数据：
  - `KanbanView.tsx` 第 610-612 行：`col.rows.map()` 渲染所有卡片，无虚拟化
  - `GalleryView.tsx` 第 77 行：`rows.map()` 渲染所有卡片，无虚拟化
  - `CalendarView.tsx`、`GanttView.tsx`、`WbsView.tsx` 同理全量渲染
- 后端已有 10k 行基准测试脚本（`scripts/bench_10k_rows.py`），说明大数据量是真实场景。

### 收益

- **看板/画廊视图**：当表有 1000+ 行时，DOM 节点数从 N 降到约 50-100，首屏渲染从数百 ms 降到 <50ms，滚动帧率从 ~30fps 提升到 60fps。
- **内存**：5000 行卡片每个含 5-10 个子元素，DOM 内存从 ~50MB 降到 ~5MB。
- **交互响应**：拖拽看板卡片、点击卡片不再因全量重渲染卡顿。

### 方案

**推荐 `@tanstack/react-virtual`**（而非 `react-window`）：

| 对比项 | react-window | @tanstack/react-virtual |
|--------|-------------|------------------------|
| API 风格 | 组件式（FixedSizeList 等） | Hook 式（useVirtualizer） |
| 灵活性 | 预定义列表/网格组件 | 完全自定义渲染容器和元素 |
| 动态高度 | 支持但 API 较繁琐 | 原生支持 `estimateSize` + 动态测量 |
| 维护状态 | 维护中，更新较慢 | TanStack 团队活跃维护 |
| 与现有代码集成 | 需包裹固定尺寸容器 | 可直接在现有 flex/grid 容器内用 |

**实施要点**：

1. **看板列虚拟化**：每列卡片列表用 `useVirtualizer({ count: col.rows.length, getScrollElement, estimateSize })`，渲染可视区域的卡片。
2. **画廊虚拟化**：用 `useVirtualizer` 配合 `Row`/`Col`，或用 CSS `grid` + `transform: translateY` 定位可视行。
3. **网格视图（可选）**：AntD Table 5.x 支持 `virtual` 属性（需 `scroll={{ y }}`），可直接开启，无需引入额外库。
4. **日历/甘特/WBS**：这些视图有复杂布局（时间轴、层级结构），虚拟化难度高，优先级低。

### 成本与风险

- 改造成本：看板 + 画廊约 2-3 天。
- 风险：动态卡片高度需正确估计，否则滚动条跳动；需处理卡片内异步内容（图片加载）导致的高度重算。
- 降级：虚拟化失败时回退到全量渲染，不影响功能正确性。

### 优先级：**高**（看板/画廊） / 中（网格） / 低（日历/甘特/WBS）

---

## 2. @tanstack/react-query

### 现状

已安装 v5.103.0 并广泛使用（GridPage、RowDetailDrawer、各页面）。用法整体规范：

- queryKey 包含参数，缓存粒度合理
- mutations 通过 `invalidateQueries` 触发刷新
- `enabled` 控制条件拉取

但存在以下可改进点：

1. **缺乐观更新（Optimistic Updates）**：`updateRow`、`deleteRows` 等 mutation 完成后才刷新，用户需等待。
2. **缺自定义 Query Hooks**：所有 `useQuery` 内联在组件中，无复用层，跨组件相同数据重复定义 key。
3. **缺预取（Prefetching）**：切换视图/翻页时无预取，每次切换都有 loading 空白。
4. **缓存策略粗粒度**：全局 `staleTime: 30s`，未针对不同数据类型差异化（如用户偏好可 60s，表格数据可 10s）。

### 收益

- **乐观更新**：inline 编辑单元格即时反映，无需等 API 返回，体验接近本地应用。
- **自定义 Hooks**：`useTable(wid, tid)`、`useTableRecords(...)` 等，减少重复、统一错误处理。
- **预取**：翻页/视图切换无 loading 闪烁。
- **差异化缓存**：减少不必要的网络请求，提升响应速度。

### 方案

1. **抽取查询 Hooks**（`frontend/src/api/hooks/`）：
   ```ts
   // useTable.ts
   export function useTable(wid: string, tid: string) {
     return useQuery({
       queryKey: ['table', `${wid}/${tid}`],
       queryFn: () => tableApi.get(wid, tid),
       enabled: !!wid && !!tid,
     })
   }
   ```
2. **乐观更新**：对 `updateRow` mutation，在 `onMutate` 中直接修改 query cache 中的行数据，失败时回滚。
3. **预取**：在视图 Tab hover 时 `queryClient.prefetchQuery` 预取下一视图数据。
4. **差异化 staleTime**：按 queryKey 前缀设置不同 `staleTime`。

### 成本与风险

- 改造成本：约 1-2 天（抽 hooks + 乐观更新）。
- 风险：乐观更新需处理回滚逻辑，复杂 mutation（批量操作）需谨慎。
- 收益立竿见影，风险可控。

### 优先级：**高**

---

## 3. zustand

### 现状

- `package.json` 已声明 `zustand: ^5.0.15`，但 `src/` 中**零引用**（grep 无匹配）。
- 当前状态管理：
  - **AuthContext**（`auth/AuthContext.tsx`）：user/token/loading/login/logout，用 React Context。
  - **TableSettingsProvider**（`theme/TableSettingsProvider.tsx`）：表格显示设置，用 React Context。
  - **GridPage**：单组件内 20+ `useState`，视图配置、筛选、排序、分页、对话框开关全堆在一起，约 1000 行。

### 收益

1. **替代 Context**：AuthContext 和 TableSettingsProvider 用 zustand 后，避免"任何 state 变化导致所有消费者重渲染"的问题。当前 Context value 是整对象，`settings` 一变所有 `useTableSettings()` 消费者全重渲染。
2. **拆分 GridPage 状态**：将 GridPage 的视图状态（filters/sortings/activeViewId/mode 等）抽到 zustand store，组件体积大幅缩减，状态变更可被精确订阅。
3. **跨组件共享**：视图状态可被 RowDetailDrawer、ViewConfigDialog 等子组件直接读写，减少 props  drilling。

### 方案

1. **Auth Store**（替代 AuthContext）：
   ```ts
   // store/auth.ts
   import { create } from 'zustand'
   interface AuthState { user, token, loading, login, logout, refresh }
   export const useAuthStore = create<AuthState>((set) => ({ ... }))
   ```
2. **TableSettings Store**（替代 TableSettingsProvider）：
   ```ts
   // store/tableSettings.ts
   export const useTableSettingsStore = create<TableSettingsState>(...)
   ```
3. **GridView Store**（拆分 GridPage 状态）：
   ```ts
   // store/gridView.ts
   interface GridViewState {
     activeViewId, viewFilters, viewSortings, viewFilterLogic,
     viewOptionsDraft, mode, offset, limit, searchQuery, ...
     setViewFilters, addFilter, removeFilter, setSortings, ...
   }
   ```
4. **渐进迁移**：先迁移 TableSettings（最简单），再迁移 Auth，最后拆分 GridPage。

### 成本与风险

- 改造成本：TableSettings 0.5 天，Auth 0.5 天，GridPage 拆分 2-3 天。
- 风险：GridPage 状态拆分需谨慎，视图自动保存的 debounce 逻辑依赖 state 变化，迁移后需保证行为一致。
- 已有依赖，无新增包体积。

### 优先级：**中**（Context 替换） / 高（GridPage 拆分，与性能强相关）

---

## 4. react-hook-form

### 现状

- 13 个文件使用 AntD `Form` 组件，走 AntD 的受控表单模式（`onFinish` + `rules` 校验）。
- 2 处手动管理状态：
  - `RowDetailDrawer.tsx`：`useState<Record<string, unknown>>` 存所有字段值，手动 `setValues`。
  - `CreateEditViewForm.tsx`：`useState` 管理 name/vt/opts，手动禁用按钮。
- AntD Form 已提供：字段注册、校验规则、错误展示、提交回调、数据回填。

### 收益评估

- **react-hook-form 的核心优势**：非受控（minimal re-render）、Headless、性能好。
- **但项目已深度使用 AntD Form**：AntD Form 内部有自己的字段状态管理，与 react-hook-form 的非受控哲学冲突。强行集成需用 `Controller` 包裹每个 AntD 控件，反而增加复杂度。
- 手动表单（RowDetailDrawer、CreateEditViewForm）改用 AntD Form 即可获得校验能力，无需引入 react-hook-form。

### 结论

**不建议引入 react-hook-form**。理由：

1. AntD Form 已满足 90% 表单需求，且与 AntD 控件深度集成。
2. react-hook-form + AntD 需用 `Controller` 包裹，代码量增加，性能优势被抵消。
3. 真正的痛点是 RowDetailDrawer/CreateEditViewForm 没用 AntD Form，迁移到 AntD Form 即可（零新增依赖）。
4. 项目无 Headless UI 需求，react-hook-form 的 Headless 优势无法体现。

### 优先级：**不引入**（建议将手动表单迁移到 AntD Form）

---

## 5. React Compiler（React 19）

### 现状

- React 版本 `18.3.1`，React Compiler 需 React 19。
- 代码中已有大量手动优化：`useMemo`、`useCallback`、`React.memo`。
- GridPage 有大量 `useMemo`（columns、aggregates、effectiveFilters 等），是 React Compiler 的典型受益场景。

### 收益

- **消除手动 memo**：React Compiler 自动优化渲染，可删除大部分 `useMemo`/`useCallback`/`React.memo`，代码更简洁。
- **性能提升**：自动精细控制重渲染范围，比手动 memo 更准确。
- **减少心智负担**：开发者无需考虑 memo 依赖数组。

### 方案

React Compiler 不能单独引入，必须先升级到 React 19。升级路径：

1. **升级 React 19**：
   - `react`、`react-dom` → `^19.0.0`
   - `@types/react`、`@types/react-dom` → `^19.0.0`
   - 检查 AntD 5 是否兼容 React 19（AntD 5.13+ 支持）
   - 检查 `@xyflow/react`、`@dnd-kit/*`、`@tanstack/react-query` 是否兼容
2. **引入 React Compiler**：
   - 安装 `babel-plugin-react-compiler`
   - Vite 配置中启用
3. **验证**：运行 E2E 测试确保行为不变。

### 成本与风险

- 改造成本：React 19 升级 1-2 天，React Compiler 配置 0.5 天，回归测试 1 天。
- 风险：
  - React 19 破坏性变更（如 `use` hook、ref 转发变更）需逐一适配。
  - 第三方库兼容性需逐一验证。
  - React Compiler 仍在演进，生产环境稳定性需评估。
- 收益是长期的，但短期风险较高。

### 优先级：**低**（需先完成 React 19 升级，建议作为独立迭代）

---

## 综合推荐方案

按 ROI（收益/成本）排序，建议分三阶段实施：

### 阶段一：高 ROI，立即可做（约 3-5 天）

| 库/方案 | 动作 | 预期收益 |
|---------|------|---------|
| `@tanstack/react-virtual` | 看板/画廊视图虚拟化 | 大数据量渲染性能提升 10x |
| `@tanstack/react-query` | 抽取自定义 hooks + 乐观更新 + 预取 | 编辑响应速度提升，减少 loading |
| AntD Table `virtual` | 网格视图开启虚拟滚动（`scroll={{ y }}`） | 大分页（200行）下流畅滚动 |
| 手动表单 → AntD Form | RowDetailDrawer、CreateEditViewForm 改用 AntD Form | 统一校验，零新增依赖 |

### 阶段二：中 ROI，状态管理优化（约 3-4 天）

| 库/方案 | 动作 | 预期收益 |
|---------|------|---------|
| `zustand` | 替换 TableSettingsProvider、AuthContext | 减少 Context 全量重渲染 |
| `zustand` | 拆分 GridPage 视图状态到 store | GridPage 组件瘦身，可维护性提升 |

### 阶段三：长期演进，独立迭代（约 3-5 天）

| 库/方案 | 动作 | 预期收益 |
|---------|------|---------|
| React 19 + React Compiler | 升级 React 19，启用 Compiler | 消除手动 memo，代码简化 |

### 不建议引入

- **react-hook-form**：与 AntD Form 冲突，收益低。

---

## 决策点

请用户确认以下决策：

1. **是否启动阶段一**？（虚拟化 + react-query 优化 + AntD 表单迁移）
2. **GridPage 状态拆分是否纳入阶段二**？（影响 zustand 的使用范围）
3. **React 19 升级是否排期**？（建议独立迭代，不与上述改动并行）
4. **虚拟化范围**：仅看板/画廊，还是也覆盖网格视图？

## 验收标准

- 看板/画廊视图在 5000 行数据下首屏渲染 < 100ms，滚动 60fps。
- inline 编辑单元格无感知延迟（乐观更新生效）。
- `make check`（lint + typecheck + cov）全绿。
- E2E 测试全通过（`frontend/tests/e2e/`）。
