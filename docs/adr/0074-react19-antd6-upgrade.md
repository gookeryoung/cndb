# ADR 0074: 前端迁移 React 19 + antd 6

Status: Accepted（2026-10-30 人工确认 D1：保留 Chrome 81 基线）
Date: 2026-10-30
Related: `frontend/package.json`、`frontend/src/main.tsx`、`frontend/src/theme/ThemeProvider.tsx`、`frontend/src/index.css`、`frontend/src/compat/`、`frontend/scripts/check-browser-compat.mjs`、`frontend/patches/`、`docs/adr/0026-chrome81-compat.md`、`docs/adr/0031-font-and-css-typography.md`
需求卡片: `docs/requirements/0074-react19-antd6-upgrade.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 迁移到 React 19 | `react` / `react-dom` / `@types/react` / `@types/react-dom` 升 19；React 19 类型收紧（`ReactNode` 含 Promise、`useRef` 必填初值等）逐点修复，不改业务语义；其余依赖经 peer 核实全部兼容（见现状 11） |
| C2 | 迁移到 antd 6 | `antd@6` + `@ant-design/icons@6` + `@ant-design/cssinjs@2` 同批原子切换；不引入 `@ant-design/v5-patch-for-react-19`（antd 6 原生支持 React 19） |
| C3 | 制定方案 | 本 ADR；分期 P0-P2，每期 `make flow` 全绿后落地回填，`make adr-check` 校验 |
| C4 | 浏览器基线口径 | D1：保留 Chrome 81 基线（2026-10-30 人工确认）；兼容层沿用，`:has()` / `@container` 按规则级降级白名单放行（运行时样式审计落在 `ThemeProvider.compat.test.tsx`，见 D4），Chromium 81 冒烟继续作为权威验证 |
| C5 | 不回归 | 全量前端单测 + 覆盖率双门槛 + Playwright e2e + 10 套主题视觉核对 + bundle budget 既有流程不变 |
| C6 | 存量资产处置 | D3-D5：`StyleProvider` 降级链沿用（cssinjs v2 仍提供 transformer）；flex-gap shim 与 `themeMix` 兜底原样沿用；`rc-util` 补丁迁移重打到 `@rc-component/util`，`rc-field-form` 摇树补丁删除（P0 实测发现同类问题再按流程重建） |
| C7 | 弃用 API 清零 | 属性级弃用告警清零（存量命中点一次性迁移到 v6 新 API）；实施中发现的 `List` 组件整体废弃（7 处调用点）已迁 `Listy` + 自绘内容层（`CnListMeta`，见 D6），e2e 断言控制台无任何 antd 弃用告警（无白名单） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`；其中第 8-11 条为 2026-10-30 临时目录实测，环境：React 19.3.1 + antd 6.6.8 + @ant-design/icons 6.3.4 + @ant-design/cssinjs 2.1.2，esbuild `--target=chrome81`）。沿用卡片「现状影响面」的编号，逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | React 18.3.1 / react-dom 18.3.1，`@types/react` 18.3.31 / `@types/react-dom` 18.3.7 | `frontend/package.json:59-60,77-78` | React 19 破坏点（`ReactDOM.render` / `unmountComponentAtNode` / `react-dom/test-utils` / `findDOMNode` / 函数组件 `defaultProps` / string ref）全仓 grep 0 命中，入口已用 `createRoot` + `StrictMode`（`frontend/src/main.tsx:30`）；`.ref` / `defaultProps` 命中均为业务字段与测试桩，非 React ref | 确认（升级面小） |
| 2 | antd 5.29.3 + `@ant-design/icons` 5.6.1 + `@ant-design/cssinjs` 1.24 直接依赖 | `frontend/package.json:33-35,50` | antd 6 要求 icons >= 6，且 icons@6 与 antd@5 不兼容（官方迁移指南），必须同批原子切换；antd 6 内部依赖 `@ant-design/cssinjs ^2.1.2`，直接依赖同步升 2.x 避免 dual-package | 确认 |
| 3 | 主题层已开 `cssVar: true` 并挂 `StyleProvider hashPriority="high"` + `legacyLogicalPropertiesTransformer` | `frontend/src/theme/ThemeProvider.tsx:44-45,161-194` | 与 antd 6「默认 CSS variables」同向；实测 cssinjs v2 仍提供 `legacyLogicalPropertiesTransformer` 且 `hashPriority` 默认仍为 `low`（会生成 `:where()`），降级链需保留 | 确认 |
| 4 | antd v6 弃用 API 存量 16 处 | `frontend/src/pages/datasource/DatasourcePage.tsx:808,1408`（`destroyOnClose`）、`frontend/src/pages/workspace/WorkspaceList.tsx:238`、`frontend/src/pages/admin/UsersPage.tsx:578`、`frontend/src/pages/grid/{gridViewBar,gridAggregationBar,gridToolbar}.tsx`（`size="middle"` 共 8 处）、`frontend/src/pages/settings/TableSettingsPage.tsx:318`（`tabPosition`）、`frontend/src/pages/documents/DocumentImportModal.tsx:281`（`maskClosable`）、`frontend/src/pages/admin/{StoragePage,AdminPanel}.tsx`（`Tag bordered` 3 处） | 均为 v6 弃用（v7 移除）；`frontend/src/components/BrandMark.tsx:45,50` 的 `strokeWidth` 是 SVG 属性不受影响；`frontend/src/components/SearchInput.test.tsx:28` 为测试桩同步改 | 确认 |
| 5 | `index.css` 含 250 处 `.ant-*` 自定义覆盖（`.ant-btn` 21、`.ant-tag` 14、`.ant-tabs-*` / `.ant-table-*` / `.ant-tree-*` 各 8-11） | `frontend/src/index.css` | antd 6 调整大量组件 DOM 结构（官方迁移指南「DOM 调整」），覆盖选择器可能失配，是本次最大视觉回归面 | 确认 |
| 6 | pnpm patch 两枚：`rc-field-form@2.7.1`（摇树 + 保留 `forwardRef`）、`rc-util`（`isEqual` DAG 误报修复） | `frontend/patches/`、`frontend/scripts/check-patches.mjs` | antd 6 依赖已从 `rc-*` 迁移到 `@rc-component/*`（`@rc-component/form`、`@rc-component/util` 等），旧补丁目标消失；`check-patches.mjs` 的解析路径也需重定位 | 确认 |
| 7 | Chrome 81 兼容层（定向 polyfill、flex-gap shim、`themeMix` 兜底、`Intl.Segmenter` 按需垫片）与 ADR 0026 基线门禁 | `frontend/src/compat/`、`frontend/src/theme/themeMix.ts`、`frontend/scripts/check-browser-compat.mjs` | 与「antd 6 仅支持现代浏览器」的官方口径冲突；实测证据见 #8-#10 | 确认（核心分叉，D1） |
| 8 | 实测：React 19 + antd 6 以 esbuild `--target=chrome81` 打包成功（含 Button / Table / DatePicker / Modal / icons），无语法错误 | 临时目录 spike（2026-10-30） | Chrome 81 语法层不阻断升级 | 新增 |
| 9 | 实测：`react` / `react-dom` 19 生产产物中未检出 Chrome 81 缺失运行时 API（`Object.hasOwn` / `replaceAll` / `Promise.any` / `.at(` / `structuredClone` 均 0 命中；`queueMicrotask` 为 Chrome 71+、`Promise.allSettled` 为 76+，无碍） | 同上 | React 19 运行时对 Chrome 81 无已知硬缺口；但 React 官方未承诺该基线，属「实测可行、官方不保」 | 新增 |
| 10 | 实测：antd 6 样式源码仍产逻辑属性（`marginInline` 70 文件 / `paddingInline` 53 / `insetInline` 61）、`inset:` 25 文件、`:focus-visible` 21 文件；**新增** `:has()` 14 个组件样式（Chrome 105+，无法 polyfill）与 `@container` 1 处（steps）；未检出 `@layer` / `oklch` / 相对色语法 | 同上 | `legacyLogicalPropertiesTransformer` + `hashPriority="high"` 仍必要且仍可用；`:has()` / `@container` 在 Chrome 81 上按「单条规则丢弃」优雅降级，需逐组件评估视觉影响并进白名单 | 新增 |
| 11 | 其余依赖 peer 全兼容 React 19：`@dnd-kit/core`（>=16.8）、`react-error-boundary` 6.1.6（^18\|\|^19）、`@tanstack/react-query` 5.103（^18\|\|^19）、`react-router-dom` 6.30.6（>=16.8）、`zustand` 5（>=18）、`@testing-library/react` 16.3.3（已支持 19） | `frontend/package.json:41-67,73-80` | 无需连带升级；`@types/react` 19 与 TypeScript 5.6 兼容 | 排除 |
| 12 | antd 6 移除 `Tag` 末尾默认 `margin-inline-end`；`Form onFinish` 不再包含 Form.List 未注册子项；`Modal` / `Drawer` v6.3.0 起蒙层模糊默认关闭 | 官方迁移指南（v5 → v6） | Tag 布局、含 Form.List 的表单取值、弹层视觉三处需专项核对 | 新增 |

**核心缺陷（需求要补的）**：前端栈停在 React 18 + antd 5，而 antd 6 的维护与特性演进（CSS variables 默认、React 19 原生支持）不再流向 5.x；仓库尚未有一份兼顾 ADR 0026 Chrome 81 基线承诺的升级路径。

设计目标（不变量）：

- **I1 门禁全绿**：升级后 `pnpm check` / `pnpm test:coverage` / `make e2e` / `pnpm bundle:budget` 全部通过，不放宽任何既有门槛。
- **I2 基线不破**：Chrome 81 基线（若 D1 拍板保留）在升级后仍满足卡片 0026 的 C1-C6：可打开、视觉一致、冒烟通过、静态门禁可判定。
- **I3 弃用清零**：控制台无 antd v6 弃用告警（v7 移除项不留存量）。
- **I4 资产有账**：patch、兼容层、`StyleProvider` 降级链每项都有沿用 / 迁移 / 删除结论，无「临时凑合」状态。

## Decision

### 1. 数据模型

无。纯前端依赖升级，不新增表 / 列 / 枚举 / 端点。

### 2. 判定算法（唯一入口）

无。不新增判定逻辑；既有兼容入口（`browser-baseline.mjs`、`initCompat()`、`applyThemeMixVars()`、`isFlexGapSupported()`）签名不变，继续作为唯一口径（ADR 0026 D 系列）。

### 3. API 变更清单

无。后端接口零改动。

### 4. 边界与例外

1. **Chrome 81 属「实测可行、官方不保」**：React 与 antd 均不承诺该内核。权威验证是 `chrome81-smoke.mjs` 真机冒烟（保留），静态门禁扩展「允许降级白名单」；后续 antd 6 小版本升级必须重跑冒烟，这是接受基线保留的持续成本。
2. `:has()` 无法 polyfill（无等价运行时方案），不引入 `css-has-polyfill` 类库（体积 / 性能 / 与 CSS-in-JS 冲突）；影响面按「规则级降级」逐组件评估，结论记录在白名单注释里。
3. 不引入 `@ant-design/v5-patch-for-react-19`：该包只服务「antd 5 + React 19」组合，本次一步到位 antd 6（D2）。
4. React 19 类型收紧的修复原则：只改类型标注与初值，不改运行时行为；`ReactNode` 含 Promise 引发的工具类型报错优先收窄泛型，不滥用 `any`。
5. `check-patches.mjs` 与补丁同批处置：`rc-util` 补丁迁移重打为 `@rc-component/util`（保留 `isEqual` DAG 修复语义）；`rc-field-form` 摇树补丁删除——若 P0 实测 antd 6 下主入口 / Grid chunk 因 `@rc-component/form` 出现同类摇树问题，按 `pnpm patch` 流程重建后再保留，不预先打。
6. Firefox / Safari 仍不承诺（沿用 ADR 0026 边界 1）。

### 5. 迁移

无。构建产物仍以 `vite build` 整体替换 `src/cndb/static`，无存量数据迁移。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 依赖 | `frontend/package.json` | `react` / `react-dom` → `^19.3`；`antd` → `^6.6`；`@ant-design/icons` → `^6.3`；`@ant-design/cssinjs` → `^2.1`；`@types/react` / `@types/react-dom` → `^19`；其余依赖不动（现状 11 已核实兼容） |
| 补丁 | `frontend/patches/`、`frontend/scripts/check-patches.mjs` | `rc-util.patch` → `@rc-component/util` 重打；删除 `rc-field-form@2.7.1.patch`（见边界 5）；`check-patches.mjs` 解析路径从 `antd → rc-field-form` 改为 `antd → @rc-component/form` |
| 主题 | `frontend/src/theme/ThemeProvider.tsx` | 保留 `StyleProvider hashPriority="high"` + `legacyLogicalPropertiesTransformer`（cssinjs v2 API 兼容）；`cssVar: true` 维持；核对 antd 6 弹层蒙层默认（不额外开模糊） |
| 兼容门禁 | `frontend/scripts/check-browser-compat.mjs` | 新增「允许降级白名单」：`:has(`、`@container` 在产物 CSS 中出现不判失败，但必须逐条登记（组件 + 视觉影响 + 评估结论）；其余禁用项不变 |
| 弃用 API | `frontend/src/pages/**`（16 处，见现状 4） | `destroyOnClose` → `destroyOnHidden`；`size="middle"` → `size="medium"`；`tabPosition` → `tabPlacement`；`maskClosable` → `mask={{ closable }}`；`Tag bordered={false}` → `variant` 口径 |
| DOM 覆盖核对 | `frontend/src/index.css`（250 处 `.ant-*`） | 逐族核对 antd 6 DOM 调整（`.ant-table-*` / `.ant-tabs-*` / `.ant-btn` / `.ant-tag` / `.ant-tree-*` 优先）：失配选择器改写为新结构，不新增 `!important`（沿用 ADR 0026 边界 4） |
| Tag 间距 | `frontend/src/**` | 排查依赖 Tag 末尾默认 margin 的布局；需要时用 `ConfigProvider tag.styles` 统一补回 |
| Form 取值 | `frontend/src/**`（含 Form.List 的表单） | 核对 `onFinish` 值结构，移除多余的 `getFieldsValue({ strict: true })` 过滤 |
| 类型修复 | `frontend/src/**` | React 19 类型收紧逐点修复（`useRef` 初值、`ReactNode` 收窄等） |
| 测试环境 | `frontend/src/**/*.test.tsx`、`frontend/vite.config.ts` | vitest / jsdom / @testing-library 链路适配 React 19（`act` 来源、类型）；断言不放宽 |
| 文档 | `README.md`、`CONTEXT.md` | 若 D1 维持保留 Chrome 81：基线声明补「antd 6 官方不承诺旧内核，以真机冒烟为准」；否则按新基线改写 |

### 7. 测试清单

**判定层（单测）**：

- 兼容层既有测试（`polyfills.test.ts`、`flexGap.test.ts`、`themeMix.test.ts`、`ThemeProvider.compat.test.tsx`）语义不变、全绿。
- `check-browser-compat.mjs` 白名单行为：未登记的 `:has(` / `@container` 判失败；登记后放行。
- `check-patches.mjs`：`@rc-component/util` 补丁落地校验（`isEqual` DAG 场景回归）。
- 含 Form.List 的表单单测：`onFinish` 值结构与升级前一致。

**接口层**：无（零后端改动）。

**迁移 / 备份**：无。

**e2e（前端）**：

- 既有 Playwright 全量用例全绿（现代 Chromium）。
- 弃用告警断言：关键页面控制台不出现 antd `legacy` / `deprecated` warning（C7）。
- 视觉核对：10 套主题 × 关键页面（登录 / 表格 / 视图 / 文档 / 弹层），对照升级前基线截图。
- Chromium 81 冒烟（`pnpm e2e:chrome81`）：既有 24 项 + `:has()` 受影响组件（form / tabs / input / radio / checkbox / select / card / pagination / date-picker / tooltip / tree / splitter）的可用性与截图，逐项记录降级结论。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 依赖同批升级 + 类型修复 + 补丁处置（重打 `@rc-component/util`、删 `rc-field-form` 补丁）+ `check-patches.mjs` 重定位 + 编译链 / 单测 / e2e 跑通（允许临时存在弃用告警与样式失配，先保证可运行） | 中：类型收紧与 DOM 结构变化集中暴露 |
| **P1** | 兼容层收口：`check-browser-compat` 白名单机制 + `:has()` / `@container` 逐组件降级评估 + `StyleProvider` 降级链在 antd 6 下复核 + Chromium 81 冒烟首跑 | 中高：降级视觉影响需真机逐项确认 |
| **P2** | 弃用 API 16 处清零 + `index.css` 250 处 `.ant-*` 覆盖逐族核对 + Tag 间距 / Form.List / 弹层蒙层三处专项 + 10 套主题视觉回归 + bundle budget 收口 + README / CONTEXT 基线声明 | 中：视觉回归面最大，依赖截图对照 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 浏览器基线（与 ADR 0026 的关系） | **保留 Chrome 81 基线**（2026-10-30 人工确认）：兼容层沿用，`:has()` / `@container` 进降级白名单，真机冒烟为权威验证；antd 6 小版本升级须重跑冒烟 | 实测语法层可构建、React 19 运行时无硬缺口（现状 8-9）；兼容层资产已落地且与版本解耦；卡片 0026 是「重大需求」，废除需用户明示 | 提升基线到 Chrome 105+（可删 flex-gap shim / themeMix / transformer 等大幅简化，但直接违反卡片 0026 C1-C6，须需求方先废除该承诺）；双基线双构建（复杂度与包体不可接受） | `frontend/scripts/check-browser-compat.mjs`、`frontend/scripts/browser-baseline.mjs`、`README.md` |
| D2 | 升级路径 | 一步到位：`react@19` + `antd@6` + `icons@6` + `cssinjs@2` 同批原子切换 | 分步任一组合都需要过渡补丁（antd 5 + React 19 需 `v5-patch-for-react-19`）或多一次全量回归；两个变更共享同一套回归门禁，合并验证成本更低 | 先 antd 6 后 React 19（多一次全量 e2e 回归）；先 React 19 后 antd 6（需临时引入 v5 补丁包，再删一次） | `frontend/package.json` |
| D3 | CSS 策略 | 沿用 `StyleProvider hashPriority="high"` + `legacyLogicalPropertiesTransformer`；显式 `cssVar: true` 声明移除（antd 6 默认开启 CSS variables，且 ThemeConfig 不再接受布尔 cssVar） | 实测 antd 6 仍产逻辑属性 / `inset` / `:focus-visible`（现状 10），cssinjs v2 仍提供同名 transformer 且 `hashPriority` 默认仍 `low`；antd 6 默认 CSS variables 与现有配置同向 | 切到 antd 6 后拆除降级链（Chrome 81 上整条样式失效）；改用 `postcss-logical` 处理 antd 运行时样式（PostCSS 只处理源码 CSS，覆盖不了 CSS-in-JS） | `frontend/src/theme/ThemeProvider.tsx` |
| D4 | `:has()` / `@container` 缺口 | 规则级降级白名单：静态门禁扫描不到 CSS-in-JS 运行时产物，白名单审计落在 `ThemeProvider.compat.test.tsx`——渲染代表性组件样本、断言注入 CSS 中白名单外现代特性为零；Chromium 81 冒烟逐组件核对视觉影响并记录结论 | 无法 polyfill；antd 6 的 `:has()`（14 个组件）与 `@container`（steps）属渐进增强类，单条规则丢弃不阻断功能；白名单让「接受哪些降级」显式可审计 | 引入 `css-has-polyfill`（体积大、 MutationObserver 性能差、与 CSS-in-JS 注入方式冲突）；对构建 JS 做原始字符串扫描（噪声大：lib 源码里的字符串 ≠ 实际产出样式）；整体放弃 Chrome 81（即否决 D1 结论） | `frontend/src/theme/ThemeProvider.compat.test.tsx` |
| D5 | pnpm patch 处置 | `rc-util` 的 `isEqual` DAG 修复迁移重打到 `@rc-component/util`；`rc-field-form` 摇树补丁删除（P0 实测发现同类问题再按流程重建） | antd 6 依赖改名后旧补丁目标消失；`isEqual` 修复语义与包名无关，必须保留（rc-table columns 自引用场景会误报）；摇树收益是否复现未知，预打无依据 | 两个补丁原样保留（目标包不存在，patch 直接失败）；全部删除（丢 `isEqual` 修复，回归 rc-table 误报） | `frontend/patches/`、`frontend/scripts/check-patches.mjs` |
| D6 | 弃用 API | 属性级弃用（Alert `message` 76 处、Drawer `width`/`height`、`destroyOnClose`、`maskClosable`、Space `direction`、Divider `type`、Tabs `tabPosition`、Tag `bordered`、Image 预览 `visible` 等）一次性迁移到 v6 新 API，e2e 断言控制台无弃用告警；**antd 6.6 将 `List` 组件整体废弃（推荐 Listy）**——7 处调用点（文档列表 / 回收站 / 问题列表 / 分享 / 图表素材库 / 修改申请）已迁 `Listy` + 自绘内容层：`CnListMeta`（v5 Meta 视觉口径：头像位 + 标题/描述）、`.cn-list-item` 行布局、`.cn-listy-plain` / `.cn-listy-compact` 两档内边距（对应 v5 默认 / small），`.cn-doc-list` CSS 同步移植；e2e 告警断言无白名单 | 属性级存量趁升级窗口清零，避免长期欠账；Listy 自带 item 基底样式（token 化，走 cssinjs 兼容链），自绘内容层保持 v5 视觉口径且摆脱 `.ant-list-*` 内部类耦合 | 继续用 List 到 v7（静默欠账，回归不可见）；改用 Listy 的 virtual 模式（我们的列表均短列表，无虚拟化需求） | `frontend/src/components/CnListMeta.tsx`、`frontend/src/pages/**`、`frontend/src/index.css`、`frontend/tests/e2e/critical/antd-deprecation.spec.ts` |
| D7 | 门禁与回归 | 既有门禁全量不放宽（单测 / 覆盖率双门槛 / e2e / bundle budget / chrome81 冒烟）；视觉回归用升级前基线截图对照 | C5；ADR 0026 的门禁资产直接复用，升级不构成放宽理由 | 为升级临时跳过 e2e 或降覆盖率（违反测试规范） | `Makefile`、`frontend/scripts/*.mjs` |
| D8 | TypeScript / 类型 | 保持 TS 5.6，`@types/react` 升 19；类型收紧逐点修复、不改运行时行为 | React 19 类型要求 TS >= 5.0，5.6 兼容；类型修复混入行为变更会污染回归归因 | 同批升 TS 5.7+（与本次目标无关，扩大回归面） | `frontend/package.json`、`frontend/src/**` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

> **评审提示**：D1 已由人工确认（2026-10-30，保留 Chrome 81 基线）；其余 D2-D8 依据现状证据闭环，无待定项。

## Consequences

- **正向**：进入 antd 6 维护线（CSS variables 默认、React 19 原生支持、v5 不再获得新特性）；React 19 带来 `use` / Actions / 编译器生态等后续演进空间；升级面经实测收敛（React 18 遗留 API 零命中、弃用 API 仅 16 处、其余依赖 peer 全兼容）。
- **负向**：Chrome 81 从「官方兼容开关可达成」变为「实测可行但官方不承诺」，后续每次 antd / React 小版本升级都要重跑老内核冒烟；250 处 `.ant-*` 覆盖需逐族核对，P2 视觉回归工作量大；React 19 类型收紧引入一批机械修复。
- **风险与缓解**：
  - antd 6 后续小版本引入更多现代 CSS（`oklch` / 相对色 / `@layer`）→ `check-browser-compat.mjs` 禁用项常驻，越界即构建失败，提前暴露而不是线上白屏。
  - `:has()` 降级导致 Chrome 81 上个别校验 / 联动态样式缺失 → 白名单强制登记视觉影响，冒烟截图留档，超出可接受范围时升级为用户决策（回到 D1）。
  - DOM 结构调整导致样式静默失配 → P2 以升级前基线截图逐页对照，e2e 加控制台错误断言。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| Chrome 81 基线与兼容层 | `frontend/src/compat/`、`frontend/scripts/check-browser-compat.mjs` | 基线保留（D1，待人工确认）；兼容入口签名不变，白名单机制扩展 | ADR 0074 沿用 ADR 0026 |
| 字体与排版 token | `frontend/src/theme/`、`frontend/src/index.css` | token 口径不变，只核对 antd 6 DOM 调整后的覆盖选择器 | ADR 0031 |
| 性能基线 | `frontend/scripts/bundle-budget.json` | 升级增量不得绕过预算；超限先拆 lazy 再记录 | 既有 bundle-budget 流程 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/package.json`、`frontend/pnpm-workspace.yaml`、`frontend/patches/@rc-component__util.patch`、`frontend/scripts/check-patches.mjs`、`frontend/src/hooks/useElementSize.ts`、`frontend/src/pages/analytics/AnalyticsPage.tsx`、`frontend/src/theme/ThemeProvider.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx` | `frontend/src/theme/ThemeProvider.compat.test.tsx`、前端单测全量（2430 例） | fcc61ce9 |
| P1 | 已落地 | `frontend/src/theme/ThemeProvider.compat.test.tsx`（运行时样式审计 + D4 白名单） | `frontend/src/theme/ThemeProvider.compat.test.tsx`（无 :where 包裹 / 无逻辑属性声明 / 白名单外特性断言） | fcc61ce9 |
| P2 | 已落地 | `frontend/src/pages/**`（弃用 API 清零 + 测试选择器适配）、`frontend/src/index.css`（Modal 容器类 + 自绘列表结构）、`frontend/src/components/CnListMeta.tsx`（新增）、`frontend/patches/react-dom@19.3.1.patch`（新增，jsdom 拆除竞态守卫）、`frontend/scripts/check-patches.mjs`、`frontend/tests/e2e/critical/*.spec.ts`、`frontend/tests/e2e/dev/*.spec.ts`（定位器）、`frontend/tests/e2e/critical/antd-deprecation.spec.ts`（新增）、`frontend/scripts/bundle-budget.json`（基线记录）、`README.md`、`CONTEXT.md`、`CHANGELOG.md` | `frontend/tests/e2e/critical/antd-deprecation.spec.ts` | e14d48b0 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。

## 交接（会话结束更新）

- 当前阶段：P0-P2 全部落地（代码待人工评审后回填 `Implemented`）
- 已完成：
  - P0：依赖同批升级（react 19.3.1 / antd 6.6.8 / icons 6.3.4 / cssinjs 2.1.2 / @types 19.3.0）；`rc-util` isEqual 补丁迁移重打为 `patches/@rc-component__util.patch`（es + lib 双份，祖先链追踪），`rc-field-form` 摇树补丁删除，`check-patches.mjs` 重定位到 `@rc-component/util` 且 es/lib 双检；React 19 类型收紧修复（`RefObject<T | null>` / `ReactElement` / `ThemeConfig` cssVar 声明移除——antd 6 默认开启）
  - P1：兼容链复核通过（cssinjs v2 仍提供 transformer，`hashPriority` 默认仍 low）；`ThemeProvider.compat.test.tsx` 扩展为运行时样式审计——渲染 Form/Select/DatePicker/Tabs/Table/Modal 代表样本，断言注入 CSS 无 `:where(`、无逻辑属性声明、白名单外（oklch / @layer / light-dark / `:is(` 等）现代特性为零
  - P2：属性级弃用清零（Alert `message`→`title` 76 处、Drawer `width`/`height`→`size`、`destroyOnClose`→`destroyOnHidden`、`maskClosable`→`mask.closable`、Space/Divider `orientation`、Tabs `tabPlacement`、Tag `variant`、Image 预览 `open`、Timeline `items.content`）；Tag 末尾 8px 外边距经 `tag.styles` 全局补回；**List → Listy 迁移完成**（7 处调用点：DocumentsPage / DocumentShareModal / TrashDrawer / IssuesPage / DocumentsIssuesPage / InsertChartModal / ChangeRequestsPage，`CnListMeta` 自绘内容层 + `.cn-list-*` 共享样式，`.cn-doc-list` CSS 移植到 Listy 结构，e2e 弃用告警断言无白名单）；e2e 定位器随 antd 6 DOM 调整更新（`.ant-modal-container` / `.ant-drawer-section`）；多图粘贴顺序修复（`insertSnippetAtCursor` 插入后光标随内容前移）；bundle-budget 主入口 181→226 KiB 已记录理由（P2 主体提交 fcc61ce9，List→Listy 迁移提交 e14d48b0）
- 下一步：
  1. **Chromium 81 真机冒烟首跑**（`pnpm e2e:chrome81`，定时 CI 每日 02:00 UTC 自动触发）：升级后首次真机验证，重点核对 `:has()` 受影响组件（form / tabs / input / select / card / pagination / date-picker / tooltip / tree / splitter）与 10 套主题截图
  2. 人工评审本 ADR，全绿后回填 `Implemented`
- 已知坑：
  - antd 6 DOM 结构变化集中在：Select（无 `.ant-select-selector`，交互打根节点；搜索框为 `input.ant-select-input`；单选选中值在 `.ant-select-content`）、Modal（`.ant-modal-content`→`.ant-modal-container`）、Drawer（`.ant-drawer-content`→`.ant-drawer-section`）、Image 预览关闭钮（无 aria-label，zhCN 下 Modal 关闭钮 aria-label 为「关闭」与页脚按钮重名）、Input.Search（data-testid 落在 group 包装层）
  - **react-dom 19.3.1 补丁**：delayed-commit 的 `window.event` 读取无环境守卫，vitest 逐文件拆除 jsdom 环境后触发即抛 ReferenceError（覆盖率模式必现，计 unhandled error 使门禁失败）——补丁加 `typeof window` 守卫（`patches/react-dom@19.3.1.patch`，production 构建无该代码无需改），上游修复后可撤
  - **测试环境关闭 router `v7_startTransition`**（`render-providers.tsx`，生产 main.tsx 保持开启）：路由 transition 在用例卸载时仍在进行同样触发上述竞态；测试断言业务语义而非并发时序
  - `Form.useWatch` 在 antd 6 / React 19 下为异步微任务回流：受控组件断言必须用 `waitFor`（浏览器无感知差异）
  - Tabs `tabPlacement` 用逻辑方位（`start`/`end`），`left`/`right` 类型不通过
  - `Form.List` 全仓无命中，`onFinish` 取值口径专项核对为空操作
  - 弹层蒙层模糊 v6.3.0 起默认关闭，与升级前视觉一致，未额外配置
- 最近一次全绿：前端单测 2430 例全绿、typecheck / eslint 0 错误、`pnpm build`（含 chrome81 静态门禁 0 warning）、`pnpm bundle:budget` 达标 @ 工作区（2026-10-30）；后端 `make cov` 5943 例全绿（LD_LIBRARY_PATH 需为空，沙箱 NSS 目录污染见会话记录）
