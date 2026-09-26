# Grid 列宽自适应与列序调整设计

## 需求来源

- `.trae/req/`：Grid 表格列宽自适应 + 表头拖拽调宽 + 拖拽调整列顺序（用户确认方案，两轮迭代）。
- 粒度决策：列宽、列序均为**视图级**配置，仅作用于 grid 模式；字段管理器的全局 `Field.order` 不动。

## 数据模型

- 持久化载体：grid 视图的 `view_options`（JSON，后端 `View.view_options` 既有列，零迁移）。新增两个键：
  - `column_widths`: `Record<string, number>` — key 为字段 id 字符串（`String(f.id)`），value 为像素宽度；缺省键走类型化估算宽度。
  - `field_order`: `string[]` — 字段 id 字符串数组，表示列顺序；缺省回退 `Field.order`；未出现在数组中的字段（新建字段）按 `Field.order` 追加归位。
- 键均允许缺省/非法值，读取端做防御：非法宽度（非有限数）与非法 id 忽略。
- 不修改后端模型、schema 与 API — `view_options` 本就是自由 JSON dict。

## 接口定义

### buildColumns.tsx

- `buildColumns(fields, wid, viewSortings, viewFilters, onFilterApply, onFilterReset, onCellSave?, inlineOps?, options?)`：
  - 新增末位可选参数 `options?: ColumnOptions`，定义：
    - `columnWidths?: Record<string, number>` — 视图级宽度覆盖。
    - `fieldOrder?: string[]` — 视图级列序。
    - `onColumnResize?: (fieldId: string, width: number) => void` — 由 GridTableSection 在拖拽结束时回调（宽度传实际拖出的像素值，已夹取最小/最大约束）。
    - `onColumnOrderMove?: (fieldId: string, targetFieldId: string) => void` — 拖拽列 A 落到列 B 上时回调；目标为操作列时忽略。
    - `onColumnResetWidth?: (fieldId: string) => void` — 双击 th 右缘热区时回调；GridPage 删除该字段宽度覆盖，回退类型化估算；无覆盖时短路不产生写入。
  - 宽度计算：`columnWidths[String(f.id)]` 优先；否则按字段类型估算（`estimateColumnWidth(f)` 导出纯函数便于测试），再叠加表头字符数修正（每超出 4 字 +14px，上限 +60）。
  - 列序计算：`applyFieldOrder(fields, fieldOrder)` 导出纯函数 — 先按 fieldOrder 中出现且存在的 id 排前，其余字段按 `Field.order` 追加；隐藏字段照旧先过滤。

### gridTableSection.tsx

- 新增 props：`onColumnResize?: (fieldId: string, width: number) => void`、`onColumnOrderMove?: (fieldId: string, targetFieldId: string) => void`。
- `sortableColumns` useMemo 扩展为统一的表头交互注入：
  - 排序：沿用既有 onHeaderCell 三态循环（asc → desc → null），行为不变。
  - 调宽：th 右缘 8px 热区 — mousemove 时该区间置 `cursor: col-resize`；mousedown 在热区内开始拖拽（记录起始 x 与列宽，`stopPropagation` 阻断排序 click），document mousemove 实时更新宽度预览（受控 `width`），mouseup 提交 `onColumnResize(fieldId, width)`；拖拽期间置全局 `suppressClickRef`，th onClick 检测到即跳过排序。宽度约束：最小 60px、最大 600px。
  - 列序：th 注入 `draggable: true` 与 HTML5 DnD 事件（dragstart 记录源 fieldId，dragover preventDefault，drop 回调 `onColumnOrderMove`）。resize 拖拽进行中禁止 dragstart（互斥）。操作列（`__row_ops__`）不参与排序注入与拖放。
- `scroll.x` 改为「各列宽之和 + rowSelection 40」，下限保留 `Math.max(..., 1200)` 语义改为列宽总和与 1200 取大。

### gridToolbar.tsx

- 新增可选 prop `onResetColumnLayout?: () => void`：更多菜单追加「重置列宽与列序」项；缺省（非 grid 模式或无覆盖）时菜单项置灰。
- GridPage 传入条件：`mode === 'grid' && hasColumnLayoutOverride`（column_widths 非空或 field_order 非空）。

### GridPage.tsx

- 读取 `viewOptionsDraft?.column_widths / field_order` 传入 buildColumns。
- 新增回调 `handleColumnResize(fieldId, width)`：写入 `viewOptionsDraft.column_widths`（浅拷贝对象）→ 触发既有防抖 `debouncedPersist`；`handleColumnOrderMove(fieldId, targetFieldId)`：重排 `field_order` 数组（目标为空数组时以当前可见列顺序初始化）→ 同样走防抖。
- 未激活视图（本地草稿态）时回调仍更新 draft，保存行为与 filters/sortings 一致。

## 算法与流程

1. 列构建：fields（已滤 hidden）→ applyFieldOrder 重排 → 逐列取宽度（覆盖 > 估算）→ 输出 ColumnsType。
2. 拖宽：mousedown(热区) → 锁定 resize 状态 → mousemove 计算新宽并夹取 [60, 600] → mouseup 提交回调 → draft 持久化（500ms 防抖）。
3. 列序拖放：dragstart 记源 → drop 命中目标 th → 数组重排（把源 id 移到目标 id 的位置）→ 初始化/更新 field_order → 防抖持久化。
4. 幂等性：重复拖放同一位置（active === over 语义）由调用方短路，不产生写入。

## 异常处理

- resize/drag 过程中组件卸载：mouseup/mouseleave 监听挂 document，useEffect 清理时移除监听并复位状态。
- `column_widths` 中不存在的字段 id：不清理（字段可能临时隐藏），宽度读取按需匹配，残留键无副作用。
- field_order 含已删除字段 id：applyFieldOrder 自动忽略不存在项；field_order 缺项由追加逻辑兜底。
- resize 与排序点击冲突：热区 mousedown stopPropagation + suppressClick 标志，保证拖宽不触发排序。

## 验收标准

- [x] 各字段类型列有合理的默认宽度，长文本/关联列更宽、布尔列更窄
- [x] 表头右缘可拖拽调宽，最小 60px；松手后刷新页面宽度保持（视图级持久化）
- [x] 表头拖拽可调整列顺序，刷新后保持；操作列固定最右不参与
- [x] 拖宽/拖列序不误触排序；排序三态循环回归测试不破坏
- [x] 未保存视图草稿时同样生效；切换视图各自独立记忆
- [x] 重置入口：双击表头右缘重置单列宽度；更多菜单「重置列宽与列序」一键清空覆盖
