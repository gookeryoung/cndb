# ADR 0117: 低版本浏览器性能专项（Chromium 81 交互时延与兜底成本）

Status: Accepted
Date: 2026-11-07
Related: `frontend/src/theme/themeMix.ts`、`frontend/src/index.css`、`frontend/src/compat/flexGap.ts`、`frontend/src/compat/index.ts`、`frontend/src/main.tsx`、`frontend/scripts/chrome81-smoke.mjs`、`frontend/scripts/browser-baseline.mjs`、`frontend/src/pages/grid/gridTableSection.tsx`、`docs/adr/0026-chrome81-compat.md`、`docs/adr/0116-frontend-performance-program.md`
需求卡片: `docs/requirements/0117-legacy-browser-performance.md`（需求原文与约束编号的唯一副本）

> 无需求卡片（需求直接立项）时，本行写「无卡片」，「口径」中逐字粘贴原句并就地编号 C1..Cn；补卡片时再迁回卡片。
>
> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）；无卡片时在此粘贴。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「针对 CHROME81 等低版本浏览器」 | 硬基线继续由 `BROWSER_BASELINE = 'chrome81'` 单点定义；本 ADR 只优化 Chromium 81 的交互时延，其他低版本仅保「可打开」 |
| C2 | 「性能优化提升」 | 冒烟采集 `PerformanceObserver('longtask')` 最长任务 + 「点击→下一帧」时延；参考数据集 5000 行 × 20 列；基线存本 ADR「落地状态」附注 |
| C3 | 「性能优化提升」 | 主题切换：`applyThemeMixVars` 一次计算样式快照（读）→ 批量写；按主题缓存 `--cn-mix-*` 结果，切回同主题命中缓存不重写 |
| C4 | 「性能优化提升」 | flex-gap 垫片：待扫描根去重；扫描前先判 `display:flex`，非 flex 根不再展开整棵子树；空闲回调切片预算 ≤ 8ms；保留现场熔断开关 |
| C5 | 「性能优化提升」 | 复用现有虚拟化（主表 / 看板 / 甘特）；本 ADR 只加「参考规模下 DOM 上限」的 e2e 断言，不新增渲染路径 |
| C6 | 「制定可行方案」 | 新增 `frontend/scripts/perf-budget.mjs` 存放阈值常量；`chrome81-smoke.mjs` 增加断言段，超限 `process.exitCode = 1` |
| C7 | 「CHROME81 等低版本」 | 能力探测收敛到 `frontend/src/compat/capabilities.ts`（`supportsColorMix` / `isFlexGapSupported` 等），主题与垫片只调用该模块；禁止新增 UA 版本判断 |
| C8 | 「性能优化提升」（不回归） | 现代内核路径不变：原生 `color-mix()`、原生 flex gap、主题平滑过渡保持；降级只由能力探测与 `@supports` 触发 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。无需求卡片时，「与卡片的关系」列改为「对应约束」（C1..Cn）。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | flex-gap 垫片监听 `body` 子树 `childList` + `class/style`，新增节点走 `querySelectorAll('*')` 全量展开，每个容器 / 子元素多次 `getComputedStyle` | `frontend/src/compat/flexGap.ts:153-158`、`:196-214`、`:87-129` | 旧内核常驻成本随 DOM 规模与交互频率放大；弹窗 / 表格滚动时反复触发扫描 | 确认 |
| 2 | 主题 `--cn-mix-*` 兜底重算已改为「快照读 + 批量写」，且写入前比对内联值、值未变不重写 | `frontend/src/theme/themeMix.ts:124`、`:259-286` | 同步样式重算由上百次降为一次；切回同一主题不再重复写样式 | 确认（C3 已完成） |
| 3 | 全页主题过渡已收进能力门控 | `frontend/src/index.css:44` | Chromium 81 跳过该规则，瞬时换色；现代内核保持平滑渐变 | 确认（C8 已满足） |
| 4 | 旧内核冒烟只断言功能 / 视觉，无时延与长任务断言；`browser-compat.spec.ts` 无 performance 断言 | `frontend/scripts/chrome81-smoke.mjs:170-357`、`frontend/tests/e2e/critical/browser-compat.spec.ts` | 性能回退不可见，只能靠人工体感 | 确认 |
| 5 | 主表已开虚拟滚动，看板 / 甘特用 `useVirtualizer` | `frontend/src/pages/grid/gridTableSection.tsx:224`、`frontend/src/pages/grid/views/kanban/KanbanColumn.tsx:50`、`frontend/src/pages/grid/views/GanttView.tsx:236` | 可排除「整表重挂」为旧内核卡顿主因 | 排除（C5 只补断言） |
| 6 | 兼容层在首次渲染后按能力动态加载，唯一入口 `initCompat()` | `frontend/src/main.tsx:101-102`、`frontend/src/compat/index.ts:10-15` | 现代内核不下载垫片；旧内核的垫片与主题兜底是常驻成本 | 确认 |
| 7 | 图表 / Dashboard 在主题切换时**不重建实例**：`ChartCanvas` 只在挂载时 `init` 一次，主题变化走 `setOption(option, true)`；每个图表每次切换读 4 个主题色 | `frontend/src/pages/grid/views/dashboard/chart/ChartCanvas.tsx`、`widgets/ChartWidget.tsx` | 旧内核切主题的图表成本是「4 次 getComputedStyle + 一次 option 全量下发」，无实例销毁 / 重建 | 确认（P0 核实，无需改渲染路径） |

**核心缺陷（需求要补的）**：现有兼容层只解决「能不能用」（功能与视觉等价），没有「够不够快」的口径、预算与门禁；而兜底实现（mix 变量、flex-gap 观察器）本身是旧内核的常驻成本，既无量化基线，也无随 DOM 规模解耦的约束。

设计目标（不变量）：

- **I1 时延可判定**：旧内核关键交互（主题切换、视图切换、首屏可交互）有固定阈值，由命令退出码判定，不依赖人工体感。
- **I2 兜底成本可解耦**：主题切换的同步样式读取次数为常数，不随 DOM 规模增长；垫片扫描按空闲切片且有熔断。
- **I3 现代内核不降级**：原生 `color-mix()`、原生 flex gap、平滑过渡在现代内核保持，不因本 ADR 新增降级路径。
- **I4 降级可回滚**：每项降级都有能力探测入口或开关，关闭后功能仍可用（视觉可接受）。

## Decision

### 1. 数据模型

无。

### 2. 判定算法（唯一入口）

| 入口 | 签名 | 职责 |
|---|---|---|
| `frontend/scripts/perf-budget.mjs` | `export const PERF_BUDGET = { themeSwitchMs, viewSwitchMs, firstInteractiveMs, maxLongTaskMs }` | 旧内核性能阈值唯一来源；冒烟与 e2e 共用，禁止散落数字 |
| `frontend/src/compat/capabilities.ts` | `supportsColorMix()` / `isFlexGapSupported()` | 运行时能力探测唯一入口；主题兜底与垫片只调用它 |
| `initCompat()` | `(): void` | 兼容层装载唯一入口（保持 ADR 0026 口径），不新增第二入口 |
| `applyThemeMixVars()` | `(root?: HTMLElement): void` | `--cn-mix-*` 唯一写入方；内部保证「先读完、再统一写」 |

### 3. API 变更清单

无。

### 4. 边界与例外

1. 低版本定义：Chromium 81 / Edge 81（含内嵌 WebView）为硬基线；Firefox ESR / Safari 等只保「可打开、无未捕获异常」。
2. 参考数据集：5000 行 × 20 列、10 个视图；固定机器（CI runner）采集，跨机器数字不作横向比较，只比同机基线。
3. 阈值初值：主题切换 ≤ 200ms、视图切换 ≤ 800ms、首屏可交互 ≤ 3000ms、单次长任务 ≤ 250ms；P0 实测后只允许收紧，放宽须在「决策记录」追加理由。
4. 允许的降级：旧内核关闭装饰性过渡 / 阴影 / 模糊；不允许牺牲文字与背景的对比度、边框可见性等可读性口径。
5. 主题兜底缓存以「主题模式 + 字体等影响 token 的偏好」为键；仅当输入变化时重算并重写。
6. 垫片熔断：`window.__CNDB_DISABLE_FLEX_GAP_SHIM__ = true` 后，已写入的 margin 在下一轮扫描还原；冒烟验证熔断后页面仍可操作。

### 5. 迁移

无。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 主题兜底 | `frontend/src/theme/themeMix.ts` | 快照读 + 批量写；写入前比对内联值，值未变不写 |
| 主题过渡 | `frontend/src/index.css` | 全页过渡由 `@supports (color-mix(...))` 门控 |
| 兼容探测 | `frontend/src/compat/capabilities.ts`（新增） | 收敛 `supportsColorMix` / `isFlexGapSupported`；删除旧的 `flexGapSupport.ts` |
| flex-gap 垫片 | `frontend/src/compat/flexGap.ts` | 待扫描根去重、class/style 变更浅扫（不展开子树）、空闲切片预算 ≤ 8ms、自身写入不触发重扫 |
| 旧内核冒烟 | `frontend/scripts/chrome81-smoke.mjs` | 性能段：longtask 统计、首屏可交互 / 主题切换 / 视图切换时延，超阈值非 0 退出 |
| 阈值常量 | `frontend/scripts/perf-budget.mjs`（新增） | 阈值单点定义 |
| 图表主题 | `frontend/src/pages/grid/views/dashboard/` | 已核实：图表实例复用、仅 `setOption`，无需改渲染路径 |

### 7. 测试清单

**判定层（单测）**：`themeMix` 快照读次数（mock `getComputedStyle` 计数，断言 1 次）与值未变不重写；`flexGap` 新增子树扫描、class/style 变更不展开子树、自身写入不触发重扫；`capabilities` 在各能力缺失时的返回值。

**接口层**：无。

**迁移 / 备份**：无。

**e2e（前端）**：`chrome81-smoke.mjs` 性能断言（首屏可交互、主题切换、视图切换、最长任务，阈值取 `perf-budget.mjs`）；`browser-compat.spec.ts` 保持功能断言；`perf/journeys.spec.ts` 断言主表挂载行数 ≤ 100、DOM 元素 ≤ 8000（与数据规模无关的虚拟化上限）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 基线与门禁：`perf-budget.mjs` + 冒烟性能段 + 基线表；核实图表重建热点 | 低 |
| **P1** | 主题与探测收敛：`--cn-mix-*` 缓存与不重写、`capabilities.ts` 单一探测（快照读与过渡门控已完成） | 低 |
| **P2** | 垫片预算与熔断验证、长列表 DOM 上限断言、图表 / Dashboard 热点修复 | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 覆盖范围 | 只把 Chromium 81 / Edge 81 作为硬基线，其他低版本仅保可打开 | 与 ADR 0026 C6 一致；维护多版本性能矩阵成本过高 | 全浏览器版本矩阵（无对应 CI 资源，且需求原文只点名 Chrome 81） | `frontend/scripts/browser-baseline.mjs` |
| D2 | 优化顺序 | 先建立可判定基线（P0），再按测量结果优化 | 避免凭体感猜热点；`browser-compat.spec.ts` 已证明只有功能断言会漏掉时延回退 | 直接改疑似热点（无法证明收益，也无法防回退） | `frontend/scripts/chrome81-smoke.mjs` |
| D3 | 主题切换策略 | 能力探测 + 快照读写分离 + 旧内核跳过全页过渡 | Chrome 81 无 `color-mix()`，兜底变量必须运行时算；全树 transition 是旧内核主要放大项 | 旧内核也保留全页过渡（大量过渡属性建立，主线程被占）；构建期预生成 mix 变量（主题受字体 / 偏好驱动，无法穷举） | `frontend/src/theme/themeMix.ts`、`frontend/src/index.css` |
| D4 | flex-gap 垫片 | 保留运行时垫片，加去重 / 短路 / 预算 / 熔断 | ADR 0026 已落地且 e2e 覆盖；构建期 CSS 后处理需改写 200+ 处写法，风险高 | 移除垫片（旧内核间距塌陷）；构建期转换（改动面与回归成本过大） | `frontend/src/compat/flexGap.ts` |
| D5 | 性能门禁载体 | `chrome81-smoke.mjs` 增性能断言，阈值集中在 `perf-budget.mjs` | 已有 Chromium 81 真实内核冒烟与定时 CI，复用成本最低 | 仅靠人工体验记录（不可判定、不可回归）；只看 Web Vitals 上报（旧内核无 INP / Event Timing） | `frontend/scripts/chrome81-smoke.mjs` |
| D6 | 长列表 | 沿用现有虚拟化，只补规模断言 | 主表、看板、甘特已虚拟化，无证据表明需另建路径 | 为旧内核单独实现渲染路径（维护双路径，收益未证实） | `frontend/src/pages/grid/gridTableSection.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：旧内核卡顿有量化口径与 CI 门禁，回归可见；主题切换与垫片的兜底成本与 DOM 规模解耦；能力探测单点收敛，后续低版本适配不再散落版本判断。
- **负向**：旧内核牺牲全页过渡等装饰效果；新增常量与探测模块；CI 定时任务耗时增加（真实 Chromium 81 冒烟）。
- **风险与缓解**：阈值受 runner 性能波动影响 → 只比同机基线并留 20% 余量；垫片改动可能造成间距回归 → 保留 `flexGap.test.ts` 与冒烟间距实测。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 兼容基线 | `.browserslistrc`、`browser-baseline.mjs` | 复用 Chromium 81 基线，不新增版本矩阵 | ADR 0026 |
| 现代内核性能 | 首屏 / 预取 / 包体预算 | 0116 管现代内核首屏与包体；本 ADR 管旧内核交互时延与兜底成本，互不替代 | ADR 0116 |
| 兼容层入口 | `initCompat()` | 不新增第二装载入口 | ADR 0026 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/scripts/perf-budget.mjs`、`frontend/scripts/chrome81-smoke.mjs` | `.github/workflows/chrome81-smoke.yml` | 工作区未提交 |
| P1 | 已落地 | `frontend/src/theme/themeMix.ts`、`frontend/src/index.css`、`frontend/src/compat/capabilities.ts` | `frontend/src/theme/themeMix.test.ts`、`frontend/src/theme/ThemeProvider.test.tsx`、`frontend/src/compat/capabilities.test.ts` | `70d7da02` + 工作区未提交 |
| P2 | 已落地 | `frontend/src/compat/flexGap.ts`、`frontend/tests/e2e/perf/journeys.spec.ts` | `frontend/src/compat/flexGap.test.ts`、`frontend/tests/e2e/perf/journeys.spec.ts` | 工作区未提交 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

### 基线（Chromium 81，同机采集）

阈值唯一来源 `frontend/scripts/perf-budget.mjs`；冒烟每次运行打印 `[chrome81] perf: {...}`，CI 日志留存读数，只允许与同机历史比较。

| 指标 | 采集口径 | 阈值 |
|---|---|---|
| 首屏可交互 | 导航开始 → 应用头部出现且内容非空 | ≤ 3000ms |
| 主题切换 | 点击主题卡片 → 下一帧（React 提交 + 主题变量重算 + 重绘） | ≤ 200ms |
| 视图切换 | 点击视图按钮 → 下一帧（同步渲染，不含网络） | ≤ 800ms |
| 单次长任务 | `PerformanceObserver('longtask')` 最长 duration（主题 / 视图切换窗口） | ≤ 250ms |

> 首次同机读数由 CI 定时任务采集后回填本表；本机无 Chromium 81 运行环境时不伪造数字。

## 交接（会话结束更新）

- 当前阶段：P0 / P1 / P2 全部落地，等待人工确认 `Status` 是否改 `Implemented` 与同机基线回填
- 已完成：冒烟性能段（longtask + 首屏 / 主题 / 视图时延，超阈值非 0 退出）；`perf-budget.mjs` 阈值单点；`applyThemeMixVars` 快照读 + 批量写 + 值未变不写；全页过渡能力门控；`capabilities.ts` 收敛能力探测；flex-gap 垫片去重 / 浅扫 / 8ms 切片 / 自写抑制；图表主题核实为实例复用
- 下一步：CI 首次采集后把读数回填「基线」表；如某项超阈值，先看是 runner 抖动还是真实回退
- 已知坑：Chromium 81 无 Event Timing / INP，只能用 `PerformanceObserver('longtask')` + `requestAnimationFrame` 手工计时；无头 Chromium 81 无 WebGL，设计预览走降级提示；运行后端测试前需 `unset LD_LIBRARY_PATH`
- 最近一次全绿：`make flow` + 前端全量单测 + `make check-docs` @ 工作区未提交（2026-11-07）
