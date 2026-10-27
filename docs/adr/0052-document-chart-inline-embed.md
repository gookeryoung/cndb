# ADR 0052: 文档图表由「外部实例引用」改为「正文内嵌 Markdown」

Status: Accepted
Date: 2026-10-27
Related: `frontend/src/components/Document/chartBlock.ts`、`frontend/src/components/Document/ChartEmbed.tsx`、`frontend/src/components/Document/MarkdownPreview.tsx`、`frontend/src/components/Document/refWidth.ts`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/pages/documents/InsertChartModal.tsx`、`frontend/src/pages/documents/ChartDesignerModal.tsx`、`frontend/src/pages/public/PublicSharePage.tsx`、`frontend/src/api/charts.ts`、`frontend/src/api/publicShare.ts`、`src/cndb/plugins/documents/models.py`、`src/cndb/plugins/documents/routers/charts.py`、`src/cndb/plugins/documents/routers/public.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/services/charts/`、`src/cndb/plugins/documents/services/charts/inline.py`、`src/cndb/plugins/documents/services/export/docx.py`、`src/cndb/plugins/documents/services/export/pdf.py`、`src/cndb/plugins/documents/services/export/images.py`、`src/cndb/plugins/documents/services/importers/markdown.py`、`src/cndb/plugins/documents/services/content.py`、`src/cndb/plugins/documents/services/search.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、ADR 0008（离线依赖）、ADR 0010（文档导入）、ADR 0017（游客分享）、ADR 0026（Chrome 81）、ADR 0042（插入入口）、ADR 0045（表引用导出）、ADR 0048（图表模板与实例）、ADR 0051（引用宽度）
需求卡片: `docs/requirements/0052-document-chart-inline-embed.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」或「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「从引用改为嵌入 md 的设计」 | 图表定义以 ` ```chart ` 围栏 JSON 块写入正文（`version` / `template` / `title` / `width` / `config`）；预览、导出、游客分享都从**正文块**渲染，不再按 ID 查 `documents_chart`（D1 / D2 / D3） |
| C2 | 「嵌入 md」 | 围栏是 Markdown 原生结构：`importers/normalize.py` 已对围栏内容原样保留（`normalize.py:107-150`），导入导出管线按文本透传；不引入 HTML 注入、不依赖附件同目录文件（D1 / D7） |
| C3 | 「便于导入导出」（导出） | Markdown 导出**保留定义块**并追加一对静态 SVG `![标题](assets/chart-<指纹>.svg)`；DOCX / PDF 从块渲染 PNG（沿用唯一渲染器）；资产名改内容指纹（D6） |
| C4 | 「便于导入导出」（导入） | `.md` 导入保留图表块；导出产物中的配对静态图按指纹识别并剥离，避免重导入出现「图 + 块」双份；坏块 / 未知模板保留原文并在导入告警中列出（D7 / D11） |
| C5 | 存量 `{{chart:<id>}}` 兼容 | 一次性 alembic 数据迁移把正文、历史版本、草稿、修改申请中的旧引用展开为内嵌块；失效引用写为降级文字；迁移后运行期**单一语法**（D5 / D12） |
| C6 | 权限与可见性 | 内嵌图表渲染权限 = 文档读权限；成员走 `POST /charts/render-preview`，游客走 `POST /documents/share/{token}/charts/render-preview`（token 有效即可，不再有图表 ID 白名单）；图表素材库 CRUD 仍按 owner / editor（D10） |
| C7 | 编辑与版本链路 | 图表编辑 = 正文编辑：设计器保存后改写对应图表块，经草稿 / 版本 / 修改申请链路；不再有「改实例不进文档版本」的旁路（D9） |
| C8 | 既有零回归 | 模板注册表、唯一渲染器、图表素材库 API、表引用 `{{table:…}}` 与宽度、DOCX / PDF / 游客分享、无图表文档导出保持不变（D4 / D8 / I8） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 正文以 ` ```chart ` 围栏块承载定义（独占段落），渲染只读块内配置 | `frontend/src/components/Document/chartBlock.ts`、`src/cndb/plugins/documents/services/charts/inline.py` | 正文自包含，离开数据库也能渲染 / 恢复 | 确认（C1 落点：围栏块） |
| 2 | 图表实例存 `documents_chart`（`template_key + config`） | `src/cndb/plugins/documents/models.py:382-409`、迁移 `e0f1a2b3c4d5` | 定义与正文分离，是导出丢可编辑性、导入无法还原的根因 | 确认（D2 / D4） |
| 3 | 预览按 ID 拉 `/charts/{id}/render`，客户端 ETag 缓存 | `frontend/src/components/Document/ChartEmbed.tsx:43-55`、`frontend/src/api/charts.ts:122-140` | 改为内嵌后渲染入参是定义，缓存键 / 端点形态需重定 | 确认（D3） |
| 4 | 插入：设计器保存实例 → 页面插入 `{{chart:<id>}}` | `frontend/src/pages/documents/DocumentEditorPage.tsx:735-740`、`InsertChartModal.tsx:74`、`ChartDesignerModal.tsx:296-305` | 插入产物要从 ID 占位符改成定义块；保存语义改为「写正文」 | 确认（D4 / D9） |
| 5 | 设计器实时预览走 `POST /charts/render-preview`（按 template + config，不落库） | `frontend/src/pages/documents/ChartDesignerModal.tsx:108-112`、`src/cndb/plugins/documents/routers/charts.py:107-121` | 该端点天然适配内嵌定义，可直接复用为正文渲染入口 | 确认（D3 依据） |
| 6 | Markdown 导出保留定义块并追加 `![alt](assets/chart-<指纹>.svg)`，资产按内容指纹命名 | `services/charts/inline.py`、`export/images.py`、`routers/documents.py:662-690` | 导出物既可由第三方查看器看图，也可重导入还原定义 | 确认（D6） |
| 7 | DOCX / PDF 按段落切分，图表块整体渲染 `to_png` 后嵌入 | `export/docx.py:146-190`、`export/pdf.py:120-160`、`services/charts/inline.py` | 围栏块被整块消费，不逐行误判；渲染按块定义进行 | 确认（D6） |
| 8 | 游客分享匿名渲染端点用「正文引用 ID 集合」做白名单 | `src/cndb/plugins/documents/routers/public.py:184-206` | 内嵌后无 ID 可白名单，改按正文定义渲染 | 确认（D10） |
| 9 | Markdown 导入只做标题提取 + 空白规整；围栏内容原样保留 | `importers/markdown.py:33-58`、`importers/normalize.py:107-150` | 内嵌块天然不丢；需补「配对静态图剥离 + 告警」 | 确认（D7） |
| 10 | 备份把 `charts` 键纳入工作区备份，导入不改写正文引用 | `src/cndb/plugins/workspaces/services/backup_io.py:391-398`、`:594-640`、`routers/workspaces.py:574` | 内嵌后正文自包含，新备份天然往返；旧 v8 备份的旧引用无 id 映射 | 确认（D12：备份格式不变） |
| 11 | 宽度写在占位符参数，按引用出现序号改写 | `frontend/src/components/Document/refWidth.ts:27-60`、`MarkdownPreview.tsx:282-330`、`DocumentEditorPage.tsx:747-750` | 图表宽度改由块字段承载；表引用宽度逻辑不动 | 确认（D8） |
| 12 | 帮助与术语对外描述 `{{chart:编号}}` 与宽度写回 | `frontend/src/pages/help/content/tutorials.tsx:573-580`、`CONTEXT.md:66-68` | 语法、术语与帮助需同步；新术语写入 `CONTEXT.md` | 确认（文档收尾） |
| 13 | 图表断言集中在块解析 / 导出 / 组件测试 | `tests/test_documents_charts_inline.py`、`tests/test_document_export_chart_inline.py`、`tests/test_documents_charts_{registry,render,api,migration,backup}.py`、`frontend/src/components/Document/{chartBlock,ChartEmbed}.test.*`、`frontend/tests/e2e/critical/document-chart-embed.spec.ts` | 语法切换后样例仍需前后端同批维护 | 确认（§7） |
| 14 | 正文按大小分级存储（内联 / `gz:` base64 / 外存 `.md.gz`） | `src/cndb/plugins/documents/services/content.py:151-194`、`:213-241` | 数据迁移必须按同一策略解码 / 回写，外存文件需原地重写 | 新增（D5 约束） |
| 15 | 历史版本 / 草稿 / 修改申请各自保存正文副本 | `models.py:131-150`、`:243-245`、`:284` | 旧引用若不迁移，历史版本与待审申请会显示裸占位符 | 新增（D5 范围） |
| 16 | 全文检索 FTS 表保存正文快照 | `src/cndb/plugins/documents/services/content.py:993`、`search.py:443-480` | 迁移改写正文后 FTS 需同步，否则搜索片段残留旧占位符 | 新增（§5 迁移） |

**核心缺陷（需求要补的）**：图表定义与文档正文是两份数据 —— 正文只有「指向实例的 ID」，离开数据库正文就丢失图表内容；导出只能降级成静态图，导入无法还原可编辑图表，历史版本 / 备份 / 第三方编辑器也都无法独立解释这张图。

设计目标（不变量）：

- **I1 正文自包含**：单个图表块携带渲染所需的全部信息（`template + config + width`），渲染路径不得查 `documents_chart`；删除素材库实例不影响已插入正文。
- **I2 单一语法**：运行期只解析 ` ```chart ` 围栏块；`{{chart:<id>}}` 只作为迁移输入存在，迁移完成后不再解析。
- **I3 唯一渲染器**：内嵌块仍走 `render_chart`（共享图元层 → SVG / PNG 双写端），前端与导出不得各自绘制。
- **I4 指纹稳定**：内嵌块 → 规范 JSON（键排序、UTF-8、无多余空白）→ SHA-256 前 12 位为指纹；导出静态图命名与导入去重都只认该指纹。
- **I5 失效不阻断**：单个坏块只降级该块（预览占位、导出占位段落、导入告警），整篇仍可预览 / 导出 / 导入。
- **I6 权限随正文**：内嵌图表可见性 = 文档读权限；游客分享仅凭分享 token；不提供按图表 ID 的跨文档枚举面。
- **I7 编辑即正文**：图表编辑进入文档草稿 / 版本 / 修改申请链路，与普通文本同一条写入路径。
- **I8 既有零回归**：无图表文档的预览与三种导出逐字节不变；模板注册表、渲染结果、图表素材库 CRUD、表引用 `{{table:…}}` 与宽度、图片引用均保持现状。

## Decision

### 1. 数据模型

**无数据库表 / 列变更**。新增的是「正文文本层」的图表块格式：

````markdown
```chart
{
  "version": 1,
  "template": "bar-line-dual-axis",
  "title": "2024–2028 营收趋势",
  "width": 75,
  "config": { "caption": {}, "labels": {}, "theme": {}, "data": {} }
}
```
````

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `version` | int | 是 | 块格式版本，当前只接受 `1`；未知版本 → 降级 |
| `template` | string | 是 | 注册表模板 key；不存在 / 下线 → 降级 |
| `title` | string | 否 | 图表名（≤255）：导出 alt、降级文字与设计器标题，不参与绘图 |
| `width` | int | 否 | 显示宽度 25–100，缺省 / 非法回退 75（对齐 ADR 0051 口径） |
| `config` | object | 是 | 模板 schema 的完整配置（caption / labels / theme / data） |
| `legacy_id` | int | 否 | 仅由存量迁移写入，供 downgrade 还原；**不参与指纹、不参与渲染** |

- 规范 JSON：`json.dumps(payload_without_legacy_id, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`，指纹 = `sha256(...).hexdigest()[:12]`。
- 序列化（导出 / 编辑器改写）输出 2 空格缩进、键顺序固定的可读 JSON；未知顶层键保留（手改字段不丢）。
- 上限：单块序列化后 ≤ 32KB；单篇正文 ≤ 50 个图表块；设计器保存 / 插入 / 导入超限时拒绝或告警（D2）。
- `documents_chart` 表保留为**图表素材库**：`template_key + config` 仍是可复用资产的存储形态，但正文不再引用其 ID（D4）。

### 2. 判定与渲染（唯一入口）

**后端模块** `src/cndb/plugins/documents/services/charts/inline.py`：

| 符号 | 语义 |
|---|---|
| `INLINE_CHART_LANG = "chart"`、`INLINE_CHART_VERSION = 1`、`MAX_BLOCK_BYTES = 32 * 1024`、`MAX_BLOCKS_PER_DOC = 50` | 唯一常量来源 |
| `InlineChartSpec` | `template_key` / `config` / `width` / `title` / `version` / `legacy_id` / `fingerprint` / `source`（原文） |
| `iter_inline_chart_blocks(content) -> Iterator[InlineChartBlock]` | 扫描正文，返回块位置（起止行）、`spec` 或 `error`；围栏须**独占一个段落**（段落外文本不解析） |
| `parse_inline_chart_block(lines) -> InlineChartBlock` | 单个块解析：围栏长度匹配 → JSON 解析 → 字段 / 版本 / 大小 / 模板校验 |
| `serialize_inline_chart_block(spec) -> str` | 规范可读 JSON + 围栏；导入 / 迁移 / 编辑器改写共用 |
| `render_inline_chart(spec) -> ChartDocument` | 唯一渲染入口：`render_chart(template_key, config)`；模板下线抛既有 `BadRequestTemplateError`，由调用方降级 |
| `migrate_legacy_chart_refs(content, resolve) -> tuple[str, int]` | 迁移 / 备份导入用：把 `{{chart:<id>}}` 展开为块（或降级文字），返回 `(新正文, 改动块数)` |

- **围栏识别**：起始行 `^ {0,3}`{3,}chart\s*$`，结束行同长度或更长的反引号；两者都必须落在段落边界（正文按 `\n\n+` 分段，段内只有围栏行）。行内混排（`前文 ```chart`）仍按普通 Markdown。
- **判定顺序**：大小 → JSON 语法 → `version` → `template` 存在性 → `config` 宽松归一。失败产出稳定错误码（`json_invalid` / `version_unsupported` / `template_missing` / `too_large` / `config_invalid`），供前端 / 导出映射为占位文字。
- **宽松渲染 / 严格保存**：渲染用 `normalize_config`（未知键忽略、缺键回退默认，I3 / ADR 0048 I6）；设计器保存前走 `require_valid_config`，非法不入正文。
- **前端模块** `frontend/src/components/Document/chartBlock.ts`：与后端同构的 `parseChartBlock` / `serializeChartBlock` / `rewriteChartBlock` / `rewriteChartBlockWidth` / `iterChartBlocks`；`refs.ts` 合并 table / chart 两种切片。解析样例与后端同批维护。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /api/v1/workspaces/{wid}/charts/render-preview` | 语义扩展（契约不变）：设计器预览 + **正文内嵌图表渲染**；成员鉴权；请求 `template_key + config`，响应 SVG |
| `POST /api/v1/documents/share/{token}/charts/render-preview` | 新增：游客免登录渲染正文内嵌图表（token 有效；请求体 ≤32KB；`Cache-Control: no-store`） |
| `GET /api/v1/documents/share/{token}/charts/{chart_id}/render` | **删除**（ADR 0048 D9 的 ID 白名单端点，单一语法后不再需要） |
| `GET /api/v1/workspaces/{wid}/charts/{id}/render` | 保留：图表素材库预览；文档渲染不再调用 |
| `GET/POST/PUT/DELETE /api/v1/workspaces/{wid}/charts[/{id}]` | 保留：图表素材库 CRUD（owner / editor），与正文解耦 |
| `GET /{wid}/documents/{doc_id}/export` | 行为变更（契约不变）：图表块按 D6 渲染；路径 / 参数 / MIME / 文件名不变 |

### 4. 边界与例外

1. **块级独占**：图表块必须独占段落；与正文同段混排按普通文本（与 ADR 0048 D4 的段落级口径一致）。
2. **坏块降级文字**：`[图表定义无效：JSON 格式错误]`、`[图表定义无效：模板 xxx 不存在或已下线]`、`[图表定义无效：配置校验失败]`、`[图表定义无效：定义超过 32KB]`、`[图表定义无效：版本 2 不受支持]`；预览用 Alert、导出用段落、导入变告警。
3. **模板演进**：注册表升级后旧块自动回退默认值（宽松归一）；模板下线时该块降级，不影响其它块（I5）。
4. **素材库与正文解耦**：插入素材库图表 = 复制定义；素材库后续修改 / 删除**不会**回写已插入正文（D4）。
5. **游客分享**：分享页仍只渲染图表、不渲染 `{{table:…}}`（沿用 ADR 0017 口径）；匿名渲染端点只接受合法 token + 合法模板 + ≤32KB 配置，不提供文档 / 图表枚举能力。
6. **迁移残留**：迁移只能展开能解析到实例的旧引用；实例已删 / 跨工作区的旧引用写成与今日一致的降级文字。旧 v8 备份中的 `{{chart:id}}` 无 id 映射（备份不导出实例 id），导入后按原文保留、渲染为普通文本（D12 已知限制）。
7. **分级存储**：迁移必须按 `content.py` 的三种存储形态（内联 / `gz:` / 外存 `.md.gz`）解码并回写，并同步 `content_size` / `content_hash`；外存文件原地替换（D5）。
8. **FTS**：迁移结束时对被改写的文档执行与 `content.py:993` 同形的 `INSERT OR REPLACE`，保持检索快照与最新正文一致。
9. **草稿 / 修改申请**：迁移覆盖 `documents_draft.content` 与 `documents_change_request.proposed_content`；迁移后它们的哈希与最新版本哈希可能变化，`stale` 判定按新哈希重算（不额外改业务规则）。
10. **宽度作用域**：图表宽度随块（新插入默认 50，缺省 / 非法回退 75）；数据表宽度仍是 ADR 0051 的占位符 `width` 参数，二者互不影响（D8）。图表块工具栏提供「保存图片」，按当前渲染 SVG 导出 PNG / JPEG / SVG（纯前端，不上传）
11. **体积上限的执行点**：设计器保存 / 工具栏插入 / Markdown 导入；既有超限文档仍可只读渲染（不截断、不丢块）。
12. **不落渲染结果**：SVG / PNG 只在请求期生成；正文只存定义（I3 / ADR 0048 D10 延续）。

### 5. 迁移

单条 alembic revision（`down_revision = e0f1a2b3c4d5`，建议 id `x2y3z4a5b6c7_embed_document_charts`），**仅数据迁移、无 DDL**，迁移脚本自包含（不 import 应用服务，避免后续代码演进影响历史迁移）：

1. 读取 `documents_chart` 全表 → `{id: (workspace_id, title, template_key, config)}`；读取 `documents_document` 的 `id → workspace_id`。
2. 逐行处理 `documents_version.content`（全量历史版本）、`documents_draft.content`、`documents_change_request.proposed_content`：
   - 按存储形态解码（内联 / `gz:` base64 / 外存 `v{n}.md.gz`）；
   - 正则识别段落级 `{{chart:<id>|width=N}}`；可解析（实例存在且同工作区）→ 用迁移内联的序列化器写出块（含 `legacy_id`、`width`），不可解析 → 写今日同款降级文字；
   - 无旧引用则跳过；
   - 回写：按原阈值重新编码（外存版本写回同一 `v{n}.md.gz`），更新 `content_size` / `content_hash`；版本表同时刷新 `documents_document.content_path`（若走外存）。
3. 对每个被改写的文档，更新 `documents_fts` 的 content 列（标题 / 摘要 / 作者不变）。
4. `downgrade()`：对含 `legacy_id` 的块还原为 `{{chart:<id>|width=N}}`（`width=75` 省略参数），无 `legacy_id` 的原生块保持原样（旧版前端将其显示为代码块，属可接受的部分回滚）；同样更新 FTS 与哈希。
5. 幂等：第二次 upgrade 时已无旧引用，全部行跳过，不产生二次膨胀。

兼容性：迁移与前端 / 导出切换必须**同一版本发布**，不做前后端版本错配（旧前端不认围栏块，新前端不认旧占位符）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 解析 | `frontend/src/components/Document/chartBlock.ts`（新增） | `parseChartBlock` / `serializeChartBlock` / `iterChartBlocks` / `rewriteChartBlock`（按出现序号整块替换）/ `parseBlockWidth`；围栏与段落规则与后端同构 |
| 切片 | `frontend/src/components/Document/refs.ts` | `splitRefs` 合并 `tableRef` + 图表块；保留 `chartsOnly` 供游客页只渲染图表 |
| 嵌入 | `frontend/src/components/Document/ChartEmbed.tsx` | 入参由 `chartId` 改为 `spec`：成员 `POST render-preview`、游客 `POST share render-preview`；React Query 键含规范定义，编辑后自然刷新；失败 / 加载降级沿用；宽度取 `spec.width` |
| 预览 | `frontend/src/components/Document/MarkdownPreview.tsx` | 图表片段透传 `spec` 与出现序号；坏块渲染 Alert；`onEditChart` / 宽度回调改为按块序号 |
| 编辑器 | `frontend/src/pages/documents/DocumentEditorPage.tsx` | `insertChartBlock(spec)` 写入块（前后空行）；编辑回调按 occurrence 调 `rewriteChartBlock`；调宽调 `rewriteChartBlockWidth`；删除按 ID 取实例 / 失效渲染缓存的逻辑 |
| 插入弹窗 | `frontend/src/pages/documents/InsertChartModal.tsx` | 页签一模板；页签二「图表素材库」→ **复制定义**插入；文案标明「复制，不随素材库更新」 |
| 设计器 | `frontend/src/pages/documents/ChartDesignerModal.tsx` | `target` 支持 `{kind:'create'}` 与 `{kind:'editBlock', spec, occurrence}`；create 保存仍写素材库并回传 spec；editBlock 不调实例 API，只回传新 spec；预览端点不变 |
| 宽度 | `frontend/src/components/Document/RefWidthControl.tsx`、`refWidth.ts` | 控件复用；图表宽度由块序列化承载，`refWidth.ts` 仅保留表引用改写（ADR 0051 C3） |
| API 封装 | `frontend/src/api/charts.ts`、`publicShare.ts` | 复用 `renderPreview`；新增 `publicShareApi.renderInline`；移除文档侧的 `renderSvg` / ETag 缓存（素材库端点如需保留另设） |
| 帮助 | `frontend/src/pages/help/content/tutorials.tsx` | 图表专题改为「插入图表 = 写入正文块」，示例与宽度说明同步 |

### 7. 测试清单

**判定层（后端单测）**：

- `tests/test_documents_charts_inline.py`：围栏识别（3/4 反引号、段落独占、行内混排不解析）、JSON 往返、字段默认与非法回退、版本 / 模板 / 大小 / 数量上限、指纹稳定性（键序无关、`legacy_id` 不参与）、坏块错误码、手写未知键保留、SVG 文本转义。
- `tests/test_documents_charts_render.py` 增补：同一定义经 `render_inline_chart` 与 `render_chart` 产物一致（I3）。

**接口层**：

- `tests/test_documents_charts_api.py` 增补：`render-preview` 对成员可用、超 32KB 拒绝；坏模板 400。
- `tests/test_document_export_chart_inline.py`：Markdown 导出保留块 + 生成 `assets/chart-<指纹>.svg`、相同定义复用一份资产；DOCX 含 image 部件、PDF `%PDF`；坏块降级且导出 200；无图表文档导出与现状逐字节一致（I8）。
- `tests/test_documents_file_import_chart_blocks.py`：导出 `.md` → 再导入：块保留、配对静态图被剥离、指纹不匹配的图片保留；坏块 / 未知模板给告警且不阻断。
- `tests/test_document_public_share.py` 增补：匿名 `POST .../charts/render-preview` token 有效 200、失效 token 404、超大配置 413/400；旧 `GET .../charts/{id}/render` 已移除（404）。
- `tests/test_document_upload_*.py` 相关：`.md` 导入后正文块逐字保留（与 `normalize_markdown` 围栏规则一致）。

**迁移 / 备份**：

- `tests/test_documents_chart_inline_migration.py`：upgrade 覆盖最新版本 / 历史版本 / 草稿 / 修改申请；内联与 `gz:` 内容改写正确；外存版本文件原地重写；失效实例写降级文字；FTS 同步；幂等；downgrade 能还原 `legacy_id` 块。
- `tests/test_documents_charts_backup.py`：新备份（正文已内嵌）往返后图表仍可渲染；旧 v8 备份正文旧引用按原文保留（已知限制断言）。

**前端单测**：

- `chartBlock.test.ts`：与后端同批样例（含坏块、宽度、指纹无关字段、重写第 N 块）。
- `ChartEmbed.test.tsx`：成员 / 游客两种渲染端点、成功内联、失败 Alert、宽度、无回调不出控件。
- `InsertChartModal.test.tsx`：素材库插入复制定义；`ChartDesignerModal.test.tsx`：create 写库 + 回传、editBlock 不改库、预览防抖。
- `DocumentEditorPage.test.tsx`：插入块、编辑第 2 个块只改该块、调宽、查看态无控件。
- `refWidth.test.ts` / `TableEmbed.test.tsx`：表引用宽度不回归（ADR 0051）。

**e2e（前端）**：扩展 `frontend/tests/e2e/critical/document-chart-embed.spec.ts`：插入图表 → 编辑器源码含 ` ```chart ` 块 → 发布 → 查看态内联渲染 → 导出 zip 同时含定义块与 `assets/chart-<指纹>.svg` → 游客页免登录渲染 → 把导出的 `.md` 再导入为新文档，图表可渲染且块未重复。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0 后端内嵌地基** | `charts/inline.py`（解析 / 序列化 / 指纹 / 渲染）+ 导出 DOCX / PDF / Markdown 改读块 + 导入配对图剥离与告警 + 游客匿名渲染端点 + 判定 / 接口测试；此期**同时保留**旧语法解析（过渡） | 中（围栏扫描与逐行导出器的拼接、指纹稳定性） |
| **P1 前端引用改造** | `chartBlock.ts` / `refs.ts` / `ChartEmbed` / `MarkdownPreview` / 编辑器 / 插入弹窗 / 设计器 / 宽度控件 + 前端单测与 msw | 中（按块序号改写、设计器 create / editBlock 双模式） |
| **P2 存量迁移与收口** | alembic 数据迁移（含外存 / gz / FTS）+ 删除旧语法解析与旧端点 / 旧测试迁移 + 图表素材库文案 + 帮助 / CHANGELOG + e2e + 更新 ADR 0048 / 0051 / CONTEXT | 高（迁移涉及历史版本与三种存储形态，必须同版本发布） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 内嵌载体语法 | **` ```chart ` 围栏 + JSON 块**，独占段落 | C1 / C2；`normalize_markdown` 已原样保留围栏（#9）；人工可读可改、diff 友好、零 HTML 注入面 | ① HTML 注释块（不可读、需扫描注释）；② 扩成 `{{chart:...\|json}}` 单行（超长不可读）；③ 外部 `.json` / 附件引用（回到「正文不自包含」） | `charts/inline.py`、`chartBlock.ts` |
| D2 | 载荷字段与指纹 | `version + template + title + width + config`（迁移期加 `legacy_id`）；规范 JSON SHA-256 前 12 位为指纹；单块 32KB / 单篇 50 块 | C1；Q8；导出资产命名与导入去重需要稳定标识；未知键保留保障手改 | ① 只存 config 不存模板名（无法渲染）；② 存渲染后 SVG（违反 I3 / 正文膨胀）；③ 压缩单行 JSON（不可读）；④ 指纹含 `legacy_id`（迁移后改变导出文件名） | `inline.py` |
| D3 | 正文渲染入口 | 复用 `POST /charts/render-preview`；游客新增 `POST /documents/share/{token}/charts/render-preview`；**不按 ID 查库、不落渲染结果** | C1 / C6；I3；端点现成（#5）；定义在正文，服务端无需额外数据 | ① 新 `GET` 带 JSON 查询参数（URL 超长）；② 保存时预渲染 SVG 存正文（双源 / 版本噪音）；③ 前端绘制（违反 I3） | `routers/charts.py`、`routers/public.py`、`ChartEmbed.tsx` |
| D4 | 图表素材库去留 | **保留 `documents_chart` 为素材库**；插入 = 复制定义；正文与素材库互不回写；库 CRUD 端点不变 | C1 / C8；Q2；避免删表带来的迁移 / 备份 / 旧数据风险；仍保留「复用资产」价值 | ① 删表（存量实例与备份兼容成本高）；② 正文继续按 ID 引用（回到缺陷）；③ 正文与素材库双向同步（改一处影响多篇，语义不可控） | `models.py`、`routers/charts.py`、`InsertChartModal.tsx` |
| D5 | 存量引用迁移 | **一次性 alembic 数据迁移**：可解析引用展开为块（含 `legacy_id`），失效引用写降级文字；覆盖历史版本 / 草稿 / 修改申请；迁移后运行期单一语法 | C5；I2；历史版本与待审申请也不能显示裸占位符（#15）；回滚经 `legacy_id` 可部分还原 | ① 双语法长期并存（渲染 / 导出 / 白名单三处分叉）；② 不迁移、旧内容显示原始文本（历史回归）；③ 只迁移最新版本（历史版本仍坏） | `alembic/versions/..._embed_document_charts.py` |
| D6 | Markdown 导出形态 | **保留定义块 + 追加 `![标题](assets/chart-<指纹>.svg)`**；DOCX / PDF 从块渲染 PNG | C3；Q4；第三方查看器可看图，平台重导入可还原定义；指纹命名不依赖 ID | ① 只输出静态图（可编辑性丢失）；② 只输出块（GitHub 等看不到图）；③ SVG data URI 内联（体积大、查看器兼容不一） | `export/inline_chart.py`、`export/images.py`、`docx.py`、`pdf.py` |
| D7 | 导入去重与容错 | 配对静态图按「紧邻块 + 指纹匹配」剥离；坏块 / 未知模板保留原文 + 导入告警，不阻断、不静默改写 | C4；Q5；保留修复能力；指纹匹配避免误删用户图片 | ① 导入时把所有图表块转成纯文本（丢定义）；② 不剥离配对图（重导入出现图 + 块双份）；③ 按任意 `assets/chart-*.svg` 删除（误删风险） | `importers/markdown.py`、`export/inline_chart.py` |
| D8 | 宽度归属 | 图表宽度写入块 `width`（新插入默认 50，缺省 / 非法回退 75 / 25–100）；表引用宽度维持 ADR 0051 占位符参数；编辑态提供「保存图片」导出 PNG / JPEG / SVG | C6 / C8；Q6；随正文分发、按块独立；不动表引用成熟逻辑 | ① 存素材库（全局同宽）；② 图表也保留占位符参数（双处来源）；③ 仅 CSS 偏好（不随文档分发） | `inline.py`、`chartBlock.ts`、`chartImageSave.ts` |
| D9 | 编辑链路 | 图表编辑 = 正文编辑：设计器 `editBlock` 只回传新定义，编辑器按出现序号整块替换；create 仍写素材库并插入副本；进草稿 / 版本 / 修改申请 | C7；Q7；消除「实例改了正文未变」的旁路 | ① 继续编辑素材库实例（正文副本不更新，用户困惑）；② 引入独立图表版本表（与文档版本双轨） | `ChartDesignerModal.tsx`、`DocumentEditorPage.tsx`、`chartBlock.ts` |
| D10 | 游客分享 | 新增 token 鉴权的 `POST .../charts/render-preview`；**删除**按图表 ID 的匿名端点与白名单 | C6；I6；定义已在分享正文中，无需 ID 白名单；攻击面只剩「合法 token + 合法模板 + ≤32KB 配置」 | ① 保留 ID 白名单（内嵌后无 ID 可查）；② 分享页预渲染整页 SVG（体积 / 缓存 / 主题问题） | `routers/public.py`、`PublicSharePage.tsx`、`publicShare.ts` |
| D11 | 失效降级 | 单块降级：预览 Alert、DOCX / PDF 占位段落、Markdown 导出保留原块 + 导入告警；不阻断整篇 | C4 / C8；I5；与 ADR 0048 D7 / ADR 0045 口径一致 | ① 导出 4xx（一块坏导致整篇失败）；② 静默丢块（读者不知缺失） | `inline.py`、`ChartEmbed.tsx`、`docx.py`、`pdf.py` |
| D12 | 迁移回滚与备份 | `downgrade` 只还原含 `legacy_id` 的块；**备份格式不变**（正文自包含）；旧 v8 备份的旧引用无 id 映射，按原文保留 | C5 / C8；Q3；新备份天然往返；旧备份本就不重写 id（#10），不新增破坏 | ① 备份升 v9 导出实例 id（新备份已内嵌，无用）；② 猜测旧 id 映射（可能张冠李戴）；③ downgrade 尝试还原原生块（无原始 ID 可用） | `alembic/...`、`backup_io.py` |
| D13 | 迁移后的 FTS | 迁移结束时同步改写文档的 FTS content 行 | #16；避免搜索结果展示已不存在的 `{{chart:id}}` 文本 | 全量 rebuild（迁移外行为，耗时且无必要） | `alembic/...` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：文档正文第一次做到「图表自包含」——`.md` 单独导出 / 导入 / 复制到别的文档都能还原可编辑图表；图表随文档读权限分发，游客分享不再需要 ID 白名单；图表编辑回到文档版本 / 修改申请链路，消除实例与正文的双轨漂移。
- **负向**：正文会因 JSON 定义变长（每块数百字节到数十 KB），历史版本迁移是一次高风险数据操作；导出链路要处理围栏块与配对静态图，导入要剥离配对图；前端切片 / 改写从「短占位符」升级为「多行块 + 序号定位」。
- **风险与缓解**：迁移误伤历史内容 → 迁移自包含 + 分级存储用例 + `legacy_id` 可回滚 + 幂等测试；指纹漂移导致去重失效 → 固定序列化规则 + 前后端同批样例；旧 v8 备份降级 → ADR 与帮助明示「仅新备份完整往返」；大定义拖慢预览 → 32KB / 50 块上限 + 请求期渲染。

## 行业对照（可选）

无。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 图表模板 / 实例 / 渲染器 | `services/charts/`、`documents_chart` | 模板与唯一渲染器完整保留；实例改为「素材库」，正文用复制定义 | ADR 0048（本 ADR 修订其引用机制） |
| 图表引用语法与游客白名单 | `{{chart:<id>}}`、匿名 ID 渲染端点 | 由围栏块与 token 渲染端点替代，迁移后不再解析 | ADR 0048 D4 / D9 |
| 图表宽度 | 占位符 `width` 参数 | 图表改为块字段；表引用仍按 ADR 0051 | ADR 0051 |
| 数据表引用与导出 | `{{table:…}}`、表宽度 | 不变 | ADR 0045 / 0051 |
| 文档导入管线 | `importers/` 围栏透传 | 追加配对图剥离与告警，不改变源格式转换 | ADR 0010 |
| 游客只读边界 | 分享 token | 新增匿名渲染端点，仅 token + 模板 + 体积约束 | ADR 0017 |
| 插入入口 | 工具栏可选回调 | 入口不变，插入物从占位符变为块 | ADR 0042 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 后端内嵌地基 | 已落地 | `src/cndb/plugins/documents/services/charts/inline.py`、`src/cndb/plugins/documents/services/export/docx.py`、`src/cndb/plugins/documents/services/export/pdf.py`、`src/cndb/plugins/documents/services/importers/markdown.py`、`src/cndb/plugins/documents/routers/public.py` | `tests/test_documents_charts_inline.py`、`tests/test_document_export_chart_inline.py`、`tests/test_documents_file_import_chart_blocks.py`、`tests/test_document_public_share.py` | `ac0bf21f` |
| P1 前端引用改造 | 已落地 | `frontend/src/components/Document/chartBlock.ts`、`frontend/src/components/Document/refs.ts`、`frontend/src/components/Document/ChartEmbed.tsx`、`frontend/src/components/Document/MarkdownPreview.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/pages/documents/ChartDesignerModal.tsx`、`frontend/src/pages/documents/InsertChartModal.tsx` | `frontend/src/components/Document/chartBlock.test.ts`、`frontend/src/components/Document/refs.test.ts`、`frontend/src/components/Document/ChartEmbed.test.tsx`、`frontend/src/pages/documents/DocumentEditorPage.test.tsx`、`frontend/src/pages/documents/ChartDesignerModal.test.tsx`、`frontend/src/pages/documents/InsertChartModal.test.tsx` | `ac0bf21f` |
| P2 存量迁移与收口 | 已落地 | `src/cndb/alembic/versions/x2y3z4a5b6c7_embed_document_charts.py`、`src/cndb/plugins/documents/services/export/__init__.py`、`src/cndb/plugins/documents/routers/documents.py`、`frontend/src/api/publicShare.ts` | `tests/test_documents_chart_inline_migration.py`、`tests/test_document_public_share.py`、`frontend/tests/e2e/critical/document-chart-embed.spec.ts` | `ac0bf21f` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0–P2 代码与测试已落地，Status 待人工确认后由 `Accepted` 转 `Implemented`
- 已完成：`charts/inline.py` 判定 / 序列化 / 指纹 / 渲染 + 导出（md / docx / pdf）+ 导入配对图剥离与告警 + 游客 render-preview + alembic 数据迁移；前端 `chartBlock.ts` / `refs.ts` / `ChartEmbed` / 编辑器 / 设计器 editBlock / 插入弹窗；ADR 0048 / 0051 / CONTEXT / 帮助 / CHANGELOG 已同步为内嵌块口径
- 下一步：人工确认后改 `Status: Implemented`；发布时确保后端迁移与前端同版本上线（正文已无旧语法）
- 已知坑：围栏块必须段落独占，行内混排不解析；指纹不含 `legacy_id`；旧 v8 备份的 `{{chart:id}}` 无 id 映射，按原文保留；外存版本（>2MB）迁移需原地重写 `v{n}.md.gz`；FTS 是独立 content 表，需 `INSERT OR REPLACE` 同步；素材库删除不回写正文（定义已复制）；图表块按光标插入，未移动光标时落在正文最前，导出 `.md` 首个非空行是块而非 H1，重导入标题因此取自文件名（e2e 按文件名定位重导入文档）
- 最近一次全绿：`make check-fast`、`make test`（5806 passed / 17 skipped）、`make check-docs`（48 个 ADR / 0 error / 4 warning）；P2 收尾时另跑过 `make cov`（96.66%，门槛 95%）、`make frontend-coverage`（核心集合 lines 97.78% / branches 100%，全局 82.89%）
- e2e：`frontend/tests/e2e/critical/document-chart-embed.spec.ts` 已在 Windows 本机跑通（Playwright chromium，2 passed），覆盖插入 / 调宽 / 编辑 / 导出 / 游客渲染 / 重导入去重
