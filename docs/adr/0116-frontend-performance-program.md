# ADR 0116: 前端性能提升专项（首屏 / 文档按需加载 / 路由预取 / 性能门禁）

Status: Accepted（评审通过 2026-11-06）
Date: 2026-11-06
Related: `frontend/src/main.tsx`、`frontend/src/components/ProtectedRoute.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/pages/workspace/TablesList.tsx`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/useGridData.ts`、`frontend/scripts/bundle-budget.mjs`、`frontend/tests/e2e/perf/grid-lcp.spec.ts`、`docs/adr/0046-web-performance-bottlenecks.md`
需求卡片: `docs/requirements/0116-frontend-performance-program.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C10），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 三条性能旅程与结构化基线 | 新增 `frontend/tests/e2e/perf/journeys.spec.ts`，复用现有 webServer + seed 夹具，串行 1 worker；输出 `test-results/perf/*.json`（LCP/FCP/TTFB、longtask、event timing、资源 transferSize）；基线存 `frontend/tests/e2e/perf/baselines.json`，按 ±15% 容差比较，超限失败；CI 上传 artifact |
| C2 | 扩展 chunk 体积门禁 | 扩展 `scripts/bundle-budget.mjs` 的 `resolve`，新增 `moduleMarker`：读取 `dist/.vite/chunk-modules.json`，按模块路径定位 chunk 并汇总 gzip；新增 CSS / 字体总量与 6 个页面 chunk 条目 |
| C3 | 认证与 shell 路由 chunk 并行 | `main.tsx` 在 `createRoot().render()` 前判断 `getToken()` 与 `location.pathname`：命中 `/w/*` 时立即 `import('@/layouts/MainLayout')` 并预取对应落地页 chunk；不阻塞渲染，失败静默 |
| C4 | 首屏字体 ≤150 KB | 优先 `@fontsource-variable/inter`、`@fontsource-variable/outfit`、`@fontsource-variable/jetbrains-mono`（各保留 latin 子集）；若 variable 包体积不达标，再裁到 Inter 400/500/600 + Outfit 600/700 + Mono 400/500；同步更新 `fontAssets.test.ts` |
| C5 | 入口 gzip ≤215 KB | 先用 `chunk-modules.json` 归因入口内 `@rc-component/form`（pnpm patch 补 `sideEffects` + barrel 纯 re-export 使其可摇树），再把 axios 改为首次请求时动态加载；不改调用点、不重写为 fetch |
| C6 | 文档查看态不加载编辑器 | `MarkdownLiveEditor`、`ChartDesignerModal` 改 `React.lazy`；`viewMode === 'view'` 只渲染 `MarkdownPreview`；悬停编辑入口时预取编辑 chunk（查看态自身保持零 CodeMirror 请求）；`isAssetDoc` 路径不触发 Markdown 依赖 |
| C7 | 表行 hover 预取 | 新增 `frontend/src/pages/workspace/tablePrefetch.ts`：150–300ms 防抖后并行预取 `['table', key]`、`['table-views', wid, tid]` 与 `import('@/pages/grid/GridPage')`；行数据在「有快照」时立即按快照参数预取，无快照时等视图列表返回后按落地视图（`normalizeFilters` + `viewModeOf`）预取，queryKey 从 `useTableRecords` 抽出的唯一构造器读取 |
| C8 | 冷进表单次行请求 | `useGridViewStore` 增加按 `tableKey` 的 sessionStorage 快照（`cndb_grid_view_state_v1`）；`GridPage` 首帧若命中快照则直接 `viewStateOwned=true` 并按快照筛选请求；无快照时首笔行请求挂起到「视图列表返回且落地视图参数写入 store」后再发，不再先打一笔空筛选；视图列表为空时直接放行，不阻塞首屏 |
| C9 | RUM 复用既有端点 | `webVitals.ts` 保持 `window.__cndVitalsEndpoint` 单入口；补充 `path` + `navigationType` 字段；未配置端点时零请求；失败不重试、不影响交互 |
| C10 | 门禁收紧与文档回填 | LCP 先保留 5000ms，连续 10 次 CI 基线稳定后改为「中位数 +10%，硬上限 4500ms」；新增表格 INP/longtask 断言；每期回填 ADR 落地表、交接与 CHANGELOG |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 认证串行链：`loading` 为 true 时 `ProtectedRoute` 直接返回 Spin，子路由不渲染 | `frontend/src/components/ProtectedRoute.tsx:11-24`、`frontend/src/App.tsx:190-198` | `MainLayout` lazy chunk 下载被推迟到 `/auth/me` 返回后，慢网多一个 RTT | 确认 C3 |
| 2 | 首屏 12 个 `@fontsource` 字重静态引入 | `frontend/src/main.tsx:9-20` | 构建产物 12 个 woff2 共 233.7 KB；首屏文本按实际字重下载，仍有可裁剪空间 | 确认 C4 |
| 3 | 主入口 230 KB gzip（2026-11-06 analyze 构建） | `frontend/dist/assets/index-*.js` | react-dom / router 之外含 rc-form、axios 等可归因依赖，入口无预算余量 | 确认 C5 |
| 4 | 文档查看态静态引入 `MarkdownLiveEditor` 与 `ChartDesignerModal` | `frontend/src/pages/documents/DocumentEditorPage.tsx:73-123`、`:1690-1832` | 只读文档仍下载 CodeMirror（111 KB gzip）及其 lezer 语言包，页面 chunk 118 KB gzip | 确认 C6 |
| 5 | hover 仅预取表详情 | `frontend/src/pages/workspace/TablesList.tsx:248-256`、`frontend/src/layouts/MainLayout.tsx:169-176` | 点击进表仍需下载 GridPage 与 Table/Select/Picker 共享 chunk，并等视图 / 行数据 | 确认 C7 |
| 6 | 首帧 store 未归属当前表，先按空筛选请求行 | `frontend/src/pages/grid/GridPage.tsx:198-201`、`frontend/src/pages/grid/useGridData.ts:24-51` | 默认视图带筛选时产生两次行请求，并可能先闪现未筛选列表 | 确认 C8 |
| 7 | 体积门禁仅覆盖 11 个条目 | `frontend/scripts/bundle-budget.json` | 文档页、CodeMirror、CSS、字体可无声膨胀 | 确认 C2 |
| 8 | LCP 固定 5000ms；本机基线 ~1500ms，CI 3500–4800ms | `frontend/tests/e2e/perf/grid-lcp.spec.ts:19-21` | 阈值过松，真实回归难以触发；且缺少交互指标 | 确认 C10 |
| 9 | 设计装配已有 longtask 门禁，表格无 INP / longtask | `frontend/tests/e2e/perf/design-assembly-open.spec.ts` | 表格筛选、翻页、开详情缺基线 | 确认 C1 / C10 |

**核心缺陷（需求要补的）**：首屏把「认证 → shell chunk → 页面数据」串行化，文档查看把编辑态重依赖静态带入，而现有门禁只覆盖少数 chunk 与一个宽松 LCP，无法阻止真实回归。

设计目标（不变量）：

- **I1 首屏不新增串行依赖**：已登录用户的 auth 请求与 shell / 落地页 chunk 下载必须并行；匿名用户不得因预取产生额外请求。
- **I2 查看不加载编辑依赖**：文档查看态不得请求 CodeMirror、lezer 语言包或图表设计器；编辑能力与权限判定不得降级。
- **I3 预取不改变查询语义**：预取 queryKey、参数与服务端请求必须与正式 hook 完全一致；失败静默、可去抖，不得写入错误缓存。
- **I4 门禁可复现且不可放水**：性能读数同机串行、取中位数；预算调整必须带原因留痕，禁止改 omit / 白名单掩盖回归。
- **I5 零后端契约变更**：不新增 / 修改 API、数据模型、迁移与权限口径。

## Decision

### 1. 数据模型

无。前端新增一项本地缓存：`sessionStorage` 键 `cndb_grid_view_state_v1`，值为 `{ [wid/tid]: { viewId, filters, sorts, filterLogic, mode, offset, limit } }`，仅用于首帧命中，不参与持久化偏好。

### 2. 判定算法（唯一入口）

无业务判定。性能判定唯一入口为：

- `frontend/scripts/bundle-budget.mjs`：chunk gzip 体积的 FAIL 判据（`budget` 硬上限）。
- `frontend/tests/e2e/perf/journeys.spec.ts`：性能旅程基线比较入口（中位数 + 容差）。
- `frontend/src/utils/perfBudget.ts`：前端只读常量（LCP 硬上限、字体目标、文档页目标），仅测试与调试引用。

### 3. API 变更清单

无。

### 4. 边界与例外

1. 无 token 或路径不在 `/w/*` 时不预取 shell；匿名登录页只保留既有 AuthLayout 静态代码。
2. 预取失败（离线、401、chunk 404）必须静默，不改变页面错误态；正式请求失败才走既有错误边界。
3. 文档 `isAssetDoc`（PDF / Office / 图片 / PPTX 原件）继续走 `DocumentAssetView`，不因本方案引入 Markdown 依赖。
4. 只读用户不进入编辑态，不触发编辑器预取；权限判定仍以 `current_user_actions` 为准。
5. `sessionStorage` 不可用（隐私模式 / 配额满）时退化为原行为，不抛错。
6. LCP 阈值调整只在连续 10 次 CI 稳定基线后生效；未达标前保持 5000ms，避免抖动误伤。

### 5. 迁移

无后端迁移。前端本地缓存带版本键，结构变更时整键丢弃，不做数据迁移。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 启动 | `frontend/src/main.tsx` | token + `/w/*` 时预取 `MainLayout` 与落地页 chunk；字体 import 改为 variable / 裁剪字重 |
| 路由 | `frontend/src/App.tsx`、`frontend/src/components/ProtectedRoute.tsx` | 预取与认证并行；不改路由结构与权限门禁 |
| 文档 | `frontend/src/pages/documents/DocumentEditorPage.tsx` | `MarkdownLiveEditor`、`ChartDesignerModal` 改 lazy；查看态空闲预取编辑器；补 Suspense fallback |
| 表格 | `frontend/src/pages/workspace/TablesList.tsx`、`frontend/src/layouts/MainLayout.tsx` | 接入 `tablePrefetch`，hover 防抖后预取表 / 视图 / 首帧行 / GridPage chunk |
| 表格数据 | `frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/useGridData.ts`、`frontend/src/store/gridView.ts` | 首帧从 sessionStorage 种子化视图状态；抽出 queryKey 构造器供预取复用 |
| 观测 | `frontend/src/utils/webVitals.ts` | 补 `navigationType` 字段；保持单端点、静默失败 |
| 门禁 | `frontend/scripts/bundle-budget.mjs`、`frontend/scripts/bundle-budget.json` | `moduleMarker` 定位；新增 CSS / 字体 / 6 个页面 chunk 条目 |
| 测试 | `frontend/tests/e2e/perf/`、相关单测 | 三条旅程、文档查看态无 CodeMirror、hover 预取、单次行请求、字体资产 |

### 7. 测试清单

**判定层（单测）**：

- `tablePrefetch.test.ts`：防抖窗口内只发一次预取；queryKey 与 `useTableRecords` 一致；失败静默。
- `gridViewSeed.test.ts`：sessionStorage 命中 / 未命中 / 损坏 / 配额异常；首帧筛选参数正确。
- `gridViewParams.test.ts`：视图模式映射、filters list/dict 归一化、落地视图选择顺序（预取与 GridPage 共用）。
- `fontAssets.test.ts`：字重集合与目标字节数；variable 包缺失时回退清单。
- `webVitals.test.ts`：未配置端点零请求；配置后字段包含 `path` / `navigationType`；sendBeacon 抛错不影响主流程。

**接口层**：无（零后端变更）。

**迁移 / 备份**：无。

**e2e（前端）**：

- `perf/journeys.spec.ts`：冷启动进表、文档查看态、表格交互三条旅程产出 JSON 并对比基线。
- `perf/document-open.spec.ts`：查看态网络无 `codemirror` / `@lezer` chunk；点击编辑后编辑器可见。
- `perf/grid-prefetch.spec.ts`：hover 后出现预取请求；未 hover 不请求；冷进表行请求次数 = 1。
- `perf/grid-lcp.spec.ts`：保留 LCP 硬上限；新增 INP / longtask 断言。
- 全量 e2e 回归：登录、表格、文档、设计打开不受影响。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 性能旅程 + 基线 + chunk / CSS / 字体预算扩展（C1 C2） | 低 |
| **P1** | 首屏并行预取、字体瘦身、入口归因减重（C3 C4 C5） | 中 |
| **P2** | 文档查看态懒加载编辑器与图表弹窗（C6） | 中 |
| **P3** | 表格 hover 预取、单次行请求、RUM 字段、门禁收紧（C7 C8 C9 C10） | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体推进顺序 | 先度量与门禁，再首屏、文档、路由预取，分 P0–P3 | 无基线无法证明收益；文档懒加载单笔收益最大 | 直接并行改所有页面（无法归因、回归定位成本高） | `frontend/tests/e2e/perf/`、`frontend/scripts/bundle-budget.mjs` |
| D2 | 性能度量方式 | Playwright 同机串行 + 结构化 JSON + 仓库基线 + 容差 | 复用既有 webServer / seed 夹具；可覆盖交互指标 | Lighthouse CI（环境方差大、无法稳定覆盖登录后交互） | `frontend/tests/e2e/perf/journeys.spec.ts` |
| D3 | chunk 预算定位方式 | `bundle-budget.mjs` 新增 `moduleMarker`，按 `chunk-modules.json` 模块归属定位并汇总 gzip | hash 文件名会随构建变化；模块归属稳定 | 手写 hash `assetPattern`（每次构建失效）；引入 `manualChunks` 强制命名（可能改变分包与加载顺序） | `frontend/scripts/bundle-budget.mjs` |
| D4 | 首屏认证与 shell 关系 | token 存在且 `/w/*` 时并行预取 `MainLayout` 与落地页 chunk，不阻塞认证 | 消除一个 RTT + chunk 下载串行；匿名不预取 | 缓存 `user` 后跳过 `/auth/me`（角色 / 权限闪烁，安全口径放松）；等待认证后再预取（无收益） | `frontend/src/main.tsx` |
| D5 | 字体瘦身方式 | 优先 variable 字体，目标首屏字体 ≤150 KB；视觉截图兜底 | 12 字重 233.7 KB，variable 可覆盖多字重 | 引入 CDN（违背本地打包口径）；全量改系统字体（品牌与排版回归） | `frontend/src/main.tsx`、`frontend/package.json` |
| D6 | 入口减重范围 | 先归因移出 `@rc-component/form`（pnpm patch 可摇树）；仍超 215 KB 时把 axios 改为首次请求按需加载 | rc-form 在入口约 46 KB 原始体积；axios 约 120 KB 原始体积，按需加载既减入口又不改 401 / 错误归一语义 | 无归因直接重写 axios 为 fetch（上传进度 / 取消 / 测试面风险大）；升级 / 降级 react-router（非本期收益点，风险大） | `frontend/src/api/client.ts`、`frontend/patches/@rc-component__form@1.8.6.patch` |
| D7 | 文档查看态加载边界 | `MarkdownLiveEditor` 与 `ChartDesignerModal` lazy；查看态只保留 `MarkdownPreview` | 查看是主路径；CodeMirror 111 KB + lezer 语言包只在编辑需要 | 按文件类型拆包（md 文档无法区分查看 / 编辑）；继续静态引入但异步初始化（仍占下载与解析） | `frontend/src/pages/documents/DocumentEditorPage.tsx` |
| D8 | 表格预取范围 | hover 防抖后预取表详情、视图、首帧行与 GridPage chunk；无快照时行参数等视图列表返回后按落地视图派生 | 点击进表是高频路径；queryKey 与正式 hook 一致可命中缓存 | 预取全部行 / 全部表（带宽浪费、后端压力）；仅预取表详情（现状不足） | `frontend/src/pages/workspace/tablePrefetch.ts` |
| D9 | 冷进表请求收敛 | 按表 sessionStorage 种子化视图状态；无快照时首笔行请求挂起到落地视图参数就位（视图为空直接放行） | 消除两次行请求与未筛选闪现 | 等视图加载后再请求（多一个 RTT）；取消空筛选兜底（无默认视图的表可能空白） | `frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/useGridData.ts` |
| D10 | RUM 接入 | 复用 `window.__cndVitalsEndpoint`，补 `navigationType`，未配置零请求 | 项目暂无监控后端；避免本期扩后端 | 自建采集 / 存储服务（超出前端专项，需独立 ADR） | `frontend/src/utils/webVitals.ts` |
| D11 | LCP 阈值收紧节奏 | 连续 10 次 CI 稳定后启用「中位数 +10%」与 4500ms 硬上限 | 当前 3500–4800ms 波动，立即收紧会误伤 | 立即改为 3000ms（runner 方差大）；继续固定 5000ms（无法拦截回归） | `frontend/tests/e2e/perf/grid-lcp.spec.ts` |
| D12 | `MainLayout` 全量重挂 | 先 profiling，仅当暖缓存切换 >300ms 且改动可控时才处理；非必达 | `key={location}` 承载页面切换状态隔离，移除有串扰风险 | 直接移除 key（跨表状态 / 滚动 / 弹窗串扰）；本期强制 keep-alive（复杂度超收益） | `frontend/src/layouts/MainLayout.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：只读文档打开体积预计从约 289 KB gzip 降至 ≤150 KB；首屏字体与入口各降一档；认证与 shell 并行缩短首屏关键路径；表格点击命中预取缓存；体积与交互门禁可拦截真实回归。
- **负向**：一次构建 / 一次 perf 旅程的 CI 时间增加；hover 预取增加少量后台请求；字体替换与懒加载需要视觉回归兜底。
- **风险与缓解**：懒加载编辑器首帧延迟 → 编辑入口 hover 预取 + Suspense 骨架；字体视觉差异 → `fontAssets.test.ts` + 关键页面截图；预算收紧误伤 → 先按实测冻结基线，超基线只 warn 一个迭代后再 FAIL；预取污染缓存 → queryKey 唯一构造器 + 失败静默 + 测试断言；axios 按需加载 → chunk 在模块求值时即并行下载，首个请求 await 加载，401 / 错误归一逻辑不变。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 读路径性能 | 表列表 / 记录查询 | 本 ADR 只加前端预取与单次请求，不改后端分页与截断口径 | ADR 0046 |
| 字体与排版 | `frontend/src/main.tsx`、`frontend/src/theme/` | 字重集合由本 ADR 调整，排版 token 不变 | ADR 0031 |
| 浏览器兼容 | `frontend/src/compat/` | variable 字体与 lazy 不得破坏 Chrome 81 基线；老内核仍走现有垫片 | ADR 0026 |
| React / antd 运行栈 | `frontend/package.json` | 不升级运行时大版本；入口减重不改 antd 版本 | ADR 0074 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/scripts/bundle-budget.mjs`（entryCss / fonts / moduleMarker 三种 resolve）、`frontend/scripts/bundle-budget.json`（9 个新条目）、`frontend/tests/e2e/perf/journeys.spec.ts`、`frontend/tests/e2e/perf/baselines.json` | `frontend/tests/e2e/perf/journeys.spec.ts`、`frontend/tests/e2e/perf/design-assembly-open.spec.ts` | 待提交 |
| P1 | 已落地 | `frontend/src/main.tsx`（认证并行预取 + 7 字重）、`frontend/src/api/client.ts`（axios 按需加载）、`frontend/patches/@rc-component__form@1.8.6.patch`（barrel 摇树）、`frontend/scripts/check-patches.mjs`（补丁形态守门） | `frontend/src/theme/fontAssets.test.ts`、`frontend/src/api/client.test.ts`；入口实测 198 KiB / 字体 142 KiB | 待提交 |
| P2 | 已落地 | `frontend/src/pages/documents/DocumentEditorPage.tsx`（编辑器 / 图表弹窗 lazy + 编辑入口 hover 预取） | `frontend/tests/e2e/perf/document-open.spec.ts`；文档页实测 29 KiB | 待提交 |
| P3 | 进行中 | `frontend/src/pages/workspace/tablePrefetch.ts`、`frontend/src/pages/grid/gridViewSeed.ts`、`frontend/src/pages/grid/gridViewParams.ts`、`frontend/src/store/gridView.ts`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/useGridData.ts`、`frontend/src/api/hooks.ts`、`frontend/src/utils/webVitals.ts`、`frontend/tests/e2e/perf/grid-lcp.spec.ts`（INP / longtask 在 journeys） | `frontend/src/pages/workspace/tablePrefetch.test.ts`、`frontend/src/pages/grid/gridViewSeed.test.ts`、`frontend/src/pages/grid/gridViewParams.test.ts`、`frontend/src/store/gridView.test.ts`、`frontend/src/utils/webVitals.test.ts`、`frontend/tests/e2e/perf/grid-prefetch.spec.ts`；LCP 收紧待 10 次 CI 基线 | 待提交 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P3 进行中（代码与测试已落地，仅剩 LCP 阈值收紧需连续 10 次 CI 基线）
- 已完成：P0 预算扩展与性能旅程；P1 认证并行预取 / 字体 7 字重 / 入口 198 KiB；P2 文档页 lazy 后 29 KiB；P3 表格 hover 预取（无快照时先视图后行）/ sessionStorage 种子化 / 无快照首笔行请求挂起到落地视图 / RUM `navigationType`
- 下一步：CI 连续采 10 次 journeys 与 grid-lcp 读数后，把 LCP 改为「中位数 +10%，硬上限 4500ms」，并把 CI 中位数写回 `baselines.json` 的 `ci` 环境
- 已知坑：`baselines.json` 首轮为空（只记录不 FAIL），必须用 CI artifact 的 `test-results/perf/journeys.json` 回填；`dist/.vite/chunk-modules.json` 只在 build 后存在；CodeMirror chunk 归属靠模块路径匹配，改文件名不影响断言；axios 按需加载后首个请求需等 chunk，本地 dev 会多一次请求但无功能变化；性能用例必须走已发布文档（`?parent=&status=published` 深链），草稿默认进编辑态会把编辑器 chunk 带进来
- 最近一次全绿：`make check-fast`、`PYTEST_JOBS=3 make test`、前端全量单测（257 文件 / 3138 用例）、`pnpm build` 与 `pnpm bundle:budget`、`pnpm e2e --project=chromium-authed tests/e2e/perf --workers=1`（10 passed）（2026-11-06）
