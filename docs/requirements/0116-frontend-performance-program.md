# 需求卡片：前端性能提升专项（首屏 / 文档按需加载 / 路由预取 / 性能门禁）

- 编号：0116
- 来源 / 提出人：用户（会话 2026-11-06）
- 日期：2026-11-06
- 关联 ADR：`docs/adr/0116-frontend-performance-program.md`（S2，待评审）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请针对本项目的前端性能提升，制定可行方案。

> 按此推进。

## 方案（口径）

按 2026-11-06 已确认的性能方案执行，范围限定为前端与前端门禁，零后端接口 / 数据模型 / 迁移变更：

1. **先度量后优化**：补齐首屏、文档打开、表格交互三条性能旅程的结构化指标与 chunk 体积预算，再动代码。
2. **首屏关键路径**：认证请求与已登录 shell 路由 chunk 并行；字体按实际使用字重裁剪；定位并移出入口中的非必要依赖。
3. **文档按需加载**：查看态不加载 CodeMirror 编辑器与图表设计弹窗，编辑态按需下载并提前预取。
4. **路由与数据预取**：表行 hover 预取表详情、视图、首屏行数据与 GridPage chunk；冷进表只发一次行请求。
5. **持续观测**：沿用既有 `window.__cndVitalsEndpoint` 上报钩子，不新增后端服务；性能预算调整必须带原因留痕。

**边界**：不改 React / react-router 等运行时硬依赖版本；不重写表格渲染层（已虚拟滚动且单元格已 memo）；不引入 SSR；PPTX / Three.js / ECharts 的既有懒加载口径不变。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「制定可行方案」「按此推进」 | 先建立可复现的性能基线：冷启动进表、打开文档查看态、表格交互三条旅程输出 LCP/FCP/TTFB、long task、event timing、资源传输量 JSON；基线存仓库并按容差比较 | `frontend/tests/e2e/perf/`、`frontend/scripts/` | 「性能旅程用例产出 JSON artifact，超基线失败」 |
| C2 | 「前端性能提升」 | 扩展 chunk 体积门禁：除现有条目外覆盖主入口 CSS、字体总量、`DocumentEditorPage`、CodeMirror 共享 chunk、`MainLayout`、`WorkspaceList`、`DesignEditorPage`、`AnalyticsPage`；按模块标记定位 chunk，避免 hash 改名失效 | `frontend/scripts/bundle-budget.mjs`、`bundle-budget.json` | `pnpm build && pnpm bundle:budget` 覆盖新增条目且可 FAIL |
| C3 | 「首屏性能」 | 已登录（存在 token 且路径 `/w/*`）时，在 `/auth/me` 进行中即预取 `MainLayout` 与当前路径对应页面 chunk，二者并行 | `frontend/src/main.tsx`、`frontend/src/App.tsx`、`frontend/src/components/ProtectedRoute.tsx` | 网络瀑布显示 auth 与 shell chunk 并行；匿名用户不预取 |
| C4 | 「首屏性能」 | 首屏字体传输从 12 个字重 233.7 KB 降至 ≤150 KB：优先 variable 字体或裁剪到实际使用字重；保持 `@fontsource` 本地打包、无 CDN | `frontend/src/main.tsx`、`frontend/package.json` | 构建后字体传输统计 ≤150 KB；视觉截图无回归 |
| C5 | 「首屏性能」 | 定位主入口内 `@rc-component/form` 等非首屏必需依赖并移出；入口 gzip 从 230 KB 降至 ≤215 KB。axios 替换为 fetch 封装属可选项，未达收益则不做 | `frontend/src/main.tsx`、`frontend/src/App.tsx`、`frontend/src/components/ErrorBoundary.tsx` | 入口 gzip ≤215 KB；`bundle:budget` 通过 |
| C6 | 「文档按需加载」 | 查看态只加载 `MarkdownPreview`，不加载 `MarkdownLiveEditor`（CodeMirror 及其 lezer 语言包）与 `ChartDesignerModal`；编辑态再按需加载，并在查看态空闲或悬停编辑入口时预取 | `frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/components/Document/` | 查看态无 CodeMirror 请求；文档页打开 JS ≤150 KB gzip；编辑首帧不劣化 >100ms |
| C7 | 「路由预取」 | 表行 hover 在 150–300ms 防抖后预取表详情、`table-views`、首屏 `table-records`（queryKey 与 `useGridData` 首帧一致）与 `GridPage` chunk；扫过列表不产生请求风暴 | `frontend/src/pages/workspace/TablesList.tsx`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/grid/GridPage.tsx` | hover 后网络出现对应预取；未 hover 不请求；冷进表无重复请求 |
| C8 | 「性能提升」 | 冷进表用 `sessionStorage` 按 `wid/tid` 种子化视图状态，按默认 / 上次视图只发一次行请求，消除「空筛选 → 筛选」双请求与列表闪烁 | `frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/useGridData.ts` | 冷进表行请求次数 = 1；默认视图筛选结果正确 |
| C9 | 「性能提升」 | 沿用既有 `window.__cndVitalsEndpoint` 作为 RUM 接入点，仅在配置时上报；采样失败静默，不影响主流程；不新增后端服务 | `frontend/src/utils/webVitals.ts` | 未配置端点时零网络请求；配置后只发 beacon |
| C10 | 「按此推进」 | 性能门禁收紧口径：LCP 阈值由固定 5000ms 改为「CI 实测中位数 +10%」并保留 4500ms 硬上限，需连续 10 次稳定基线后生效；新增表格 INP / long task 断言；全期更新 CHANGELOG 与 ADR 落地状态 | `frontend/tests/e2e/perf/grid-lcp.spec.ts`、`frontend/tests/e2e/perf/`、`docs/adr/0116-*.md`、`CHANGELOG.md` | perf 用例全绿且可拦截回归；ADR 落地表与 CHANGELOG 更新 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 首屏认证串行链 | `frontend/src/components/ProtectedRoute.tsx:11-24`、`frontend/src/App.tsx:190-198` | `loading` 为 true 时子路由不渲染，shell chunk 下载被推迟到 `/auth/me` 之后 |
| 2 | 首屏字体 | `frontend/src/main.tsx:9-20` | 12 个 `@fontsource` 字重，构建产物 233.7 KB woff2 |
| 3 | 入口体积 | `frontend/dist/assets/index-*.js`（2026-11-06 实测 230 KB gzip） | 含 rc-form、axios 等，需归因后移出 |
| 4 | 文档页静态重依赖 | `frontend/src/pages/documents/DocumentEditorPage.tsx:73-123`、`:1690-1832` | 查看态仍静态引入编辑器与图表弹窗 |
| 5 | 表格行预取 | `frontend/src/pages/workspace/TablesList.tsx:248-256`、`frontend/src/layouts/MainLayout.tsx:169-176` | 仅预取表详情，未预取视图 / 行数据 / 页面 chunk |
| 6 | 冷进表重复请求 | `frontend/src/pages/grid/useGridData.ts:24-51`、`frontend/src/pages/grid/GridPage.tsx:198-201` | store 未归属当前表时先按空筛选请求，视图加载后重发 |
| 7 | 体积门禁覆盖 | `frontend/scripts/bundle-budget.json` | 仅 11 个条目，文档 / CodeMirror / CSS / 字体未覆盖 |
| 8 | LCP 门禁阈值 | `frontend/tests/e2e/perf/grid-lcp.spec.ts:19-21` | 本机基线 ~1500ms，CI 3500–4800ms，固定 5000ms 偏松 |
| 9 | 表格交互门禁 | `frontend/tests/e2e/perf/` | 仅有设计装配 long task 用例，表格无 INP 基线 |

## 未决问题（已确认）

- [x] ① 是否允许裁剪字体字重：**结论** 允许，优先 variable 字体，视觉快照兜底（2026-11-06 用户「按此推进」）。
- [x] ② 是否重写 axios：**结论** 属可选项，只有入口明确降至 ≤215 KB 需要时才做；不做基线承诺（2026-11-06 用户「按此推进」）。
- [x] ③ 是否新增性能后端 / RUM 服务：**结论** 不新增，本期只复用 `__cndVitalsEndpoint` 钩子（2026-11-06 用户「按此推进」）。
- [x] ④ LCP 阈值收紧节奏：**结论** 连续 10 次 CI 基线稳定后启用「中位数 +10%」与 4500ms 硬上限（2026-11-06 用户「按此推进」）。
- [x] ⑤ 是否改动 MainLayout 的 `key={location}` 重挂：**结论** 先 profiling，仅当暖缓存切换 >300ms 且改动可控时再做，不作为必达项（2026-11-06 用户「按此推进」）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-11-06「按此推进」）
