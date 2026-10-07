# 图表视图设计

对应需求：`.trae/req/req-18-图表视图.md`。实施计划：`.claude/artifacts/plans/chart-view.md`。

## 概念

图表视图（view_type = "chart"）是纯前端聚合的可视化视图：行数据在浏览器内按配置归桶/聚合后交 ECharts（SVGRenderer）渲染，同时附带描述统计面板。6 种图表类型共用一套 view_options 契约，经 `visibleWhen` 按 chart_type 条件显隐。

## 依赖项

- `echarts` ^6.1.0：`echarts/core` 按需注册（Bar/Line/Pie/Scatter/BoxplotChart + Grid/Tooltip/LegendComponent + SVGRenderer），全量经 ChartView 懒加载 chunk 隔离（约 199KB gzip，不进主包）。
- `simple-statistics` ^7.12.1：分位数（R-7）/标准差/峰度偏度等。注意 v7 的 `mode(x)` 返回单个 number（非数组）。
- 复用 `matrixBoard.ts` 的 `axisKeyForRow` / `sortAxisKeys`（维度归桶与排序）、`UNGROUPED_LABEL`。

## view_options 契约（view_type = "chart"）

| key | 类型 | 必填 | 默认 | 说明 |
|-----|------|------|------|------|
| chart_type | string | 是 | bar | bar / line / pie / scatter / histogram / boxplot |
| dimension_field | string | 条件 | — | 维度字段；bar/line/pie/boxplot 必填 |
| measure_field | string | 条件 | — | 度量字段（数值）；bar/line/pie/histogram/boxplot 必填 |
| x_field | string | 条件 | — | 散点横轴数值字段；scatter 必填（候选 number/float/percentage/timestamp） |
| y_field | string | 条件 | — | 散点纵轴数值字段；scatter 必填 |
| group_field | string | 否 | — | 系列分组字段（select/multi_select/link），拆多系列；仅 bar/line |
| aggregation | string | 否 | sum | sum / avg / count / min / max；仅 bar/line/pie |
| date_granularity | string | 否 | month | 维度字段为日期时的分桶粒度：year/quarter/month/week/day |
| bin_policy | string | 否 | auto | 直方图分箱策略：auto（平方根）/ sturges / freedman-diaconis；仅 histogram |
| show_stats_panel | boolean | 否 | true | 是否显示描述统计面板 |
| show_trend_line | boolean | 否 | — | 散点图叠加 OLS 趋势线；仅 scatter |

后端校验：`views.py _validate_view_fields` 与 `seed.py _validate_view_fields` 的 view_options 白名单均增加 `dimension_field` / `measure_field` / `x_field` / `y_field`（group_field 已在），引用不存在字段返回 400；ViewType 枚举不扩（view_type 为自由字符串）。

## 数据流与算法（chartBoard.ts 纯逻辑层）

- 统一入口 `buildChartData(rows, fields, cfg)` 按类型产出 `ChartData` 联合：
  - `category`：categories + series[]（无值桶为 null，不虚构 0）；`pie`：items[]；`scatter`：points[] 与 rowIds[] 平行（点击散点回开行详情）；`histogram`：bins[]；`boxplot`：boxes[]（[min,Q1,med,Q3,max]）+ outliers[]（[类目索引, 值]）。
- 数值提取 `toNumber`：null/undefined/空串/NaN/±Infinity/boolean 剔除；数字字符串接受。
- 维度归桶复用 `axisKeyForRow`（select 标签/link 首值/日期按粒度分桶/其余 String 化，空值归「未分组」）；排序复用 `sortAxisKeys`（日期桶字典序==时序，「未分组」恒末尾）；分组系列名同规则排序。
- 聚合口径：sum/avg/min/max 只计有效数值；count 只计有效值数（对齐 SQL `COUNT(col)`）。
- 分箱 `histogramBins`：auto=平方根 `ceil(sqrt(n))`；sturges=`ceil(log2(n)+1)`；freedman-diaconis 按 IQR 求 h（IQR=0 回退 Sturges）；箱数上限 512；空数组/单值/全同值单箱；边界标签整数原样、浮点 6 位有效数字 `from~to`，末箱闭区间含 max。
- `computeStats`：count/sum/mean/median/mode（单值）/std（样本标准差 n-1，n<2 为 null）/min/max/range/p25/p75（线性插值 R-7）/iqr/skewness（n<3 为 null）/outlierCount（IQR 法：[Q1-1.5·IQR, Q3+1.5·IQR] 之外）；空数组返回 null。
- `pearson`：n<2 或任一轴恒定（分母 0）返回 null；`olsLine`：最小二乘 slope/intercept/r/r2，奇异（X 恒定）返回 null。

## 渲染（ChartView.tsx）

- 生命周期：`echarts.init(container, undefined, { renderer: 'svg' })` 仅在必填字段齐备时挂载；chart_type 切换不重建实例，`setOption(option, true)` notMerge 覆盖；ResizeObserver 随 init 挂载/卸载；卸载 dispose。
- 主题桥接：`useTheme()` 的 mode 进 option memo 依赖——主题切换触发重渲染，`getComputedStyle` 重读 `var(--cn-text-primary/--cn-text-secondary/--cn-border/--cn-bg-container)`（jsdom 回退浅色默认）重建 option；系列色用 antd 8 色预设（同 MatrixView AXIS_COLORS 策略，按索引循环，不绑主题变量）。
- 散点点击行详情：rowIds 与 points 平行，经 clickCtxRef/onRowClickRef 每次 render 更新防 init effect 闭包过期；`params.seriesType === 'scatter'` 才触发（趋势线/箱线离群点不触发）。
- 统计面板 StatsPanel：14 项指标 + 「样本量 N / 总行数 M」（total prop，暴露 fetch-all 截断口径）+ 口径 tooltip；散点附加 Pearson r / R² / 斜率 / 截距；`fmtStat`（null→'—'，整数原样，浮点 6 位有效数字）。
- 空态两档：必填字段缺失（chart-empty-config，按 chart_type 提示维度/度量或 X/Y 字段）/ 无行（chart-empty-rows）。
- GridPage 接线：MODE_BUTTONS 增 chart 项；KANBAN_MODES（fetch-all 集合）增 'chart'；lazy import。

## 表单（visibleWhen 机制）

- `ViewOptionSchema` 增可选 `visibleWhen?: (opts) => boolean`；`groupOptionSchema(schema, opts?)` 第二参传入当前 opts，undefined 恒显示（既有 schema 零行为变化）。
- CreateEditViewForm / ViewConfigDialog 的折叠重置 effect 依赖改为分区标签 join（而非 sections 引用），chart_type 切换引起 visibleWhen 变化时分区标签恒定，不误重置用户折叠态。

## 异常处理

- 度量值无效（空/非数值/Infinity）：聚合与统计口径统一剔除；散点任一轴无效整行剔除。
- 维度空值归「未分组」桶（排序恒末尾）；多系列无值桶为 null（不虚构 0）。
- 直方图 FD 策略 IQR=0（数据过度集中）：回退 Sturges；单值/全同值收敛单箱。
- 后端 400：view_options 引用不存在字段（dimension_field/measure_field/x_field/y_field），detail 含具体键名。
- 前端空态兜底：历史数据/清空场景缺必填字段时引导配置，不渲染图表。

## 测试约定

- `chartBoard.test.ts`（23 条）：toNumber/extractNumbers 边界 / 聚合五口径+日期分桶+空值剔除+未分组 / group_field 多系列 null 桶 / pie 扇区数据 / scatter 无效行剔除+rowIds 平行 / boxplot 五数概括+IQR 离群 / 分箱三策略+FD IQR=0 回退+边界 / computeStats 精确值+偏度+空数组 / pearson 完美相关+奇异 / olsLine 精确斜率截距。
- `ChartView.test.tsx`（16 条）：空态（必填字段缺失 / 空行 / scatter 缺 X/Y）/ bar 聚合 option+类目序+未分组末尾 / group_field 多系列+legend / line 类型 / scatter OLS 趋势线 / 统计面板数值+截断口径 / 散点附加 Pearson r/R²/回归系数 / show_stats_panel 关闭 / 主题切换重建 option / pie option（series.type、扇区 name/value/itemStyle.color）/ histogram option（series.type=bar、barCategoryGap=0、bins labels 做 xAxis）/ boxplot option（主 series=boxplot+离群值 scatter、xAxis.data=拼音序分组）/ scatter 点击散点触发 onRowClick / scatter 非散点系列（趋势线）不触发。
- `CreateEditViewForm.test.tsx`：图表类型渲染、visibleWhen 条件显隐（scatter 出 X/Y 隐维度/聚合；histogram 出分箱）、提交 opts。
- `test_views_api.py`：chart 视图创建 201（bar + scatter + line + pie + boxplot + histogram 全 6 种类型）与 400（measure_field/x_field/group_field 不存在）；6 种 chart_type 在同一张表上连续创建（模拟 seed 注入）都通过校验并正确列出。
- `examples/datasets/*/views.json` 所有 chart 视图引用字段经 CSV 表头/硬编码表字段校验通过；`python -c` 扫描验证 34 个 chart 视图（bar×9 / line×5 / pie×5 / scatter×4 / histogram×6 / boxplot×5）全部字段引用有效。
- e2e `view-mode-switch.spec.ts`：电商销售表点图表按钮 → SVG 图表 + 统计面板渲染。
- bundle-budget：新增 ChartView 基线 204_265 gzip bytes；GridPage 基线更新 38_793（接线 +1.8KB gzip）。

## seed 示例（覆盖全部 6 种 chart_type）

所有示例位于 `examples/datasets/<工作区名>/views.json`，字段名与同名 CSV 表头 / 硬编码表 DataField.name 一致；合计 34 个 chart 视图，每类 type 至少 4 条。

### 工作区-某企业销售管理（8 张表中 6 张含 chart 视图）

| 表名 | 视图名 | chart_type | 关键配置 |
|------|--------|------------|----------|
| 电商销售 | 月度销售额趋势 | line | dimension_field=日期, date_granularity=month, measure_field=销售额, aggregation=sum |
| 电商销售 | 商品类别销售额排名 | bar | dimension_field=商品类别, measure_field=销售额, aggregation=sum |
| 电商销售 | 支付方式销售占比 | pie | dimension_field=支付方式, measure_field=销售额, aggregation=sum |
| 电商销售 | 订单评分分布 | histogram | measure_field=评分, bin_policy=auto |
| 电商销售 | 单价与数量散点 | scatter | x_field=单价, y_field=数量, show_trend_line=true |
| 营销活动 | 渠道预算对比 | bar | dimension_field=渠道类型, measure_field=预算_元, aggregation=sum |
| 营销活动 | 预算与实际花费散点 | scatter | x_field=预算_元, y_field=实际花费_元, show_trend_line=true |
| 营销活动 | 活动转化率分布 | histogram | measure_field=转化率_%, bin_policy=freedman-diaconis |
| 客户流失 | 合约类型流失率 | bar | dimension_field=合约类型, measure_field=是否流失, aggregation=avg |
| 客户流失 | 月消费金额分布 | histogram | measure_field=月消费_元, bin_policy=sturges |
| 产品开发 | 片区项目数 | bar | dimension_field=片区, measure_field=项目编号, aggregation=count |
| 员工表 | 部门薪资分布 | boxplot | dimension_field=部门, measure_field=薪资 |
| 员工表 | 全公司薪资分布 | histogram | measure_field=薪资, bin_policy=auto |
| 日常待办 | 状态任务数 | bar | dimension_field=状态, measure_field=待办编号, aggregation=count |

### 工作区-项目管理（3 张表中 3 张含 chart 视图）

| 表名 | 视图名 | chart_type | 关键配置 |
|------|--------|------------|----------|
| WBS任务分解 | 状态任务数 | bar | dimension_field=任务状态, measure_field=任务ID, aggregation=count |
| WBS任务分解 | 任务负责人占比 | pie | dimension_field=负责人, measure_field=任务ID, aggregation=count |
| WBS任务分解 | 工期分布 | histogram | measure_field=工期_天, bin_policy=auto |
| 资源排期 | 团队投入人天 | bar | dimension_field=团队, measure_field=投入人天, aggregation=sum |
| 资源排期 | 月度投入趋势（按团队分组） | line | dimension_field=排期日期, date_granularity=month, measure_field=投入人天, aggregation=sum, group_field=团队 |
| 资源排期 | 排期月度投入分布 | boxplot | dimension_field=团队, measure_field=投入人天 |
| 待办事项 | 类别占比 | pie | dimension_field=类别, measure_field=编号, aggregation=count |

### 工作区-科研项目管理（4 张表中 4 张含 chart 视图）

| 表名 | 视图名 | chart_type | 关键配置 |
|------|--------|------------|----------|
| 科研项目 | 立项年份经费趋势 | line | dimension_field=立项年份, measure_field=经费总额_万元, aggregation=sum |
| 科研项目 | 项目类别经费对比 | bar | dimension_field=项目类别, measure_field=经费总额_万元, aggregation=sum |
| 科研项目 | 项目类别数量占比 | pie | dimension_field=项目类别, measure_field=课题编号, aggregation=count |
| 科研项目 | 计划周期分布 | histogram | measure_field=计划周期_月, bin_policy=sturges |
| 科研经费 | 预算科目已拨金额 | bar | dimension_field=预算科目, measure_field=已拨金额_万元, aggregation=sum |
| 科研经费 | 拨付日期年度投入趋势 | line | dimension_field=拨付日期, date_granularity=year, measure_field=已拨金额_万元, aggregation=sum |
| 项目进展 | 进展阶段进度分布 | boxplot | dimension_field=进展阶段, measure_field=进度百分比 |
| 课题负责人 | 职称分布占比 | pie | dimension_field=职称, measure_field=负责人编号, aggregation=count |

### 工作区-某地区数据（2 张表中 2 张含 chart 视图）

| 表名 | 视图名 | chart_type | 关键配置 |
|------|--------|------------|----------|
| 房价预测 | 房龄与房价散点 | scatter | x_field=房龄_年, y_field=房价_万元, show_trend_line=true |
| 房价预测 | 各城市房价分布 | boxplot | dimension_field=城市, measure_field=房价_万元 |
| 房价预测 | 房间数量与房价散点 | scatter | x_field=房间数, y_field=房价_万元 |
| 气温天气 | 城市月度最高温趋势 | line | dimension_field=日期, date_granularity=month, measure_field=最高温_℃, aggregation=avg, group_field=城市 |
| 气温天气 | 城市风速分布 | boxplot | dimension_field=城市, measure_field=风速_m/s |
