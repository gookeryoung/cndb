# ADR 0045: 文档数据表引用支持视图过滤与导出真实渲染

Status: Accepted（2026-10-27 人工评审通过）
Date: 2026-10-27
Related: `frontend/src/pages/documents/InsertTableModal.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/components/Document/tableRef.ts`、`frontend/src/components/Document/TableEmbed.tsx`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/services/export/docx.py`、`src/cndb/plugins/documents/services/export/pdf.py`、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/services/core/view_access.py`
需求卡片: `docs/requirements/0045-document-table-ref-view-and-export.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「插入数据表引用，需要支持特定视图数据的插入」 | `InsertTableModal` 在「选表」下新增可选「视图」下拉；数据源为 `viewApi.list`（后端 `visible_view_filter` 已按当前用户收敛），不选＝整表；`DocumentEditorPage` 的 `insertTableRef` 拼成 `{{table:<id>\|view=<vid>\|limit=<n>}}`（`view` 在 `limit` 之前，解析器键序无关） |
| C2 | 「以便于过滤项」 | 预览侧沿用既有 `TableEmbed` → `viewApi.rows`（`filters` / `filter_type` / `sortings`），本期不改取数逻辑，只把 `view` 参数开放到插入 UI；引用失效仍走既有 `Alert` 降级 |
| C3 | 「导出文件应能正确渲染插入的数据表」 | 新增服务端解析器 `documents/services/export/table_refs.py`：独占段落 `{{table:…}}` → 真实表格。DOCX 用 `doc.add_table`、PDF 用 `platypus.Table`、Markdown 用静态 GFM 表格；`limit` 不限制导出行数，另有安全上限 `MAX_EXPORT_TABLE_ROWS=5000` |
| C4 | 「而不是只显示一行代码」 | 导出列 = 表字段中 `trashed=False` 且 `hidden=False`，按 `order` 排序，再剔除当前用户角色隐藏字段（`get_hidden_field_names`）；行由 `list_rows(db=db,user=user)` 输出，已含视图过滤 / 排序 / 行级权限；导出物中不得出现 `{{table:` 字面量 |
| C5 | 隐含（引用无效不阻断导出） | 解析器捕获表 / 视图读取的 `HTTPException`，渲染为 `[数据表引用无效：表 #N / 视图 #M …]` 文本段；整篇导出仍返回 200 |
| C6 | 隐含（既有引用不回归） | 无 `view` 的 `{{table:<id>\|limit=<n>}}` 继续按整表解析；前端 `tableRef.ts` 不改，未知参数 / 非法 `view` 的容错不变 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用需求卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 插入弹窗只有「选表 + 每页行数」，无视图选择 | `frontend/src/pages/documents/InsertTableModal.tsx:44-66` | 用户无法表达「按某视图过滤」，只能引用整表 | 确认（C1 主缺口） |
| 2 | 插入占位符只拼 `table` / `limit`，不写 `view` | `frontend/src/pages/documents/DocumentEditorPage.tsx:688-695` | 即便手写 `view` 也只能靠改源码模式，入口不可达 | 确认（C1 落点） |
| 3 | 占位符解析器已支持 `view=<数字>`，且键序无关 | `frontend/src/components/Document/tableRef.ts:34-73` | 语法层无需扩展，改动集中在 UI 与导出 | 排除（C6 复用） |
| 4 | 预览已按视图行取数（`viewApi.rows`），列取表字段非隐藏项 | `frontend/src/components/Document/TableEmbed.tsx:38-69` | 预览口径可直接作为导出对齐基准 | 确认（C2/C4 基准） |
| 5 | 导出路由只把正文交给格式渲染器，不做占位解析 | `src/cndb/plugins/documents/routers/documents.py:626-678`、`services/export/__init__.py:95-106` | `{{table:…}}` 作为普通段落进入导出物 | 确认（C3 主缺口） |
| 6 | DOCX 渲染逐行输出普通段落，表格仅识别 GFM `\|` 行 | `src/cndb/plugins/documents/services/export/docx.py:69-155` | 占位符原样成段；无结构化取数入口 | 确认（C3/C4） |
| 7 | PDF 渲染同上 | `src/cndb/plugins/documents/services/export/pdf.py:84-145` | 同上 | 确认（C3/C4） |
| 8 | 视图行查询已做表 READ + 视图 VIEW_READ + filters/sorts | `src/cndb/plugins/tables/routers/views.py:670-698` | 导出可复用同一服务层判定，不新增权限口径 | 确认（C5 依据） |
| 9 | `list_rows` 同时应用行级权限与角色字段隐藏 | `src/cndb/plugins/tables/services/core/records.py:448-573` | 导出按当前用户口径取数即可，无需自行判权 | 确认（C4/C5） |
| 10 | seed 阶段把符号视图名解析为数字 ID，语法与前端一致 | `src/cndb/cli/seed/documents.py:102-138` | 后端只需接受数字 ID；符号名不进导出链路 | 排除（不改） |
| 11 | Markdown 导出原样返回正文；带站内图片时另走 zip 归档 | `services/export/__init__.py:34-92`、`routers/documents.py:654-667` | 表格改写须发生在归档前，否则 zip 内的 .md 仍是占位符 | 新增（C3 补充） |
| 12 | 导出渲染器签名固定为 `(markdown_text, title, images)` | `services/export/__init__.py:95-106` | 需要加可选 `tables` 参数，同时保持既有调用零破坏 | 新增（C3 落点） |
| 13 | 视图 `field_options` / `field_order` 存在，但预览未使用 | `src/cndb/plugins/tables/models.py:252-259`、`TableEmbed.tsx:60-69` | 若本期引入会同时改变预览列口径，超出「过滤项」诉求 | 排除（D3） |

**核心缺陷（需求要补的）**：占位语法早已能表达「按视图取数」，但插入 UI 不能产生 `view` 参数；导出链路又只认 Markdown 文本，占位符没有任何服务端解释器，于是「插入的数据表」在导出物里退化为一行代码。

设计目标（不变量）：

- **I1 单一语法，双端同构**：导出解析规则必须与前端 `tableRef.ts` 的段落级语法一致（独占段落、数字 ID、键值参数），不得出现「预览能渲染、导出不认」的组合。
- **I2 权限即当前用户**：导出取数复用 `get_table_or_404(READ)` + `get_view_or_404(VIEW_READ)` + `list_rows(user=…)`，不引入旁路；无权限一律降级为占位文字，不泄露表 / 视图是否存在。
- **I3 预览与导出同口径**：列 = 表字段非隐藏（含角色隐藏），行 = 视图过滤 / 排序 + 行级权限；导出不因 `limit` 缩水。
- **I4 导出不因引用失败整篇失败**：单个坏引用只影响该段。
- **I5 既有零回归**：无 `view` 的引用、纯 Markdown 文档、图片归档路径、既有导出 API 契约（路径 / 参数 / MIME / 文件名）全部不变。

## Decision

### 1. 数据模型

无（沿用现有 `{{table:…}}` 语法；不落库、不加列、不加枚举）。

### 2. 判定算法（唯一入口）

新增 `src/cndb/plugins/documents/services/export/table_refs.py`，作为导出侧唯一解释器：

| 符号 | 签名 / 语义 |
|---|---|
| `TableRefSpec` | `table_id: int`、`view_id: int | None` |
| `ResolvedTable` | `table_name`、`view_name: str | None`、`header: list[str]`、`rows: list[list[str]]`、`total: int`、`truncated: bool`、`error: str | None` |
| `parse_table_ref_line(line)` | 与前端同构：`^\{\{table:(\d+)((?:\|[a-zA-Z]+=[^|}]*)*)\}\}$`（先 `strip()`） |
| `make_table_resolver(db, workspace_id, user)` | 返回 `TableResolver = Callable[[TableRefSpec], ResolvedTable]`；闭包内按 `(table_id, view_id)` 记忆化，避免同篇文档重复引用重复查库 |
| `rewrite_markdown_table_refs(content, resolver)` | 逐段替换为静态 GFM 表格（含说明行），供 `.md` 导出与归档复用 |
| `MAX_EXPORT_TABLE_ROWS = 5000` | 导出安全上限，与视图行端点 `limit ≤ 5000` 同量级 |

解析顺序（每一步失败即短路为降级文本，不抛到路由层）：

1. `get_table_or_404(table_id, workspace_id, db, user, TableAction.READ)`；`HTTPException` → `[数据表引用无效：表 #N 不存在或无访问权限]`。
2. 有 `view`：`get_view_or_404(db, table, user, view_id, ViewAction.VIEW_READ)`；`HTTPException` → `[数据表引用无效：视图 #M 不存在或无访问权限]`。
3. 列：`table.fields` 过滤 `trashed` / `hidden`，按 `order, id` 排序，再剔除 `get_hidden_field_names(db, table, user)`；结果为空 → `[数据表引用无效：表 #N 无可显示字段]`。
4. 行：`list_rows(db.get_bind(), table, filters=view.filters or None, filter_logic=view.filter_type, sorts=view.sortings or None, limit=MAX_EXPORT_TABLE_ROWS + 1, offset=0, db=db, user=user)`；`total` 取返回值；`truncated = len(rows) > MAX_EXPORT_TABLE_ROWS`，保留前 5000 行。
5. 单元格文本化：`None` → `-`；`bool` → `true/false`；`dict/list` → `json.dumps(ensure_ascii=False)`；其余 `str()`。Markdown 单元格额外把 `|` 转义为 `\|`、换行转 `<br>`；DOCX/PDF 换行转空格。

说明行：`{表名} · {视图名} · 共 {total} 行`，有视图才拼视图名；截断时追加 `（仅导出前 5000 行）`。

三个渲染器共用该解释器：

- DOCX：命中占位段落时先 `doc.add_paragraph(caption)` 再 `doc.add_table`（沿用 `Table Grid` + 主题表头底纹 / 文字色）。
- PDF：`Paragraph(caption)` + `_make_pdf_table(header + rows, preset, cjk_font)`。
- Markdown：`rewrite_markdown_table_refs` 输出 caption（斜体行）+ GFM 表格，随后再走图片归档改写。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{workspace_id}/documents/{doc_id}/export` | 行为变更（非契约变更）：正文中独占段落的 `{{table:…}}` 解析为真实表格；路径、`format` 参数、MIME、文件名规则、权限（工作区成员）均不变 |

无新增 / 废弃端点。

### 4. 边界与例外

1. **`limit` 不约束导出**：`limit` 仅用于预览分页；导出统一取全部匹配行，超过 5000 行截断并标注（D2/D9）。
2. **行内混排不解析**：`前面 {{table:1}} 后面` 与预览一致，按普通文本输出。
3. **视图字段显示不生效**：仅应用 `filters` / `filter_type` / `sortings`；`field_options` / `field_order` 不参与（D3）。
4. **坏引用降级**：表不存在、跨工作区、无表读权限、视图不可见 / 无 VIEW_READ（`get_view_or_404` 统一 404）均渲染占位文字；不区分「不存在」与「看不到」，与 ADR 0003 的 I6 口径一致。
5. **同篇重复引用**：解析器闭包按 `(table_id, view_id)` 记忆化，一次导出只查一次。
6. **导出用户与作者不同**：按**导出发起人**权限取数（行级权限 / 字段隐藏随之收敛），而非文档作者。
7. **Markdown 归档顺序**：先做表格改写再做 `render_markdown_archive`，保证 zip 内 `.md` 无占位符（I4 / #11）。
8. **无字段 / 零行**：无可见字段 → 占位文字；零行 → 只输出表头 + 说明行「共 0 行」。
9. **大单元格**：DOCX/PDF 只做换行转空格，不做截断（Word / reportlab 自行折行）。

### 5. 迁移

无（纯读路径变更，无表结构 / 数据迁移）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 组件 | `frontend/src/pages/documents/InsertTableModal.tsx` | 新增 `views` / `viewsLoading` / `viewId` / `onViewIdChange` props；在选表下拉后新增视图 `Select`（`allowClear`、`data-testid="insert-table-view"`，占位「全部数据（不按视图过滤）」）；未选表时禁用；底部说明补一句「选择视图后按该视图的过滤 / 排序取数」 |
| 页面 | `frontend/src/pages/documents/DocumentEditorPage.tsx` | 新增 `insertViewId` state；`viewsQuery`（`queryKey=['views', workspaceId, insertTableId]`，`viewApi.list`，`enabled: insertOpen && insertTableId !== null`）；表变更时清空视图；`insertTableRef` 按 `table` → `view` → `limit` 顺序拼参并清空三项；`InsertTableModal` 透传新 props |
| API 封装 | `frontend/src/api/views.ts` | 不改（`viewApi.list` 已存在且带可见性收敛） |
| 测试 fixture | `frontend/src/test/msw.ts` | 已有 `GET /tables/:tid/views`（`mockViews`）与 `/views/:vid/rows`，无需新增 handler；如用例需要多视图，仅在该用例 `server.use` 覆盖 |

默认不自动套用表的默认视图（D8）：不选＝整表。

### 7. 测试清单

**判定层（单测）**：

- `tests/test_document_export_table_refs.py::TestParse`：合法 `{{table:1}}` / `view` / `limit` / 键序无关 / 混排不解析 / 非数字表 ID / 空串；与前端 `tableRef.test.ts` 的样例保持一致（I1）。
- `TestRewriteMarkdown`：静态 GFM 表格 + 说明行；单元格 `|` 与换行转义；无视图 / 有视图说明行差异；坏引用输出占位文字且不含 `{{table:`。

**接口层**：

- `TestExportResolver`（真实 SQLite 表 + 视图 + 记录）：
  - 视图过滤命中 / 不命中行数正确，排序生效；
  - 列排除字段 `hidden` 与角色隐藏字段；
  - 超过上限截断并带「仅导出前 5000 行」（monkeypatch `MAX_EXPORT_TABLE_ROWS` 为小值）；
  - 同篇重复引用只取一次（计数桩）；
  - 表不存在 / 跨工作区 / 无权限视图 → 返回 `ResolvedTable.error`。
- `TestExportEndpoint`（`client`）：含 `{{table:…}}` 的文档分别导出 `md` / `docx` / `pdf`：200、内容无 `{{table:`、md 含表头与数据、docx 解包含 `word/document.xml` 表格节点、pdf 以 `%PDF` 开头；带图片 + 表格引用时 zip 内 `.md` 已无占位符。
- 既有 `tests/test_documents_plugin.py` 导出用例、`tests/test_document_export_images.py` 全绿（I5）。

**迁移 / 备份**：无。

**前端单测**：

- `DocumentEditorPage.test.tsx`：
  - 选表后视图下拉出现且仅含 `mockViews`（`全部数据`）；选中后插入 `{{table:100|view=200}}`；
  - 不选视图插入仍为 `{{table:100}}`（既有断言回归）；
  - 切换表清空已选视图；关闭弹窗后重开无残留。
- 既有「插入表格引用」用例（`:72-100`、`:476-487`）随弹窗新增控件调整定位后全绿；查看模式不可见断言（`:111-126`、`:489-501`）不变。

**e2e（前端）**：无（无新增端到端流程；导出为后端行为，由接口层用例覆盖）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0 后端导出渲染** | `table_refs.py`（解析 / 解析器 / md 改写）+ DOCX / PDF 接入 + 导出路由接线 + 判定层 / 接口层测试 | 中（跨插件调用与降级边界；需确保不因单个坏引用 500） |
| **P1 前端插入视图** | `InsertTableModal` 视图下拉 + `DocumentEditorPage` 状态 / 查询 / 拼参 + 前端单测 + 帮助文案同步 | 低（复用既有 `viewApi.list` 与占位语法） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案：占位符在哪解析、怎么渲染 | **后端集中解析**：新增 `export/table_refs.py`，三种格式共用解析与取数，各自输出对应表格对象 | 导出是服务端行为，权限 / 行级过滤 / 字段隐藏都必须在服务端收敛；三格式共用一套口径避免漂移 | ① 前端导出前把占位符替换成静态 Markdown（DOCX/PDF 拿不到结构化表格，且绕过服务端权限）；② DOCX / PDF 各自内联正则解析（两份解释器必然漂移） | `services/export/table_refs.py`、`{docx,pdf}.py` |
| D2 | 导出行数 | **全部匹配行 + 5000 行安全上限**，`limit` 只作预览分页 | 需求方 2026-10-27 确认；导出是快照，按 `limit` 会静默缺数据 | 只导出 `limit` 行（≤50，内容不完整） | `table_refs.py` |
| D3 | 视图口径范围 | **仅 filters / filter_type / sortings**；列仍取表字段（排除 hidden） | 需求方 2026-10-27 确认；与预览现状一致，改动面最小 | 同时应用 `field_options` / `field_order`（会连带改变预览列口径，超出「过滤项」诉求） | `table_refs.py`、`TableEmbed.tsx`（不改） |
| D4 | Markdown 导出形态 | **转静态 GFM 表格快照**（含说明行），导出物无占位符 | 需求方 2026-10-27 确认；与「导出文件正确渲染」一致 | 保留占位符文本（用户明确否决「只显示一行代码」） | `table_refs.py`、`services/export/__init__.py` |
| D5 | 导出说明行 | **加**：`表名 · 视图名 · 共 N 行`，截断追加提示 | 需求方 2026-10-27 确认；与预览说明文字口径一致 | 纯表格无说明（读者无法判断数据来源 / 完整性） | `{docx,pdf}.py`、`table_refs.py` |
| D6 | 坏引用处理 | **降级占位文字，导出继续**；不区分不存在 / 无权限 | 导出主文件不应被单段失败拖垮；沿用 ADR 0003 的 404 统一口径 | 抛出 4xx / 整篇失败（一张表被删就导不出文档） | `table_refs.py` |
| D7 | 解析器与前端语法的关系 | **同构正则 + 段落级独占**，两端口径一致并补同样例测试 | 预览与导出必须认同一批占位符（I1） | 后端放宽为行内任意位置解析（预览会与导出口径分裂） | `table_refs.py`、`tableRef.ts`（不改） |
| D8 | 视图下拉默认值 | **默认不选＝整表**，不自动套默认视图 | 插入瞬间用户可能尚未决定过滤范围；自动套用会让「看似整表」的引用实际被过滤 | 自动选「默认视图」（用户无法从 UI 判断引用是否带过滤） | `InsertTableModal.tsx` |
| D9 | 安全上限取值 | **5000 行**，与视图行查询端点 `le=5000` 同量级 | 避免超大表导出拖垮请求 / 生成超大 docx / pdf | 不设上限（大表可 OOM / 超时）；上限 1000（常用报表会被截断） | `table_refs.py` |
| D10 | 重复引用是否缓存 | **解析器闭包内按 `(table, view)` 记忆化** | 同一文档多处引用同一视图是常见写法，避免重复查询 | 每次重新查（N 次引用 N 次查询） | `table_refs.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：插入 UI 终于能表达「某视图的数据」，过滤诉求可自助完成；导出的 Word / PDF / Markdown 都是可读的真实表格，占位符不再以代码形态泄漏；导出权限与预览口径统一到当前用户。
- **负向**：导出链路新增一次跨插件查库（表 / 视图 / 行），大表导出耗时增加；每个占位符至少一次行查询（已记忆化）；DOCX / PDF 渲染器签名扩展，需同步既有单测与调用方。
- **风险与缓解**：跨插件调用失败或表被删导致导出异常 → D6 统一降级并补接口层用例；超出上限的数据静默缺失 → 说明行显式标注截断；前端视图列表与后端可见性漂移 → 直接复用 `viewApi.list`（同一 `visible_view_filter`）。

## 行业对照（可选）

无。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 视图可见性与 VIEW_READ | `visible_view_filter`、`get_view_or_404` | 导出复用同一判定，不新增视图权限口径 | ADR 0003 |
| 行级权限与角色字段隐藏 | `list_rows(db, user)`、`get_hidden_field_names` | 导出按当前导出用户的权限收敛 | ADR 0004 |
| 插入入口位置 | `MarkdownToolbar` → `InsertTableModal` | 视图下拉只加在既有弹窗内，不改入口可见性 | ADR 0042 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 后端导出渲染 | 已落地 | `src/cndb/plugins/documents/services/export/table_refs.py`、`src/cndb/plugins/documents/services/export/docx.py`、`src/cndb/plugins/documents/services/export/pdf.py`、`src/cndb/plugins/documents/routers/documents.py` | `tests/test_document_export_table_refs.py` | — |
| P1 前端插入视图 | 已落地 | `frontend/src/pages/documents/InsertTableModal.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx` | `frontend/src/pages/documents/DocumentEditorPage.test.tsx` | — |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：Accepted，P0 / P1 均已落地（全部期完成，待人工确认 Status 是否改 `Implemented`）
- 已完成：需求卡片 0045（C1–C6 与四项口径经需求方确认）；P0 后端导出解释器 `export/table_refs.py` + DOCX / PDF / Markdown 接入 + 导出路由接线；P1 前端 `InsertTableModal` 视图下拉 + `DocumentEditorPage` 状态 / 查询 / 拼参
- 下一步：人工确认后 Status 改 `Implemented`；按需在真实大表上抽查导出耗时
- 已知坑：导出解析必须与 `tableRef.ts` 保持段落级同构；Markdown 归档需先改写表格再打包；`list_rows` 仅在同时传 `db` 与 `user` 时才做角色字段隐藏；DOCX / PDF 渲染器签名扩展后 `tables` 必须保持可选（既有调用方零破坏）
- 最近一次全绿：`make check-fast`（ruff check / format、pyrefly 0 error、前端 tsc + eslint）；`tests/test_document_export_table_refs.py` 24 例、`frontend/src/pages/documents/DocumentEditorPage.test.tsx` 60 例、`tests/test_document_export_images.py` + `tests/test_documents_plugin.py` 77 例全绿
