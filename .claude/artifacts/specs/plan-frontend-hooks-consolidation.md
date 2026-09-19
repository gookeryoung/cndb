# 前端共性 Hooks 统一治理计划

## 一、背景与必要性分析

### 现状盘点（探索结论）

| Hooks 资产 | 位置 | 定性 |
|---|---|---|
| `useResponsive`（+ 测试） | `frontend/src/hooks/useResponsive.ts` | 通用 hook，已在规范位置 |
| 8 个 React Query 领域 hooks | `frontend/src/api/hooks.ts` | 领域数据请求 hooks，与 API 层共置合理 |
| `useNewRowAutoScroll`（+ 测试） | `frontend/src/pages/grid/useNewRowAutoScroll.ts` | rc-table 虚拟滚动专用，强耦合 GridPage |
| `useTableFlexFillStyle`（私有内联） | `frontend/src/pages/modals/FileImportPreview.tsx#L28` | 单次使用的私有样式注入 |
| zustand store hooks / `useTheme` | `src/store/`、`src/theme/` | 状态与主题共置，职责合理 |

### 确认存在的重复共性模式

1. **防抖（debounce）— 3 处独立手写实现**（达到抽象门槛）
   - `components/report-editor/PreviewPanel.tsx#L66-71`：300ms 防抖渲染结果（值防抖）
   - `pages/grid/GridPage.tsx#L733-738`：500ms 防抖自动保存视图配置（回调防抖）
   - `hooks/useResponsive.ts#L57-70`：100ms 防抖 resize 回调（回调防抖）
2. **容器尺寸测量（ResizeObserver + window resize 双通道）— 2 处**（达到抽象门槛）
   - `pages/grid/GridPage.tsx#L215-224`：`gridAreaSize`（初值 `{h:400, w:800}`）
   - `hooks/useResponsive.ts`：window 尺寸监听（同族模式）

### 评估后不抽取的单处模式（YAGNI，本次不动）

- 轮询 `setInterval`（`ImportExportDialog.tsx#L96-130`，仅 1 处；改造为 React Query `refetchInterval` 属另议）
- 剪贴板复制（`GridPage.tsx#L750`，仅 1 处）
- 自定义 DOM 事件监听（`ReportsPage.tsx#L362-374`，仅 1 处）
- localStorage 安全读写（多为模块级工具函数而非 hook 场景）

### 决策（已经用户确认）

1. **不引入 ahooks**：项目数据请求已由 React Query 承担，与 ahooks `useRequest` 职责重叠；当前真实需求仅 2~3 个小 hook，自研约 80 行零依赖代码即可覆盖。若未来通用 hook 需求增长（≥5 个且含复杂场景）再评估按需引入。
2. **src/hooks 只收领域无关的通用 hooks**：`api/hooks.ts` 留在 api 层、`useNewRowAutoScroll` 留在 grid 页、`useTheme` 留在 theme 层，不强迁。

## 二、改动方案

### 1. 新增 `frontend/src/hooks/useDebouncedValue.ts`

- 签名：`useDebouncedValue<T>(value: T, delayMs: number): T`
- 语义：值变化后 `delayMs` 内无新变化才更新返回值；依赖变更/组件卸载时 `clearTimeout` 清理
- 实现：`useState` + `useEffect`（约 20 行），中文 JSDoc
- 消费点：`PreviewPanel.tsx#L66-71` 整段替换为 `const debouncedResult = useDebouncedValue(result, 300)`

### 2. 新增 `frontend/src/hooks/useDebouncedCallback.ts`

- 签名：`useDebouncedCallback<F extends (...args: never[]) => void>(fn: F, delayMs: number): (...args: Parameters<F>) => void`
- 语义：内部用 `ref` 保存最新回调（调用点无需 `useCallback` 包裹）；返回的防抖函数在依赖变更/组件卸载时取消未执行的 pending 调用（与 GridPage 原实现 `clearTimeout` 语义一致）
- 消费点：
  - `GridPage.tsx#L732-738`：改为 `const debouncedPersist = useDebouncedCallback(persistCurrentView, 500)`，effect 内守卫逻辑（`skipSaveRef` / `activeViewId`）与既有 eslint-disable 注释保持原样
  - `useResponsive.ts#L57-70`：内部 timer 手写逻辑替换为 `useDebouncedCallback`（模块级稳定的 `getResponsiveState` 作为回调，测试保障语义不变）

### 3. 新增 `frontend/src/hooks/useElementSize.ts`

- 签名：`useElementSize<T extends HTMLElement>(initial?: { width: number; height: number }): [RefObject<T | null>, { width: number; height: number }]`
- 语义：返回 ref + 实时尺寸；内部 `ResizeObserver` 观察元素 + `window.resize` 兜底双通道（对齐 GridPage 原实现）；挂载时立即测量一次；卸载时 `disconnect` + 移除监听
- 消费点：`GridPage.tsx#L211-224` 替换为 `const [gridAreaRef, gridAreaSize] = useElementSize<HTMLDivElement>({ width: 800, height: 400 })`；唯一取值点 `GridPage.tsx#L1083` 由 `.w/.h` 同步改为 `.width/.height`

### 4. 新增 `frontend/src/hooks/index.ts`（barrel）

- re-export `useResponsive`、`useDebouncedValue`、`useDebouncedCallback`、`useElementSize`
- 模块顶部中文 docstring 写明收纳约定：**仅收领域无关、≥2 个调用点的通用 hooks；领域 hooks 就近共置（api 层查询 hooks 留 `src/api/hooks.ts`，页面专用 hooks 留页面目录）**
- 既有直接路径引用（`@/hooks/useResponsive`）不受影响，双路径并存

### 5. 新增配套测试（vitest + jsdom，fake timers）

- `useDebouncedValue.test.ts`：防抖窗口内多次变更只取最终值、超时后更新、卸载后不更新、delayMs=0
- `useDebouncedCallback.test.ts`：pending 调用在依赖变更/卸载时被取消、ref 更新后调用最新闭包、参数透传
- `useElementSize.test.tsx`：挂载即测初始尺寸、ref 绑定后测量（复用 `src/test/setup.ts` 的 ResizeObserver polyfill）、卸载清理
- 回归：既有 `useResponsive.test.ts`、GridPage 相关测试全部保持语义不变

## 三、不改动的文件（明确排除）

- `src/api/hooks.ts`、`src/pages/grid/useNewRowAutoScroll.ts`、`src/theme/ThemeProvider.tsx`、`src/store/*`
- `ImportExportDialog.tsx` 轮询、`ReportsPage.tsx` 事件监听、剪贴板复制（单处 YAGNI）
- 不新增任何 npm 依赖

## 四、验证

1. 单 hook 级：`cd frontend && pnpm test:coverage`（新增 3 个 hook 测试 + 全量回归）
2. 门禁：`make frontend-check`（typecheck + lint + test/coverage 双门槛）
3. 收尾：`make check` 全套门禁全绿后方可提交

## 五、提交拆分

单次逻辑变更，一次提交：
`refactor: 前端新增 useDebouncedValue/useDebouncedCallback/useElementSize 通用 hooks，收敛三处防抖与两处尺寸测量重复实现`
