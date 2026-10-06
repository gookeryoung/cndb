# 图表视图与统计分析工具 Implementation Plan

> Status: APPROVED
> Source: user request（"针对数据的图视图制定功能扩展计划，引入图表相关库实现更丰富的数据展示能力，并增加一系列统计学的工具便于进行统计学分析"）
> Mode: (default) Planner → Architect → Critic
> Iterations: 2 / 3
> Author: user
> Last updated: 2026-10-06

## Requirements summary

为 cndb 新增第 7 种视图类型「图表视图」（`view_type = "chart"`）：引入图表库渲染柱状/折线/饼图/散点/直方图/箱线图 6 种图表，配套纯前端统计学工具（描述统计、分箱、离群值检测、相关与回归），支撑对表数据的可视化与统计分析。当前现状：`viewModes.ts` 仅 6 种模式、`package.json` 零图表依赖、全库无 chart 视图代码（仅甘特图图标命中 "chart" 字样）。

## Acceptance criteria

- AC-1 视图创建：CreateEditViewForm 出现「图表」类型；chart_type 6 选项（bar/line/pie/scatter/histogram/boxplot）可配；配置项按 chart_type 条件显示（visibleWhen）
- AC-2 维度聚合图（bar/line/pie）：dimension_field × measure_field 聚合（sum/avg/count/min/max）数据正确；group_field 多系列；日期维度按 date_granularity 分桶且字典序升序
- AC-3 直方图：measure_field 按 bin_policy（auto=Sturges / square-root / freedman-diaconis）分箱，bin 边界与计数正确（FD 退化 IQR=0 回退 Sturges）
- AC-4 箱线图：每组预计算 [min,Q1,median,Q3,max]（线性插值分位）+ 离群点散点系列
- AC-5 散点图：x_field/y_field 双数值轴 + 可选 OLS 趋势线 + Pearson r 与 R² 展示；点击散点打开对应行详情
- AC-6 统计面板：count/sum/mean/median/mode/样本标准差(n-1)/min/max/极差/P25/P75/IQR/偏度/离群值数(IQR 法)；显示「样本量 N / 总行数 M」暴露截断口径
- AC-7 异常路径：未配必填字段渲染引导空态；后端对 view_options 引用不存在字段返回 400
- AC-8 体积门禁：主入口与 GridPage 基线不超；bundle-budget BASELINES 新增 ChartView chunk 基线条目
- AC-9 种子：电商销售表「月度销售额趋势」(line) + 员工表「部门薪资分布」(boxplot) 两个示例视图，seed 幂等重跑
- AC-10 回归：make check 全绿；既有 6 种视图与表单零行为变化（visibleWhere 未配置时恒显示）

## RALPLAN-DR

### Principles

1. 跟随 matrix 模板：纯前端聚合、零新后端端点、ViewType 不扩枚举（前端 VALID_MODES 为准入闸口）
2. 最小代码：ECharts 手写 ~60 行 adapter（init/setOption/dispose/ResizeObserver），不引第三方 React 封装
3. 依赖显式：新依赖仅 echarts + simple-statistics 两个，均随 chart 懒加载 chunk 隔离，不进首屏
4. 统计口径显式：样本标准差 n-1、线性插值分位、IQR 离群值法；面板标注样本量/总数，禁止静默截断误导统计结论
5. 外科手术式：visibleWhen 为可选 schema 扩展（undefined 恒显示），既有视图 schema 零改动零行为变化

### Decision drivers

1. 统计学图表刚需（箱线图/直方图/回归线）——用户明确要求"统计学分析"
2. bundle-budget 体积门禁不可破（主入口 185KB / GridPage 37KB gzip 基线）
3. vitest/jsdom 可测性（无 canvas 原生依赖）
4. 中文文档生态与维护活跃度

### Viable options

**Option A: ECharts 按需引入 + simple-statistics（chosen）**
- `echarts/core` + Bar/Line/Pie/Scatter/BoxplotChart + SVGRenderer 按需注册，懒加载 chunk 约 110-130KB gzip；simple-statistics 约 8KB gzip
- boxplot 系列原生、histogram 由 chartBoard 预计算 bin + bar 呈现；SVGRenderer 在 jsdom 可跑
- Apache-2.0 / MIT，中文文档一流

**Option B: Chart.js + react-chartjs-2 + 手写统计模块（rejected）**
- 体积最小（core 约 70KB gzip），但箱线图需第三方插件 @sgratzl/chartjs-chart-boxplot（体积优势缩水）；统计函数全手写约 250 行，分位数插值与 FD 分箱边界是真实易错点；文档英文
- rejected rationale：统计学图表覆盖与统计正确性两头都要补第三方/自研，总体成本反超 A

**Option C: Recharts 声明式 + 手写统计（rejected）**
- React 声明式最顺手，但无箱线图/直方图、大数据量性能弱、维护放缓
- rejected rationale：图表类型覆盖直接不满足统计学刚需，出局

## Implementation steps

1. 依赖引入：`frontend/` 下 `pnpm add echarts simple-statistics`（引入新依赖属暂停条件，本 plan 即授权凭据；版本以安装时最新稳定版锁定）— `frontend/package.json`
2. 模式注册（四处同步）：ViewMode 联合与 VALID_MODES 加 `'chart'` — `frontend/src/pages/grid/views/viewModes.ts:11,14`；`frontend/src/store/gridView.ts:12`；断言数组同步 — `frontend/src/pages/grid/views/viewModes.test.ts:75`
3. schema 扩展：`ViewOptionSchema` 增加可选 `visibleWhen?: (opts: Record<string, unknown>) => boolean`；`groupOptionSchema(schema, opts?)` 增加可选第二参过滤不可见项（undefined 恒显示）；新增 CHART_OPTIONS（11 项，见下）+ `getOptionSchema` case — `frontend/src/pages/grid/view-config/viewOptionSchema.ts:44,252,278`
4. 表单接入：sections memo 传当前 opts — `frontend/src/pages/grid/view-config/CreateEditViewForm.tsx:165`；viewTypeOptions 加 `{ value: 'chart', label: '图表' }` — 同文件 `:187-194`；ViewConfigDialog 的 groupOptionSchema 调用传 opts — `frontend/src/pages/grid/view-config/ViewConfigDialog.tsx:181`
5. 纯逻辑层：新建 `frontend/src/pages/grid/views/chartBoard.ts`——`buildChartData(rows, fields, opts)`（聚合/多系列/日期分桶复用 matrixBoard 的 dateBucket，必要时从 `views/matrixBoard.ts` 导出）、`computeStats(values)`、`histogramBins(values, policy)`、`pearson(pairs)`、`olsLine(pairs)`；空值/非数值剔除规则同聚合语义
6. 视图组件：新建 `frontend/src/pages/grid/views/ChartView.tsx`——ECharts adapter（init 用 SVGRenderer、setOption 差量更新、ResizeObserver、dispose）+ StatsPanel（AC-6 指标 + 样本量/总行数）+ 未配置引导空态；主题色经 getComputedStyle 读 `var(--cn-*)` 构建 option，系列色复用 antd 8 色预设（同 axisColor/tagColors 策略）；scatter on('click') 打开行详情
7. GridPage 接线：lazy import — `frontend/src/pages/grid/GridPage.tsx:52-59` 区域；MODE_BUTTONS 加 chart 项 — `:112`；KANBAN_MODES(fetch-all 集合) 加 `'chart'` — `:312`；渲染分支 — `:1065-1068` 区域后加 `mode === 'chart'` 分支
8. 后端校验白名单：opt_keys 增加 `dimension_field/measure_field/x_field/y_field`（group_field 已在）— `src/cndb/plugins/tables/routers/views.py:31-47`；seed 校验同步 — `src/cndb/cli/seed.py:1620-1633`
9. 种子示例：`examples/datasets/工作区-某企业销售管理/views.json` 电商销售表加「月度销售额趋势」(line, dimension=日期/month, measure=销售额, agg=sum)；员工表加「部门薪资分布」(boxplot, dimension=部门, measure=薪资)；同步检查 `test_backup_seed_roundtrip.py` 与 `test_seed_report_examples.py` 夹具期望
10. 单测（逻辑层）：新建 `chartBoard.test.ts`——聚合正确性、日期分桶、多系列、分箱三策略边界（FD IQR=0 回退）、computeStats 已知数据集精确值断言、IQR 离群值、完美线性数据 pearson=1/ols 斜率截距、空数组/全空值/单元素边界
11. 单测（组件层）：新建 `ChartView.test.tsx`——mock echarts 断言 setOption option 结构（图表类型/系列数据/分箱标签）；StatsPanel 数值渲染；空态引导；CreateEditViewForm.test.tsx 补图表类型与 visibleWhen 条件显隐（chart_type=scatter 时 x_field/y_field 出现、dimension_field 消失）；viewModes.test.ts 同步
12. 后端测试：视图创建 view_options 引用不存在字段返回 400 用例（补 dimension_field/measure_field 路径）
13. e2e：`frontend/tests/e2e/critical/view-mode-switch.spec.ts` 补图表视图创建→切换→svg 容器渲染断言
14. 体积门禁：`pnpm build && node scripts/bundle-budget.mjs` 验证主入口/GridPage 不超；BASELINES 新增 ChartView chunk 条目并记录基线 — `frontend/scripts/bundle-budget.mjs:40-44`
15. 收尾：`.trae/req/` 补需求记录 + `.trae/designs/chart-view.md` 落设计契约（view_options 表/算法/异常处理/测试约定，按项目设计文件规范）；make check 全绿后 commit + make push

### chart 视图 view_options 契约（view_type = "chart"）

| key | 类型 | 适用 | 说明 |
|-----|------|------|------|
| chart_type | enum | 全部 | bar/line/pie/scatter/histogram/boxplot，默认 bar |
| dimension_field | field | bar/line/pie/boxplot | 维度字段（select/multiselect/text/date/datetime/link/boolean），必填（visibleWhen） |
| measure_field | field | bar/line/pie/histogram/boxplot | 数值度量字段（number/float/percentage/timestamp），必填（visibleWhen） |
| x_field | field | scatter | X 数值字段，必填（visibleWhen） |
| y_field | field | scatter | Y 数值字段，必填（visibleWhen） |
| group_field | field | bar/line | 系列分组字段（select/multiselect/link） |
| aggregation | enum | bar/line/pie | sum/avg/count/min/max，默认 sum |
| date_granularity | enum | 日期维度 | year/quarter/month/week/day，默认 month（复用 matrix 分桶） |
| bin_policy | enum | histogram | auto(square-root)/sturges/freedman-diaconis，默认 auto |
| show_stats_panel | switch | 全部 | 默认 true |
| show_trend_line | switch | scatter | OLS 趋势线，默认 false |

## Workspace setup

- 实施前运行 `git status --short` 与 `git branch --show-current`：当前 main、工作区干净（2026-10-06 核验）。
- 项目惯例为单人 main 直行迭代（历史提交链均无 feature 分支），默认按惯例在 main 实施；如需隔离改用 `git worktree add -b codex/chart-view ../cndb-chart-view`。【待用户复核】
- 若实施时工作区已 dirty（local-mode 遗留未提交改动风险），先保护现有改动再动手，勿混入。

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| ECharts chunk 体积拖累首屏 | 仅经 ChartView 懒加载静态导入，Rollup 自动独立 chunk；bundle-budget 验证主入口/GridPage 基线；新增 ChartView chunk 基线防劣化 |
| jsdom 无 canvas，ECharts 单测不可跑 | 强制 SVGRenderer + 单测 mock echarts 断言 option 结构（不测像素）；e2e 用真实浏览器覆盖渲染 |
| CSS 变量主题在 ECharts 内部样式不生效 | init/setOption 时 getComputedStyle 读取 `var(--cn-*)` 注入 option；主题切换经 ThemeProvider 重渲染触发 setOption 重建（实现时验证主题切换联动） |
| visibleWhen 机制波及两个既有表单 | undefined 恒显示=既有 schema 语义零变化；CreateEditViewForm/ViewConfigDialog 既有测试全量回归 |
| 统计结论被 2000 行 fetch-all 截断误导 | StatsPanel 显示「样本量 N / 总行数 M」（useGridData 已有 total） |
| 统计口径争议（样本/总体、分位插值法） | 固定样本标准差 n-1 + 线性插值分位（simple-statistics 默认），面板 tooltip 注明口径 |
| 多值字段（multiselect/link）维度归属歧义 | 每行按首个值归桶（与 matrix getMultiSelectFirstLabel 语义一致），设计文件注明 |
| seed 视图数变化破坏既有种子测试 | 第 9 步显式同步两个种子测试夹具期望并回归 |

## Verification steps

- AC-1/7：`pnpm vitest run src/pages/grid/view-config/CreateEditViewForm.test.tsx`（条件显隐 + 图表选项）；后端 `uv run pytest tests/ -k view` 校验 400
- AC-2/3/4/5/6：`pnpm vitest run src/pages/grid/views/chartBoard.test.ts src/pages/grid/views/ChartView.test.tsx`（断言 option 结构与统计精确值）
- AC-8：`pnpm build && node scripts/bundle-budget.mjs` 输出全 ok
- AC-9：`uv run cndb seed` 幂等重跑 + `uv run pytest tests/test_backup_seed_roundtrip.py tests/test_seed_report_examples.py`
- AC-10：`make check` 全绿 + `pnpm e2e:critical`（含 view-mode-switch）
- 全量门禁：make check（lint/typecheck/cov）本地通过后方可 commit

## ADR

- **Decision**: 新增图表视图采用 ECharts 按需引入（echarts/core + SVGRenderer）+ simple-statistics 统计库，纯前端聚合（零新端点），视图注册完全复用 matrix 模板链路。
- **Drivers**: 统计学图表刚需（决定性）、体积门禁与懒加载隔离、jsdom 可测性、中文生态。
- **Alternatives considered**: A ECharts+simple-statistics（chosen）；B Chart.js+手写统计（rejected：箱线图需第三方插件+统计正确性风险，总成本反超）；C Recharts+手写统计（rejected：无箱线图/直方图，覆盖不满足刚需）。
- **Why chosen**: boxplot 原生系列 + histogram 预计算即可呈现，覆盖 6 种图表一步到位；simple-statistics 以 8KB 代价消弭分位插值/分箱边界/回归的手写错误面；两者均可懒加载隔离于首屏之外。
- **Consequences**: 前端新增 2 个运行时依赖（用户已授权方向）；ECharts 命令式 API 需维护 ~60 行 adapter（dispose/resize 生命周期归 ChartView）；图表颜色不走 CSS 而经主题注入层（getComputedStyle 桥）；chartBoard.ts 成为统计与图表数据变换的单一真相源，后续报表/聚合栏如需统计可复用。
- **Follow-ups**: 面积图/堆叠开关/雷达图等变体（group_field 天然支持堆叠，交互开关未做）；统计面板在 grid 聚合栏的复用（count/sum/avg → 全量指标）；>2000 行时服务端聚合端点（当前 2000 上限内纯前端足够）；写入 `.trae/designs/chart-view.md` 的正式设计契约（第 15 步）。

## Review trail

- Planner draft v1: ECharts+simple-statistics 方向、15 步实施清单；散点字段命名未决（measure_field 复用 vs 独立 x/y）、未处理截断透明、未纳 bundle-budget 新基线
- Architect challenge v1: steelman 指出「命令式 adapter 风险」可由 mock-option 测试策略控住维持 A；tension 提出统计完整性与截截断数据矛盾 → StatsPanel 样本量/总数；x/y 命名混淆 → 散点独立 x_field/y_field；visibleWhen 滥用风险 → 限定签名与使用范围
- Critic verdict v1: REVISE — AC-5 缺趋势线/相关系数可验证断言、bundle-budget 未防 chart chunk 劣化、种子测试夹具风险未列 mitigation
- Planner draft v2: 采纳全部——AC-5/AC-6 补精确断言项、实施步骤 14 增 BASELINES 条目、风险表补种子测试与多值字段归属
- Architect challenge v2: tension 复核通过（能力vs体积/依赖vs正确性/UXvs机制/完整vs截断四条均有取舍依据）
- Critic verdict v2: APPROVED with 3 reservations（见下）
- Final iterations: 2 / 3

### Critic reservations（APPROVED 附保留）

1. ECharts 主题色桥接（getComputedStyle 时序与主题切换联动）依赖实现期验证，若 ThemeProvider 无主题 state 触发重渲染需补联动机制——实施步骤 6 验证点，未过则回补。
2. `test_backup_seed_roundtrip` / `test_seed_report_examples` 的视图数期望值未逐一核验（仅列风险项），实施第 9 步须先跑基线再改种子。
3. visibleWhen 属 schema 机制性扩展，波及 CreateEditViewForm 与 ViewConfigDialog 两表单；虽有「undefined 恒显示」语义保底，仍建议实施后人工过一遍既有 5 种视图的创建/编辑表单。
