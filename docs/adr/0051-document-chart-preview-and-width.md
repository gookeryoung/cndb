# ADR 0051: 文档图表实时预览占比与图表 / 表格引用宽度

Status: Accepted（2026-10-27 人工评审通过：预览占比、引用宽度参数与导出口径按建议方案）
Date: 2026-10-27
Related: `frontend/src/pages/documents/ChartDesignerModal.tsx`、`frontend/src/components/Document/chartRef.ts`、`frontend/src/components/Document/tableRef.ts`、`frontend/src/components/Document/ChartEmbed.tsx`、`frontend/src/components/Document/TableEmbed.tsx`、`frontend/src/components/Document/MarkdownPreview.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/pages/documents/InsertTableModal.tsx`、`src/cndb/plugins/documents/services/export/chart_refs.py`、`src/cndb/plugins/documents/services/export/table_refs.py`、`src/cndb/plugins/documents/services/export/docx.py`、`src/cndb/plugins/documents/services/export/pdf.py`、ADR 0017（游客分享）、ADR 0026（Chrome 81）、ADR 0042（工具栏插入入口）、ADR 0045（数据表引用导出）、ADR 0048（图表模板与实例）
需求卡片: `docs/requirements/0051-document-chart-preview-and-width.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」或「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）；原文序号 1 / 2 / 4，照原样保留。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「1.实时预览的图片太小……需提高占比。」 | 设计器弹窗 1080 → 1200px（`maxWidth: calc(100vw - 24px)`）；桌面左右分栏由「左表单 + 右 400px 固定预览」改为预览列 `flex-basis: 56%` / 表单 `44%`，预览列 `min-width: 0` 且 SVG 继续按容器铺满；窄屏（`useResponsive().isMobile`）上下堆叠，预览 100% 宽（D3 / D8） |
| C2 | 「2.在文档中显示宽度需可调……默认为75%宽度。」 | `{{chart:<id>|width=N}}`：`N` 为 25–100 整数，缺省 75，非法 / 越界回退 75；前端 `ChartRef.width` 与后端 `ChartRefSpec.width` 同构解析；`ChartEmbed` 宿主 `figure` 宽度 `N%`；编辑模式下嵌入块提供宽度控件，选中后按**引用出现序号**改写正文占位符（D1 / D2 / D4） |
| C3 | 「4.表格当前占的宽度也太宽，默认75%，允许宽度可调。」 | `{{table:<id>|view=…|limit=…|width=N}}`：在既有参数语法上追加 `width`，默认 / 值域 / 回退与 C2 完全一致；`TableEmbed` 宿主容器宽度 `N%`，超出列宽时容器内横向滚动；`InsertTableModal` 增加宽度输入（默认 75），编辑模式嵌入块同样有宽度控件（D1 / D2 / D4） |
| C4 | 隐含（既有能力零回归） | 未带 `width` 的存量引用统一按 75% 呈现（显示变化为本次需求确认项）；占位符仍为段落级独占、行内混排不解析；失效降级 / 游客分享 / 编辑图表入口 / 无引用文档渲染保持不变；DOCX / PDF 导出按宽度百分比，Markdown 导出不改写语法（D5 / D7） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用需求卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 设计器弹窗固定 1080px；左侧表单 `flex:1`，右侧预览固定 400px | `frontend/src/pages/documents/ChartDesignerModal.tsx:325`、`:353-355`、`:581` | 预览实际约占内容宽 37%，长图 / 多系列图看不清；弹窗不支持窄屏布局 | 确认（C1 落点：改宽 + 分栏比例 + 响应式） |
| 2 | 图表 SVG 根节点 `width="100%"`，只带 viewBox | `src/cndb/plugins/documents/services/charts/svg.py:100-105` | 渲染器不关心宿主宽度，改容器即可放大，不需要改图元 / 双写端 | 确认（C1 / C2 依据：宿主定宽） |
| 3 | `ChartEmbed` 的 `figure` 无宽度，内层 `maxWidth:100%` | `frontend/src/components/Document/ChartEmbed.tsx:51-58` | 图表永远占满正文宽度 | 确认（C2 落点） |
| 4 | 图表占位符语法无参数；导出侧正则同样无参数 | `frontend/src/components/Document/chartRef.ts:24-36`、`src/cndb/plugins/documents/services/export/chart_refs.py:28` | 没有承载「宽度」的位置；前后端需同批扩展参数语法 | 确认（C2 落点：新增参数） |
| 5 | 图表插入一律写 `{{chart:<id>}}` | `frontend/src/pages/documents/DocumentEditorPage.tsx:733-735` | 新插入默认即 75%，无需改插入文案；后续调宽由嵌入控件改写 | 确认（C2 落点） |
| 6 | 表引用已支持 `view` / `limit` 键值参数 | `frontend/src/components/Document/tableRef.ts:34-73`、`src/cndb/plugins/documents/services/export/table_refs.py:36-98` | `width` 可直接作为第三个参数扩展，语法形态不变 | 确认（C3 落点） |
| 7 | `TableEmbed` 外层 `div` 无宽度，antd Table 默认 100% | `frontend/src/components/Document/TableEmbed.tsx:84-105` | 表引用永远占满正文；窄列 + 多字段时观感拥挤 | 确认（C3 落点） |
| 8 | 插入表弹窗只有表 / 视图 / 每页行数 | `frontend/src/pages/documents/InsertTableModal.tsx:41-88` | 插入时无法预设宽度 | 确认（C3 落点：增加默认 75 的宽度输入） |
| 9 | 导出：图表 DOCX 图片按正文可用宽度、PDF 上限为正文宽度；Markdown 只写 `![](assets/chart-<id>.svg)`；表引用 DOCX / PDF 铺满正文 | `src/cndb/plugins/documents/services/export/docx.py:129-153`、`pdf.py:20-37`、`:118-128`、`chart_refs.py:122-152`、`table_refs.py:195-213` | 网页改窄后导出仍满宽会不一致；Markdown 无可靠的图片宽度表达 | 确认（C4 / Q4：DOCX / PDF 跟随，Markdown 不改写） |
| 10 | 游客分享页复用同一 `ChartEmbed` | `frontend/src/pages/public/PublicSharePage.tsx`、`ChartEmbed.tsx:24-46` | 宽度参数在游客页天然生效；游客只读不应出现宽度控件 | 确认（C2 / C4：分享页只读生效） |
| 11 | 既有解析 / 嵌入 / 导出测试按「无 width」断言 | `frontend/src/components/Document/{chartRef,tableRef}.test.ts`、`ChartEmbed.test.tsx`、`frontend/src/pages/documents/ChartDesignerModal.test.tsx`、`tests/test_document_export_{chart,table}_refs.py` | 默认值进入解析结果后，既有期望对象需同批补 `width: 75` | 确认（C4：测试同批更新） |
| 12 | Markdown 原生表格样式 `width: 100%` | `frontend/src/components/Document/MarkdownPreview.tsx:130-140` | 原生 Markdown 表格没有引用语法承载宽度；本次不改 | 排除（C3 仅指 `{{table:…}}` 动态表引用） |
| 13 | 宽度改写没有现成纯函数；`splitRefs` 片段不保留原文位置 | `frontend/src/components/Document/chartRef.ts:47-86` | 同一图表 / 表可被引用多次，按「出现序号」定位改写需要独立纯函数 | 新增（D4 落点：`refWidth.ts`） |
| 14 | 设计器无响应式分支；弹窗宽度固定 | `ChartDesignerModal.tsx:320-355`、`frontend/src/hooks/useResponsive.ts` | 窄屏并排会把表单 / 预览都挤到不可用 | 新增（D8 依据：复用 `useResponsive`） |

**核心缺陷（需求要补的）**：文档引用模型只有「引用谁」，没有「显示多宽」——图表 / 数据表嵌入层和 DOCX / PDF 导出层都硬编码满宽；设计器预览列又固定 400px，导致预览与正文两头都不合适。

设计目标（不变量）：

- **I1 宽度唯一来源**：引用宽度只存在于正文占位符参数 `width`，按引用（occurrence）独立；不写图表实例 config，不新增表字段。默认 75，值域 25–100 整数，非法 / 越界回退 75。
- **I2 前后端同构解析**：`chartRef.ts` / `tableRef.ts` 与 `chart_refs.py` / `table_refs.py` 对同一批样例给出相同 `width`；序列化 / 改写规则只在前端 `refWidth.ts` 一处实现。
- **I3 默认口径一致**：Web 预览、游客分享、DOCX / PDF 导出的缺省宽度均为正文可用宽度的 75%；Markdown 导出保持语法原样（C4 / D5）。
- **I4 设计器预览同源且可读**：预览仍走 `render-preview` 的同一 SVG，仅放大宿主容器；预览列占比 ≥ 55%，窄屏堆叠后可占满宽度。
- **I5 失效不阻断**：宽度参数非法只回退 75，不使整段引用失效；引用失效仍按原降级文字处理。
- **I6 存量零迁移**：不改数据库、不改接口契约、不做数据回填；旧文档无 `width` 时按 75% 呈现（已确认的显示变化）。
- **I7 既有零回归**：行内混排仍不解析；`view` / `limit` 语义不变；无引用的文档渲染逐字节不变。

## Decision

### 1. 数据模型

**无新增表 / 列 / 迁移**。宽度是正文占位符的一个参数：

| 引用类型 | 语法 | 参数顺序 | 缺省 |
|---|---|---|---|
| 图表 | `{{chart:<id>|width=N}}` | `width` 可单独出现；无其他参数 | 75 |
| 数据表 | `{{table:<id>|view=<id>|limit=<n>|width=N}}` | 保留既有参数顺序，`width` 追加在末尾 | 75 |

- `N` 为 25–100 的整数；缺省、非整数、`<25`、`>100` 一律按 75 解析（不是钳制到边界）。
- 新建插入仍写不含 `width` 的占位符（等价 75），避免旧语法无谓变长；用户调整宽度后写入显式 `width=N`。
- 未知参数继续忽略；`width` 只影响呈现，不参与权限 / 数据口径。

### 2. 判定与改写（唯一入口）

**前端纯函数** `frontend/src/components/Document/refWidth.ts`：

| 符号 | 语义 |
|---|---|
| `DEFAULT_REF_WIDTH = 75`、`MIN_REF_WIDTH = 25`、`MAX_REF_WIDTH = 100` | 唯一常量来源 |
| `parseRefWidth(value: string \| undefined): number` | 缺省 / 非整数 / 越界 → 75；合法整数原样返回 |
| `rewriteRefWidth(content, { kind, chartId/tableId, occurrence, width }): string` | 按段落扫描，找到同 kind + 同 ID 的第 `occurrence` 个占位符（0 基），在段内注入或替换 `|width=N`；保留该段原有 `view` / `limit` 与首尾空白；未命中原样返回 |

- `tableRef.parseTableRef` / `chartRef.parseChartRef` 都调用 `parseRefWidth`，`TableRef` / `ChartRef` 增加 `width` 字段，默认 75。
- `MarkdownPreview` 在切片渲染时按 kind 维护出现序号，把 `refOrdinal` 传给 `ChartEmbed` / `TableEmbed`；嵌入控件回调 `onRefWidthChange({kind, id, occurrence, width})` 只由 `DocumentEditorPage` 在**编辑模式**注入。
- `DocumentEditorPage` 用 `setContent(prev => rewriteRefWidth(prev, change))` 改写正文；不改编辑器选区、不自动保存（沿用既有保存口径）。

**后端解析**：

- `ChartRefSpec` / `TableRefSpec` 增加 `width: int = DEFAULT_REF_WIDTH`；两处正则升级为「数字 ID + 可选键值参数」（图表与表同构）。
- DOCX / PDF 只消费 `spec.width`；Markdown 导出的改写函数不读取宽度（I3）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| 全部图表 / 文档 / 导出端点 | 无契约变更；宽度只在正文文本与导出渲染内部生效 |

### 4. 边界与例外

1. **非法宽度不降级引用**：非整数 / `0` / 负数 / `>100` 按 75 呈现；引用本身仍正常渲染（I5）。
2. **重复引用各自独立**：同一图表 / 表在正文出现多次，宽度按出现序号分别改写；不提供「全部同步」批量操作。
3. **只读场景无控件**：查看模式、游客分享页只按参数呈现，不出现宽度控件；写权限仍由文档编辑权限决定（ADR 0042 模式）。
4. **宽度作用域**：仅 `{{chart:…}}` 与 `{{table:…}}`；上传图片、Markdown 原生表格不在本次范围（C3 / 卡片 Q2 确认）。
5. **窄宽度可读性**：25% 时图表按比例缩小、数据表在宿主容器内横向滚动（`overflow-x: auto`），不撑破正文。
6. **设计器预览**：SVG 仍 `width="100%"`；只改宿主列宽，不改后端 `render-preview` / `to_svg` 契约（I4）。
7. **导出宽度**：DOCX 图片 `width = 正文可用宽度 × N%`；DOCX 表引用按 `tblW` 百分比收敛列宽；PDF 图片 / 表格以 `正文可用宽度 × N%` 作为排版宽度上限；Markdown 导出保持原语法（Q4 确认）。
8. **存量文档**：无 `width` 的引用按 75% 呈现；这是本次需求明确接受的显示变化（I6）。
9. **超长表**：宽度只影响外框，列多时仍走横向滚动；分页 / 行数上限不变。

### 5. 迁移

无数据库迁移、无备份格式变更、无存量回填。占位符语法是向后兼容的超集：旧正文原样解析为 `width=75`；回滚只需还原前端 / 后端代码，正文中已写入的 `|width=` 会被旧解析器忽略（旧正则不接受参数时会退化为普通文本——发布前必须按 P0/P1/P2 整体上线，不做前后端版本错配）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 解析 | `frontend/src/components/Document/tableRef.ts`、`chartRef.ts` | 增加 `width` 字段与解析；图表正则升级为可选键值参数 |
| 改写 | `frontend/src/components/Document/refWidth.ts`（新增） | `parseRefWidth` / `rewriteRefWidth` 唯一实现；单测覆盖重复引用与参数保留 |
| 控件 | `frontend/src/components/Document/RefWidthControl.tsx`（新增） | `Popover + InputNumber`：25/50/75/100 快捷值 + 自定义（25–100）；仅在传入回调时渲染 |
| 嵌入 | `ChartEmbed.tsx`、`TableEmbed.tsx` | 宿主宽度按 `width%`；表格容器 `overflow-x:auto`；接入 `refOrdinal` 与 `RefWidthControl`；游客 / 查看模式不传回调 |
| 预览 | `MarkdownPreview.tsx` | 切片时计算 kind 内出现序号，透传 `onRefWidthChange`（可选） |
| 页面 | `DocumentEditorPage.tsx` | 编辑模式注入宽度改写回调；插入表 / 图表后的默认宽度天然为 75 |
| 插入表 | `InsertTableModal.tsx` | 增加宽度输入（默认 75，25–100），插入时非 75 才写 `|width=` |
| 设计器 | `ChartDesignerModal.tsx` | 弹窗 1200 + `maxWidth`；预览列 ≥ 56%，`min-width:0`；`useResponsive().isMobile` 时上下堆叠、预览 100% |
| 主题 | `frontend/src/index.css` | 仅在需要时补宽度控件的紧凑样式；不引入动画 / 新 token |

### 7. 测试清单

**判定层（单测）**：

- `tableRef.test.ts` / `chartRef.test.ts`：缺省 `width=75`；`width=50` 正常；`width=0/-5/abc/50.5/101` 回退 75；未知参数忽略；图表新增参数后仍拒绝行内混排。
- `refWidth.test.ts`：同 ID 多次引用按 occurrence 命中；保留 `view` / `limit` 顺序；无 `width` 时插入、已有 `width` 时替换；未命中原样返回；宽度 75 写入后仍可被解析回 75。
- 后端 `test_document_export_chart_refs.py` / `test_document_export_table_refs.py`：解析样例与前端同一批；`ChartRefSpec` / `TableRefSpec` 默认 `width=75`。

**接口层**：

- DOCX：图表图片宽度 = 可用宽度 × N%；表引用 `tblW` 百分比随 N 变化；缺省 75%。
- PDF：图表 / 表引用排版宽度随 N 变化；缺省 75%。
- Markdown 导出：改写结果与宽度参数无关（仍为 `assets/chart-<id>.svg` / GFM 表），无残留占位符。
- 游客分享渲染：宽度参数生效、无控件；坏引用降级不变。

**迁移 / 备份**：无（无迁移、无备份格式变更）。

**前端单测**：

- `ChartEmbed.test.tsx` / 新增 `TableEmbed.test.tsx`：缺省宽度 75%、自定义 50%、游客模式、无回调不出控件。
- `RefWidthControl.test.tsx`：快捷值 / 自定义 / 非法值回退 / 透传回调。
- `DocumentEditorPage.test.tsx`：编辑模式调整第 2 个同 ID 引用只改该处；查看模式无控件。
- `ChartDesignerModal.test.tsx`：预览列存在且 flex-basis ≥ 56%；移动端堆叠（mock `useResponsive`）。

**e2e（前端）**：

- 扩展现有 `frontend/tests/e2e/critical/document-chart-embed.spec.ts`：设计器预览宽度占弹窗 ≥ 55%；插入后正文默认 75%，调整到 50% 后刷新仍生效；导出 zip 中图表 / 表格宽度口径不回退满宽（docx / pdf 只验存在与下载）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0 解析与渲染** | `refWidth.ts` + 图表 / 表引用解析加 `width` + `ChartEmbed` / `TableEmbed` 宿主宽度 + 前端纯函数 / 组件测试；后端两个 spec 解析 + 导出解析测试更新 | 低（纯函数 + 样式宽度） |
| **P1 编辑器与设计器** | `RefWidthControl` + occurrence 改写接线 + `InsertTableModal` 宽度输入 + `ChartDesignerModal` 1200/56% 布局与响应式 + 单测 | 中（重复引用定位与编辑器内容改写） |
| **P2 导出与回归** | DOCX / PDF 宽度接线 + Markdown 导出不变 + e2e + 帮助 / CHANGELOG + 全量 `make flow` | 中（PDF 表格宽度与 DOCX 表格百分比在真实渲染器上的兼容性） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 宽度存在哪 | **正文占位符参数 `width=N`，按引用独立**；默认 75、25–100、非法 / 越界回退 75 | C2 / C3；Q2 需求方确认；同一图表在不同文档 / 不同段落可不同宽；零数据库变更（I6） | ① 存图表实例 config（同一图表全局同宽，无法按段落调整）；② 新增引用表存宽度（为纯展示引入迁移与备份复杂度）；③ 非法值钳制到边界（与需求方确认的「回退 75」相悖） | `chartRef.ts`、`tableRef.ts`、`chart_refs.py`、`table_refs.py` |
| D2 | 缺省宽度为何 | **75%** | C2 / C3 原文；Q3 确认存量文档也按 75% | 保留 100% 兼容旧观感（与需求原文冲突） | 同上 |
| D3 | 设计器预览如何变大 | 弹窗 1200px；预览列 `flex-basis: 56%`（≥ 内容区 55%），表单 44%；SVG 仍 100% 容器宽 | C1；现状仅 37%（#1）；渲染器已 `width="100%"`（#2） | ① 仅把 400px 调到 500px（仍不足 55%）；② 改成预览全屏弹窗（表单与预览无法对照编辑） | `ChartDesignerModal.tsx` |
| D4 | 宽度控件如何落到正文 | **编辑模式嵌入块上的紧凑控件**；按 kind + ID + 出现序号调用 `rewriteRefWidth`，只改目标段落 | C2；重复引用需各自独立（边界 2）；查看 / 游客只读（边界 3） | ① 只能手写源码（不可发现）；② 改一个 ID 全部同步（破坏按引用独立）；③ 存编辑器外的 UI 偏好（不随文档分发） | `RefWidthControl.tsx`、`MarkdownPreview.tsx`、`DocumentEditorPage.tsx` |
| D5 | 导出是否跟随 | **DOCX / PDF 跟随百分比；Markdown 保持原语法** | Q4 确认；导出与网页观感一致；Markdown 图片 / 表格宽度无标准可靠表达 | 三格式全跟随（Markdown 需注入 HTML，破坏纯 Markdown 与既有归档） | `docx.py`、`pdf.py`、`chart_refs.py`、`table_refs.py` |
| D6 | 前后端解析一致性 | 同一参数语法 + 同一批样例；前端 `refWidth.ts` 是唯一宽度常量与改写入口 | I1 / I2；ADR 0048 I3 的既有范式 | 前后端各自维护常量（默认值漂移） | `refWidth.ts`、两个后端 refs 模块 |
| D7 | 范围边界 | 只覆盖 `{{chart}}` / `{{table}}` 引用；原生 Markdown 表格与上传图片不改 | C2 / C3 与 Q2 的口径；原生表格无宽度承载语法 | 顺带改原生 Markdown 表格（需新语法 / HTML，超出需求） | `MarkdownPreview.tsx`（保持原样） |
| D8 | 窄屏设计器 | `useResponsive().isMobile` 时上下堆叠，预览 100% 宽 | C1 的可读性目标；Chrome 81 基线无新特性 | 强制并排（表单与预览都不可用） | `ChartDesignerModal.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：设计器预览从约 37% 提升到 ≥55%，图表细节可辨；图表与数据表默认 75%、可按引用独立调宽，长文档排版不再千篇一律满宽；宽度随正文文本分发，预览 / 游客分享 / DOCX / PDF 口径统一，零迁移。
- **负向**：占位符语法新增参数，前端 / 后端 / 导出三处需同步升级，版本错配会使旧解析器把带参数占位符当普通文本；同一 ID 多引用时依赖 occurrence 定位，编辑器改写逻辑增加一份纯函数与测试；PDF 表格宽度受 reportlab 排版约束，需用真实渲染断言兜住。
- **风险与缓解**：重复引用改错位置 → `refWidth.ts` 单测覆盖第 N 个同 ID 引用 + 页面测试；导出宽度变形 → DOCX `tblW` / PDF `colWidths` 按百分比计算并用导出测试断言；存量观感变化 → 已在卡片 Q3 由需求方确认，帮助文档 / CHANGELOG 明示。

## 行业对照（可选）

无。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 图表引用语法 | `{{chart:<id>}}` | 升级为可选 `width` 参数，仍段落级独占、行内混排不解析 | ADR 0048 |
| 数据表引用语法 | `{{table:<id>|view|limit}}` | 追加 `width`，既有参数语义不变 | ADR 0045 |
| 插入入口 | `MarkdownToolbar` 可选回调 | 宽度控件只进编辑模式，查看模式不出现写入口 | ADR 0042 |
| 游客分享 | `PublicSharePage` / 匿名 render | 分享页按宽度呈现但不给控件 | ADR 0017 |
| Chrome 81 基线 | 弹窗布局 / 控件 | 只用 flex / antd 既有组件，不引入新 CSS 特性 | ADR 0026 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 解析与渲染 | 未开始 | — | — | — |
| P1 编辑器与设计器 | 未开始 | — | — | — |
| P2 导出与回归 | 未开始 | — | — | — |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：Proposed（方案待人工评审，未开始实现）
- 已完成：需求卡片 0051 经需求方确认（2026-10-27，五个未决问题均按建议）；ADR 初稿完成
- 下一步：人工评审通过后把 `Status` 改 `Accepted`，由 implementer 按 P0 → P1 → P2 落地；每期回填落地状态表
- 已知坑：带 `width` 的占位符必须前后端同版本上线，旧解析器会把它当普通文本；重复引用改宽依赖 occurrence，不能用 replace-all；PDF 表格宽度需用真实 `%PDF` 渲染结果断言，不能只断言解析值
- 最近一次全绿：`make check-docs`（需求卡片落地时，2026-10-27）
