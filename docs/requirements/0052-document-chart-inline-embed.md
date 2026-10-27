# 需求卡片：文档图表由「外部实例引用」改为「正文内嵌 Markdown」

- 编号：0052（与 ADR `docs/adr/0052-*.md` 同号，ADR 待立项）
- 来源 / 提出人：用户（2026-10-27 会话）
- 日期：2026-10-27
- 关联 ADR：`docs/adr/0052-document-chart-inline-embed.md`（Proposed，待评审）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 文档插入图表，从引用改为嵌入 md 的设计，便于导入导出。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「从引用改为嵌入 md 的设计」 | 图表的完整定义（模板 key + 用户 config：数据 / 文案 / 配色 / 宽高等）**写在文档正文 Markdown 文本内**，成为正文的一部分；渲染不再依赖按 ID 读取 `documents_chart` 行。正文文本本身即可独立还原该图表 | `frontend/src/components/Document/chartRef.ts`、`MarkdownPreview.tsx`、`src/cndb/plugins/documents/services/charts/`、`models.py`（存量行处置见 Q2） | 纯函数解析样例：同一段正文在前端 / 后端解析出等价的模板 key + config + 宽度；正文中不含图表实例 ID 即可渲染 |
| C2 | 「嵌入 md」 | 内嵌语法的载体必须是 **Markdown 原生结构**（代码围栏或等价的标准 Markdown 文本块），不是 HTML 注入、不是外部文件 / 附件链接；现有 Markdown 导入导出管线（`importers/`、`export/`）对它按文本原样透传 | `src/cndb/plugins/documents/services/importers/`、`services/export/` | 导入 `.md` 后正文逐字保留图表块；导出 `.md` 中图表块可被重新导入 |
| C3 | 「便于导入导出」（导出侧） | Markdown 导出产物包含图表**可再编辑的定义**（而非只有 `assets/chart-<id>.svg` / PNG 静态图），导出的 `.md` 单独拿出也能被本平台或人工读改；DOCX / PDF 导出仍产出真实图形 | `src/cndb/plugins/documents/services/export/chart_refs.py`、`export/images.py`、`export/docx.py`、`export/pdf.py`、`routers/documents.py:631-690` | 导出 zip 的 `.md` 内保留图表定义块；DOCX 含 image 部件、PDF 含图形；无正文定义被静默丢弃 |
| C4 | 「便于导入导出」（导入侧） | 导入含图表定义块的 `.md` 后，图表在预览中直接可渲染、可编辑，无需人工绑定实例 ID；无法识别 / 模板已下线的图表块**降级为可见占位文字**，不阻断整篇导入 | `importers/markdown.py`、`services/charts/registry.py`、`MarkdownPreview.tsx` | 导出 → 再导入同一文件，图表可渲染且定义不丢；未知模板 / 坏 JSON 用例降级并给告警 |
| C5 | 隐含（与既有 `{{chart:<id>}}` 的兼容） | 存量文档里的 `{{chart:<id>|width=N}}` 不能因本次改造失效：要么迁移为内嵌定义，要么保留读取兼容；**同一文档内两种形态不得互相干扰**，行内混排仍不解析 | `chartRef.ts`、`export/chart_refs.py`、迁移 / 备份、`ChartEmbed.tsx` | 存量引用回归用例；新旧形态混排用例；备份往返用例 |
| C6 | 隐含（权限与可见性） | 图表定义随正文走，因此**渲染权限 = 文档读权限**；游客分享页按文档 token 渲染内嵌图表，不再需要「图表 ID 白名单」；写权限仍由文档编辑权限决定 | `routers/public.py:184-206`、`PublicSharePage.tsx`、`ChartEmbed.tsx`、文档权限链路 | 游客页内嵌图表免登录渲染；无权限用户不因图表定义绕过文档权限 |
| C7 | 隐含（编辑与版本链路） | 图表编辑即正文编辑：进入文档的双轨写入 / 修改申请 / 版本历史 / 自动保存口径（与普通正文一致），不产生「改了图表但正文版本未变」的旁路 | `DocumentEditorPage.tsx`、`ChartDesignerModal.tsx`、`InsertChartModal.tsx`、`services/drafts.py`、`services/change_requests.py` | 编辑图表 → 正文内容变化 → 版本 / 修改申请可见；查看态无写入口 |
| C8 | 隐含（既有能力零回归） | 图表模板两级注册表、后端唯一渲染器（SVG / PNG 双写端）、引用宽度（默认 75 / 25–100）、DOCX / PDF / 游客分享、数据表引用 `{{table:…}}`、无图表文档导出均保持现状；无图表文档前后产物一致 | 全链路 | 既有前后端测试与 `make flow` 全绿；无图表文档导出逐字节一致 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 正文只有按 ID 引用：`{{chart:<id>|width=N}}`，段落级独占 | `frontend/src/components/Document/chartRef.ts:28-48`、`src/cndb/plugins/documents/services/export/chart_refs.py:30-73` | 正文不含任何图表定义，必须查库才能渲染 |
| 2 | 图表实例存 `documents_chart` 表（`template_key + config`） | `src/cndb/plugins/documents/models.py:382-409`、迁移 `e0f1a2b3c4d5` | 定义与文档正文分离，是「导出丢可编辑性、导入无法还原」的根因 |
| 3 | 预览按 ID 拉 `/charts/{id}/render`（ETag 缓存） | `frontend/src/components/Document/ChartEmbed.tsx:43-55`、`frontend/src/api/charts.ts:122-140` | 改为内嵌后渲染入参是 config 而非 ID，缓存键与接口形态需重定 |
| 4 | 插入图表：设计器保存实例 → 页面插入 `{{chart:${chartId}}}` | `frontend/src/pages/documents/DocumentEditorPage.tsx:739`、`InsertChartModal.tsx:74`、`ChartDesignerModal.tsx` | 插入产物要从 ID 占位符改成图表定义块；设计器保存语义从「建实例」改为「写正文」 |
| 5 | 设计器实时预览走 `POST /charts/render-preview`（不落库） | `frontend/src/pages/documents/ChartDesignerModal.tsx`、`src/cndb/plugins/documents/routers/charts.py` | 该端点已「按 config 渲染」，天然适配内嵌方向 |
| 6 | Markdown 导出把引用改写为 `![alt](assets/chart-<id>.svg)` 并按 id 命名资产 | `export/chart_refs.py:135-165`、`export/images.py`、`routers/documents.py:662-682` | 导出物只有静态图、没有定义；重名资产的 ID 口径失效 |
| 7 | DOCX / PDF 按 ID 解析后 `to_png` 嵌入 | `export/docx.py:42`、`export/pdf.py:51`、`export/chart_refs.py:97-132` | 需改为从正文定义渲染；记忆化键从 id 改为定义指纹 |
| 8 | 游客分享匿名渲染端点用「正文引用的图表 ID 集合」做白名单 | `src/cndb/plugins/documents/routers/public.py:184-206`、`chart_refs.referenced_chart_ids` | 内嵌后无 ID 可白名单，改按分享文档正文定义渲染（C6） |
| 9 | Markdown 导入只做标题提取 + 空白规整，代码围栏原样保留 | `src/cndb/plugins/documents/services/importers/markdown.py:33-58`、`normalize.py:107-150` | 图表块若用围栏语法，导入侧天然不丢；需补「识别 + 校验 + 告警」 |
| 10 | 备份把 `charts` 键纳入工作区备份（严格校验、跳过记错误） | `src/cndb/plugins/workspaces/services/backup_io.py:594-620`、`routers/workspaces.py:569` | 若移除实例表，备份格式与旧备份兼容需决策（Q2） |
| 11 | 宽度参数写在占位符上，按引用出现序号改写 | `frontend/src/components/Document/refWidth.ts`、`MarkdownPreview.tsx:282-330`、`DocumentEditorPage.tsx` | 内嵌块需承载宽度；改写定位逻辑要按新语法重做 |
| 12 | 帮助文档对外描述 `{{chart:编号}}` 语法与宽度写回 | `frontend/src/pages/help/content/tutorials.tsx:573-580`、`CONTEXT.md:66-68` | 术语与帮助内容需同步（新术语写入 `CONTEXT.md`） |
| 13 | 既有测试按 ID 占位符断言 | `tests/test_document_export_chart_refs.py`、`tests/test_documents_charts_{registry,render,api,migration,backup}.py`、`frontend/src/components/Document/{chartRef,ChartEmbed}.test.*`、`frontend/tests/e2e/critical/document-chart-embed.spec.ts` | 语法变更会大面积命中，需同批迁移样例 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] **Q1 内嵌语法形态**：` ```chart ` 围栏 + JSON 载荷（`version` / `template` / `title` / `width` / `config` / 可选 `legacy_id`）。——**结论（需求方 2026-10-27 确认）：按建议**
- [x] **Q2 图表实例库去留**：保留 `documents_chart` 作为可复用素材库；正文插入时**复制定义**（含从素材库插入），正文不再引用 ID；实例表与库 CRUD 端点保持。——**结论（需求方 2026-10-27 确认）：按建议**
- [x] **Q3 存量 `{{chart:<id>}}` 处置**：一次性数据迁移把可解析引用展开为内嵌块、失效引用写为降级文字；迁移后**单一语法**，运行期不再解析 `{{chart:id}}`。——**结论（需求方 2026-10-27 确认）：按建议（直接不再解析）**
- [x] **Q4 Markdown 导出**：正文保留定义块 + 追加一对静态 SVG（`assets/chart-<指纹>.svg`，供第三方查看器看图）；资产名用内容指纹，不绑定 ID。——**结论（需求方 2026-10-27 确认）：按建议**
- [x] **Q5 导入容错**：坏 JSON / 未知模板 / 超限 config **保留原文块**、预览与导出降级为可见占位文字，并写导入告警，不阻断整篇（不静默改写成纯文本，保留可修复性）。——**结论（需求方 2026-10-27 确认）：按建议**
- [x] **Q6 宽度归属**：宽度（默认 75 / 25–100）写入内嵌块随正文分发；素材库宽度仅作插入默认值。——**结论（需求方 2026-10-27 确认）：按建议**
- [x] **Q7 编辑链路**：图表编辑 = 正文编辑，进版本历史 / 草稿 / 修改申请，不再有实例编辑旁路。——**结论（需求方 2026-10-27 确认）：按建议**
- [x] **Q8 体积上限**：单块定义 ≤ 32KB、单篇 ≤ 50 个图表块（插入 / 设计器保存 / 导入超限拒绝或告警）；既有超限文档仍可只读渲染，不做截断。——**结论（需求方 2026-10-27 确认）：按建议**

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-27，Q1–Q8 全部按建议）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。需求方已确认本卡片，进入 `adr-writer` 产出 `docs/adr/0052-document-chart-inline-embed.md`。
