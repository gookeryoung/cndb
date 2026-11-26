# 0162 文档页列表化布局改造（S1）

Status: 已确认（2026-11-26 人工确认方向：列表为主、复用 antd Table、侧栏可拖拽）
Related: `frontend/src/pages/documents/DocumentsPage.tsx`、`frontend/src/pages/documents/DocumentTable.tsx`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/index.css`

## 需求原句

> 文档，文件夹和文件布局不够美观紧凑，请结合其他类似应用的布局设计，给出改进建议。
> 按这个方案来：列表为主、复用 antd Table、侧栏可拖拽

## 约束（C1..C6）

| # | 约束 | 验收 |
|---|---|---|
| C1 | 桌面端默认以**列对齐列表**呈现文件夹与文档，文件夹行置顶；网格卡片保留为可选视图，默认不出现 | 根层 / 文件夹层默认渲染表格；切到「网格」后根层恢复卡片 |
| C2 | 列表复用 antd `Table`（`size="small"`、`tableLayout="fixed"`、`pagination=false`），列固定为 名称 / 状态 / 标签 / 大小 / 更新时间 / 操作 | 单元格与列宽固定，数字列 `tabular-nums` 右对齐 |
| C3 | 页头收敛：桌面端面包屑与操作同一行，工具栏不再折行；导入 / 导出收进「更多」，回收站与新建保留为直接入口 | 1024px 宽下工具栏单行；导入 / 导出可从「更多」打开 |
| C4 | 文件夹详情头部压缩为单行工具条，名称、递归统计与重命名 / 移动 / 删除能力不减少 | `doc-series-detail` 仍含名称、计数与三个操作 |
| C5 | 桌面侧栏可拖拽调宽并持久化，范围 200–420px，默认 260px；双击恢复默认 | 拖动后宽度写入 localStorage，刷新保持；越界被夹取 |
| C6 | 移动端布局与交互不回归；批量选择、行操作菜单、可见性提示、状态聚合语义保持原口径 | 既有移动端用例全绿 |

## 现状影响面

- 桌面根层是 `minmax(240px, 1fr)` 卡片网格，文档是自绘 `Listy` 行，行高与数据表页（`antd Table`）不一致。
- 桌面工具栏 9 个控件在 `Space wrap` 中，1024px 下「导入 / 导出」折到第二行。
- 侧栏宽度写死 240px，多级标题被截断。
- 需求 0065 的排序 / 筛选 / 深链口径、ADR 0155 的跨工作区移动、ADR 0156 的引用修复、需求 0088 的导出行为均不得变化。

## 不做

- 不改后端接口、数据结构、权限判定。
- 不引入新的重型依赖（Table 为 antd 既有组件）。
- 不改移动端的信息架构（仍为卡片 + 两行列表）。

## 落地结果（2026-11-26）

- C1/C2：新增 `DocumentTable`，桌面默认列表；根层文件夹与文档分表但共用列；网格视图由 `Segmented` 切回原卡片。
- C3：页头单行；导入 / 导出进「更多」；900–1100px 标签 / 状态进「筛选」气泡。
- C4：系列头部改为 `cn-doc-series-bar` 单行工具条，操作改图标 + tooltip。
- C5：`MainLayout` 新增拖拽把手与 `clampSiderWidth`，宽度写入 `cndb_sider_width_v1`。
- C6：移动端沿用 `Listy` 两行列表与卡片，既有移动端用例全绿。
- 门禁补丁（2026-11-26）：桌面改为 `Table` 后，`perf/journeys.spec.ts` 与 `perf/document-open.spec.ts` 仍用旧选择器 `.cn-list-item`（只存在于移动端），且表格里文件夹行也带 `doc-list-format-*` 图标；改由 `docFixtures.publishedDocRow` 限定在文档块 `doc-file-table` 内取行，两条 @perf 用例本地实测通过。
- 门禁：`make flow` 全绿；前端全量 285 文件 / 3533 passed；覆盖率双门槛达标。
