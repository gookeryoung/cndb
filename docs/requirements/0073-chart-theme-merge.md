# 需求卡片：新建图表列表按结构合并主题变体，主题选择移入设计器

- 编号：0073（无 ADR，S1）
- 来源 / 提出人：用户（会话）
- 日期：2026-10-30
- 关联 ADR：无（S1，方案写入本卡片「口径」节）

> 本卡片是**需求原文与约束编号的唯一副本**。

## 需求原句（逐字）

> 文档，插入图表，新建图表的列表，不应把不同主题也作为不同选项，应将同一结构形式的合并为一个（默认使用明快主题）。主题部分的内容，纳入设计图表页面中，在配色上方新增主题选择。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 新建图表的列表不应把不同主题也作为不同选项 | 插入图表弹窗「新建图表」列表中，标准类型主题变体模板（`*-business` / `*-classic` / `*-vivid|stacked|donut|trend|fill`）不再作为独立条目展示，每类结构只显示一个合并条目 | backend registry / frontend InsertChartModal | InsertChartModal 组件测试 |
| C2 | 同一结构形式的合并为一个（默认使用明快主题） | 注册表为 10 类标准类型各新增规范模板（key = 类型键，如 `line` / `pie`），default_config 取明快（vivid）预设；原变体模板保留注册（存量实例可渲染 / 可编辑），payload 以 `variant_of` 标记归属 | backend registry / layouts | registry 单测 |
| C3 | 主题部分的内容纳入设计图表页面，在配色上方新增主题选择 | 设计器在「配色」区上方新增「主题」选择（仅规范模板带 `theme_presets` 时渲染），切换即替换 config.theme 的 palette + paper；存量变体模板（无 theme_presets）不显示主题选择 | frontend ChartDesignerModal | ChartDesignerModal 组件测试 |
| C4 | 兼容性 | 存量实例（变体 key）渲染、编辑、ETag 均不受影响；payload 继续包含变体模板（设计器查找用），仅弹窗列表过滤 | backend registry | registry 单测 |

## 口径（方案）

- 变体判定在后端完成：`ChartTemplate.variant_of`（规范模板为 None，变体指向类型键）；规范模板携带 `theme_presets`（明快数据 / 商务蓝 / 经典纸面三套 palette+paper，明快排第一且为 default_config 来源）。
- 前端职责分离：InsertChartModal 按 `variant_of == null` 过滤列表；ChartDesignerModal 全量模板照常查找（编辑存量变体实例不回退）。
- 主题切换 = 整组替换 palette + paper；替换后用户仍可逐色微调（配置即自定义态，无持久「当前主题」标记）。
- 变体模板的样式差异（堆叠 / 环形 / 趋势线 / 填充）本就是 `style_fields` 开关，规范模板默认样式取明快预设值。

## 未决问题

- [x] 无（用户原句已明确合并规则与默认主题）
