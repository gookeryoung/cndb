# 需求卡片：文档图表实时预览占比与图表 / 表格显示宽度可调

- 编号：0051（与 ADR `docs/adr/0051-document-chart-preview-and-width.md` 同号）
- 来源 / 提出人：用户（2026-10-27 会话）
- 日期：2026-10-27
- 关联 ADR：`docs/adr/0051-document-chart-preview-and-width.md`（Proposed，待评审）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 文档，插入图表功能需完善：1.实时预览的图片太小，导致看不清楚，需提高占比。2.在文档中显示宽度需可调，当前占满宽度不好看，默认为75%宽度。4.表格当前占的宽度也太宽，默认75%，允许宽度可调。

说明：原文序号为 1 / 2 / 4（无 3），本卡片照原文保留，不重排、不补号。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「1.实时预览的图片太小，导致看不清楚，需提高占比。」 | 图表设计器的实时预览区占弹窗内容宽度的比例提高：预览列由固定 400px（约占 1080px 弹窗的 37%）改为**自适应且不小于内容区 55%**；弹窗宽度相应放大，预览 SVG 按容器宽度铺满（保持 `width="100%"` + 原始 viewBox 比例），不因列宽被截断 | `frontend/src/pages/documents/ChartDesignerModal.tsx` | 前端单测 / e2e 断言预览容器宽度占比 ≥ 55%，且预览 SVG 可见宽度随容器增长 |
| C2 | 「2.在文档中显示宽度需可调，当前占满宽度不好看，默认为75%宽度。」 | 文档正文中的图表引用默认按正文可用宽度 **75%** 渲染；宽度可按引用单独调整并持久化在文档正文中（不新增实例字段 / 数据库迁移）；取值有下限 / 上限并归一 | `frontend/src/components/Document/chartRef.ts`、`ChartEmbed.tsx`、`MarkdownPreview.tsx`、`DocumentEditorPage.tsx`、`src/cndb/plugins/documents/services/export/chart_refs.py` | 前后端同构解析样例 + `ChartEmbed` 单测（默认 75 / 自定义宽度 / 越界归一）+ 编辑器插入与调整用例 |
| C3 | 「4.表格当前占的宽度也太宽，默认75%，允许宽度可调。」 | 文档正文中的数据表引用默认按正文可用宽度 **75%** 渲染；宽度可按引用单独调整并持久化（扩展现有 `{{table:…}}` 参数语法，不新增表字段）；取值有下限 / 上限并归一 | `frontend/src/components/Document/tableRef.ts`、`TableEmbed.tsx`、`InsertTableModal.tsx`、`DocumentEditorPage.tsx`、`src/cndb/plugins/documents/services/export/table_refs.py` | `tableRef` 纯函数单测（默认 / 参数 / 越界）+ `TableEmbed` 单测 + 编辑器插入用例 |
| C4 | 隐含（既有能力零回归） | 未带宽度参数的存量 `{{chart:…}}` / `{{table:…}}` 按 C2 / C3 的默认 75% 呈现；占位符解析、失效降级、游客分享、编辑图表入口、三种导出格式与既有测试全部保持可用；无引用的文档渲染逐字节不变 | 全链路 | 既有前端单测 / 后端导出测试全绿 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 设计器弹窗布局：固定 1080px，左侧表单 `flex:1`，右侧预览固定 400px | `frontend/src/pages/documents/ChartDesignerModal.tsx:325`、`:353-355`、`:581` | 预览实际宽约 37%，是「看不清楚」的直接原因 |
| 2 | 图表 SVG 根节点为 `width="100%"`，跟随容器宽度 | `src/cndb/plugins/documents/services/charts/svg.py:100-105` | 只需改宿主容器宽度，渲染器无需改绘图逻辑 |
| 3 | 图表嵌入容器 `maxWidth:100%`，无宽度参数 | `frontend/src/components/Document/ChartEmbed.tsx:51-58` | 当前始终占满正文宽度 |
| 4 | 图表占位符语法无参数 | `frontend/src/components/Document/chartRef.ts:24-36`、`src/cndb/plugins/documents/services/export/chart_refs.py:28` | 需扩参数（与表引用同构），前后端同批样例 |
| 5 | 图表插入一律写 `{{chart:<id>}}` | `frontend/src/pages/documents/DocumentEditorPage.tsx:733-735` | 插入默认宽度需在此落 `width` 参数 |
| 6 | 表引用语法已支持 `view` / `limit` 参数 | `frontend/src/components/Document/tableRef.ts:34-73`、`src/cndb/plugins/documents/services/export/table_refs.py:36-98` | `width` 参数可直接扩展，无需新语法形态 |
| 7 | 表引用嵌入始终占满（antd Table 默认 100%） | `frontend/src/components/Document/TableEmbed.tsx:84-105` | 需宿主容器限宽 + 横向滚动兜底 |
| 8 | 插入表弹窗无限宽输入 | `frontend/src/pages/documents/InsertTableModal.tsx:75-82` | 需加宽度选择并写入占位符 |
| 9 | 三种导出：图表 DOCX 图片按正文可用宽度、Markdown 只有 `![](assets/chart-<id>.svg)`、表格导出铺满 | `src/cndb/plugins/documents/services/export/docx.py:141-153`、`pdf.py`、`chart_refs.py:122-152`、`table_refs.py:195-213` | 导出是否跟随 75% 需要需求方拍板（见未决问题） |
| 10 | 游客分享页复用同一 `ChartEmbed` | `frontend/src/pages/public/PublicSharePage.tsx`、`ChartEmbed.tsx` | 宽度参数在分享页同样生效，无需额外接口 |
| 11 | 既有测试 | `frontend/src/components/Document/{chartRef,tableRef}.test.ts`、`ChartEmbed.test.tsx`、`TableEmbed` 相关、`ChartDesignerModal.test.tsx`、`tests/test_document_export_{chart,table}_refs.py` | 默认值变化会命中既有断言，需同批更新 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] **Q1 预览占比目标**：预览列不小于内容区 55%，弹窗由 1080px 放大到 1200px（左表单 + 右预览并排）；窄屏改为上下堆叠。——**结论（需求方 2026-10-27 确认）：按建议**
- [x] **Q2 宽度调节的落点与交互**：宽度写在占位符参数里（`{{chart:<id>|width=75}}`、`{{table:<id>|width=75}}`），编辑模式下在嵌入块提供「25% / 50% / 75% / 100% / 自定义」选择，选中即改正文参数；不改图表实例字段、不加迁移。——**结论（需求方 2026-10-27 确认）：按建议**
- [x] **Q3 默认值与存量文档**：所有未带 `width` 的存量引用统一按 75% 呈现（含游客分享与编辑预览）。——**结论（需求方 2026-10-27 确认）：接受该显示变化**
- [x] **Q4 导出是否跟随宽度**：DOCX / PDF 图片与表格按「正文可用宽度 × 宽度百分比」嵌入，Markdown 导出沿用原样（不改写图片 / 表格语法）。——**结论（需求方 2026-10-27 确认）：按建议**
- [x] **Q5 取值范围**：宽度百分比取 `25–100`、整数、非法 / 越界回退默认 75。——**结论（需求方 2026-10-27 确认）：按建议**

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-27，按建议推进 ADR）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
