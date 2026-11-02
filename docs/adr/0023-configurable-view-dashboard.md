# ADR 0023: 可配置复杂视图模板（dashboard 画布）

Status: Implemented（2026-11-02 人工确认）
Date: 2026-10-23
Related: `frontend/src/pages/grid/views/ChartView.tsx`、`frontend/src/pages/grid/views/chartBoard.ts`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`frontend/src/pages/grid/view-config/CreateEditViewForm.tsx`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/views/viewModes.ts`、`frontend/src/pages/grid/useGridData.ts`、`src/cndb/plugins/tables/routers/views.py`、`src/cndb/plugins/tables/models.py`、`src/cndb/plugins/analytics/services/compute.py`、`docs/adr/0022-gallery-view-content-tables.md`
需求卡片: 无卡片（需求直接立项，原句逐字见 §口径）
> 本 ADR 已合并原 ADR 0077（dashboard 整屏导出与登录态只读分享），口径 / 决策 / 落地状态见文末「续作」小节（编号 0077 不复用）。

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
// frontend/src/pages/grid/views/dashboard/dashboardLayout.ts
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

编辑态与预览态：`editing` 为本地布尔；编辑态显示栅格底纹、手柄、添加按钮、属性面板、撤销栈（快照式，上限 50 步）；`⌘/Ctrl+S` 保存，`Esc` 退出编辑并回滚未保存变更（有确认）。保存走既有 `PATCH /views/{id}`（`view_options` 整体替换）；单用户编辑下采用后写覆盖，`updated_at` 乐观并发比对随 P2 批量取数一同接入（避免与取数缓存失效在同轮改两处契约）。

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
| `POST .../views/{view_id}/dashboard/data` | 新增：批量取 widget 数据。请求 `{ "widget_ids": ["w1"], "globals": {"date_from": "2026-01-01"}, "force": false }`；响应 `{ "items": [{ "widget_id", "dataset", "meta": { "scanned", "total", "truncated", "cached", "unapplied_globals" } }], "errors": [{ "widget_id", "detail" }] }`；权限：视图可读 + 每张参与表各自 READ（跨表目标表越权 / 软删整组降级为 `errors[]`） |
| `GET .../views/{view_id}/dashboard/data` | 不提供：避免 URL 长度与缓存口径分裂（配置在 body 里更可控） |
| `GET / POST / DELETE /api/v1/accounts/preferences/dashboard-templates[/{id}]` | 新增（P3 模板，账户偏好域）：列表 / 另存（同名覆盖，保留模板 id）/ 删除。模板只存「结构 + 字段名/类型快照」，后端统一剥离 `query.table_id`，落地时前端按目标表重新认领字段（D13） |
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
| 布局 | `dashboardLayout.ts`、`dashboardDraft.ts`、`useDashboardDraft.ts` | 纯函数（I2）+ 5 种预设 + 快照撤销栈与 draft 操作 |
| 配置 | `DashboardConfigDrawer.tsx` | 属性面板（布局 / 数据 / 外观；懒加载） |
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
4. `query.table_id`（P3）：正整数且逐表 `get_table_or_404(READ)`；**保存期严格**——目标表不存在 / 越权 / 软删即 400（`widgets[i].query.table_id`）；字段引用按**目标表** schema 校验，而不是视图所属基表。
5. `chart.type` 在注册表白名单；`roles` 必填项非空且字段类型匹配（数值角色不接受文本列）；`agg / sort / stack / dual_axis` 取值合法；`top_n ≤ 100`。
6. `global_filters[].id` 唯一、`kind ∈ {date_range, select, search}`、`field` 存在且类型匹配。
7. 序列化出口按白名单裁剪未知键（写入前裁剪，不报错 —— 保证跨版本配置可读）。

**读路径宽容（不变量补充 I4）**：取数时同一个归一函数带 `allow_unavailable_targets=True`，目标表不可用（越权 / 软删 / 删除）时跳过该 widget 的字段级校验、原样透传配置，由取数层把整组降级为「无权限访问目标表」错误卡，不整页 400；保存期保持严格，不放宽落库入口。

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
- 跨表（P3）：保存期保留 `table_id`、目标表字段缺失 400（定位 `widgets[i].kpi`）、非正整数 / 不存在 / 跨工作区 / 软删目标表 400；取数期按表分组扫描（基表组套视图 filters + 全局筛选，跨表组不套）、目标表字段隐藏生效、目标表软删或 viewer 无 READ 降级为错误卡、`widget_ids` 子集只扫对应表。
- 模板（P3）：另存剥离 `query.table_id`、同名覆盖保留 id、数量 / 体积上限 400、字段快照只留 `{name: type}`、删除未知 id 404、非法配置 400。
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
| **P1** | 可视化搭建：所见即所得的布局编辑器 | `DashboardGrid` 拖拽/缩放/吸附；数字输入 + 键盘微调；5 种预设；`DashboardConfigDrawer`（布局 / 数据 / 外观三段）；撤销栈与脏检查；窄屏塌陷 | ① 拖拽期只改 `transform` 预览，松手才写坐标（避免逐帧 reflow）；② `resolveOverlap` 下推 + `compact` 上浮是保存前唯一出口；③ 手柄只出现在编辑态与 hover 态，不用常驻控件占用卡面；④ 撤销存「widgets 快照」而非操作日志（≤32 块内存可控）；⑤ 保存走既有 `PATCH /views/{id}` 后写覆盖，`updated_at` 乐观并发比对随 P2 批量取数接入 | 拖拽 60fps（20 块以上不卡）；任意拖动后保存 → 重载无重叠无洞；撤销/重做与 `Esc` 行为有单测；e2e 拖拽用例通过 | 拖拽与滚动抢手势 → pointer sensor `distance:4`，容器滚动区不拦 `wheel` |
| **P2** | 图表够用：常见业务图表 + 大表口径 | `chartRegistry` + 8 类新图（area/stack/combo/radar/funnel/gauge/heatmap/treemap）；多度量与双轴；TopN / 排序 / 数值格式 / 阈值配色；`TableWidget`；服务端聚合端点 + 缓存；单卡 PNG 导出 | ① option 装配拆成 `axis/tooltip/legend/palette` 四个 helper，builder 只写差异；② 服务端 `Dataset` 与客户端同构（I3），`compute_summary` 输出直接映射；③ 同 `(table, filters)` 只扫一次，多 widget 共享行集；④ 新图表类型按需 `echarts.use`，不进主入口；⑤ 每类图一个 option 快照测试（`toMatchSnapshot`，锁配色与轴口径） | 大表（1.2 万行）首屏 ≤2s 且不拉全量行；每类图有快照；服务端/客户端同数据结果一致；`bundle-budget` 通过 | 新图类型膨胀体积 → 分 group 动态 `import()`，`gauge/treemap` 这类低频图后置 |
| **P3** | 模板化：复用与联动 | 另存为模板 / 从模板创建（字段映射 + 缺字段标记）；跨表 widget（逐表 READ + 字段隐藏）；全局筛选联动（`{{global.x}}`）；定时刷新；整屏导出 / 只读分享（由 ADR 0077 承接） | ① 模板 = 去掉 `query.table_id` 与字段名的「结构 + 角色意图」，落地时按目标表重新解析字段（同名优先，类型兜底）；② 跨表校验逐表 `get_table_or_404(READ)`，失败降级为无权限卡；③ 全局筛选注入在取数前统一改写 `filters`，不在渲染层拼条件；④ 刷新用 `refresh_interval` + 页面可见性暂停（后台标签不轮询） | 模板跨表落地后缺字段有明确提示且可一键改；跨表越权用例 403/无权限卡；全局筛选生效范围有单测 | 模板跨表映射歧义 → 只自动认领同名同类型字段，其余标「待配置」，不猜 |

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
| D13 | 模板存哪 | 存账户偏好（`user.preferences.dashboard_templates`），不做团队级模板表 | 模板是「个人复用习惯」，复用偏好域零迁移、零新权限；存量 preferences 读写链路现成 | 新建团队模板表：要补权限、备份、管理入口，而本期无共享模板诉求 | `plugins/accounts/services/preferences.py`、`routers/preferences.py` |
| D14 | 跨表取数与降级 | 保存期逐表 READ 严格校验；取数期按 `(table_id)` 分组扫描，基表组套视图 filters + 全局筛选、跨表组不套；目标表不可用时整组降级为错误卡 | 跨表字段与基表 schema 无关，继承基表筛选会误伤；读路径宽容可避免一张表失效炸整页，且配置保存时已校验过 | 取数期也严格拒绝：目标表被删后整个画布 400；跨表组继承基表 filters：字段名不着边、筛选静默失效 | `dashboard_config.py`、`dashboard_data.py`、`routers/views.py` |

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
| P0 | 已落地 | `frontend/src/pages/grid/views/dashboard/DashboardView.tsx`、`frontend/src/pages/grid/views/dashboard/WidgetShell.tsx`、`src/cndb/plugins/tables/services/core/dashboard_config.py`、`src/cndb/plugins/tables/routers/views.py`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`frontend/src/pages/grid/view-config/CreateEditViewForm.tsx`、`src/cndb/cli/seed/views.py` | `tests/test_dashboard_config.py`、`tests/fixtures/dashboard/schema_cases.json`、`frontend/src/pages/grid/views/dashboard/*.test.ts`、`frontend/src/pages/grid/views/dashboard/*.test.tsx` | fccfa05c |
| P1 | 已落地 | `frontend/src/pages/grid/views/dashboard/DashboardGrid.tsx`、`frontend/src/pages/grid/views/dashboard/DashboardConfigDrawer.tsx`、`frontend/src/pages/grid/views/dashboard/dashboardLayout.ts`、`frontend/src/pages/grid/views/dashboard/dashboardDraft.ts`、`frontend/src/pages/grid/views/dashboard/useDashboardDraft.ts`、`frontend/src/pages/grid/views/dashboard/WidgetShell.tsx`、`frontend/src/pages/grid/views/dashboard/DashboardView.tsx`、`frontend/src/pages/grid/GridPage.tsx` | `frontend/src/pages/grid/views/dashboard/dashboardLayout.test.ts`、`frontend/src/pages/grid/views/dashboard/dashboardDraft.test.ts`、`frontend/src/pages/grid/views/dashboard/DashboardConfigDrawer.test.tsx`、`frontend/src/pages/grid/views/dashboard/DashboardView.test.tsx`、`frontend/tests/e2e/critical/dashboard-edit.spec.ts` | 56292c12 |
| P2 | 已落地 | `frontend/src/pages/grid/views/dashboard/chart/chartRegistry.ts`、`frontend/src/pages/grid/views/dashboard/chart/option.ts`、`frontend/src/pages/grid/views/dashboard/chart/dataset.ts`、`frontend/src/pages/grid/views/dashboard/chart/types.ts`、`frontend/src/pages/grid/views/dashboard/chart/register.ts`、`frontend/src/pages/grid/views/dashboard/chart/ChartCanvas.tsx`、`frontend/src/pages/grid/views/dashboard/useDashboardData.ts`、`frontend/src/pages/grid/views/dashboard/widgets/TableWidget.tsx`、`frontend/src/pages/grid/views/dashboard/DashboardView.tsx`、`frontend/src/pages/grid/GridPage.tsx`、`src/cndb/plugins/tables/services/core/dashboard_data.py`、`src/cndb/plugins/tables/routers/views.py`、`src/cndb/core/cache.py`、`src/cndb/core/events.py`、`frontend/scripts/bundle-budget.json` | `tests/test_dashboard_data.py`、`frontend/src/pages/grid/views/dashboard/chart/dataset.test.ts`、`frontend/src/pages/grid/views/dashboard/chart/option.test.ts`、`frontend/src/pages/grid/views/dashboard/chart/__snapshots__/option.test.ts.snap`、`frontend/src/pages/grid/views/dashboard/chart/register.test.ts`、`frontend/src/pages/grid/views/dashboard/chart/ChartCanvas.test.tsx`、`frontend/src/pages/grid/views/dashboard/useDashboardData.test.tsx`、`frontend/src/pages/grid/views/dashboard/DashboardView.test.tsx` | 437480c6 |
| P3 | 已落地 | `frontend/src/pages/grid/views/dashboard/DashboardTemplateDialog.tsx`、`frontend/src/pages/grid/views/dashboard/dashboardTemplate.ts`、`frontend/src/pages/grid/views/dashboard/dashboardGlobals.ts`、`frontend/src/pages/grid/views/dashboard/GlobalFilterBar.tsx`、`frontend/src/pages/grid/views/dashboard/DashboardConfigDrawer.tsx`、`frontend/src/pages/grid/views/dashboard/DashboardView.tsx`、`frontend/src/pages/grid/views/dashboard/dashboardModel.ts`、`frontend/src/pages/grid/views/dashboard/useDashboardData.ts`、`frontend/src/api/preferences.ts`、`src/cndb/plugins/accounts/services/preferences.py`、`src/cndb/plugins/accounts/routers/preferences.py`、`src/cndb/plugins/tables/services/core/dashboard_config.py`、`src/cndb/plugins/tables/services/core/dashboard_data.py`、`src/cndb/plugins/tables/routers/views.py` | `tests/test_dashboard_templates.py`、`tests/test_dashboard_cross_table.py`、`tests/test_dashboard_config.py`、`tests/fixtures/dashboard/schema_cases.json`、`frontend/src/pages/grid/views/dashboard/dashboardTemplate.test.ts`、`frontend/src/pages/grid/views/dashboard/dashboardGlobals.test.ts`、`frontend/src/pages/grid/views/dashboard/GlobalFilterBar.test.tsx`、`frontend/src/pages/grid/views/dashboard/DashboardTemplateDialog.test.tsx`、`frontend/src/pages/grid/views/dashboard/DashboardConfigDrawer.test.tsx`、`frontend/src/pages/grid/views/dashboard/DashboardView.test.tsx`、`frontend/tests/e2e/critical/dashboard-p3.spec.ts` | 8ae5c758 |

## 交接（会话结束更新）

- 当前阶段：P3 已落地，P0-P3 全部交付（整屏导出 / 只读分享已由 ADR 0077 承接，不在本期）
- 已完成：P0 契约与只读画布；P1 布局编辑器——`DashboardGrid` 拖拽 / 缩放 / 方向键微调（拖拽期仅 `transform` 预览，松手提交一次），`DashboardConfigDrawer`（布局 / 数据 / 外观，lazy 加载）数字输入与组件增删，5 种版式预设，快照式撤销栈（≤50 步）+ 脏检查，显式保存 / `Ctrl+S` 与 `Esc` 确认回滚，窄屏塌陷 + 编辑入口禁用；`GridPage` 保存链路先写 draft 再立即持久化，避开 500ms 防抖窗口；P2 图表注册表与 14 类图（新增 area/stack/combo/radar/funnel/gauge/heatmap/treemap），多度量 / 双轴 / TopN / 排序 / 数值格式 / 阈值配色 / 色板，`TableWidget` 列白名单 + 本地排序 + 点行开详情，大表（>2000 行）走 `POST .../views/{id}/dashboard/data` 服务端批量聚合（同表只扫一次、TTL 60s / LRU 128 缓存 + 事件失效），小表客户端同构 Dataset，PATCH 视图接入 `updated_at` 乐观并发（409）；P3 模板另存 / 从模板创建（模板存账户偏好、字段快照 + 同名 / 同类型自动认领 + 缺字段标「待配置」一键改）、跨表 widget（`query.table_id` 逐表 READ，字段按目标表 schema 校验，取数按表分组扫描，目标表越权 / 软删降级「无权限访问目标表」错误卡）、`{{global.x}}` 全局筛选联动（缺值条件忽略并标「未应用全局筛选」）、`refresh_interval` 定时刷新（后台标签页跳过）与手动刷新；P3 e2e `frontend/tests/e2e/critical/dashboard-p3.spec.ts` 5 例覆盖模板同表往返 / 跨表来源切换与服务端取数 / 全局筛选未应用标记 / 定时刷新 / 缺字段映射；模板另存时跨表 widget 的引用字段按目标表 schema 补录类型快照（基表字段优先、同名字段不覆盖，读取失败降级为基表快照并提示），缺字段映射覆盖跨表来源
- 下一步：无（本 ADR 已全部交付）；整屏导出 / 只读分享见 ADR 0077
- 已知坑：① dnd-kit 的 `listeners` 是 `{ onPointerDown }` 映射，必须逐事件展开到 DOM，若整体作为 `listeners={...}` 透传则拖拽永不激活；② dnd-kit 在拖拽激活后于 document 捕获阶段拦截 click，松手 50ms 后才移除，e2e 拖拽后需等待再点工具栏；③ 图标类子元素会抢 pointer 事件，拖拽手柄内的 icon 需 `pointerEvents: none`；④ `ChartCard` 的 ECharts 实例必须常驻容器（dispose 会清空 DOM，React 再卸载子节点会抛 `removeChild`）；⑤ 排序 / TopN 必须先保留原始 categories 索引再重排，若拿排序后索引去访问原始顺序的 `series.data` 会标签数值错位；⑥ SQLite `func.now()` 只有秒级精度，`update_view` 的乐观并发令牌需显式写微秒级 UTC；⑦ dashboard 14 类图使 `DashboardView` chunk 增长（echarts 模块按需注册但随 dashboard chunk 加载），`bundle-budget` 基线已带 reason 更新；⑧ 跨表目标表可用性判定必须 catch `(HTTPException, CndbError)`——`get_table_or_404` 的越权拒绝抛 `PermissionDeniedError`（`CndbError` 子类，非 `HTTPException`），只 catch 后者会让降级错误卡变成整页 500/403；⑨ 读路径重归一化必须带 `allow_unavailable_targets=True`（哨兵 `UNAVAILABLE_TARGET` 原样透传 widget），否则目标表被软删后整页 400；保存路径保持严格；⑩ 跨表 widget 强制走服务端取数（客户端只预取基表行集），`hasCrossTable` 决定 `useServer`，否则跨表卡会静默拿到基表行；⑪ 模板对话框必须 lazy 且仅在打开时挂载（`templateMode !== null`），常挂载会把对话框源码拉进 `DashboardView` chunk 致 bundle 预算超限；antd 6 的 `Drawer` 宽度参数是 `size`（`width` 已弃用会告警）；⑫ dashboard P3 e2e 必须用 API 自建唯一命名视图并在 `finally` 删除（连同同名模板），不可改写 seed「销售画布」——该视图被 `dashboard-edit.spec.ts` 并行持有；属性面板「数据」页签需限定 `.ant-drawer` 内定位，页面导航存在同名 `数据表 / 数据分析` Tab，`getByRole("tab", { name: "数据" })` 会触发 strict violation；⑬ 模板另存的字段类型快照必须按 `query.table_id` 逐表补录（`collectTemplateTableIds` + `fieldApi.list`），只传基表字段会让跨表 widget 的引用字段不在快照里，落地时静默漏掉缺字段映射（`buildDashboardTemplate` 的 `extraFields` 按表 id 合并，基表同名优先）
- 最近一次全绿：`make check`（后端 6256 passed / 覆盖率 95.50%，前端 226 文件 / 2759 passed / 覆盖率双门槛达标）、`make e2e`（101 passed / 21 skipped）、`pnpm build`（chrome81 静态门禁 0 warning）与 `pnpm bundle:budget`（DashboardView 57.51 KiB ≤ 57.76 KiB）

## 续作：dashboard 整屏导出与登录态只读分享（原 ADR 0077，已并入本 ADR）

> 原独立文件已删除，编号 0077 不复用（追溯：`git log -- docs/adr/0077-dashboard-fullscreen-export-readonly-share.md`）。下列各节保留原 ADR 的约束 / 决策编号，代码与提交里的 `ADR 0077 Cx / Dx` 指的就是本节。
> 需求卡片：`docs/requirements/0077-dashboard-fullscreen-export-readonly-share.md`（需求原文与约束编号的唯一副本）

### 口径（原 ADR 0077）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 整屏导出 | 新增画布级捕获目标：按 `normalizeLayout` 当前布局一次性把全部 widget 渲染进同一张 PNG / PDF；单卡 PNG 保留为快捷入口，不替代整屏 |
| C2 | 整屏导出 | `DashboardView` 工具栏从「仅 `canEdit`」改为「所有可见者」；导出 / 刷新 / 复制链接不要求 `EDIT_VIEWS`（D5） |
| C3 | 整屏导出 | PNG（默认）与 PDF（可选）；复用 `html2canvas-pro` + `jsPDF`，两者继续在导出点击时动态导入（D3） |
| C4 | 整屏导出 | 捕获区 = 全局筛选栏 + 画布主体；排除画布工具栏与应用导航；背景取当前主题页面色，空 / 错状态照实输出（D4） |
| C5 | 只读分享 | 「复制只读链接」生成带 `view` / `mode=dashboard` / `present=1` 的深链；打开即进入只读展示（D6 / D7） |
| C6 | 只读分享 | 不新增匿名入口，不新增 share token；接收者走既有登录态 + 表 `READ` + 视图可见性判定（D2 / D8） |
| C7 | 只读分享 | 可见范围沿用视图三档（`private` / `shared` / `table`）与既有授权名单；分享设置直接复用「视图权限」抽屉（D8） |
| C8 | 只读分享 | 展示态要求 `view` 必须解析成功，**不回落到默认视图**；不可见 / 已删 / 非 dashboard 视图按「链接无效」处理（D9） |
| C9 | 只读分享 | 展示态隐藏 `GridToolbar` / `GridViewBar` / 聚合条与行详情入口，保留刷新、导出、退出展示；窄屏沿用单列塌陷（D7） |
| C10 | 整屏导出 | 既有 `ExportPanel` 的 PDF 默认行为不变；新增导出辅助函数按需导入，不进入 `GridPage` / `DashboardView` 主 chunk（D10） |
| C11 | 整屏导出 / 只读分享 | 零后端端点、零表结构、零迁移；权限判定复用 `get_table_or_404` + `get_view_or_404`（D1 / D8） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

### Decision（原 ADR 0077）

### 1. 数据模型

**无新增表、无新增列、无新增迁移**：

- 画布配置继续存 `tables_dataview.view_options`（ADR 0023 D2）。
- 分享范围继续由 `tables_dataview.visibility` + `tables_dataviewpermission` 授权名单表达（ADR 0003）。
- 只读链接是**无状态深链**：`?view=<id>&mode=dashboard&present=1`，不落库、不生成 token、不存快照。链接本身不携带任何权限或数据。

### 2. 判定算法（唯一入口）

**后端权限判定不变**：分享链接打开后仍由 `GridPage` 走既有链路——`useTable` / `useTableViews` 取当前用户可见视图，`get_table_or_404(READ)` + `get_view_or_404(VIEW_READ)` 决定 404/403；`records` / `dashboard/data` 继续叠加行级权限与字段隐藏。本 ADR **不新增任何判定入口**。

前端新增两个纯函数（`dashboardShare.ts`），只负责链接与展示态解析，不做权限判定：

```ts
export interface DashboardShareInput {
  origin: string
  pathname: string      // /w/{wid}/tables/{tid}
  viewId: number | string
}
export function buildDashboardShareUrl(input: DashboardShareInput): string
// `${origin}${pathname}?view=${viewId}&mode=dashboard&present=1`

export type PresentTarget =
  | { kind: 'normal' }
  | { kind: 'present'; view: View }
  | { kind: 'invalid'; reason: 'missing_view' | 'not_visible' | 'not_dashboard' }

export function resolvePresentTarget(
  views: View[],
  requestedViewId: string | null,
  present: boolean,
): PresentTarget
```

判定顺序固定：

1. `present !== true` → `normal`（既有回落逻辑不变）。
2. `requestedViewId` 缺失 → `invalid/missing_view`。
3. `views` 中不存在该 id → `invalid/not_visible`（**禁止回落到默认视图**，I2 / C8）。
4. 目标视图 `view_type !== 'dashboard'` → `invalid/not_dashboard`。
5. 命中 → `present`。

`GridPage` 在 `present` 模式下以该结果驱动渲染：`invalid` 显示「链接无效或无权访问」空态；`present` 隐藏工具栏并渲染只读画布。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/tables/{tid}/views` | 不变：只返回当前用户可见视图，作为 `resolvePresentTarget` 的输入 |
| `GET .../views/{view_id}` / `POST .../views/{view_id}/dashboard/data` / 行记录读取 | 不变：权限、行级权限、字段隐藏与缓存口径全部沿用 |
| `PATCH .../views/{view_id}` / 可见性与授权端点 | 不变：分享设置复用「视图权限」抽屉 |
| 新增导出 / 分享端点 | **无**：整屏导出为前端视觉快照；只读分享为无状态深链 |

### 4. 边界与例外

1. **导出目标**：`DashboardView` 内新增专用捕获容器，包住 `GlobalFilterBar` + `DashboardGrid`，不含画布工具栏、应用侧栏 / 顶栏、弹窗与行详情抽屉（C4）。
2. **数据就绪**：页面行集加载中、或服务端批量取数 `loading` 时导出按钮禁用；捕获前连续等待两帧，确保 `Skeleton` 已退出、图表已 `setOption`（C4 / I1）。
3. **空 / 错状态**：单卡取数失败或空数据照实导出，不中断整屏；整张画布无 widget 时禁用导出并提示。
4. **主题与背景**：捕获背景取当前 `--cn-bg-page`（读取失败回退 `#ffffff`）；PDF 背景通过新增可选参数传入，既有 `ExportPanel` 默认仍为白色（C10 / 16）。
5. **尺寸与清晰度**：沿用 `computeRenderScale` 的画布像素预算与单边上限；超大画布宁可降低 scale 也不分配失败；PDF 继续走 `computePageSize` + `MAX_PAGE_PT` 分页。
6. **文件名**：`<视图名>-<YYYYMMDD_HHMMSS>.<png|pdf>`，视图名按 Windows 非法字符清洗，空名回退「画布」。
7. **只读链接**：链接只在 dashboard 视图生成；非 dashboard 视图不展示「复制只读链接」入口。链接不含 `q` / 其他视图参数，保证转发结果稳定。
8. **权限变化**：视图删除、转 `private`、从 `shared` 名单移除、表 / 工作区删除后，接收者打开链接得到「链接无效或无权访问」，不回落到默认视图（C8）。
9. **展示态交互**：隐藏 `GridToolbar`、`GridViewBar`、底部聚合条、行详情与导入 / 导出入口；保留刷新、导出、退出展示；表格 widget 点击行不打开详情（C9 / I3）。
10. **窄屏**：沿用 ADR 0023 D4 的单列塌陷；展示态与正常态一致，不额外存储移动端布局。
11. **自动刷新**：展示态沿用画布 `settings.refresh_interval`，后台标签页不轮询（ADR 0023 P3）；不新增推送。
12. **导出与权限**：导出结果只反映当前用户可见字段与行；不生成可被他人越权读取的服务器快照（I2）。

### 5. 迁移

无迁移。分享为无状态深链，导出为客户端行为；`tables_dataview` / 授权表 / 备份格式均不变，存量零迁移、无 downgrade。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 导出编排 | `frontend/src/pages/grid/views/dashboard/dashboardExport.ts`（新增） | `exportDashboardToPng` / `exportDashboardToPdf`：等待就绪 → 捕获专用容器 → 下载；文件名与主题背景 |
| 捕获复用 | `frontend/src/pages/import-export/ImportExportDialog/exportPdf.ts` | 抽出 `captureElement(target, backgroundColor)`（展开滚动 / 测量 / 渲染 / 恢复）；新增可选背景参数；保持既有 `exportViewToPdf` 默认行为 |
| 图片导出 | `frontend/src/pages/import-export/ImportExportDialog/exportPng.ts`（新增或并入 `exportPdf.ts`） | 用同一 `captureElement` 产出 PNG Blob 并触发下载 |
| 链接与展示解析 | `frontend/src/pages/grid/views/dashboard/dashboardShare.ts`（新增） | `buildDashboardShareUrl`、`resolvePresentTarget` 纯函数 |
| 画布页 | `frontend/src/pages/grid/views/dashboard/DashboardView.tsx` | 工具栏对所有可见者渲染；新增导出（PNG / PDF）、复制链接、退出展示；新增捕获容器 ref；展示态隐藏编辑并禁用行点击 |
| 页面接线 | `frontend/src/pages/grid/GridPage.tsx` | 解析 `present=1`；展示态隐藏 `GridToolbar` / `GridViewBar` / 聚合条；向 `DashboardView` 传 `presenting` / `onExitPresent` / 分享回调；`invalid` 显示空态 |
| 视图栏 | `frontend/src/pages/grid/gridViewBar.tsx` | 桌面 / 移动「更多」菜单新增「复制只读链接」，仅当前视图为 dashboard 时可用 |
| 体积预算 | `frontend/scripts/bundle-budget.json` | 若新增独立导出 chunk，按实测补条目与 `reason`；`DashboardView` 基线不得因静态引入上涨 |

### 7. 测试清单

**判定层（单测）**

- `buildDashboardShareUrl`：origin / pathname 组合正确；仅保留 `view` / `mode=dashboard` / `present=1`；数字 / 字符串 id 一致；不丢路径前缀。
- `resolvePresentTarget`：非展示态返回 `normal`；缺 `view` / 视图不在可见列表 / 非 dashboard → 对应 `invalid`；命中返回 `present`；**显式断言不回落到默认视图**。
- 文件名构造：非法字符清洗、空视图名回退、时间戳格式。
- `captureElement` / `exportViewToPng`（html2canvas mock）：背景色传入、包围盒尺寸、scale 上限、滚动容器恢复（成功与抛错两条路径）。

**组件（vitest）**

- `DashboardView`：只读身份仍渲染导出 / 刷新 / 复制链接；编辑身份保留原工具栏；加载中禁用导出；展示态无编辑 / 模板 / 删除入口，且行点击不触发回调。
- `GridPage`：`present=1` 时隐藏页面工具栏与聚合条；目标视图不可见或非 dashboard 显示「链接无效或无权访问」；正常模式渲染不变。
- `GridViewBar`：dashboard 视图出现「复制只读链接」并复制正确 URL；非 dashboard 不出现 / 禁用。
- `ViewPermissionDrawer`：既有三档与名单用例回归，分享设置未引入新写口径。

**接口层**

- 无新增端点。回归：不可见视图 `GET` → 404；可见只读视图可读、写 → 403；行级权限 / 字段隐藏在 `records` 与 `dashboard/data` 两种取数路径均生效。
- 匿名访问只读链接仍被 `ProtectedRoute` 挡到登录页；不存在绕过登录的 dashboard 公开端点。

**迁移 / 备份**

- 无迁移；工作区备份 / 恢复、视图导入导出不新增字段，往返用例不改。

**e2e（前端）**

- owner 建 dashboard → 视图权限设为 `shared` 并授权 viewer → 复制只读链接 → viewer 在第二个登录态直达链接：画布可见、无编辑 / 删除 / 行详情入口。
- 只读链接触发 PNG / PDF 下载（Playwright `download` 事件，文件名与后缀正确、文件非空）。
- 收回报权 / 视图转 `private` / 删除视图后，同一链接显示「链接无效或无权访问」，不展示默认视图。
- 只读用户（无 `EDIT_VIEWS`）仍可使用整屏导出。

**低配模拟（人工实测，非门禁）**

- 探针：`frontend/tests/perf/dashboard-export.spec.ts`（耗时）+ `frontend/tests/perf/dashboard-export-memory.spec.ts`（内存峰值），公共夹具 `frontend/tests/perf/fixtures.ts`，配置 `frontend/playwright.perf.config.ts`；运行 `pnpm e2e:perf`（需先 `make frontend-build`；不在 `make e2e` / CI 分片内，单 worker 串行独占）。
- 手段：CDP `Emulation.setCPUThrottlingRate` 6×（约等于一颗比宿主机单核慢 6 倍的 CPU，偏低端笔记本 / 政务终端档位）、视口 1366×768、`--enable-precise-memory-info`；内存按 `--type=` 分类采样 Chromium 各进程 RSS（25ms），并在页面侧 hook `toDataURL` / `getContext` 记录编码阶段与画布尺寸。
- 口径：点击 `导出 PNG / PDF` → 下载落盘的墙钟耗时，含导出库动态导入、html2canvas 捕获、编码与 jsPDF 组装。
- 实测（2026-11-01，宿主机 24 核；**两次独立运行取区间**，非真机、无内存压力与 swap 干扰）：

| 场景 | 捕获画布 | PNG 1× / 6× | PDF 1× / 6× | 进程组 RSS 增量峰值（粗采） |
|---|---|---|---|---|
| 典型（2 列 × 3 行，6 块） | 3443 × 3912（13.5 M px） | 310-320ms / 1.6-2.4s | 375-407ms / 2.1-3.1s | 28-139 MB |
| 超大（20 块整行，200 行单元） | 1841 × 17381（32.0 M px，命中 `MAX_CANVAS_PIXELS` 预算） | 512-528ms / 2.85-3.15s | 669-689ms / 3.85-4.2s | 220-431 MB（明细见下） |

- 耗时结论：整屏导出是**纯 CPU 型**耗时（6× 降速下近似 5-6× 墙钟），最坏档（超大画布 PDF @6×）约 4 秒量级，PNG 约 3 秒，未出现画面为空 / 失败；首次导出仅比热态多 50-70ms（动态导入成本可忽略）。

**内存峰值（超大画布 1841 × 17381 = 32.0 M px，位图理论 122 MB；25ms 采样、3 次独立运行取区间）**

- PNG：基线 735-739 MB → 峰值 897-903 MB（渲染进程 391 MB → 544-549 MB）；总增量 158-168 MB / 渲染进程增量 149-158 MB；峰值出现在点击后 +455~482 ms，落在 `toDataURL('image/png')` 编码窗口（387→509 ms）内，编码返回 1.4 MB base64。
- PDF：基线 750-873 MB → 峰值 1112-1121 MB（渲染进程 398-522 MB → 753-762 MB）；总增量 239-371 MB / 渲染进程增量 231-364 MB；峰值出现在 +581~631 ms，落在逐页 `toDataURL('image/jpeg', 0.95)` 编码窗口（433→646 ms）内，编码返回 1.2 MB base64。
- 归因：峰值增量约为位图理论值的 1.2-1.4×（PNG）与 2-3×（PDF）——PDF 捕获后仍按页新建 `pageCanvas` 再编码，超大画布单页时它与主画布同尺寸，等于同时存在两份 122 MB 位图；两者峰值都出现在编码阶段而非捕获阶段（捕获时位图是逐块绘制的）。
- 回收：PNG 导出后 +10 s 回落到基线（+21~23 MB，属分配器碎片）；PDF +10 s 后残留 +13~140 MB（受基线抖动影响，属 GC 惰性），连续 5 次导出 RSS 由 570 MB 升到约 800 MB 后趋稳、第 5 次出现回落（672-686 MB），**无泄漏式单调累积**。
- 低配判断：单次导出峰值增量 PNG ≤ ~170 MB、PDF ≤ ~370 MB；叠加浏览器常驻内存后，4 GB 档设备峰值占用约 0.8-1.2 GB，处于安全区；2 GB 档接近压力区。若后续放宽 `MAX_CANVAS_PIXELS` / `TARGET_RENDER_DPI`，需按「每多一份全尺寸画布 ≈ +122 MB」复核。

**遗留项修复后复测（2026-11-01，同口径超大画布）**

- `computeRenderScale` 改按长边折算单边上限（`sideCap = MAX_CANVAS_SIDE / max(w, h)`）：捕获画布 1841×17381 → **1735×16384**，不再超浏览器单边名义上限；超高内容分辨率略降（位图 122 → 108 MB），宽内容与既有尺寸不受影响（单测锁定 `computeRenderScale(1000, 9000) = 16384/9000`）。
- `exportViewToPdf` 单页场景（`cols=rows=1`）复用主画布 `toDataURL`，不再创建同尺寸切片画布：绝对峰值 RSS PNG 856 MB / PDF 948 MB（修复前 903 / 1112-1121 MB），PDF 与 PNG 峰值差由 ~220 MB 收窄到 ~92 MB（剩余为 JPEG 编码缓冲）；多页仍走切片路径（单测锁定两条路径）。
- 结论：两项遗留优化均已落地并经探针复测验证，无新增待跟进。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 抽取 `captureElement`；新增整屏 PNG / PDF 编排；`DashboardView` 工具栏对所有可见者开放并加导出入口；主题背景参数 | 中（捕获尺寸与旧内核兼容需实测；既有 PDF 行为须保持不变） |
| **P1** | `dashboardShare` 纯函数；`GridPage` 展示态与禁止回落；画布展示态工具栏；视图栏复制链接 | 中（展示态权限语义与既有深链回落逻辑交叉，需单测锁定） |
| **P2** | 分享设置入口联动（复用视图权限抽屉）、只读 / 失效 e2e、体积预算与文档回填 | 低 |

### 决策记录（原 ADR 0077）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | **前端视觉快照导出 + 登录态只读深链**，零后端模型 / 端点 / 迁移 | 导出与分享都建立在「当前用户已可见的渲染结果」上；现有 `html2canvas-pro`、`jsPDF` 与视图权限链路可直接复用 | ① 服务端渲染 PDF / PNG：需新增图像渲染与中文字体链路，且要与前端图表口径保持同构；② 新建 dashboard 分享表与 token：需复制文档分享的撤销 / 计数 / 归属校验，本需求无匿名诉求 | `dashboardExport.ts`、`dashboardShare.ts`、`GridPage.tsx` |
| D2 | 是否支持匿名只读分享 | **不支持**；只读链接必须登录，匿名能力仍只属于文档分享（ADR 0017） | ADR 0003 D5 已彻底移除表 / 视图匿名分享，理由是匿名面会绕过表权限、行级权限与字段隐藏；dashboard 数据聚合面更大，不能例外 | ① 新增 dashboard 匿名 token（等于复活 D5 已删除的公开读取面）；② 导出静态快照托管为公开链接（需新增对象存储、清理与访问控制） | `view_access.py`、`GridPage.tsx` |
| D3 | 导出格式 | **PNG（默认）+ PDF（可选）** | PNG 适合聊天 / 文档直接粘贴；PDF 适合打印与归档；两者都已有成熟前端实现 | ① 仅 PDF：聊天场景不便；② 仅 PNG：长画布打印不友好；③ 后端导出新格式：重复实现 | `dashboardExport.ts`、`exportPng.ts` |
| D4 | 导出捕获范围与背景 | 捕获 **全局筛选栏 + 画布主体**；排除画布工具栏 / 应用导航；背景取当前主题色 | 筛选值决定数据口径，必须与画面一起出现；工具栏属于操作面，不属于展示内容；白底 + 深色图表不可读 | ① 只截画布主体：导出图缺少筛选口径；② 截整个 `gridAreaRef`：会把编辑按钮带进文件；③ 固定白底：深色主题不可读 | `DashboardView.tsx`、`exportPdf.ts` |
| D5 | 导出入口与权限 | `DashboardView` 工具栏对所有可见者渲染，导出 / 刷新 / 复制链接不需要 `EDIT_VIEWS` | 用户能看见数据就应能带走自己的视图；导出不放大权限；只读用户目前完全没有画布操作入口 | ① 仅编辑者导出：只读协作者只能截图；② 只放在数据导入 / 导出弹窗：入口与画布语境割裂 | `DashboardView.tsx`、`GridPage.tsx` |
| D6 | 只读链接形态 | `?view=<id>&mode=dashboard&present=1` 的现有路由深链，不新增路由 / 端点 | 复用 `GridPage` 的取数与权限链路，链接稳定、可刷新、可转发；无状态最容易撤销（权限一变即失效） | ① 新增 `/present/...` 路由：要复制 table / views / rows 取数逻辑；② 短链 / token：需落库与撤销面 | `dashboardShare.ts`、`GridPage.tsx` |
| D7 | 展示态边界 | 只读展示：隐藏页面工具栏、聚合条、行详情与导入导出；保留刷新 / 导出 / 退出；禁用行点击 | 只读分享用于「看板展示」，不应出现任何写入口；刷新与导出是只读诉求 | ① 复用普通 GridPage：写入口与行详情仍在；② 全屏浏览器 API 自动进入：非用户手势无法可靠全屏 | `DashboardView.tsx`、`GridPage.tsx` |
| D8 | 分享范围与设置 | 沿用视图三档可见性 + 既有授权名单；分享设置复用「视图权限」抽屉 | 已有唯一权限模型与产品入口；不引入第二套 grant 口径 | ① dashboard 独立分享名单：与视图权限双写，易漂移；② 链接自带角色：URL 不可信 | `ViewPermissionDrawer.tsx`、`gridViewBar.tsx` |
| D9 | 目标视图失效 | 展示态 **不回落到默认视图**，直接「链接无效或无权访问」 | 回落会把「无权看 A」静默变成「看到了 B」，与 ADR 0003 I6 的不泄露存在性口径冲突 | ① 继续回落默认视图：语义错误且可能展示未分享内容；② 单独返回 403 文案：泄露视图曾存在 | `resolvePresentTarget`、`GridPage.tsx` |
| D10 | 复用与体积 | 抽出 `captureElement` 供 PDF / PNG 共用；导出与分享辅助模块按需导入，`DashboardView` 不静态膨胀 | 避免两套捕获逻辑漂移；现有体积预算对 dashboard 有独立基线 | ① 复制 PDF 捕获实现到 dashboard：两处维护；② 导出库静态挂主入口：首屏与主 chunk 膨胀 | `exportPdf.ts`、`dashboardExport.ts`、`bundle-budget.json` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

### 与既有 ADR 的关系（原 ADR 0077）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| dashboard 配置与取数 | `view_options`、`dashboard/data` | 整屏导出消费现有 `Dataset`，分享沿用视图配置 | ADR 0023 |
| 视图可见性与匿名分享 | `visibility` + 授权名单 | 分享只读沿用三档可见性；**不恢复匿名分享** | ADR 0003 D5 |
| 匿名分享能力范围 | `/public/share/:token` | 匿名能力仍只覆盖文档，不扩展到表 / 视图 / dashboard | ADR 0017 C10 |
| 旧内核导出兼容 | `exportPdf.ts` 垫片与动态导入 | 整屏导出沿用同一路径 | ADR 0026 |

### 落地状态（原 ADR 0077）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/grid/views/dashboard/dashboardExport.ts`、`frontend/src/pages/import-export/ImportExportDialog/exportPdf.ts`、`frontend/src/pages/import-export/ImportExportDialog/exportPng.ts`、`frontend/src/pages/grid/views/dashboard/DashboardView.tsx` | `frontend/src/pages/grid/views/dashboard/dashboardExport.test.ts`、`frontend/src/pages/import-export/ImportExportDialog/exportPdf.test.ts`、`frontend/src/pages/import-export/ImportExportDialog/exportPng.test.ts`、`frontend/src/pages/grid/views/dashboard/DashboardView.test.tsx` | `b9ccd0b8` |
| P1 | 已落地 | `frontend/src/pages/grid/views/dashboard/dashboardShare.ts`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/gridViewBar.tsx` | `frontend/src/pages/grid/views/dashboard/dashboardShare.test.ts`、`frontend/src/pages/grid/GridPage.present.test.tsx`、`frontend/src/pages/grid/gridViewBar.test.tsx`、`frontend/tests/e2e/critical/dashboard-readonly-share.spec.ts` | `b9ccd0b8` |
| P2 | 已落地 | `frontend/src/pages/grid/ViewPermissionDrawer.tsx`、`frontend/src/pages/grid/gridViewBar.tsx`、`frontend/src/pages/grid/views/dashboard/DashboardView.tsx` | `frontend/src/pages/grid/ViewPermissionDrawer.test.tsx`、`frontend/tests/e2e/critical/dashboard-export.spec.ts`、`frontend/tests/e2e/critical/dashboard-readonly-share.spec.ts` | `b9ccd0b8` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；P0-P2 全期落地并经人工确认（2026-11-01），`Status` 由 `Accepted` 转 `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

### 交接（原 ADR 0077）

- 当前阶段：P0-P2 已全部落地并经人工确认，`Status` 定为 `Implemented`（2026-11-01）
- 已完成：整屏导出（PNG / PDF 共用 `captureElement`、专用捕获容器、主题背景、数据就绪门控）、登录态只读深链（禁止回落、展示态隐藏页面 chrome 与行详情、退出展示）、视图栏复制链接、分享设置复用视图权限抽屉并补画布提示、e2e 两条（导出格式校验 / 只读分享与失效）
- 下一步：低配设备表现已用 CDP CPU 降速做过可复现实测（`pnpm e2e:perf`，结论见「7. 测试清单 · 低配模拟」）；仅剩真机复核（真实内存压力 / 集成显卡 / 低内存 OOM 边界），如需扩展（例如整屏导出加图片格式选项）另开需求卡片，不改本 ADR 已收口的口径
- 已知坑：① 既有 PDF 捕获目标是 `gridAreaRef`，dashboard 的导出必须换专用容器，否则工具栏会被截进文件；② `html2canvas-pro` 在 Chrome 81 需先加载 `Intl.Segmenter` 垫片（沿用 `exportPdf.ensureIntlSegmenter`）；③ `DashboardGrid` 自身滚动，捕获前必须展开滚动容器并按后代包围盒取尺寸；④ 深色主题导出需传主题背景，不能沿用写死的白色；⑤ 展示态 `?view` 未命中时**绝不能**走 `GridPage` 的默认视图回落；⑥ 大表 / 跨表走服务端取数，导出前要等 `useDashboardData.loading` 结束；⑦ 导出编排与分享辅助全部按需导入（`DashboardView` 内动态 `import('./dashboardExport')`），`DashboardView` 静态依赖只保留类型；⑧ 视图权限抽屉已改为 `lazy` 且仅在打开时挂载，避免回涨 `GridPage` chunk；⑨ Chromium 对含中文的 anchor download 文件名会回落为 `download`，e2e 用文件魔数而非文件名断言；⑩ `present=1` 时先等 `useTableViews` 结束再判失效，避免把「加载中」误判成「链接无效」
- 最近一次全绿：`make check-fast`、`pnpm build` + `pnpm bundle:budget`、新增 e2e 4 例（2026-11-01）；低配模拟探针 `pnpm e2e:perf` 全过（耗时 3 例 + 内存峰值 4 例，2026-11-01）
