# 甘特图视图设计

来源：`.trae/req/` 甘特图视图需求；2026-10-08 滚动与今日标线修正。

## 视图配置（GANTT_OPTIONS，view_options 字段）

- `start_date_field` / `end_date_field`：必填，date/datetime；缺任一显示配置引导空态。
- `actual_end_field`：实际完成日期，可选，条内渲染虚线框对比计划/实际。
- `title_field`：任务名称，可选，留空按 schema 自动推断，兜底取首字段。
- `group_field`：分组/着色字段（select 等），可选；分组启用后左侧渲染 WBS 组头（G1/G1.1 编号）。
- `progress_field`：进度百分比（0-100，越界截断）；进度 > 20% 时条内显示百分比文本。
- `assignee_field`：负责人，可选。
- `time_scale`：默认时间粒度 `day | week | month | quarter`，默认 `month`。
- `show_today_line`：今日标线开关，默认 `true`。

## 时间轴算法（ganttTimeline.ts 纯函数）

- `daysBetween` 含头含尾；`computeTimeRange` 前后各扩展 7/21 天。
- 双层表头：锚定层（year/month，全显）+ 当前粒度层（语义锚点标记 + `minGapPx` 稀疏化）。
- 8 档 `ZOOM_LEVELS`（quarter→day）；`selectZoomLevelForScale` 目标总宽 [600, 3000] 取中间档；
  `autoAdjustLevel` 仅在同 currentScale 档位内微调（用户切换粒度不漂移）。
- 不变量：各段天数之和 == 总天数，各段宽度之和 == 总天数 × pxPerDay（周/月/季首尾段按 range 裁剪计宽）。

## 滚动架构（2026-10-08 修正）

- 右侧 body（`data-testid="gantt-body"`）是唯一真实滚动容器，横纵双轴 `overflow: auto`。
  双轴同容器保证横向可达范围与行内容裁剪窗口一致——禁止拆成"外层横向 + 内层纵向"两层嵌套，
  否则内层纵向滚动条（约 17px）会把每行最右端内容裁成永久不可见。
- 顶层表头为 `overflow: hidden` 裁剪容器（`data-testid="gantt-header-scroll"`），
  通过带防抖标志的 scroll 事件与 body 双向同步 `scrollLeft`（防御 Shift+滚轮直接滚动 header）。
- 左列任务名列与 body 共享同一 virtualizer（`@tanstack/react-virtual`，overscan 8），
  纵向 scrollTop 双向同步。
- 左列表头高度 = 右侧双层表头高度（2 × `headerHeight`），保证左右行不错位。
- 鼠标滚轮默认纵向滚动行；Shift+滚轮横向滚动时间轴；底部导航条提供左移/右移/滚动到今天/回到起点。

## 今日标线与边界线

- 今日标线（`data-testid="gantt-today-line"`）：红色（`#ff4d4f`，含顶部圆点），竖贯 body 全高，
  表示当前日期/进度基准；`show_today_line: false` 时不渲染。
- 挂载后若今日在时间轴范围内，自动横向居中定位到今日标线（一次性，不动画）。
- 右边界虚线（`data-testid="gantt-boundary-line"`）位于 `left = 总宽 - 2`，
  画在总宽内侧——禁止画在 `left = 总宽` 处，2px 边框会向右扩展滚动溢出区导致滚动条过早出现；
  覆盖锚定层、当前层、body 网格背景三处。

## 空态

- 缺 start/end 配置 → 配置引导；无数据 → "暂无数据"；全部行日期无效 → 无有效任务提示。
