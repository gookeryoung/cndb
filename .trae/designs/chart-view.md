# 图表视图设计

对应需求：`.trae/req/req-18-图表视图.md`（单图）、`.trae/req/req-19-图表视图多图.md`（多图）。实施计划：`.claude/artifacts/plans/chart-view.md`、`.claude/artifacts/plans/chart-view-multi.md`。

## 概念

图表视图（view_type = "chart"）是纯前端聚合的可视化视图：行数据在浏览器内按配置归桶/聚合后交 ECharts（SVGRenderer）渲染，同时附带描述统计面板。6 种图表类型共用一套 view_options 契约，经 `visibleWhen` 按 chart_type 条件显隐。一个 chart 视图支持单图（扁平键）与多图（charts[] 数组）双形态，渲染端与校验端同时支持。

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
| charts | array | 否 | — | 多图形态：元素为上述扁平键集的配置对象（同表结构），非空数组时按多图网格渲染 |

### 单图 / 多图双形态与双向转换

- 扁平键（上表除 charts 外）为合法单图形态；`charts` 为非空对象数组时为多图形态，两形态**不并存**（保存出口保证）。
- 转换真相源在 `viewOptionSchema.ts`：
  - `normalizeChartList(draftOpt)`：charts 非空数组 → 逐条目浅拷贝；否则从扁平键提取 CHART_OPTIONS 键组装单条目（hidden_fields 等非图表键不进入条目）。
  - `serializeChartList(list)`：图表数 >1 → `{ charts: [...] }`；==1 → 扁平键对象；条目级空值清洗（''/null/undefined/空数组剔除），清洗后为空的条目整体剔除，全部为空返回 null。
- 条目编辑态统一收敛在 `useChartListDraft.ts` 共享 hook（ViewConfigDialog 与 CreateEditViewForm 的单一真相源）：当前条目索引（clamp）、`patchEntry`（条目级 patch）、`addEntry` / `removeEntry`，以及 `writeBackChartList` 双形态写回（条目数 ==1 → 删 charts 键与全部 CHART_OPTIONS 扁平键后合入条目；>1 → 写回 charts[]，双形态不并存）。
- ViewConfigDialog 保存出口与 CreateEditViewForm 提交出口同规则：先删 charts 键与全部 CHART_OPTIONS 扁平键，再合入 serialize 产物（防止添加图表后扁平键残留；CreateEditViewForm 场景保留非图表键）。
- 后端校验：`views.py _validate_view_fields` 与 `seed.py _validate_view_fields` 在扁平键白名单外追加——`charts` 为 list 时逐条目校验（元素非 dict 返回 400「view_options.charts[i] 不是对象」；dict 内 dimension_field/measure_field/x_field/y_field/group_field 引用不存在字段返回 400，detail 定位 `view_options.charts[i].<key>`）。ViewType 枚举不扩（view_type 为自由字符串）。

### 多图渲染与条目管理

- 渲染端 `resolveChartList(viewOptions)`（ChartView.tsx 内）：charts 非空数组 → 逐条目 resolveOpts（multi=true）；否则扁平键整体解析一次（multi=false）。
- 多图：dashboard 式自适应网格 `repeat(auto-fill, minmax(420px, 1fr))`、gap 12px，每卡独立 ChartCard（边框卡片 + 自动标注卡片头 `{类型中文} · {关键字段名}`，纯展示不可配 title；scatter 取 `x × y`，histogram/boxplot 取度量，其余取维度）。每卡独立 ECharts 实例 / 统计面板 / 散点点击语义；实例随卡片卸载 dispose。上限 6（待用户复核）。
- 单图（扁平来源）：保持既有全宽 flex 容器，无卡片头——渲染行为与多图上线前完全一致。
- 空态分档：无行 → 视图级 chart-empty-rows；多图某卡必填缺失 → 该卡内空态，data-testid 带索引后缀 `chart-empty-config-{i}`（单图保持 `chart-empty-config`）；卡片头 testid `chart-card-title-{i}`。
- ViewConfigDialog（仅 view_type='chart' 的专属设置 tab 顶部）：Segmented（`图表 1 / 图表 2 / …`）+ 「添加图表」（上限 6 禁用 + tooltip）+ 「删除当前图表」（单条目禁用；删至单条目写回扁平形态）；分区渲染传当前条目 opts 使 visibleWhen 按该条 chart_type 显隐；条目索引在对话框打开时重置为 0；折叠重置 effect 依赖分区标签 join 不受条目切换影响。
- CreateEditViewForm（创建 / 编辑视图表单）同套多图配置：chart 类型时渲染条目管理条（Segmented + 添加 / 删除，语义与 ViewConfigDialog 一致），配置项读写走 hook 当前条目；编辑 `charts[]` 视图时逐条目回显可切换；视图类型切换时 opts 清空并重置条目索引；提交出口经 serialize 保证双形态不并存。

## 数据流与算法（chartBoard.ts 纯逻辑层）

- 统一入口 `buildChartData(rows, fields, cfg)` 按类型产出 `ChartData` 联合：
  - `category`：categories + series[]（无值桶为 null，不虚构 0）；`pie`：items[]；`scatter`：points[] 与 rowIds[] 平行（点击散点回开行详情）；`histogram`：bins[]；`boxplot`：boxes[]（[min,Q1,med,Q3,max]）+ outliers[]（[类目索引, 值]）。
- 数值提取 `toNumber`：null/undefined/空串/NaN/±Infinity/boolean 剔除；数字字符串接受。
- 维度归桶复用 `axisKeyForRow`（select 标签/link 首值/日期按粒度分桶/boolean 按是/否/其余 String 化，空值归「未分组」）；排序复用 `sortAxisKeys`（日期桶字典序==时序，「未分组」恒末尾）；分组系列名同规则排序。
- 聚合口径：sum/avg/min/max 只计有效数值；count 只计有效值数（对齐 SQL `COUNT(col)`）。
- 分箱 `histogramBins`：auto=平方根 `ceil(sqrt(n))`；sturges=`ceil(log2(n)+1)`；freedman-diaconis 按 IQR 求 h（IQR=0 回退 Sturges）；箱数上限 512；空数组/单值/全同值单箱；边界标签整数原样、浮点按 `labelPrecision(width, max)` 自适应有效数字 `from~to`（下限 6 位，按整数位数+箱宽所需小数位升位，上限 17 位防超出 double 精度——大量级窄区间下固定 6 位会把相邻边界折叠成同串导致类目轴标签重复不可读），末箱闭区间含 max。
- `computeStats`：count/sum/mean/median/mode（单值）/std（样本标准差 n-1，n<2 为 null）/min/max/range/p25/p75（线性插值 R-7）/iqr/skewness（n<3 为 null）/outlierCount（IQR 法：[Q1-1.5·IQR, Q3+1.5·IQR] 之外）；空数组返回 null。
- `pearson`：n<2 或任一轴恒定（分母 0）返回 null；`olsLine`：最小二乘 slope/intercept/r/r2，奇异（X 恒定）返回 null。

## 渲染（ChartView.tsx）

- 组件结构：主组件解析 resolveChartList 并负责布局壳（单图全宽 flex / 多图 grid）；`ChartCard` 子组件封装单卡内容——missing 判定、buildChartData、ECharts option 装配、生命周期、StatsPanel、必填缺失空态；`missingFieldLabels` / `chartKeyFieldLabel` / `CHART_TYPE_LABELS` 为文件内纯函数。
- 生命周期：`echarts.init(container, undefined, { renderer: 'svg' })` 仅在必填字段齐备时挂载；chart_type 切换不重建实例，`setOption(option, true)` notMerge 覆盖；ResizeObserver 随 init 挂载/卸载；卸载 dispose。
- 主题桥接：`useTheme()` 的 mode 进 option memo 依赖——主题切换触发重渲染，`getComputedStyle` 重读 `var(--cn-text-primary/--cn-text-secondary/--cn-border/--cn-bg-container)`（jsdom 回退浅色默认）重建 option；系列色用 antd 8 色预设（同 MatrixView AXIS_COLORS 策略，按索引循环，不绑主题变量）。
- 散点点击行详情：rowIds 与 points 平行，经 clickCtxRef/onRowClickRef 每次 render 更新防 init effect 闭包过期；`params.seriesType === 'scatter'` 才触发（趋势线/箱线离群点不触发）。
- 统计面板 StatsPanel：14 项指标 + 「样本量 N / 总行数 M」（total prop，暴露 fetch-all 截断口径）+ 口径 tooltip；散点附加 Pearson r / R² / 斜率 / 截距；`fmtStat`（null→'—'，整数原样，浮点 6 位有效数字）。
- 空态：无行 → 视图级 chart-empty-rows（多图/单图共用，先于卡片判定）；必填字段缺失 → 卡内 chart-empty-config（多图带索引后缀，见「多图渲染与条目管理」）。
- GridPage 接线：MODE_BUTTONS 增 chart 项；KANBAN_MODES（fetch-all 集合）增 'chart'；lazy import。

## 表单（visibleWhen 机制）

- `ViewOptionSchema` 增可选 `visibleWhen?: (opts) => boolean`；`groupOptionSchema(schema, opts?)` 第二参传入当前 opts，undefined 恒显示（既有 schema 零行为变化）。
- CreateEditViewForm / ViewConfigDialog 的折叠重置 effect 依赖改为分区标签 join（而非 sections 引用），chart_type 切换引起 visibleWhen 变化时分区标签恒定，不误重置用户折叠态。

## 异常处理

- 度量值无效（空/非数值/Infinity）：聚合与统计口径统一剔除；散点任一轴无效整行剔除。
- 维度空值归「未分组」桶（排序恒末尾）；boolean 维度按是/否归桶（对齐 formatFieldDisplayValue 展示语义，非 true/false 字面量）；多系列无值桶为 null（不虚构 0）。
- 直方图 FD 策略 IQR=0（数据过度集中）：回退 Sturges；单值/全同值收敛单箱；分箱标签精度按箱宽自适应升位（见数据流节），保证相邻边界在标签中两两可辨。
- 极端数据不变式（chartBoard.test.ts「极端数据不变式」describe 锚定）：分箱计数不丢（Σcount==有效样本数）、from≤to 且边界单调、首箱含 min 末箱含 max，覆盖大量级窄区间 / 负值混合量级 / 科学计数法量级跨度 / FD 极小非零 IQR 四类场景；度量全空 bar 产出空类目数组不抛异常；中文日期等非法值整桶归未分组。
- 后端 400：view_options 引用不存在字段（扁平键 dimension_field/measure_field/x_field/y_field，及 charts[i] 内五字段键），detail 含具体键名并定位到 `charts[i].<key>`；charts 元素非 dict 返回 400。
- 前端空态兜底：历史数据/清空场景缺必填字段时引导配置，不渲染图表。

## 测试约定

- `chartBoard.test.ts`（32 条）：toNumber/extractNumbers 边界 / 聚合五口径+日期分桶+空值剔除+未分组 / group_field 多系列 null 桶 / pie 扇区数据 / scatter 无效行剔除+rowIds 平行 / boxplot 五数概括+IQR 离群 / 分箱三策略+FD IQR=0 回退+边界 / computeStats 精确值+偏度+空数组 / pearson 完美相关+奇异 / olsLine 精确斜率截距 / 极端数据不变式 4 条（大量级窄区间标签两两可辨、负值混合量级、科学计数法量级跨度、FD 极小非零 IQR clamp）/ 极端维度 4 条（boolean 是/否分桶、度量全空不抛异常、单行全同值单箱、非法日期归未分组）。
- `ChartView.test.tsx`（27 条）：空态（必填字段缺失 / 空行 / scatter 缺 X/Y）/ bar 聚合 option+类目序+未分组末尾 / group_field 多系列+legend / line 类型 / scatter OLS 趋势线 / 统计面板数值+截断口径 / 散点附加 Pearson r/R²/回归系数 / show_stats_panel 关闭 / 主题切换重建 option / pie option（series.type、扇区 name/value/itemStyle.color）/ histogram option（series.type=bar、barCategoryGap=0、bins labels 做 xAxis）/ boxplot option（主 series=boxplot+离群值 scatter、xAxis.data=拼音序分组）/ scatter 点击散点触发 onRowClick / scatter 非散点系列（趋势线）不触发；多图 3 条——charts 两元素渲染 2 容器+卡片头标注 / 每卡独立统计面板 / 某卡必填缺失对应索引空态；选项调整重渲染 4 条（聚合 sum→count 数据更新且 init 仅 1 次 / 粒度 month→year 重分桶 / 分箱 auto→sturges 箱数变化 / bar→scatter notMerge 无残留）；极端数据不崩 4 条（度量全空 / 单行直方图单箱 / 大量级窄区间 xAxis 标签两两可辨 / 负值 avg 聚合）。
- `ViewConfigDialog.test.tsx`：chart 多图条目管理 3 条——扁平单图 Segmented 仅图表 1+禁删最后 / 添加图表保存输出 charts[]（空条目清洗）/ 切换条目 visibleWhen 按该条 chart_type 显隐+删除后保存回扁平形态。
- `viewOptionSchema.test.ts`：normalizeChartList / serializeChartList 5 条——扁平归一单条目 / charts[] 浅拷贝 / ==1 扁平 >1 charts[] / 条目级空值清洗 / 多图往返幂等。
- `CreateEditViewForm.test.tsx`：图表类型渲染、visibleWhen 条件显隐（scatter 出 X/Y 隐维度/聚合；histogram 出分箱）、提交 opts；chart 多图条目管理 3 条——新建多图添加后逐条目配置提交为 charts[] 形态 / 编辑 charts[] 视图条目回显可切换且修改仅落当前条目 / 扁平单图添加再删除写回扁平形态（双形态不并存）。
- `test_views_api.py`：chart 视图创建 201（bar + scatter + line + pie + boxplot + histogram 全 6 种类型）与 400（measure_field/x_field/group_field 不存在）；多图 charts[] 合法创建 201 并原样存取、charts[1].measure_field 不存在 400（detail 定位索引）、charts 元素非 dict 400；6 种 chart_type 在同一张表上连续创建（模拟 seed 注入）都通过校验并正确列出。
- `examples/datasets/*/views.json` 所有 chart 视图引用字段经 CSV 表头/硬编码表字段校验通过；扫描验证 19 个 chart 视图（14 个多图视图共 45 个图表配置 + 5 个扁平单图，bar×16 / line×7 / pie×6 / scatter×5 / histogram×10 / boxplot×6）全部字段引用有效。
- e2e `view-mode-switch.spec.ts`：电商销售表点图表按钮 → SVG 图表 + 统计面板渲染。
- bundle-budget：新增 ChartView 基线 204_265 gzip bytes；GridPage 基线更新 38_793（接线 +1.8KB gzip）。

## seed 示例（覆盖全部 6 种 chart_type，双形态）

所有示例位于 `examples/datasets/<工作区名>/views.json`，字段名与同名 CSV 表头 / 硬编码表 DataField.name 一致。同表 ≥2 个 chart 视图已合并为一个 charts[] 多图视图（14 个多图视图承载 45 个图表配置），恰 1 个 chart 视图的表保持扁平单图形态（5 个）——双形态契约均有示例覆盖；50 个图表配置（bar×16 / line×7 / pie×6 / scatter×5 / histogram×10 / boxplot×6）全部字段引用有效。图表序列记法：类型(维度→度量或X×Y, 聚合, 分箱策略)；日期桶标注在维度后，group=多系列分组字段。

### 工作区-某企业销售管理

| 表名 | 视图名 | 图表序列 |
|------|--------|----------|
| 电商销售 | 销售经营概览（多图×5） | line(日期/月→销售额,sum) · bar(商品类别→销售额,sum) · pie(支付方式→销售额,sum) · histogram(评分,auto) · scatter(单价×数量,趋势线) |
| 营销活动 | 营销活动效果概览（多图×3） | bar(渠道类型→预算_元,sum) · scatter(预算_元×实际花费_元,趋势线) · histogram(转化率_%,freedman-diaconis) |
| 客户流失 | 客户流失分析（多图×2） | bar(合约类型→是否流失,avg) · histogram(月消费_元,sturges) |
| 员工表 | 员工薪资分析（多图×2） | boxplot(部门→薪资) · histogram(薪资,auto) |
| 产品开发 | 片区项目数（单图） | bar(片区→项目编号,count) |
| 日常待办 | 状态任务数（单图） | bar(状态→待办编号,count) |

### 工作区-项目管理

| 表名 | 视图名 | 图表序列 |
|------|--------|----------|
| WBS任务分解 | 任务执行概览（多图×3） | bar(任务状态→任务ID,count) · pie(负责人→任务ID,count) · histogram(工期_天,auto) |
| 资源排期 | 资源投入概览（多图×3） | bar(团队→投入人天,sum) · line(排期日期/月→投入人天,sum,group=团队) · boxplot(团队→投入人天) |
| 待办事项 | 类别占比（单图） | pie(类别→编号,count) |

### 工作区-科研项目管理

| 表名 | 视图名 | 图表序列 |
|------|--------|----------|
| 科研项目 | 科研项目经费概览（多图×4） | line(立项年份→经费总额_万元,sum) · bar(项目类别→经费总额_万元,sum) · pie(项目类别→课题编号,count) · histogram(计划周期_月,sturges) |
| 科研经费 | 经费投入概览（多图×2） | bar(预算科目→已拨金额_万元,sum) · line(拨付日期/年→已拨金额_万元,sum) |
| 项目进展 | 进展阶段进度分布（单图） | boxplot(进展阶段→进度百分比) |
| 课题负责人 | 职称分布占比（单图） | pie(职称→负责人编号,count) |

### 工作区-某地区数据

| 表名 | 视图名 | 图表序列 |
|------|--------|----------|
| 房价预测 | 房价分析概览（多图×3） | scatter(房龄_年×房价_万元,趋势线) · boxplot(城市→房价_万元) · scatter(房间数×房价_万元) |
| 气温天气 | 城市气候概览（多图×2） | line(日期/月→最高温_℃,avg,group=城市) · boxplot(城市→风速_m/s) |

### 工作区-低质量数据（极端数据健壮性示例）

| 表名 | 视图名 | 图表序列 | 覆盖点 |
|------|--------|----------|--------|
| 16-日期格式大全 | 日期格式解析概览（多图×5） | bar(ISO日期/年→非法日期,count) · bar(斜杠日期/季→非法日期,count) · bar(紧凑日期/周→非法日期,count) · line(美式日期/日→非法日期,count) · line(中文日期/月→非法日期,count) | 七种日期格式解析分桶；非法日期（text）作 count 度量演示非空计数 |
| 17-数字格式大全 | 数字格式分布概览（多图×3） | histogram(会计负数,sturges) · histogram(科学计数法,freedman-diaconis) · scatter(货币金额×欧元小数) | 负值与 1e10 量级跨度分箱；大量级窄区间下 labelPrecision 保证箱标签可辨；欧式小数/货币前缀数值解析 |
| 18-布尔与百分比 | 布尔与比例概览（多图×4） | bar(是否→完成率,avg) · bar(布尔英文→精确比例,min) · pie(中文真假→完成率,max) · histogram(全角比例,auto) | boolean 维度按是/否归桶；负百分比（-12.5%）聚合；percentage 字段作度量 |
| 19-特殊值杂项 | 特殊值聚合概览（多图×4） | bar(订单状态→混合数值,sum) · bar(订单状态→混合数值,count) · histogram(混合数值,auto) · boxplot(订单状态→混合数值) | 同维度 sum/count 对比演示 COUNT 剔除空值行（active 组 2 行 count=1）；空值行直方图/箱线剔除 |
