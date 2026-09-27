# 矩阵视图设计

对应需求：`.trae/req/req-14-矩阵视图.md`。

## 概念

矩阵视图是二维分类网格：纵轴（row_field）与横轴（column_field）各为一个分类字段，行数据按「纵轴值 × 横轴值」二维分组填入对应单元格，单元格内渲染行卡片。视觉采用「左侧彩色竖条 + 区域标题加粗」组合模式。

## view_options 契约（view_type = "matrix"）

| key | 类型 | 必填 | 说明 |
|-----|------|------|------|
| row_field | string | 是 | 纵轴分类字段名（select/multi_select/link/text/date/datetime） |
| column_field | string | 是 | 横轴分类字段名（同上） |
| date_granularity | string | 否 | 日期轴分桶粒度：year/quarter/month/week/day，默认 month；仅当轴字段为 date/datetime 时生效 |
| title_field | string | 否 | 单元格卡片标题字段；留空取主键字段，仍无则回退 id |

## 数据流与算法

- 纯前端分组（同 gantt/wbs 模式）：行数据经现有 useGridData 查询（受视图 filters/sortings/搜索约束），不新增后端端点。
- 分组 key 求值（matrixBoard.ts `axisKeyForRow`）：
  - select：`getSelectLabel` 取标签；multi_select / link：取首值标签（`getMultiSelectFirstLabel` / `getLinkFirstLabel`）；text 及未知类型：`String(value)`；date/datetime：按 date_granularity 分桶（year→YYYY，quarter→YYYY-Qn，month→YYYY-MM，week→YYYY-ww，day→YYYY-MM-DD）。
  - 空值归「未分组」。
- 桶排序：日期桶按时间升序；分类桶按 `localeCompare('zh-CN')` 升序。
- 网格构建（`buildMatrixGrid`）：单次遍历 rows 产出 `{ rowKeys, columnKeys, cells }`，cells 以 `rowKey::colKey` 复合键存 RowResponse[]，行内保持 API 返回顺序。

## 渲染（MatrixView.tsx）

- 布局：左上角标注格 + 顶部横轴列头行 + 左侧纵轴行头列 + 右侧单元格网格；网格区域独立横向/纵向滚动，行头与列头分别 sticky。
- 轴区视觉提示（角格 + 行头列 + 列头行构成 L 形轴区）：纵横双色契约——纵轴复用 `--cn-brand-color`，横轴用独立轴色 `--cn-axis-col-color`（index.css 每主题定义：浅色主题 #722ed1 紫、github-light 用 #8250df、深色主题 #a78bfa；品牌色本身为紫的 midnight 改用 #22d3ee 青、品牌色为青的 oled 改用 #a78bfa 紫）。淡染底经 `color-mix` 混入 `--cn-bg-page`（不透明，sticky 滚动不透底），层次自角向外衰减——角格 7% 最重且为上下双色分段（上半纵轴色 / 下半横轴色）、行列头 4% 各随其轴、数据区 0；轴区内侧分界线为轴色 25% 混入边框色并随所在轴着色（列头下缘与角格下缘 = 横轴色，行头右缘与角格右缘 = 纵轴色）；全部经 `color-mix` + `var(--cn-*)`，无新增硬编码组件色。
- 「未分组」兜底桶：与真实类别的边界用虚线（轴色 35% 混入边框色，dashed）——未分组列头与其列单元格左缘、未分组行头与其行单元格上缘，颜色各随所在轴。
- 数据列间淡竖线：`color-mix(in srgb, var(--cn-text) 7%, transparent)` 1px solid，首列除外（行头右缘轴色分界线已覆盖）。
- 左上角标注格：两行「纵轴/横轴」主题色徽章（brand 色 12% 淡染 chip）+ 加粗字段名，底色为轴区淡染最重的 7% 档（上下双色分段），突出方位语义。
- 区域标题：`MatrixAxisHeader` 组件统一渲染 —— 左侧 4px 圆角彩色竖条 + 加粗标题 + 数量徽章；纵轴行头与横轴列头复用，颜色按索引循环调色板（复用 `resolveTagColor` 同源色板）。
- 单元格：渲染该格全部行卡片（title_field 格式化值，density 控制间距），点击卡片触发 onRowClick 打开行详情；非空单元格显式 container 白底与轴区淡染对比，空单元格保持 page 中性弱底。单元格高度随内容自适应（不设 maxHeight/内部滚动），CSS Grid 行轨道高度由该行最高单元格决定；纵轴行头垂直居中。
- density 三档（compact/comfortable/spacious）影响卡片 padding 与字号，参照 KanbanView 密度映射模式。

## 后端

- `views.py _validate_view_fields` 的 view_options 校验键增加 `row_field`、`column_field`（title_field 已覆盖）。
- `seed.py _validate_view_fields`（视图种子校验）同步增加两键。
- ViewType 枚举不扩（跟随 gantt/wbs 现状：view_type 为自由字符串，前端 VALID_MODES 为准入闸口）。
- 无新增 API 端点。

## 前端改动清单

- `viewModes.ts`：ViewMode 联合类型与 VALID_MODES 增加 `'matrix'`。
- `viewOptionSchema.ts`：新增 `MATRIX_OPTIONS`（4 项，分组：轴字段/显示），`getOptionSchema` 增加 case。
- `views/matrixBoard.ts`：纯逻辑层（axisKeyForRow、buildMatrixGrid、dateBucket），可独立单测。
- `views/MatrixView.tsx`：视图组件（懒加载）。
- `GridPage.tsx`：MODE_BUTTONS 增加 matrix 项；KANBAN_MODES 集合增加 `'matrix'`；lazy import + 空闲预取 + 渲染分支。
- `CreateEditViewForm.tsx`：viewTypeOptions 增加矩阵选项。

## seed 示例数据

- 科研项目管理工作区「科研经费」表新增视图「经费投入矩阵」：row_field=项目类别（_apply_field_import_rules 已克隆并 backfill），column_field=拨付日期，date_granularity=year，title_field=预算科目。零 CSV 变更。
- 项目管理工作区新增 `资源排期.csv`：列 排期编号/团队/任务名称/排期日期/投入人天/负责人/状态，约 24 行，团队 ∈ {研发组, 设计组, 测试组, 实施组}，日期跨约 3 个月；新增 `fields.json` 声明 排期编号 required+unique。
- 项目管理工作区 `views.json` 新增视图「资源排期矩阵」：row_field=团队，column_field=排期日期，date_granularity=week，title_field=任务名称。

## 异常处理

- view_options 缺 row_field/column_field 或字段不存在：创建/编辑时后端 400（校验键）；已存视图运行时缺失配置渲染引导空态（提示配置视图）。
- 行在某轴无值：归「未分组」桶参与网格。
- 日期解析失败（非法字符串）：该行不落入日期桶，归「未分组」。

## 测试

- `matrixBoard.test.ts`：分桶粒度、分组 key 类型分派、桶排序、空值归组。
- `MatrixView.test.tsx`：轴头渲染（竖条+加粗）、左上角标注格轴徽章与字段名、单元格高度自适应（无 maxHeight/overflowY 硬上限）、单元格卡片归属、点击回调、未配置空态。
- 后端：视图创建校验用例覆盖 row_field/column_field 不存在返回 400。
- seed 回归：test_backup_seed_roundtrip、test_seed_report_examples 不受新增数据集影响。

## 验收清单

- [x] 矩阵视图创建/渲染全链路可用
- [x] 日期轴分桶粒度可配置且时序排列
- [x] 区域标题彩色竖条+加粗
- [x] 轴区纵横双色淡染 + 分轴分界线 + 未分组虚线边界
- [x] 单元格卡片点击打开行详情
- [x] 科研经费「经费投入矩阵」示例视图
- [x] 资源排期数据集与「资源排期矩阵」示例视图
- [x] make check 全绿
