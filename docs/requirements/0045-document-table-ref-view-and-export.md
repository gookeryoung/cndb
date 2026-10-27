# 需求卡片：数据表引用支持按视图插入，且导出文件渲染真实数据表

- 编号：0045（与 ADR `docs/adr/0045-*.md` 同号，卡片存 `docs/requirements/0045-document-table-ref-view-and-export.md`）
- 来源 / 提出人：用户（口头需求）
- 日期：2026-10-27
- 关联 ADR：`docs/adr/0045-document-table-ref-view-and-export.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 插入数据表引用，需要支持特定视图数据的插入，以便于过滤项。导出文件应能正确渲染插入的数据表，而不是只显示一行代码。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「插入数据表引用，需要支持特定视图数据的插入」 | 「插入数据表引用」弹窗在选定数据表后，可再从该表的**当前用户可见视图**中选择一个视图（可选、不选＝整表）；插入的占位符带上 `view=<视图ID>` 参数 | frontend `InsertTableModal`、`DocumentEditorPage` | 前端单测：选表后出现视图下拉、仅含可见视图；选中视图后插入 `{{table:<id>\|view=<vid>}}` |
| C2 | 「以便于过滤项」 | 文档预览按所选视图的 `filters` / `filter_type` / `sortings` 取数，而非整表数据；视图切换 / 引用失效时预览有明确降级 | frontend `TableEmbed`、backend `GET /tables/{tid}/views/{vid}/rows` | 前端单测：带 `view` 的引用走 `viewApi.rows`；后端既有 `test_views_api.py` 视图行查询用例回归 |
| C3 | 「导出文件应能正确渲染插入的数据表」 | Word / PDF 导出解析正文中独占段落的 `{{table:…}}` 占位符，按占位符的 `view` 参数取数并渲染为真实表格（表头 + 数据行 + 主题表格样式），不得原样输出占位符文本；`limit` 仅约束预览分页，不限制导出行数（另设安全上限） | backend `documents/services/export/{docx,pdf}.py`、`routers/documents.py` | 单测：含 `{{table:…}}` 的正文导出 docx / pdf 后包含表格与数据；接口层用例覆盖 |
| C4 | 「而不是只显示一行代码」 | 导出表格口径与预览一致：列取表字段（排除 `hidden`），行按视图过滤 / 排序；导出物中不得出现 `{{table:` 字面量 | backend 导出链路 | 单测断言导出字节中无 `{{table:` 文本、含真实数据 |
| C5 | 隐含（引用无效不阻断导出） | 表 / 视图不存在、当前导出用户无读取权限、视图不可见时，导出**不得整篇失败**，降级为占位提示文字（与预览提示语义一致） | backend 导出链路 | 单测：无效表 ID / 无权限视图的导出仍返回文件且带降级提示 |
| C6 | 隐含（既有引用不回归） | 不含 `view` 的既有引用 `{{table:<id>\|limit=<n>}}` 预览与导出行为保持可用；前端解析器对未知参数、非法 `view` 的既有容错不变 | frontend `tableRef.ts`、backend 导出链路 | 既有 `tableRef.test.ts` / `TableEmbed` 相关用例全绿 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 插入弹窗只有「选表 + 每页行数」，无视图选择 | `frontend/src/pages/documents/InsertTableModal.tsx:45-62` | C1 主缺口 |
| 2 | 插入占位符只拼 `table` / `limit`，不写 `view` | `frontend/src/pages/documents/DocumentEditorPage.tsx:688-695` | C1 落点 |
| 3 | 占位符解析器已支持 `view=<数字>` | `frontend/src/components/Document/tableRef.ts:44-73` | C6 复用，预计不改 |
| 4 | 预览已按视图行取数（`viewApi.rows`） | `frontend/src/components/Document/TableEmbed.tsx:38-58` | C2 落点；列仍取表字段非隐藏项（`TableEmbed.tsx:60-69`） |
| 5 | 导出入口只把正文交给格式渲染器，无占位符解析 | `src/cndb/plugins/documents/routers/documents.py:626-678`、`services/export/__init__.py:95-106` | C3 主缺口 |
| 6 | DOCX 渲染逐行输出普通段落，占位符原样成段 | `src/cndb/plugins/documents/services/export/docx.py:105-155` | C3/C4 落点 |
| 7 | PDF 渲染同上 | `src/cndb/plugins/documents/services/export/pdf.py:88-140` | C3/C4 落点 |
| 8 | 视图行查询（应用 filters/sortings + 权限） | `src/cndb/plugins/tables/routers/views.py:670-698`、`services/core/records.py:list_rows` | C3/C5 复用 |
| 9 | seed 阶段把符号视图名解析为数字 ID（同一占位语法） | `src/cndb/cli/seed/documents.py:102-138` | 口径参照，不改 |
| 10 | Markdown 导出原样返回正文 | `services/export/__init__.py:34-38` | 已确认：md 也转静态 GFM 表格 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题（已全部有结论，需求方 2026-10-27 确认）

- [x] 导出格式范围：**三种格式都渲染** —— Markdown 导出把 `{{table:…}}` 转为静态 GFM 表格快照，docx / pdf 渲染为真实表格；导出物均不再出现占位符字面量。
- [x] 导出数据范围：**导出全部匹配行 + 安全上限**（上限值在 ADR 定），`limit` 仅作预览分页大小。
- [x] 视图口径：**仅应用过滤 + 排序**；列仍取表字段中未隐藏的字段（与现预览一致）。
- [x] 表格说明：**加一行说明**（表名 · 视图名 · 共 N 行），与预览说明一致。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认
