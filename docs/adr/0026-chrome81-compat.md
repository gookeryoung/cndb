# ADR 0026: Chrome 81 兼容基线（生产构建与视觉一致）

Status: Accepted
Date: 2026-10-24
Related: `frontend/vite.config.ts`、`frontend/package.json`、`frontend/src/main.tsx`、`frontend/src/theme/ThemeProvider.tsx`、`frontend/src/index.css`、`frontend/src/utils/webVitals.ts`、`frontend/src/pages/import-export/ImportExportDialog/exportPdf.ts`、`frontend/scripts/check-browser-compat.mjs`、`frontend/scripts/chrome81-smoke.mjs`、`frontend/playwright.config.ts`、`.github/workflows/chrome81-smoke.yml`
需求卡片: `docs/requirements/0026-chrome81-compat.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 页面可打开 | 构建目标降到 `chrome81`，入口前加载定向 polyfill；Chromium 81 冒烟断言无 `pageerror` / 白屏 |
| C2 | antd 组件视觉一致 | `StyleProvider hashPriority="high"` + `legacyLogicalPropertiesTransformer`，消掉 `:where()`、逻辑属性与 `inset` |
| C3 | 主题色一致 | 保留原生 `color-mix()` 为主声明，同时按当前主题预计算 `--cn-mix-*` 兜底变量 |
| C4 | flex 间距一致 | 特性探测失败的浏览器才加载 flex-gap shim，读取计算后 `rowGap` / `columnGap` 并补子元素 margin |
| C5 | 关键流程通过 | `puppeteer-core` 驱动固定版本 Chromium 81，覆盖登录 / 表格 / 视图 / 文档 / 导出 |
| C6 | Chromium 81 基线 | `.browserslistrc` 固定 `chrome >= 81`、`edge >= 81`；README 写明不承诺 Firefox / Safari |
| C7 | 回归门禁 | 构建后运行 `check-browser-compat.mjs`；真实 Chromium 81 冒烟进入定时 CI |
| C8 | 现代浏览器不回归 | 原生能力不替换；既有 Playwright e2e 全绿；包体走 bundle budget 基线流程 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 生产构建目标固定 `es2022` | `frontend/vite.config.ts:154` | Chrome 81 缺私有字段、逻辑赋值、静态块等 ES2022 语法；已实测 `--target chrome81` 可成功构建（18.7s），语法降级本身可行 | 确认 |
| 2 | antd 5 运行时 CSS-in-JS 默认 `hashPriority: 'low'` 生成 `:where()`；样式源码含 224 处 `marginInline`、198 处 `insetInline`、171 处 `paddingInline`，并有 24 处 `inset:` | `frontend/src/theme/ThemeProvider.tsx:102`、`node_modules/@ant-design/cssinjs/es/StyleContext.js:48`、`node_modules/antd/es/**/style/index.js` | Chrome 81 不认识 `:where()`（88+）会丢弃整条选择器；逻辑属性（87+）与 `inset`（87+）也会被忽略，导致组件无样式或定位错乱 | 确认 |
| 3 | 构建产物仍在调用 Chrome 81 没有的运行时 API：`Object.hasOwn` 5 处、`structuredClone` 2 处、`Array.prototype.at` 6 处、`Intl.Segmenter` 4 处 | `frontend/src/utils/webVitals.ts:14`、`frontend/src/pages/import-export/ImportExportDialog/exportPdf.ts:198`；实测扫描 `dist/assets/*.js` | 首屏或按需路径会抛 `TypeError`；`html2canvas-pro` 无条件调用 `new Intl.Segmenter`（`node_modules/html2canvas-pro/dist/html2canvas-pro.esm.js:8711`），导出 PDF / 截图必失败 | 确认 |
| 4 | 主题与业务色大量使用 `color-mix(in srgb, ...)`：`src/index.css` 94 处、TSX 28 处，共 77 种唯一表达式 | `frontend/src/index.css:176` 等、`frontend/src/pages/**` | Chrome 81 不支持 `color-mix()`（111+），声明被忽略：背景透明、文字继承、边框缺失；10 套主题均受影响 | 确认 |
| 5 | flex `gap` 广泛使用：`src/index.css` 124 处、TSX 209 处（其中约 172 处为 `display: flex`）；antd Space 对预设尺寸生成 `rowGap` / `columnGap` 类，Grid Row 写内联 `rowGap` | `frontend/src/index.css`、`frontend/src/**/*.tsx`、`node_modules/antd/es/space/index.js:93`、`node_modules/antd/es/grid/row.js:86` | Chrome 81 仅支持 grid gap，flex gap 需 Chrome 84+；不处理会导致按钮组、工具栏、卡片、表头等间距塌陷 | 确认 |
| 6 | 5 条 `:focus-visible` 规则 | `frontend/src/index.css:534`、`:1503`、`:3392`、`:4484`、`:4535` | Chrome 81 选择器无效，键盘焦点视觉缺失 | 确认 |
| 7 | 无兼容门禁；`frontend-build` 只跑 Vite，不检查产物基线 | `frontend/package.json:8`、`Makefile` 的 `frontend-build` | 任意依赖升级或新写法都可能静默破坏 Chrome 81，回归不可见 | 确认 |
| 8 | 构建降级与 polyfill 会增加关键 chunk 体积 | `frontend/scripts/bundle-budget.mjs`、`frontend/scripts/bundle-budget.json` | 可能触发 bundle budget 超限；需按现有流程先拆 lazy，再记录基线理由 | 新增 |
| 9 | 仓库未声明浏览器基线 | `README.md`、`CONTEXT.md` | 后续开发无口径可依 | 新增 |

**核心缺陷（需求要补的）**：生产构建、运行时样式与 API 都隐含以现代 Chrome 为基线，仓库没有任何机制保证 Chromium 81 可打开、可正常渲染或防止后续回退。

设计目标（不变量）：

- **I1 首屏可执行**：入口及其静态依赖在 Chromium 81 上无 `SyntaxError` / `ReferenceError`，首屏不白屏。
- **I2 视觉等价**：同一主题、同一视口下，关键页面在 Chromium 81 与当前 Chromium 上的颜色与间距一致（允许字体栅格化差异）。
- **I3 现代浏览器不回退**：现代浏览器继续使用原生 `color-mix()` 与原生 flex gap；既有 Playwright e2e 全绿。
- **I4 门禁可判定**：兼容缺口由命令退出码判定，不依赖人工记忆。

## Decision

### 1. 数据模型

无。不新增表 / 列 / 枚举 / 端点；`--cn-mix-*` 是运行时写在 `document.documentElement` 上的 CSS 变量，不持久化。

### 2. 判定算法（唯一入口）

兼容口径必须收敛到下列入口，业务代码不得自行 `@supports` 或 `typeof` 探测后走不同分支：

| 入口 | 签名 | 职责 |
|---|---|---|
| `frontend/scripts/browser-baseline.mjs` | `export const BROWSER_BASELINE = 'chrome81'` | 构建目标、静态检查、老内核冒烟共用同一常量，禁止三处各写一份 target |
| `isFlexGapSupported()` | `(): boolean` | flex gap 能力探测的唯一实现 |
| `applyThemeMixVars()` | `(root?: HTMLElement): void` | `--cn-mix-*` 兜底变量的唯一写入方 |
| `mixColor(a, pct, b)` | `(string, number, string): string` | 运行时把 `color-mix(in srgb, A p%, B)` 算成具体色值的唯一实现 |
| `initCompat()` | `(): void` | 运行时垫片的唯一装载入口；`main.tsx` 只调它 |

判定顺序：

1. `frontend/src/compat/polyfills.ts` 由**实际使用这些 API 的懒加载模块**静态导入（`webVitals.ts`、`exportPdf.ts`、`MarkdownPreview.tsx`、`DocumentEditorPage.tsx`）；ESM 保证依赖先于模块体执行，入口不常驻 polyfill。这样既满足「先补后用」，又不让入口无条件承担约 3 KiB gzip 的常驻成本。
2. `structuredClone` 不补：唯一调用点（`react-markdown` 依赖链）已用 `typeof structuredClone === 'function'` 守卫并自带 JSON 回退；补它会把整套 Map/Set internals 拖进包体。
3. `initCompat()` 在首次渲染后执行：先 `isFlexGapSupported()`，不支持才动态 `import()` shim 并给 `<html>` 打 `cn-no-flex-gap`；支持则 shim 永不下载。
4. 主题变量应用后（`useLayoutEffect`，首帧前）调用 `applyThemeMixVars()`；主题切换时重算。
5. 导出路径在动态导入 `html2canvas-pro` 之前探测 `Intl.Segmenter`，缺失才加载 `@formatjs/intl-segmenter`。
6. 上述入口之外不得再出现 `if (!Array.prototype.at)`、`Object.hasOwn || …` 之类的局部补丁。

颜色计算规则（`mixColor`）：

- 语法限定为 `color-mix(in srgb, <color> <p>%, <color>)` 与单边百分比形式（另一侧取 `100 - p`）。
- 操作数支持 `#rgb` / `#rrggbb`、`rgb()` / `rgba()`、`transparent`、`var(--x)` / `var(--x, <fallback>)`；`var()` 从 `getComputedStyle(document.body)` 读取，嵌套 `var()`（如 `rgb(var(--cn-shadow-color))`）递归解析。
- 按 CSS Color 5 做**预乘 alpha** 插值：`α = αA·wA + αB·wB`；`α > 0` 时 `c = (cA·αA·wA + cB·αB·wB) / α`，`α = 0` 时通道取 0。
- `--cn-primary` 在 `index.css` 未定义，按表达式内的 `#1677ff` 兜底解析（现状核实结论，不是新增默认值）。

flex-gap 判定规则（`isFlexGapSupported`）：

- 在离屏容器里放两个 10px 子元素，设 `display:flex; gap:10px`，实测两者外沿间距是否为 10px。
- 不能用 `@supports (gap: 1px)`：Chrome 81 支持 **grid** gap，该条件为真，会误判 flex gap 已支持。

### 3. API 变更清单

无。本次只改前端构建、运行时兼容层与门禁，不新增 / 修改任何端点与响应字段。

### 4. 边界与例外

1. 基线只承诺 Chromium 内核（Chrome / Edge 81+；360、QQ 等按内核版本对齐）。Firefox / Safari 不承诺，不做专项验证，也不为其引入垫片。
2. 不引入 `@vitejs/plugin-legacy`：Chrome 81 支持原生 ESM，双包只服务更老内核，且解决不了 CSS-in-JS 与 flex gap（D1）。
3. 现代浏览器继续走原生 `color-mix()` 与原生 flex gap；兜底声明 / 垫片只服务旧内核，不得替换主路径（D8）。
4. `StyleProvider hashPriority="high"` 会提升 antd 选择器特异性；`index.css` 中依赖低特异性的覆盖若失效，改用更具体的选择器，不新增 `!important`。
5. flex-gap shim 跳过 `display: grid` 容器，不覆盖子元素已有 margin，并提供 `window.__CNDB_DISABLE_FLEX_GAP_SHIM__` 作为现场 kill switch。
6. `Intl.Segmenter` 垫片只在导出路径加载，不得进入首屏 chunk。
7. 老内核冒烟需要外网下载固定 revision 的 Chromium 81，只进定时 CI，不作为每次提交的必跑门禁；每次提交由静态门禁兜底。
8. 构建产物体积受 `bundle-budget.json` 约束；兼容性增量超限时先拆 lazy，再按 `--update --reason` 记录基线（D10）。

### 5. 迁移

无。不涉及数据库、备份格式与 API 兼容；部署时以新构建产物整体替换 `src/cndb/static`，旧前端产物无存量迁移。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 构建基线 | `frontend/vite.config.ts` | `build.target` / `build.cssTarget` / `esbuild.target` / `optimizeDeps.esbuildOptions.target` 统一取 `BROWSER_BASELINE`；`css.postcss.plugins` 加入 `postcss-logical` |
| 浏览器声明 | `frontend/.browserslistrc` | 新增：`chrome >= 81`、`edge >= 81` |
| 依赖 | `frontend/package.json` | 新增 `core-js`、`@ant-design/cssinjs`、`@formatjs/intl-segmenter`；devDependency 新增 `puppeteer-core`、`postcss-logical` |
| 入口 | `frontend/src/main.tsx` | 渲染后调用 `initCompat()`；不常驻 polyfill |
| 运行时 API | `frontend/src/compat/polyfills.ts` | `core-js/actual/array/at`、`core-js/actual/object/has-own`；由消费模块静态导入 |
| 文档渲染 | `frontend/src/components/Document/MarkdownPreview.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx` | 静态导入 polyfill，覆盖依赖链的 `Object.hasOwn` |
| 能力探测 / 垫片 | `frontend/src/compat/flexGap.ts`、`frontend/src/compat/index.ts` | `isFlexGapSupported()`、flex-gap shim、`initCompat()` 唯一装载入口 |
| 主题 | `frontend/src/theme/ThemeProvider.tsx` | `ConfigProvider` 外包裹 `StyleProvider`（`hashPriority="high"` + `legacyLogicalPropertiesTransformer`）；body class 与 mix 变量移到 `useLayoutEffect` |
| 颜色兜底 | `frontend/src/theme/themeMix.ts` | 77 种唯一表达式注册表、`applyThemeMixVars()`、`mixColor()` |
| 样式 | `frontend/src/index.css` | 每条 `color-mix()` 前补同属性 `var(--cn-mix-*)` 声明；5 条 `:focus-visible` 改 `:focus`；作者逻辑属性交给 `postcss-logical` |
| 静态 TSX 颜色 | `frontend/src/pages/**` 等 22 处 | `color-mix(...)` 改为 `var(--cn-mix-*)`（两代浏览器结果一致） |
| 导出 | `frontend/src/pages/import-export/ImportExportDialog/exportPdf.ts` | 动态导入 `html2canvas-pro` 前按需加载 `@formatjs/intl-segmenter` |
| 采集 | `frontend/src/utils/webVitals.ts` | 删除局部 `Array.prototype.at` 补丁，统一由入口 polyfill 提供 |
| 静态门禁 | `frontend/scripts/check-browser-compat.mjs` | 校验 target 与产物 / 源码中的禁用写法；挂在 `pnpm build` 之后 |
| 老内核冒烟 | `frontend/scripts/chrome81-smoke.mjs` | `puppeteer-core` + 固定 Chromium 81 revision；`pnpm e2e:chrome81` |
| 文档 | `README.md`、`CONTEXT.md` | 写明浏览器基线与不承诺范围（CONTEXT 词条已补） |

实现要点：

- **antd 样式降级**：`@ant-design/cssinjs` 与 antd 5.29 解析到的 1.24.0 同 major，作为直接依赖固定版本；transformer 的 `keyMap` 已覆盖 `inset`、`insetInline*`、`marginInline*`、`paddingInline*` 与逻辑边框 / 圆角（`node_modules/@ant-design/cssinjs/es/transformers/legacyLogicalProperties.js`），因此 antd 生成的样式不再需要逐组件覆盖。
- **作者 CSS 逻辑属性**：`postcss-logical` 只处理源码里手写的 `padding-inline` / `margin-inline-*`，与 cssinjs transformer 覆盖不同来源，二者不可互相替代；项目固定 `zh-CN`，无 RTL 需求，转物理属性无副作用。
- **`color-mix` 双层声明**：保留原生声明为主，前一条写兜底变量；Chrome 81 丢弃第二条，现代浏览器用第二条，视觉不变。22 处静态 TSX 表达式再改写为 `var(--cn-mix-*)`；6 处动态表达式（`FlowView` / `MatrixView` / `ImportPanel` / `kanbanVisuals` 等）在渲染时调 `mixColor()` 解析 CSS 变量。
- **flex-gap shim**：读取 `getComputedStyle` 的 `display` / `flexDirection` / `flexWrap` / `rowGap` / `columnGap`（Chrome 81 的 CSSOM 会返回声明值，即使布局不消费）。单行横向用 `> * + *` 补 `margin-left`，单列纵向补 `margin-top`，换行时子元素加 margin、容器加等量负 margin 抵消首尾空隙。`MutationObserver` + `requestIdleCallback` 分批处理新增节点，`WeakMap` 去重。该机制同时覆盖业务内联 `gap` 与 antd Space / Grid 的运行时 `rowGap` / `columnGap`，无需改造 333 处调用点。
- **`:focus-visible`**：5 条规则改为 `:focus`；Chrome 81 上鼠标点击也会出现焦点样式，作为可接受降级，不引入额外 polyfill。
- **polyfill 采用定向模块且按消费方加载**：不使用全量 `core-js/stable`，也不用 `plugin-legacy` 的 `modernPolyfills`（后者会把 Babel polyfill 链引入构建）。实测入口常驻 `structured-clone` 会让主入口超预算 10 KiB（连带 Map/Set internals），而它的唯一调用点已被 `typeof` 守卫，故移除；`at` / `has-own` 下沉到懒加载消费模块，入口回到预算内。`reportError` 同样已由 `typeof reportError === 'function'` 守卫，不补。

### 7. 测试清单

**判定层（单测）**：

- `themeMix`：77 类表达式的计算结果；`transparent` 的预乘 alpha；RGB 三元组；`var(--x, fallback)` 与嵌套 `var()`；主题切换后变量重算。
- `flexGap`：特性探测（含「grid gap 为真但 flex gap 为假」的用例）、`gap` / `rowGap` / `columnGap` 解析、行 / 列 / wrap 三类间距规则、已有 margin 叠加、grid 跳过、kill switch。
- `ThemeProvider`：`StyleProvider` 包裹关系、body class 与 mix 变量在首帧前写入。
- polyfill 边界：`polyfills.ts` 只含 `at` / `has-own`，不含 `structured-clone`；四个消费模块都必须静态导入它，入口 `main.tsx` 不得常驻导入。
- 导出垫片：`ensureIntlSegmenter()` 在原生 `Intl.Segmenter` 存在时零加载，缺失时才加载 `@formatjs/intl-segmenter`。

**构建层**：

- `pnpm build` 成功，且 `check-browser-compat.mjs` 退出 0：target 为 `chrome81`；`dist/assets/*.css` 无 `:where(`、`padding-inline` / `margin-inline` / `inset:`；每条 `color-mix(` 前存在 `var(--cn-mix-` 兜底；`src` 中除 `themeMix.ts` 外无直接 `color-mix(`，无新增 `:focus-visible`。
- `pnpm bundle:budget` 不超限；超限先拆 lazy，再按 `--update --reason` 记录。

**e2e（现代 Chromium）**：

- 既有 Playwright 全量用例保持全绿。
- 关键布局尺寸断言：顶部导航、表格工具栏、antd Space 组、Grid 行、卡片画廊，确认兜底变量与垫片未改变现代浏览器表现。
- `tests/e2e/critical/browser-compat.spec.ts` 反向断言旧内核机制不介入（无 `cn-no-flex-gap`、`--cn-mix-*` 为空、原生 `color-mix` 渐变生效）。

**e2e（Chromium 81）**：

- 登录、工作区列表、数据表打开与单元格编辑、视图切换（grid / gallery / kanban / chart）、文档打开、PDF 与截图导出。
- 10 套主题逐一切换并截图，对照现代 Chromium。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 构建基线常量与 target、浏览器声明、定向 polyfill、antd `StyleProvider` / 逻辑属性 / `inset`、`:focus-visible` 替换、静态门禁骨架 | 低：均为确定性配置与官方兼容开关 |
| **P1** | `color-mix` 兜底变量与 66 项注册表、flex-gap shim、10 套主题视觉核对 | 中高：shim 的 margin 叠加与性能是主要风险 |
| **P2** | Chromium 81 冒烟脚本与定时 CI、导出路径验证、包体基线复核、README 基线声明 | 中：老内核与 `puppeteer-core` 的 CDP 兼容性需实测 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 单包 + `chrome81` esbuild 降级 + 定向 polyfill + 运行时 CSS 兜底；构建目标由 `BROWSER_BASELINE` 单一常量提供 | Chrome 81 支持原生 ESM；实测 `--target chrome81` 构建成功；单一常量避免 vite / 静态检查 / 冒烟三处 target 漂移 | `@vitejs/plugin-legacy` 双包（体积与复杂度翻倍，且解决不了 CSS-in-JS）；只改 target（API / CSS 仍会失败） | `frontend/vite.config.ts`、`frontend/scripts/browser-baseline.mjs` |
| D2 | antd 样式兼容 | `StyleProvider hashPriority="high"` + `legacyLogicalPropertiesTransformer` | 官方兼容开关；transformer 已覆盖 `inset` 与逻辑属性 | 手写覆盖 antd 全部组件样式（不可维护）；降级 antd 版本（风险与收益不匹配） | `frontend/src/theme/ThemeProvider.tsx` |
| D3 | 运行时 API | 定向 `core-js` 模块由消费模块静态导入 + `@formatjs/intl-segmenter` 按需加载；不补带 `typeof` 守卫的 `structuredClone` | 只补实际出现且未被守卫的 API；ESM 依赖先执行，消费方导入即可保证时序；入口常驻会让主入口超预算 10 KiB | 全量 `core-js/stable`（体积不可控）；入口常驻（挤占关键 chunk 预算）；`plugin-legacy` `modernPolyfills`（引入额外 Babel 链） | `frontend/src/compat/polyfills.ts`、`frontend/src/pages/import-export/ImportExportDialog/exportPdf.ts` |
| D4 | `color-mix` | 原生声明为主，运行时按主题预计算 `--cn-mix-*` 兜底；预乘 alpha 插值 | 现代浏览器零变化；10 套主题与动态表达式都能精确计算；`getComputedStyle(body)` 可读主题变量 | 构建期 PostCSS 插件（无法解析运行时主题变量与 10 套主题）；直接删 `color-mix` 改静态色（破坏现代浏览器与主题） | `frontend/src/theme/themeMix.ts`、`frontend/src/index.css` |
| D5 | flex gap | 仅在不支持时加载运行时 shim，读取计算样式补子元素 margin；探测用真实 flex 布局实测 | 一套机制覆盖作者 CSS、内联样式与 antd 运行时 CSS；不改 333 处调用点 | 逐处改 margin（成本与回归面过大）；只用 `postcss-flex-gap-polyfill`（覆盖不了内联与 antd 运行时样式）；用 `@supports` 探测（Chrome 81 grid gap 导致误判）；不处理（与 C4 冲突） | `frontend/src/compat/flexGap.ts` |
| D6 | `:focus-visible` | 5 条规则改为 `:focus` | 规则少、收益低；`:focus` 在 Chrome 81 可用 | 引入 focus-visible polyfill（额外体积与事件监听） | `frontend/src/index.css` |
| D7 | 回归验证 | 每次构建静态门禁 + 定时 Chromium 81 冒烟 | 静态门禁秒级可判定；真实老内核是 API / CSS 的唯一权威验证 | 只做静态扫描（抓不到依赖内部 API 与 CSS-in-JS 运行时）；只靠人工（不可持续） | `frontend/scripts/check-browser-compat.mjs`、`frontend/scripts/chrome81-smoke.mjs` |
| D8 | 现代浏览器策略 | 原生 `color-mix` / 原生 flex gap 保持为主路径，兜底只服务旧内核 | 满足 I3，避免为旧浏览器拖慢现代浏览器 | 全局替换为 fallback 实现（现代浏览器回退、维护成本高） | `frontend/src/index.css`、`frontend/src/compat/flexGap.ts` |
| D9 | 老浏览器回归工具 | `puppeteer-core` + 固定 Chromium revision，独立于 Playwright 套件 | Playwright 仅保证其内置 Chromium；CDP 对旧内核兼容面更宽 | 直接把 Chromium 81 塞进 Playwright project（官方不支持，注入脚本可能调用新 API） | `frontend/scripts/chrome81-smoke.mjs` |
| D10 | 兼容增量的体积 | 不新增豁免；超限按现有流程先拆 lazy，再 `--update --reason` 记录 | 兼容层是常驻代码，若不约束会长期抬升首屏 | 为兼容层开预算白名单（把门禁变成橡皮图章） | `frontend/scripts/bundle-budget.json` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：Chromium 81 可正常打开并与现代浏览器保持主题色 / 间距一致；兼容缺口有构建期与真实浏览器双层门禁；现代浏览器继续走原生实现，不受旧内核拖累。
- **负向**：新增 `core-js`、`@ant-design/cssinjs`、`@formatjs/intl-segmenter` 与 `puppeteer-core` 依赖；入口需先执行 polyfill；`StyleProvider` 提升 antd 选择器特异性，可能暴露既有覆盖规则问题；`color-mix` 注册表需随主题表达式维护。
- **风险与缓解**：
  - flex-gap shim 在大表格 / 高频 DOM 更新下可能带来性能开销 → 仅旧内核加载、`requestIdleCallback` 分批、`WeakMap` 去重、旧内核冒烟加入性能断言与 kill switch。
  - Chromium 81 下载依赖外网 → 缓存 + 定时 CI，不作为每次提交必跑；静态门禁始终保留。
  - `puppeteer-core` 与 Chromium 81 的 CDP 兼容性 → P2 首日实测；若个别 API 不可用，降级为 `--dump-dom` + 截图 + console 日志的最小冒烟，仍满足 C1 / C5 的核心断言。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 前端静态门禁 | `frontend/package.json`、`Makefile` | 新增 `check-browser-compat` 并挂在 `pnpm build` 之后 | ADR 0026 |
| 包体预算 | `frontend/scripts/bundle-budget.json` | 兼容性增量不得绕过预算；超限先拆 lazy，再记录理由 | ADR 0026 沿用现有 bundle-budget 流程 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/scripts/browser-baseline.mjs`、`frontend/vite.config.ts`、`frontend/.browserslistrc`、`frontend/src/compat/polyfills.ts`、`frontend/src/main.tsx`、`frontend/src/theme/ThemeProvider.tsx`、`frontend/src/index.css`、`frontend/scripts/check-browser-compat.mjs`、`frontend/package.json` | `frontend/src/compat/polyfills.test.ts`、`frontend/src/theme/ThemeProvider.compat.test.tsx` | 5496668a |
| P1 | 已落地 | `frontend/src/theme/themeMix.ts`、`frontend/src/compat/flexGap.ts`、`frontend/src/compat/flexGapSupport.ts`、`frontend/src/compat/index.ts`、`frontend/src/index.css`、`frontend/src/pages/`（22 处静态色改为 cn-mix 变量） | `frontend/src/theme/themeMix.test.ts`、`frontend/src/compat/flexGap.test.ts` | 5496668a |
| P2 | 已落地 | `frontend/scripts/chrome81-smoke.mjs`、`.github/workflows/chrome81-smoke.yml`、`frontend/scripts/check-browser-compat.mjs`、`frontend/src/pages/import-export/ImportExportDialog/exportPdf.ts`、`README.md` | `frontend/src/pages/import-export/ImportExportDialog/exportPdf.test.ts`、`frontend/tests/e2e/critical/browser-compat.spec.ts` | 5496668a |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。

## 交接（会话结束更新）

- 当前阶段：全期落地（P0-P2），等待人工确认是否把 `Status` 改为 `Implemented`
- 已完成：
  - P0：构建基线常量 / target / `.browserslistrc` / 定向 polyfill / `StyleProvider` 降级 / `:focus-visible` 替换 / 静态门禁并挂到 `pnpm build`
  - P1：`themeMix.ts` 77 项注册表 + `index.css` 94 处 `--cn-mix-*` 兜底 + 22 处静态 TSX 色改变量 + 动态色走 `mixColor()`；flex-gap 探测与 shim（汇总于 `initCompat()`）；静态门禁切 `--strict`
  - P2：`chrome81-smoke.mjs`（`puppeteer-core` + 固定 Chromium 81 r737027，覆盖登录 / 表 / 视图 / 文档 / PDF 导出 / 10 套主题截图）与每日定时 CI；导出路径 Intl.Segmenter 按需垫片；现代 Chromium 反向断言 e2e；README / CONTEXT 浏览器基线声明
- 下一步：无代码项。首次真实 Chromium 81 冒烟依赖 `.github/workflows/chrome81-smoke.yml` 的定时或手动触发（本地可 `CNDB_CHROME81_PATH=… pnpm e2e:chrome81`）
- 已知坑：
  - polyfill 不能回退成入口常驻：`structured-clone` 连带 Map/Set internals 会让主入口超预算 10 KiB；`at` / `has-own` 已下沉到懒加载消费模块（D3）。
  - 主入口当前 +2.9%（180.77 KiB / 上限 184.45 KiB，容差内），增量含 target 降级 helper 与兼容层；`GridPage` +3.7% 同属慢涨，后续若超限仍按 D10 先拆 lazy。
  - `hashPriority="high"` 提升了 antd 选择器特异性，P1 视觉核对时重点看 `index.css` 里对 `.ant-*` 的覆盖是否被反压。
  - flex gap 是最大成本项；Chrome 81 支持 grid gap，不能用 `@supports (gap: 1px)` 判断；Playwright 对老内核兼容性未知，P2 使用 `puppeteer-core` + CDP；Chromium 81 下载需外网，放定时 CI（快照按 revision 缓存）。
  - 老内核冒烟的主题列表由 `check-browser-compat.mjs` 与 `src/theme/meta.ts` 对表，新增主题必须同步 `chrome81-smoke.mjs`，否则构建期报错。
  - 本机下载 Chromium 81 快照走 Google 存储，研发网络可能卡在 TLS（实测本次未完成下载）；本地可复用已有安装 `CNDB_CHROME81_PATH=… pnpm e2e:chrome81`，否则以定时 CI 结果为准。
- 最近一次全绿：`make flow`（check-fast + 后端 5315 passed / 8 skipped）、前端 `pnpm test`（181 files / 2187 tests）、`make frontend-coverage`（核心集合 lines 97.69% / branches 100%，全局 82.80%）、`pnpm build`（含 `check-browser-compat --strict`）、`pnpm bundle:budget`（全部关键 chunk 在预算内）、`pnpm e2e --project=chromium-authed tests/e2e/critical/browser-compat.spec.ts` @ 2026-10-24
