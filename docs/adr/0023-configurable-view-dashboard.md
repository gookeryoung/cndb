# ADR 0023: 可配置复杂视图模板（dashboard 画布）

Status: Accepted
Date: 2026-10-23
Related: `frontend/src/pages/grid/views/ChartView.tsx`、`frontend/src/pages/grid/views/chartBoard.ts`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`frontend/src/pages/grid/view-config/CreateEditViewForm.tsx`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/views/viewModes.ts`、`frontend/src/pages/grid/useGridData.ts`、`src/cndb/plugins/tables/routers/views.py`、`src/cndb/plugins/tables/models.py`、`src/cndb/plugins/analytics/services/compute.py`、`docs/adr/0022-gallery-view-content-tables.md`
需求卡片: 无卡片（需求直接立项，原句逐字见 §口径）

## 口径（需求 → 设计落点）

需求原文（逐字）：

> 针对可配置的复杂视图模板，制定一份开发计划。计划应涵盖：各类曲线图表（如折线图、柱状图等）的展示方案；可配置布局的设计，包括布局元素的组织方式与配置方式；以及整体开发阶段划分、各阶段目标与关键实现要点。

| # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 各类曲线图表（如折线图、柱状图等）的展示方案 | 图表类型注册表 `chartRegistry`（类型 → 角色声明 + 数据变换 + option 装配），一张表决定「支持哪些图、每种图要什么字段」；数据口径分「样本量 ≤2000 客户端聚合 / 超出走服务端聚合」两层 |
| C2 | 可配置布局的设计，包括布局元素的组织方式 | 12 列 × 40px 行高栅格；三层元素：画布 Canvas → 卡片壳 WidgetShell → 内容渲染器 Widget Body；位置存 `{x,y,w,h}` 整数格 |
| C3 | 可配置布局的设计，包括…配置方式 | 三条通道并存：拖拽（移动 / 缩放 / 吸附）、数字输入（x/y/w/h + 方向键微调）、版式预设（单栏 / 两栏 / 主次 / 2×2 / KPI 条）；编辑态与预览态分离 |
| C4 | 整体开发阶段划分 | P0 契约与只读画布 → P1 布局编辑器 → P2 图表能力与聚合口径 → P3 模板化与跨表联动（§9） |
| C5 | 各阶段目标 | 每期给「目标 / 交付物 / 验收」三栏，验收可跑（单测 / e2e / 门禁） |
| C6 | 关键实现要点 | 每期列「关键实现要点」，落到函数签名、校验规则与文件路径，不写空泛描述 |

## Context

现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 与需求的关系 |
|---|---|---|---|---|
| 1 | `view_type` 为自由 `String(32)`，后端只对 `view_options` 做字段引用校验；前端类型下拉硬编码 10 项 | `src/cndb/plugins/tables/models.py:253`、`src/cndb/plugins/tables/routers/views.py:141`、`frontend/src/pages/grid/view-config/CreateEditViewForm.tsx:218` | 新增视图类型零迁移，但也没有类型白名单，写错类型要等前端渲染时才暴露 | C4 前置 |
| 2 | 图表视图已支持 6 类图（bar/line/pie/scatter/histogram/boxplot），option 装配集中在 130 行 `switch` | `frontend/src/pages/grid/views/ChartView.tsx:137` | 每加一类图要改 `buildOption` + `missingFieldLabels` + `CHART_OPTIONS` 三处，易漏 | C1 确认（需注册表化） |
| 3 | 图表配置靠在 `CHART_OPTIONS` 的 16 项扁平键 + `visibleWhen` 条件显隐 | `frontend/src/pages/grid/view-config/viewOptionSchema.ts:285` | 单图语义清晰；多图/多 widget 时扁平键无法表达「每个 widget 一套配置」 | C2 排除（需要嵌套结构） |
| 4 | 已有 `charts[]` 多图形态（`normalizeChartList` / `serializeChartList`），渲染为 `auto-fill minmax(420px,1fr)` 自适应网格 | `viewOptionSchema.ts:700`、`ChartView.tsx:632` | 只能等宽换行排列，不能指定位置 / 跨列 / 混排 KPI；且所有图共用一个数据集 | C2 排除（需要显式坐标） |
| 5 | 非 grid 视图统一拉 `VIEW_FETCH_ALL_LIMIT = 2000` 行，聚合在前端做 | `frontend/src/pages/grid/useGridData.ts:22`、`chartBoard.ts` | 大表超过 2000 行只能看截断样本；多 widget 各拉一次会造成 N 倍网络与聚合开销 | C1 风险（需服务端聚合） |
| 6 | 数据分析模块已有服务端聚合链路：`scan_rows`（含行级权限 / 字段隐藏）+ `compute_summary`（分组 × 聚合 × TopN） | `src/cndb/plugins/analytics/services/compute.py:120`、`:220`、`:310` | 画布 widget 的聚合可直接复用，不必新写一套 SQL | C1 确认（复用） |
| 7 | `ChartCard` 已抽出为可复用组件，接受 `cfg/rows/fields/total`，并被分析页直接复用 | `ChartView.tsx:446` | 画布只需把「聚合结果」转成同样的入参形态即可复用渲染，避免第二套图表实现 | C1 确认（复用） |
| 8 | 关键 chunk 有 gzip 预算门禁，`ChartView` 基线 14.4 KiB | `frontend/scripts/bundle-budget.json`、`docs/BUNDLE_BUDGET.md` | 新增画布与图表类型必须走 lazy + 独立 chunk，否则 CI 红 | C4 约束 |

**核心缺陷**：现有视图只能表达「一张表、一种形态、一套配置」——图表视图的多图是等宽平铺且共用一份数据；看板 / 矩阵 / 画廊各有固定版式。没有任何视图类型能表达「同屏多块异构内容（图表 / 指标 / 小表 / 说明）+ 指定位置与尺寸 + 每块独立取数口径 + 全局筛选联动」。

设计目标（不变量）：

- **I1 单一真相源**：`dashboard` 的配置只有一份（`view_options`），字段定义、默认值、校验规则、序列化出口共用同一套 schema；前端 TS 与后端 Python 两份实现由同一组契约用例约束。
- **I2 布局可归一**：任何合法配置经 `normalizeLayout` 后必然无越界、无重叠、无空洞（上浮压缩后），因此渲染只做「读坐标 → 生成 grid 样式」，不含兜底计算。
- **I3 取数可退化**：数据量大时降级为服务端聚合，图表只消费「已聚合的小结果」；客户端与服务端两种来源产出同一种 `Dataset` 结构，渲染层无分支。
- **I4 权限不旁路**：widget 取数走与 `GET /rows`、分析扫描同一条 `list_rows` 链路，行级权限与字段隐藏对画布同样生效；跨表 widget 逐表校验 READ。
- **I5 预览不写库**：编辑态的所有变更留在本地 draft，显式保存才落库；未保存离开有确认。
- **I6 首屏不增负**：画布与新增图表库全部 lazy 加载，主入口与 GridPage chunk 不因本 ADR 增长。

## Decision

### 1. 数据模型

**不新增表、不新增列**：`dashboard` 配置整体存 `tables_dataview.view_options`（`JSON`，现状已承载 16 项图表键与 `charts[]`），沿用视图既有权限（ADR 0003 三档可见性）、备份、seed、导入导出链路。理由见 D2。

`schema_version` 置顶层，为后续就地升级留出口：

```json
{
  "schema_version": 1,
  "canvas": { "cols": 12, "row_height": 40, "gap": 12, "padding": 16 },
  "widgets": [
    {
      "id": "w_revenue",
      "type": "chart",
      "title": "月度销售额",
      "layout": { "x": 0, "y": 4, "w": 8, "h": 8 },
      "query": {
        "filters": [{ "field_name": "日期", "op": "gte", "value": "{{global.date_from}}" }],
        "filter_logic": "AND",
        "sortings": [{ "field_name": "月份", "direction": "asc" }],
        "limit": 2000
      },
      "chart": {
        "type": "bar",
        "x": "月份",
        "y": ["销售额"],
        "series": null,
        "agg": "sum",
        "stack": "none",
        "sort": "none",
        "top_n": null,
        "dual_axis": false,
        "format": { "unit": "元", "decimals": 0 }
      },
      "display": { "show_legend": true, "palette": "default" }
    },
    {
      "id": "w_kpi_orders",
      "type": "kpi",
      "title": "本月订单",
      "layout": { "x": 0, "y": 0, "w": 3, "h": 4 },
      "query": { "filters": [], "filter_logic": "AND" },
      "kpi": {
        "value": { "field": "订单号", "agg": "count" },
        "compare": { "mode": "prev_period", "date_field": "日期", "granularity": "month" },
        "sparkline": { "field": "订单号", "agg": "count", "points": 12 }
      }
    }
  ],
  "global_filters": [
    { "id": "date_from", "kind": "date_range", "field": "日期", "label": "时间范围" }
  ],
  "settings": { "refresh_interval": 0, "theme": "inherit" }
}
```

约束：

- `widgets` ≤ **32**；`id` 匹配 `^[a-zA-Z0-9_-]{1,32}$` 且唯一（拖拽与撤销靠它定位）。
- `type ∈ {chart, kpi, table, text}`（P0 四类；`divider` / `filter` 等按需再加，白名单扩展）。
- `layout` 全整数：`1 ≤ w ≤ cols`、`1 ≤ h ≤ 20`、`0 ≤ x ≤ cols-w`、`0 ≤ y ≤ 200`；`cols` 固定 12（只在 `schema_version` 升级时才可变）。
- `query.table_id` P0-P2 **禁止**（恒等于视图所属表）；P3 放开为同工作区表 id，逐表鉴权（D8）。
- 未知键在序列化出口丢弃（白名单），保证「旧前端读到新字段不炸、新前端读到旧配置有默认值」。

### 2. 布局模型与元素组织

**坐标模型**：12 列栅格，行高 40px，间距 12px。widget 存 `{x,y,w,h}` 整数格，渲染映射为 CSS Grid：

```ts
// frontend/src/pages/grid/views/dashboard/layout/dashboardLayout.ts
export interface WidgetBox { id: string; x: number; y: number; w: number; h: number }
export function clampBox(box: WidgetBox, cols: number): WidgetBox        // 越界收敛（I2 第一道）
export function resolveOverlap(boxes: WidgetBox[], movingId: string, cols: number): WidgetBox[]
export function compact(boxes: WidgetBox[]): WidgetBox[]                 // 逐列上浮，幂等
export function findFreeSlot(boxes: WidgetBox[], w: number, h: number, cols: number): { x: number; y: number }
export function applyPreset(preset: LayoutPreset, boxes: WidgetBox[], cols: number): WidgetBox[]
export function toGridStyle(box: WidgetBox): CSSProperties               // gridColumn / gridRow
export function collapseNarrow(boxes: WidgetBox[], cols: number): WidgetBox[]
```

- 重叠语义：拖动时把重叠块**下推**（Google Data Studio / Grafana 口径），松手后 `compact` 上浮消洞；不做「自动挤位动画」，避免连串重排造成抖动。
- `normalizeLayout = compact(resolveOverlap(clampBox(...)))`，是保存前的唯一出口；渲染期不再纠正（I2）。
- 响应式只存桌面布局：`<1024px` 按 `(y, x)` 顺序单列（`w=cols`，`h` 保留），`<640px` 只收紧卡内边距；**不存多断点布局**（D4）。

**元素组织（三层，职责单向）**：

| 层 | 组件 | 只负责 | 禁止 |
|---|---|---|---|
| 画布 | `DashboardView` / `DashboardGrid` | 取数编排、全局筛选、编辑态、栅格坐标 | 不写图表 option、不读业务字段语义 |
| 卡壳 | `WidgetShell` | 标题 / 副标题 / 工具条（刷新、菜单、拖拽区）/ 四态（加载、空、错误、无权限）/ 编辑手柄 | 不知道 widget 类型 |
| 内容 | `ChartWidget` / `KpiWidget` / `TableWidget` / `TextWidget` | 把 `Dataset` 变成图形 | 不发请求、不读写布局 |

四态由卡壳统一渲染，内容组件只在 `data` 就绪时挂载 —— 避免每个内容组件各写一遍骨架屏与错误重试（现状 `ChartView` 的加载态散在页面层）。

**配置方式（三条通道，同一份 draft）**：

1. **拖拽**：拖标题栏移动（`@dnd-kit/core` 已在依赖内，复用其 pointer sensor，`distance: 4` 防误触）；右下角 16px 缩放手柄仅编辑态可见；吸附到 12 列网格线 + 同列 / 同宽边缘（阈值 6px）。
2. **数字输入**：属性面板的 `x / y / w / h` 四个 `InputNumber`；卡片聚焦后方向键移动 1 格、`Shift+方向键` 改尺寸；`aria-valuenow` 暴露当前格值（可访问性）。
3. **版式预设**：`presets.ts` 提供 5 种 —— 单栏 / 两栏等分 / 主次（8+4）/ 2×2 / KPI 条 + 图表（4×3 顶条 + 下方两列）。预设只重排现有 widget 的 `layout`，不增删内容；数量不足时留空位，多余时继续按预设列流式排列。

编辑态与预览态：`editing` 为本地布尔；编辑态显示栅格底纹、手柄、添加按钮、属性面板、撤销栈（快照式，上限 50 步）；`⌘/Ctrl+S` 保存，`Esc` 退出编辑并回滚未保存变更（有确认）。保存走既有 `PUT /views/{id}`（`view_options` 整体替换），并发冲突按 `updated_at` 比对提示「他人已修改，请刷新后重试」。

### 3. 图表展示方案

**分层**：`ChartSpec`（落库配置）→ `Dataset`（数据处理产物）→ `option`（ECharts 装配）。注册表消掉现状的三处分散改动（D7）：

```ts
// frontend/src/pages/grid/views/dashboard/chart/chartRegistry.ts
export interface ChartTypeDef {
  type: ChartTypeName
  label: string
  group: 'comparison' | 'trend' | 'composition' | 'distribution' | 'relation' | 'finance'
  roles: { x?: Role; y?: Role; series?: Role; value?: Role }   // required / optional / numeric-only
  supports: { agg: boolean; multiY: boolean; stack: boolean; dualAxis: boolean; series: boolean }
  minSize: { w: number; h: number }
  buildDataset(ds: Dataset, cfg: ChartSpec): SeriesData
  buildOption(data: SeriesData, cfg: ChartSpec, theme: ThemeColors): EChartsCoreOption
}
```

新增一类图 = 注册表加一条 + 一份 `buildOption` + 一个快照测试；`ChartWidget`、属性面板、校验三处自动生效（面板按 `roles` 生成字段选择器，按 `supports` 决定开关可见）。

**类型清单与分期**（✓ 复用现有能力，＋ 新增）：

| 类型 | 数据形态 | 必填角色 | 多系列 | 聚合 | 典型用途 | 期 |
|---|---|---|---|---|---|---|
| 柱状 `bar` | 类目 → 数值 | x, y | ✓ | ✓ | 分类对比 | ✓ P0 |
| 折线 `line` | 类目 → 数值 | x, y | ✓ | ✓ | 趋势 | ✓ P0 |
| 面积 `area` | 同折线 + 填充 | x, y | ✓ | ✓ | 累计 / 体量趋势 | ＋ P2 |
| 堆叠 `stack` / 百分比堆叠 | 类目 × 系列 → 数值 | x, y, series | ✓ | ✓ | 构成随时间的演变 | ＋ P2 |
| 组合双轴 `combo` | 类目 → 多度量（左/右轴） | x, y[] | ✓ | ✓ | 量价 / 金额与比率同屏 | ＋ P2 |
| 饼 / 环 `pie` | 类目 → 占比 | x, y | — | ✓ | 构成 | ✓ P0 |
| 散点 / 气泡 `scatter` | 双数值（+ 尺寸） | x, y | 可选 | — | 相关性 | ✓ P0 |
| 直方 `histogram` | 单数值分布 | y | — | 分箱 | 分布形态 | ✓ P0 |
| 箱线 `boxplot` | 类目 × 数值 | x, y | — | 五数概括 | 离群与离散度 | ✓ P0 |
| 雷达 `radar` | 维度 → 多指标 | x, y[] | 可选 | ✓ | 多维评分 | ＋ P2 |
| 漏斗 `funnel` | 阶段 → 数值 | x, y | — | ✓ | 转化 | ＋ P2 |
| 仪表 `gauge` | 单值 + 目标 | y, target | — | ✓ | 达成率 | ＋ P2 |
| 热力 `heatmap` | 行 × 列 → 数值 | x, series, y | — | ✓ | 二维密度 | ＋ P2 |
| 矩形树 `treemap` | 两级类目 → 数值 | x, series, y | — | ✓ | 层级占比 | ＋ P2 |

**通用配置维度**（一张表驱动，避免每类图重复 N 个字段）：

| 分组 | 配置项 |
|---|---|
| 数据角色 | `x` / `y[]`（多度量）/ `series`（长表转宽表）/ `target`（仪表） |
| 聚合 | `sum / avg / count / min / max / median / none`（`none` = 明细不聚合，仅散点 / 小表） |
| 排序与截断 | `sort: none / x_asc / x_desc / y_asc / y_desc`、`top_n`（≤100，其余并「其他」）、时间分桶粒度 |
| 轴 | 左/右轴分配、对数轴、范围（min/max）、单位 / 小数位 / 千分位 / 百分比 |
| 标记 | 数据标签（显示 / 位置 / 阈值着色）、面积平滑、堆叠模式、趋势线（散点） |
| 图例与提示 | 位置、滚动模式、统一 tooltip（数值格式化与轴一致） |
| 配色 | 默认 8 色板（现状 `SERIES_COLORS`）/ 按维度值映射（复用 `tagColors`）/ 阈值色阶 |

**KPI 卡**：主值（`field + agg`）+ 对比（`prev_period` / `prev_year`，需时间字段）+ 12 点 sparkline + 单位/小数位/前缀；对比缺基准时显「—」而不是 0%。

**迷你表格**：只读、列白名单 ≤8、行 ≤50、可点击排序、点行开既有 `RowDetailDrawer`；不接内联编辑（避免与双轨制写入纠缠）。

**数据口径（I3）**：

| 层 | 触发 | 实现 | 上限 |
|---|---|---|---|
| 客户端聚合 | 单表可读行 ≤ 2000（`VIEW_FETCH_ALL_LIMIT`） | `useGridData` 已有行集 → `chartBoard.buildChartData` | 2000 行 |
| 服务端聚合 | 行数 > 2000 或用户显式选「全量统计」 | 新批量端点，复用 `scan_rows` + `compute_summary`，返回 `categories/series/points` | 扫描上限沿用 `ANALYTICS_MAX_SCAN_ROWS` |

两种来源都归一到同一 `Dataset`（`{kind:'category'|'pie'|'scatter'|'histogram'|'boxplot', categories, series, points, meta}`），`ChartWidget` 只认 `Dataset`。卡壳右上角统一显示「样本 N / 总行数 M」的口径提示（沿用 `StatsPanel` 的表述），避免「图看着对、其实只算了 2000 行」的误判。

**批量化取数（关键）**：画布一次请求带上所有 widget 的查询，服务端对同一 `(table, 全局筛选)` **只扫描一次**，多 widget 共享行集后各自聚合 —— 既省往返，也避免 N 次全表扫描。单 widget 失败只影响该卡片（`errors[]` 带 `widget_id`），不整页报错。

**渲染与性能**：SVG renderer；卡片级 `ResizeObserver` → `chart.resize()`；`setOption(notMerge)`；不可见卡片用 `IntersectionObserver` 延迟初始化；`Dataset` 按 `query hash` 走 TanStack Query（`staleTime: 60s`），同一查询的多个 widget 命中同一缓存。

### 4. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /api/v1/workspaces/{wid}/tables/{tid}/views`、`PUT .../views/{view_id}` | 修改：`view_type=dashboard` 时走 dashboard 校验（§7）；`view_type` 增加白名单（`KNOWN_VIEW_TYPES`），未知值 400（历史 `form` 行只读兼容，见 D1） |
| `POST .../views/{view_id}/dashboard/data` | 新增：批量取 widget 数据。请求 `{ "widget_ids": ["w1"], "globals": {"date_from": "2026-01-01"}, "force": false }`；响应 `{ "items": [{ "widget_id", "dataset", "meta": { "scanned", "total", "truncated", "cached" } }], "errors": [{ "widget_id", "detail" }] }`；权限：视图可读 + 表 READ，逐 widget 复用 `list_rows` 的行级权限 |
| `GET .../views/{view_id}/dashboard/data` | 不提供：避免 URL 长度与缓存口径分裂（配置在 body 里更可控） |
| 备份 / seed / 视图导入导出 | 无结构变更：`view_options` 整体透传；seed 侧补 dashboard 的字段引用校验（`src/cndb/cli/seed/views.py:57` 同款逻辑） |

缓存：键 = `hash(table_id + 归一后 filters/sortings + 字段集合 + limit + 行级权限摘要 + widget spec)`，TTL 60s，LRU 128；表写操作按 `table_id` 失效（复用 `cndb/core/cache.py` 的失效钩子）。

### 5. 边界与例外

1. 字段被删 / 改名：保存期校验拒绝（400，`detail` 定位到 `widgets[i].chart.x`）；运行期读到的配置字段缺失 → 该卡片显示「字段缺失，请重新配置」，其它卡片照常。
2. widget 超上限（32）：保存 400；前端添加按钮在 32 时禁用并提示。
3. 空表 / 全被行级权限过滤：卡片级空态（「当前筛选下无数据」），不阻塞整页。
4. 跨表（P3）指向无 READ 的表：卡片级「无权限」态，不泄露表名以外的字段信息。
5. 全局筛选占位符 `{{global.x}}` 未提供值：该条件忽略，并在卡片头标「未应用全局筛选」。
6. 主题切换：颜色全部取自 `--cn-*` 与色板常量（`ChartView` 现有 `readThemeColors` 口径），不写死色值；reduced-motion 下关闭吸附动画与卡片入场。
7. 移动端：`<640px` 仅预览（编辑入口隐藏，提示「请在桌面端编辑布局」），避免小屏拖拽与小格子数字输入不可用。

### 6. 前端文件结构

| 层 | 文件（全部新增于 `frontend/src/pages/grid/views/dashboard/`） | 改动 |
|---|---|---|
| 入口 | `DashboardView.tsx` | 画布容器、编辑态、全局筛选、批量取数、保存与脏检查 |
| 画布 | `DashboardGrid.tsx` | CSS Grid 渲染 + 拖拽/缩放/吸附（编辑态） |
| 卡壳 | `WidgetShell.tsx` | 标题、工具条、四态、手柄、`role="group"` |
| 内容 | `widgets/{Chart,Kpi,Table,Text}Widget.tsx` | 只消费 `Dataset` |
| 布局 | `layout/dashboardLayout.ts`、`layout/presets.ts` | 纯函数（I2）+ 预设 |
| 配置 | `config/DashboardConfigDrawer.tsx`、`config/widgetSchema.ts` | 属性面板 + widget 配置 schema（扩展 `ViewOptionSchema` 的 `kind`） |
| 图表 | `chart/chartRegistry.ts`、`chart/optionBuilders/*.ts` | 类型注册表与装配函数 |
| 模型 | `dashboardModel.ts` | 解析 / 归一 / 序列化 / 版本迁移 |
| 接线 | `views/viewModes.ts`、`GridPage.tsx`、`view-config/CreateEditViewForm.tsx` | 加 `dashboard` 模式按钮（lazy + hover 预取，同 `ChartView`）、类型下拉项 |
| 配置 schema | `view-config/viewOptionSchema.ts` | 加 `DASHBOARD_OPTIONS`（画布级：`cols` 只读展示、`row_height`、`gap`、`refresh_interval`） |

新增 `ViewOptionSchema.kind`：`table_select` / `field_multi_select`（已有）/ `metrics_list`（度量 + 聚合的重复行）/ `color_rule`（阈值 → 色）/ `layout_box`（x/y/w/h 四联输入）。属性面板复用 `groupOptionSchema` 的分区与折叠逻辑，不另写一套表单。

体积：`DashboardView` 整体 `lazy()`；新增图表类型（radar/funnel/gauge/heatmap/treemap）只进 dashboard chunk；`GridPage` 只增类型常量与 lazy 引用。落地后按实测给 `bundle-budget.json` 增 `DashboardView` 条目，`reason` 写明「画布必须随视图切换加载」。

### 7. 校验规则（唯一入口）

后端 `_validate_dashboard(view_options, table, db)`，在 `create_view` / `update_view` 的既有 `_validate_view_fields` 之后调用：

1. `schema_version == 1`（未来新版本按迁移函数升级后再校验）；`widgets` 为数组且 ≤32。
2. `id` 合法且唯一；`type` 在白名单；`layout` 全整数且满足 §1 边界。
3. `query.filters[].field_name` / `sortings[].field_name` 存在于表；`op` 在既有白名单内；`limit ≤ 5000`。
4. `chart.type` 在注册表白名单；`roles` 必填项非空且字段类型匹配（数值角色不接受文本列）；`agg / sort / stack / dual_axis` 取值合法；`top_n ≤ 100`。
5. `global_filters[].id` 唯一、`kind ∈ {date_range, select, search}`、`field` 存在且类型匹配。
6. 序列化出口按白名单裁剪未知键（写入前裁剪，不报错 —— 保证跨版本配置可读）。

前端同一套规则在 `dashboardModel.normalize` 里实现（读时补默认值、写时裁剪），两侧由 `tests/fixtures/dashboard/schema_cases.json` 的同一组用例驱动（合法 / 非法各 ≥10 例），防止 TS 与 Python 口径漂移（I1）。

### 8. 测试清单

**纯函数（单测）**
- `dashboardLayout`：越界 clamp、`w>cols`、重叠下推终止（迭代上限）、`compact` 幂等、`findFreeSlot` 落位、预设重排后数量不变、窄屏塌陷顺序 `(y,x)`。
- `dashboardModel`：旧配置（无 `schema_version`）读取补默认值、未知键裁剪、空 `widgets`、`charts[]` 不误读为 dashboard、序列化往返一致。
- `chartRegistry`：每类图的必填角色缺失提示、`minSize` 与卡内尺寸关系、`supports` 与属性面板可见性一致。
- 聚合：沿用 `chartBoard.test.ts` 口径，补「服务端 `Dataset` 与客户端 `Dataset` 结构一致」用例（同一份行集两条链路结果相等）。

**组件（vitest）**
- `WidgetShell` 四态（加载 / 空 / 错误 / 无权限）。
- `DashboardConfigDrawer`：切换图表类型后角色字段联动、多度量增删、`layout_box` 越界即时收敛。
- 编辑态：拖拽后坐标写入 draft、撤销/重做、`Esc` 回滚、未保存离开确认。

**接口**
- 校验分支：越界坐标 / 重复 id / 超 32 个 / 未知 `chart.type` / 字段不存在 / 非数值字段填进数值角色 / `top_n` 越界。
- 取数：批量返回多 widget、单 widget 失败进 `errors[]` 不影响其它、行级权限与字段隐藏生效、缓存命中与写后失效、`truncated` 标记正确。
- 视图白名单：未知 `view_type` 400；历史 `form` 行读取 200。

**备份 / seed**
- 含 dashboard 的 `view_options` 备份导出 → 导入往返一致；seed 引用校验对错误字段名报错带下标。

**e2e**
- 新建 dashboard → 加图表 / KPI / 文本三块 → 拖拽换位 → 保存 → 刷新后位置与内容一致。
- 只读成员（viewer）进入：只见预览，无编辑入口；切换视图模式回 `grid` 再回 dashboard 不丢配置。

### 9. 分期

| 期 | 目标 | 交付物 | 关键实现要点 | 验收 | 风险 |
|---|---|---|---|---|---|
| **P0** | 契约先立住：配置能存、能校验、能只读渲染 | schema v1（TS + Python）+ `schema_cases.json`；`view_type=dashboard` 接线；`dashboardModel` / `dashboardLayout`（只含 `clamp/compact`）；`ChartWidget` / `KpiWidget` / `TextWidget`；固定栅格只读渲染；seed 示例一屏 | ① `ViewType` 加 `DASHBOARD` + `KNOWN_VIEW_TYPES` 白名单（历史 `form` 兼容）；② `ChartCard` 增加 `dataset` 直传入口，避免第二套图表实现；③ 批量取数先做**客户端版**（复用 `useGridData` 行集，>2000 行提示截断）；④ `DashboardView` lazy + hover 预取；⑤ 属性面板先只读展示（"配置项一览"），编辑留 P1 | `make flow` 全绿；刷新后配置与渲染一致；非法配置 400 且 `detail` 定位到 `widgets[i].xxx`；bundle 基线更新带 reason | 契约一次定不全 → 用 `schema_version` + 白名单裁剪兜底，不为将来预埋字段 |
| **P1** | 可视化搭建：所见即所得的布局编辑器 | `DashboardGrid` 拖拽/缩放/吸附；数字输入 + 键盘微调；5 种预设；`DashboardConfigDrawer`（布局 / 数据 / 外观三段）；撤销栈与脏检查；窄屏塌陷 | ① 拖拽期只改 `transform` 预览，松手才写坐标（避免逐帧 reflow）；② `resolveOverlap` 下推 + `compact` 上浮是保存前唯一出口；③ 手柄只出现在编辑态与 hover 态，不用常驻控件占用卡面；④ 撤销存「widgets 快照」而非操作日志（≤32 块内存可控）；⑤ 保存用 `updated_at` 比对做乐观并发控制 | 拖拽 60fps（20 块以上不卡）；任意拖动后保存 → 重载无重叠无洞；撤销/重做与 `Esc` 行为有单测；e2e 拖拽用例通过 | 拖拽与滚动抢手势 → pointer sensor `distance:4`，容器滚动区不拦 `wheel` |
| **P2** | 图表够用：常见业务图表 + 大表口径 | `chartRegistry` + 8 类新图（area/stack/combo/radar/funnel/gauge/heatmap/treemap）；多度量与双轴；TopN / 排序 / 数值格式 / 阈值配色；`TableWidget`；服务端聚合端点 + 缓存；单卡 PNG 导出 | ① option 装配拆成 `axis/tooltip/legend/palette` 四个 helper，builder 只写差异；② 服务端 `Dataset` 与客户端同构（I3），`compute_summary` 输出直接映射；③ 同 `(table, filters)` 只扫一次，多 widget 共享行集；④ 新图表类型按需 `echarts.use`，不进主入口；⑤ 每类图一个 option 快照测试（`toMatchSnapshot`，锁配色与轴口径） | 大表（1.2 万行）首屏 ≤2s 且不拉全量行；每类图有快照；服务端/客户端同数据结果一致；`bundle-budget` 通过 | 新图类型膨胀体积 → 分 group 动态 `import()`，`gauge/treemap` 这类低频图后置 |
| **P3** | 模板化：复用与联动 | 另存为模板 / 从模板创建（字段映射 + 缺字段标记）；跨表 widget（逐表 READ + 字段隐藏）；全局筛选联动（`{{global.x}}`）；定时刷新；整屏导出 / 只读分享（另议 ADR） | ① 模板 = 去掉 `query.table_id` 与字段名的「结构 + 角色意图」，落地时按目标表重新解析字段（同名优先，类型兜底）；② 跨表校验逐表 `get_table_or_404(READ)`，失败降级为无权限卡；③ 全局筛选注入在取数前统一改写 `filters`，不在渲染层拼条件；④ 刷新用 `refresh_interval` + 页面可见性暂停（后台标签不轮询） | 模板跨表落地后缺字段有明确提示且可一键改；跨表越权用例 403/无权限卡；全局筛选生效范围有单测 | 模板跨表映射歧义 → 只自动认领同名同类型字段，其余标「待配置」，不猜 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案：新增视图类型还是扩展现有 | 新增 `view_type=dashboard`，`chart` 保持原语义 | 画布要跨 widget 独立配置、全局筛选、混排 KPI，语义已超出「图表视图」 | 扩展 `chart` 的 `charts[]`：一个视图两种形态（扁平键 / 嵌套画布）会让校验、配置面板、e2e 三处长期分叉 | `models.py` `ViewType`、`viewModes.ts`、`GridPage.tsx` |
| D2 | 配置存哪 | 复用 `view_options` JSON，加 `schema_version` | 零迁移；备份 / seed / 导入导出 / 三档可见性全部现成 | 新建 `dashboard_widget` 表：要重做权限、备份、seed，而 widget 无独立权限需求 | `models.py:259` |
| D3 | 坐标模型 | 12 列 × 40px 行高的整数栅格 | 响应式可推导；跨屏稳定；纯函数可测 | 绝对像素坐标：缩放与断点下漂移，无法归一 | `dashboardLayout.ts` |
| D4 | 响应式 | 只存桌面布局，窄屏按 `(y,x)` 塌陷 | 多断点布局要存 N 份坐标，编辑成本翻倍 | 每断点一套布局（Grafana 式）：实现与心智成本高于收益 | `collapseNarrow` |
| D5 | 聚合位置 | 小表客户端、大表服务端，`Dataset` 同构 | 小表省一次往返；大表不截断；渲染层单一路径 | 一律服务端：小表每屏多 N 次请求；一律客户端：1.2 万行表只能看样本 | `chartBoard.ts`、`compute.py` |
| D6 | 取数粒度 | 画布级批量端点，同 `(table, filters)` 只扫一次 | 32 个 widget 逐个请求会重复全表扫描 | 每 widget 一个端点：往返与扫描成本随块数线性增长 | `dashboard/data` |
| D7 | 图表扩展方式 | 类型注册表（角色声明 + builder） | 现状加一类图要改三处，易漏；面板可由 `roles/supports` 生成 | 每类图一个组件：面板与校验四处重复，配置项越加越乱 | `chartRegistry.ts` |
| D8 | 跨表 | P3 才放开，逐表鉴权 | 跨表牵涉权限、字段命名、模板映射，先保证单表闭环 | P0 即跨表：权限与映射未定型时会把复杂度压进契约 | `_validate_dashboard` |
| D9 | 不支持的能力 | 不做地图 / 3D / 实时流 | 地图涉数据合规（另立 ADR）；3D 价值低；实时流需推送链路 | — | — |
| D10 | 编辑交互 | 拖拽 + 数字输入 + 预设三通道 | 精确对齐与键盘用户不能只有拖拽；预设降低从零排版的成本 | 仅拖拽：像素级对齐不可达，表单用户无入口 | `DashboardGrid`、`DashboardConfigDrawer` |
| D11 | 类型白名单 | `create/update` 校验 `KNOWN_VIEW_TYPES`，历史 `form` 只读兼容 | 消除「写错类型到渲染才报错」；存量行不受影响 | 继续放任自由字符串：前端新增模式与后端能力长期可能不一致 | `routers/views.py` |
| D12 | 内容组件边界 | 卡壳管四态、内容只管 `Dataset → 图形` | 四态统一后不重复写骨架/重试；内容组件可被分析页复用 | 内容组件自管请求与状态：缓存与加载态无法跨卡片统一 | `WidgetShell.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」。

## Consequences

- **正向**：一张视图可承载「指标 + 趋势 + 分布 + 明细 + 说明」的同屏叙事，替代「建 6 个图表视图来回切」；布局与图表能力都以注册表 / schema 表达，后续加类型改一处；服务端聚合让大表也能出全量图，不再受 2000 行样本限制；复用 `ChartCard`、`compute.py`、`list_rows`，不新增第二套渲染与取数。
- **负向**：`view_options` 从「十几项扁平键」变成嵌套结构，配置体积与校验复杂度上升（上限 32 块 + 白名单裁剪兜底）；拖拽编辑器是全新交互面，测试与可访问性成本高于只读视图；服务端批量聚合引入缓存一致性问题（写后失效必须覆盖）。
- **风险与缓解**：① 契约漂移 → 同一份 `schema_cases.json` 驱动 TS 与 Python 两侧测试；② 体积超限 → 全 lazy + 新图分 group 动态加载，落地即补 `bundle-budget` 条目；③ 大表首屏慢 → 服务端聚合 + 卡片级独立加载，先出骨架后填充；④ 拖拽与既有 grid 手势冲突 → `distance:4` + 编辑态才挂 sensor。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 视图可见性 | `tables_dataview.visibility` + 授权名单 | 画布沿用三档模型，不新增权限维度 | ADR 0003 |
| 行级权限 / 字段隐藏 | `list_rows`、`scan_rows` | widget 取数不得绕过，跨表逐表判定 | ADR 0004 |
| 分析聚合 | `plugins/analytics/services/compute.py` | 复用 `scan_rows` + `compute_summary`，不另写 SQL 聚合 | ADR 0006 |
| 视图配置 schema | `viewOptionSchema.ts` | 画布沿用 `ViewOptionSchema` 的 `kind/group/visibleWhen` 约定 | ADR 0022 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/grid/views/dashboard/DashboardView.tsx`、`frontend/src/pages/grid/views/dashboard/WidgetShell.tsx`、`src/cndb/plugins/tables/services/core/dashboard_config.py`、`src/cndb/plugins/tables/routers/views.py`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`frontend/src/pages/grid/view-config/CreateEditViewForm.tsx`、`src/cndb/cli/seed/views.py` | `tests/test_dashboard_config.py`、`tests/fixtures/dashboard/schema_cases.json`、`frontend/src/pages/grid/views/dashboard/*.test.ts`、`frontend/src/pages/grid/views/dashboard/*.test.tsx` | 随本次提交 |
| P1 | 未开始 | — | — | — |
| P2 | 未开始 | — | — | — |
| P3 | 未开始 | — | — | — |

## 交接（会话结束更新）

- 当前阶段：P0 已落地，下一步 P1（布局编辑器）
- 已完成：schema v1（TS `dashboardModel.ts` + Python `dashboard_config.py`）与共享契约用例 `tests/fixtures/dashboard/schema_cases.json`；`view_type=dashboard` 白名单与 create/update/seed 接线；只读栅格渲染（`DashboardView` + Chart/KPI/Text/Table）；客户端组件级 query；非法配置 400 定位 `widgets[i].xxx`；seed「销售画布」示例；`DashboardView` lazy chunk 已入 bundle 基线
- 下一步：P1 拖拽 / 缩放 / 吸附 + 数字输入 + 5 种预设 + `DashboardConfigDrawer` + 撤销栈与脏检查；先做 `DashboardGrid` 的纯函数 `resolveOverlap` 与测试
- 已知坑：`ChartCard` 的 ECharts 实例必须常驻容器（dispose 会清空 DOM，React 再卸载子节点会抛 `removeChild`），画布卡片沿用「容器不承载 React 子节点、空态用兄弟覆盖层」的写法；P0 复用 `useGridData` 的 2000 行行集，大表截断提示与服务端聚合留 P2；`applyWidgetQuery` 的排序空值恒排后（对齐 SQL NULLS LAST）
- 最近一次全绿：`make test` 6197 passed / 前端 2536 passed（一次并行抖动用例单跑通过）
