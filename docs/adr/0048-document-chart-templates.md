# ADR 0048: 文档可视化图形（类别 → 图形模板 → 用户图表实例）

Status: Accepted（2026-10-27 人工评审通过：手工录入不联动 / 游客免登录可见 / 暂不扩模板）
Date: 2026-10-27
Related: `frontend/src/components/Document/tableRef.ts`、`frontend/src/components/Document/TableEmbed.tsx`、`frontend/src/components/Document/MarkdownPreview.tsx`、`frontend/src/components/Document/MarkdownToolbar.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/pages/documents/InsertTableModal.tsx`、`src/cndb/plugins/documents/models.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/services/export/table_refs.py`、`src/cndb/plugins/documents/services/export/docx.py`、`src/cndb/plugins/documents/services/export/pdf.py`、`src/cndb/plugins/documents/services/export/images.py`、`src/cndb/plugins/documents/routers/public.py`、`src/cndb/plugins/help/services/figures/registry.py`、ADR 0008（离线依赖约束）、ADR 0017（游客分享）、ADR 0026（Chrome 81 基线）、ADR 0042（插入入口）、ADR 0045（导出占位符解释范式）、ADR 0030（服务端 SVG 先例）
需求卡片: `docs/requirements/0048-document-chart-templates.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」或「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「为文档增加可视化图形功能」 | 文档正文支持图表引用占位符，预览与 md / docx / pdf 导出均由**后端唯一渲染器**产出真实图形（D1）；渲染产物是含图号 / 标题 / 图区 / 图注的整幅图（对齐参考 HTML 的 fig-sheet 形态） |
| C2 | 「采取内置模板和用户自定义的设计」 | 模板 = 代码内置注册表（`CHART_CATEGORIES` / `CHART_TEMPLATES`，只读）；用户自定义 = `documents_chart` 实例行：`template_key` + `config`（数据 / 文案 / 配色 / 图注），保存时按模板 schema 校验（D3） |
| C3 | 「按照类别、图形模板两个层级进行管理」 | 类别（一级：趋势 / 构成 / 对比）与模板（二级）都在注册表登记；`GET /charts/templates` 按两级结构返回；实例归入其模板的类别；不提供用户自建模板（D3） |
| C4 | 「用户可以选取特定模板，在此基础上设计对应图形」 | 前端「插入图表」弹窗：类别 → 模板两级浏览 + 已有实例列表；选中模板可进入**图表设计器**（按模板 schema 生成数据表与文案面板，实时预览走 `POST /charts/render-preview`，防抖节流），保存即建实例并插入引用（D5） |
| C5 | 「能够在文档中进行引用显示」 | 独占段落占位符 `{{chart:<id>}}`：前端 `chartRef.ts` / `ChartEmbed`（与 `tableRef.ts` / `TableEmbed` 同构）；导出侧 `export/chart_refs.py`（与 `table_refs.py` 同构）；失效统一降级占位文字（D4 / D7） |
| C6 | 「请参考以上三个可编辑的HTML，设计首批模板」 | 首批 3 个模板（见 §Decision 2.首批模板）：`bar-line-dual-axis`（趋势）、`stacked-bar-horizontal`（构成）、`grouped-bar-horizontal`（对比）；图形形态与可编辑维度逐项对齐三份参考 HTML |
| C7 | 隐含（数据口径与参考 HTML 一致） | 数据 / 文案 / 配色随实例持久化；派生值（测算期增速、合计）渲染期自动计算不落库；图注支持 `{cagr}` 等模板 token 由渲染器求值替换（D11）；不绑定数据表 |
| C8 | 隐含（权限与既有文档能力一致） | 渲染 / 引用 = 工作区成员；实例 CRUD = owner / editor；导出按发起人权限；删除实例后引用降级（D8）；游客分享页**免登录渲染**——token 鉴权且仅限该分享文档正文引用的图表（D9） |
| C9 | 隐含（既有功能零回归） | 占位符新增独立语法不影响 `{{table:…}}`；导出渲染器沿用 ADR 0045 的可选参数扩展方式；无图表引用的文档渲染结果逐字节不变；既有测试全绿 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用需求卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 正文占位符只有 `{{table:…}}`：段落级独占、数字 ID、键值参数、非法回退 | `frontend/src/components/Document/tableRef.ts:34-112` | 无图表引用语法，但有成熟范式可同构复制 | 确认（C5 落点：新增 `chartRef.ts`） |
| 2 | 预览侧 `splitTableRefs` 切段后按段渲染 `TableEmbed` | `frontend/src/components/Document/MarkdownPreview.tsx:249-270` | 图表嵌入只需在切片层并行识别 `{{chart:…}}` 并挂 `ChartEmbed` | 确认（C1/C5 前端落点） |
| 3 | 插入入口是工具栏可选回调（`onInsertImage` / `onInsertTableRef`，不传不渲染） | `frontend/src/components/Document/MarkdownToolbar.tsx:191-215` | 「插入图表」按同一模式追加，不改既有按钮 | 确认（C4 入口） |
| 4 | 导出链路已有占位符服务端解释器先例（数据表）：解析 → 取数 → 三格式各自输出，坏引用降级 | `src/cndb/plugins/documents/services/export/table_refs.py`、`routers/documents.py:626-678` | 图表导出可平移该结构（解释器 + 闭包记忆化 + 降级） | 确认（C1/C5 导出落点） |
| 5 | DOCX / PDF 已有图片字节嵌入通道；Markdown 导出有图片归档改写（zip 内 `assets/`） | `services/export/docx.py:178`、`services/export/pdf.py:35`、`services/export/images.py:64-80` | PNG（docx / pdf）与 SVG 资产（md 归档）可复用既有通道 | 确认（D6 落点） |
| 6 | 帮助图示已验证「后端生成 SVG + 前端内联 + 清洗 + 失败降级」全链路 | `src/cndb/plugins/help/services/figures/{registry,builders,svg,store}.py`、`frontend/src/pages/help/HelpFigure.tsx:23-33` | SVG 字符串生成与前端内联（主题 token、sanitize）有直接先例 | 确认（D1 依据） |
| 7 | documents 插件模型均挂 `workspace_id` + `TimestampMixin`，迁移走 alembic 单条 | `src/cndb/plugins/documents/models.py:66-110` | 图表实例表同构挂 documents 插件 | 确认（D2 落点） |
| 8 | 前端无任何图表库依赖；参考 HTML 是纯 SVG 自绘（rect / line / circle / text / path） | `frontend/package.json`、参考 HTML `<script>` | 引入 ECharts 会破坏离线包体积与 Chrome 81 基线，且导出无服务端渲染 | 确认（D1 否决项依据） |
| 9 | 离线部署约束：不可运行期联网取依赖 | ADR 0008、`pyproject.toml` | 渲染器必须纯标准库 / 既有依赖实现 | 确认（D1 约束） |
| 10 | Pillow 经 reportlab 间接安装且已按运行期导入使用 | `src/cndb/plugins/tables/routers/files.py:135` | PNG 光栅后端零新增依赖 | 新增（D1 依据） |
| 11 | 游客分享页渲染正文 + 站内图片，无文档内动态占位符渲染 | `frontend/src/pages/public/PublicSharePage.tsx`、ADR 0017 | 图表引用在游客页的呈现需要显式决策 | 新增（C8 / D9） |
| 12 | Chrome 81 兼容基线由构建后静态检查兜底 | ADR 0026 | SVG / 内联 DOM 均为基线内特性；不使用 `color-mix` 等已知缺口 | 排除（渲染产物只用基线特性） |

**核心缺陷（需求要补的）**：文档正文的引用能力只有「数据表（行 × 列）」与「上传图片（静态）」两种，没有「数据 + 图形模板 → 可视化图形」的载体；参考 HTML 那样的图（数据可改、文案可改、随文档分发）在平台内无法创建、管理、引用与导出。

设计目标（不变量）：

- **I1 唯一渲染器**：同一图表实例的 SVG（Web / Markdown 导出）与 PNG（DOCX / PDF 导出）由后端**同一个**渲染入口产出，前端与导出均不得各自实现绘制逻辑。
- **I2 两级注册表是唯一真相源**：类别与模板只在代码注册表登记一次；接口、设计器 schema、渲染分派全部读注册表；用户产物只能是实例。
- **I3 引用语法同构**：`{{chart:<id>}}` 与 `{{table:<id>}}` 同为段落级独占占位符；前后端解析规则一致（同构正则 + 同样例测试）；行内混排视为普通文本。
- **I4 权限即工作区成员**：读（渲染 / 引用）按成员身份；写（CRUD）按 owner / editor；导出按发起人；不区分「不存在」与「无权限」（统一降级）。
- **I5 失效不阻断**：单个坏引用只降级该段（占位文字），预览 / 导出 / 分享整体照常。
- **I6 模板演进兼容**：实例只存 `template_key + config`，不存渲染结果；模板代码升级后旧实例必须仍可渲染（config 宽松校验 + 缺省回退），不得出现「升级即全量失效」。
- **I7 既有零回归**：无图表引用的文档在预览与三种导出中的产物逐字节不变；既有 `{{table:…}}`、图片、双轨写入行为不变。

## Decision

### 1. 数据模型

新增 `documents_chart`（documents 插件内，`models.py` 追加）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | PK | 引用 ID（占位符里的 `<id>`） |
| `workspace_id` | FK `workspaces_workspace`（CASCADE），索引 | 工作区隔离 |
| `title` | String(255) | 实例名（列表 / 插入弹窗展示） |
| `template_key` | String(64) | 指向注册表 `CHART_TEMPLATES` 的 key |
| `config` | JSON | 模板 schema 的完整配置：`caption`（图号 / 章节信息 / 标题 / 副题 / 图注）+ `labels`（图例 / 单位等文案）+ `theme`（配色）+ `data`（数据矩阵与派生开关） |
| `created_by_id` / `updated_by_id` | FK `accounts_user`（SET NULL） | 操作人 |
| 其余 | `TimestampMixin` | id / created_at / updated_at |

- 无软删除：删除即物理删除，引用处按 I5 降级（与表被删后 `{{table:…}}` 的处理一致）。
- `config` 落库前经注册表 schema 校验（Pydantic 模型逐模板声明），**宽松模式**：未知键忽略、缺失键回退模板默认值（I6）。
- 迁移：单条 alembic revision（`add_documents_chart`），建表幂等、downgrade drop table；存量零迁移、零数据回填。

### 2. 判定与渲染（唯一入口）

**首批模板（C6）**——注册表 `src/cndb/plugins/documents/services/charts/registry.py`：

| 类别（一级） | 模板 key（二级） | 名称 | 图形形态（对齐参考 HTML） | data schema 要点 |
|---|---|---|---|---|
| `trend` 趋势分析 | `bar-line-dual-axis` | 柱线组合图（双轴 · 含规划期） | 柱（左轴主值：实际 / 测算两色调 + 规划分界带与虚线）+ 折线（右轴次值），柱顶数值标签、折线点标签（深柱内加底片）、轴下区间说明、图例 | 行：年份 / 主值 / 次值 / 数据性质；`actualCount` 分界；次值可选「按主值自动推算」开关（派生） |
| `composition` 结构构成 | `stacked-bar-horizontal` | 水平堆叠条形图 | 行（如年份）× 系列堆叠，宽段内置白字 / 窄段外置标签、行合计标签、纵向网格、图例 | 行 × 系列矩阵（系列数 1–6）；合计自动派生 |
| `comparison` 目标对比 | `grouped-bar-horizontal` | 水平分组条形图 | 类别 × 两系列（现状 / 目标）成组水平条，组内双条 + 数值标签、图例 | 类别 × 2 系列矩阵；横轴上限自动扩展 |

三个模板共同的 `config` 项：`caption`（图号 / 章节信息 / 标题 / 副题 / 图注 / 数据来源）、`labels`（图例文案、单位、区间说明等）、`theme`（调色板数组 + 纸色，默认取参考 HTML 的 `#8E2318 / #1E3D57 / #5F6B4E` 系）。`bar-line-dual-axis` 的图注支持 `{cagr}` token：渲染器按规划期首末值求复合增速替换（对齐参考 HTML 的 `#cagr` 联动）。

**渲染管线（I1 的落点）** `src/cndb/plugins/documents/services/charts/render.py`：

| 符号 | 语义 |
|---|---|
| `render_chart(template_key, config) -> ChartDocument` | 唯一入口：校验 / 回填默认值 → 模板 `layout(config)` 产出**图元列表**（rect / line / circle / text / path 与画布尺寸）→ 包装整幅图（图头 meta / 标题 / 图区 / 图注） |
| `to_svg(doc: ChartDocument) -> str` | SVG 写端（Web / Markdown 导出资产）：字体用字族串，随前端主题；无脚本、无外链 |
| `to_png(doc: ChartDocument, scale=2) -> bytes` | 光栅写端（DOCX / PDF 导出）：Pillow 绘制同批图元，CJK 字体复用 `export/pdf_fonts.py` 已注册字体 |
| `render_chart_svg / render_chart_png` | 组合便捷函数；`render_chart` 是唯一分派点，导出与接口都调它 |

- 图元层是两个写端的共享中间表示；写端只做序列化，不做几何计算——保证 SVG 与 PNG 像素语义一致（同一坐标、同一配色、同一文本）。
- 轴上限自动扩展、派生值（增速 / 合计）在 `layout` 内计算（C7），不落库。

**导出解释器** `src/cndb/plugins/documents/services/export/chart_refs.py`（对齐 ADR 0045 的 `table_refs.py` 结构）：

- `parse_chart_ref_line(line)`：`^\{\{chart:(\d+)\}\}$`（先 `strip()`），与前端 `chartRef.ts` 同构。
- `make_chart_resolver(db, workspace_id, user)`：闭包按 `chart_id` 记忆化；校验工作区归属与成员身份；失效返回 `error`。
- 三格式接线：DOCX / PDF 命中占位段时以 `to_png`（2 倍分辨率）走既有 `add_picture` / `PdfImage` 通道；Markdown 导出改写为 `![alt](assets/chart-<id>.svg)` 并把 `to_svg` 字节并入 `images.py` 的归档资产字典（无归档条件的独立 .md 下载同步走该改写，SVG 落同目录）。
- 降级文本：`[图表引用无效：图表 #N 不存在或无访问权限]`（I5 / I4）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/charts/templates` | 新增：两级清单（类别 → 模板：key / 名称 / 描述 / data schema / 默认 config / 缩略预览 key） |
| `GET /api/v1/workspaces/{wid}/charts` | 新增：实例列表（`?category=` 按模板类别过滤，含 title / template_key / 更新时间） |
| `POST /api/v1/workspaces/{wid}/charts` | 新增：建实例（template_key + config，owner / editor） |
| `GET/PUT/DELETE /api/v1/workspaces/{wid}/charts/{id}` | 新增：实例读（成员）/ 改 / 删（owner / editor） |
| `POST /api/v1/workspaces/{wid}/charts/render-preview` | 新增：不落库渲染（template_key + config → SVG），设计器实时预览专用 |
| `GET /api/v1/workspaces/{wid}/charts/{id}/render` | 新增：实例渲染（SVG，`ETag` 取 `updated_at + template 指纹`，304 支持） |
| `GET /api/v1/documents/share/{token}/charts/{chart_id}/render` | 新增：游客分享免登录渲染（D9）。token 有效（active / 未过期 / 文档已发布）且 `chart_id` 在该分享文档正文引用集合内才放行，否则 404 |
| `GET /{wid}/documents/{doc_id}/export` | 行为变更（非契约变更）：`{{chart:<id>}}` 段落按 D6 渲染；路径 / 参数 / MIME / 文件名不变 |

### 4. 边界与例外

1. **行内混排不解析**：`前面 {{chart:1}} 后面` 与表引用一致，按普通文本。
2. **删除实例**：物理删除；既有引用渲染为降级占位文字（不阻止删除，与表删除行为一致）。
3. **模板 key 失效**（注册表下线某模板）：保存被 400 拒绝；存量实例渲染降级为 `[图表引用无效：模板已下线]`，列表中标记不可用（I6 的下线边界）。
4. **config 演进**：新增可编辑项旧实例自动回退默认值；删除项忽略未知键；渲染永不因缺键抛错（I6）。
5. **数据规模**：单实例 data 行 / 系列数按模板 schema 限定（如 `bar-line-dual-axis` ≤ 24 行、堆叠系列 ≤ 6），超限 400；渲染产物 SVG 尺寸有上界，防滥用。
6. **主题暗色**：SVG 用 `currentColor` / CSS 变量跟随前端明暗主题（对齐 HelpFigure 内联方案）；PNG 导出固定浅色纸底（打印口径）。
7. **游客分享（ADR 0017）**：游客页 `{{chart:…}}` 免登录渲染（D9）：匿名 render 端点要求 token 有效，且 `chart_id` 必须出现在该分享文档正文的 `{{chart:…}}` 引用集合内（防跨图表 ID 探测）；任一不满足 404，前端降级占位文字。
8. **并发编辑**：图表实例是独立实体（put 全量覆盖、`updated_at` 乐观展示），不进文档版本与修改申请链路；文档双轨写入不受影响（正文里占位符只是文本）。
9. **图片归档顺序**：Markdown 导出先做图表改写再做 `render_markdown_archive`（与 ADR 0045 表格改写同一顺序约定）。
10. **render-preview 不鉴权成员写身份**：成员即可用（只读渲染、无副作用）；防抖与频率由前端控制。

### 5. 迁移

单条 alembic revision 新建 `documents_chart`（含索引 `ix_documents_chart_ws`）；`upgrade` 幂等（`IF NOT EXISTS` 语义由 `create_table` + 既有迁移风格保证）、`downgrade` drop；无数据回填、无存量迁移。备份：`documents_chart` 纳入工作区备份表集合，备份往返测试覆盖（建 → 备 → 还 → 引用可渲染）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 解析 | `frontend/src/components/Document/chartRef.ts` | 新增：`parseChartRef` / `splitRefs` 扩展（在 `splitTableRefs` 的切段逻辑里并行识别 `{{chart:…}}`，产出 `chart` 片段；table / chart 片段可共存于同一文档） |
| 嵌入 | `frontend/src/components/Document/ChartEmbed.tsx` | 新增：按 id 拉 `GET /charts/{id}/render`（ETag），`sanitizeSvg` 后内联渲染（对齐 HelpFigure）；失败 / 加载降级为占位 / 骨架；编辑模式带「编辑图表」入口（有写权限时） |
| 工具栏 | `frontend/src/components/Document/MarkdownToolbar.tsx` | 追加可选回调 `onInsertChart`（图表按钮，不传不渲染，ADR 0042 模式） |
| 插入弹窗 | `frontend/src/pages/documents/InsertChartModal.tsx` | 新增：左栏类别分组 → 模板卡片（描述 + 静态缩略图）；「基于此模板新建」进设计器；另一页签列已有实例直接插入 `{{chart:id}}` |
| 设计器 | `frontend/src/pages/documents/ChartDesignerModal.tsx` | 新增：按模板 schema 渲染数据表（可增删行 / 系列）+ 文案面板 + 配色；右侧实时预览（`render-preview`，输入防抖 300ms）；保存（POST/PUT）后回插引用 |
| 页面 | `frontend/src/pages/documents/DocumentEditorPage.tsx` | 接线 `onInsertChart`（弹窗状态 + 插入段落级占位符，前后空行） |
| 预览 | `frontend/src/components/Document/MarkdownPreview.tsx` | 切片段识别 `chart` → 挂 `ChartEmbed` |
| API 封装 | `frontend/src/api/charts.ts` | 新增：templates / list / CRUD / render-preview / render |
| 测试 fixture | `frontend/src/test/msw.ts` | 新增 charts 相关 handler 与样例 SVG |

### 7. 测试清单

**判定层（单测）**：

- `tests/test_documents_charts_render.py`：三模板各自——坐标换算（轴上限自动扩展）、派生值（测算增速 / 合计 / `{cagr}`）、标签位置分支（柱内 / 柱外）、图元完整性（图头 / 标题 / 图注 / 图例）；`to_svg` 无脚本无外链、`to_png` 输出 PNG 魔数与尺寸、双写端文本一致性（同批图元同文本集合）。
- `tests/test_documents_charts_registry.py`：两级结构、模板 key 唯一、schema 校验（缺键回退 / 越界 400 / 未知键忽略）、模板下线降级。

**接口层**：

- `tests/test_documents_charts_api.py`：模板清单两级结构；CRUD 权限（viewer 只读、跨工作区 404）；render ETag 304；render-preview 不落库；删除后引用降级。
- `tests/test_document_export_chart_refs.py`：占位符解析同构样例（与前端 `chartRef.test.ts` 同一批）；三格式导出（md 归档含 SVG 资产、docx 含 image 部件、pdf `%PDF` 头）；坏引用降级且导出 200；重复引用记忆化；无图表文档导出与现状逐字节一致（I7）。
- `tests/test_document_public_share.py` 增补（D9）：匿名 render——token 有效且 ID 在引用集合内 200；集合外 ID / 集合内已删 / 失效或撤销 token 404。

**迁移 / 备份**：迁移幂等 + downgrade 往返；备份建 → 备 → 还 → 渲染可用。

**前端单测**：`chartRef.test.ts`（同构样例）、`ChartEmbed.test.tsx`（渲染 / 失败降级 / 主题内联）、`InsertChartModal.test.tsx`、`ChartDesignerModal.test.tsx`（选择 / 编辑 / 防抖预览 / 保存插入）、`MarkdownToolbar.test.tsx`（新按钮可选渲染）、`DocumentEditorPage.test.tsx`（插入段落级占位符）。

**e2e（前端）**：`frontend/tests/e2e/critical/document-chart-embed.spec.ts`：插入图表（选模板 → 设计器保存）→ 提交 → 发布 → 查看态内联渲染 → 导出 zip 含 `assets/chart-<id>.svg` → 游客页免登录渲染且不触碰工作区鉴权接口。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0 后端地基** | `documents_chart` 模型 + 迁移 + 注册表（3 模板 schema）+ 渲染管线（图元 / SVG / PNG 双写端）+ 模板 / CRUD / render / render-preview API + 判定层与接口层测试 + 迁移 / 备份往返 | 中（双写端一致性是核心风险，靠共享图元层 + 一致性测试兜住） |
| **P1 前端引用与设计器** | `chartRef.ts` / `ChartEmbed` / MarkdownPreview 切片 / 工具栏入口 / `InsertChartModal`（两级选择 + 已有实例）/ `ChartDesignerModal`（实时预览）+ 前端单测 + msw fixtures | 中（设计器表单按 schema 生成，模板 schema 表达力决定上限） |
| **P2 导出与游客分享** | `export/chart_refs.py` + DOCX / PDF / Markdown 归档接线 + 匿名 render 端点与 PublicSharePage 接线（D9）+ 导出测试 + e2e + 帮助文档（图表专题）+ CHANGELOG | 低-中（导出平移 ADR 0045；分享渲染复用 token 校验链路） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 渲染器放哪、用什么画 | **后端唯一渲染器**：模板 `layout` 产出共享图元，SVG 与 PNG 双写端序列化；纯标准库 + Pillow，零新增依赖 | I1 预览 / 导出同源；离线约束（#9）；Pillow 已可用（#10）；参考 HTML 证明纯 SVG 图元足够表达 | ① 前端 TS 渲染（导出侧必须再写一份 Python 绘制，双源必漂移）；② 引入 ECharts / Chart.js（离线包体积、Chrome 81 基线、无服务端渲染能力）；③ svglib 转 PDF（新增依赖且 CJK 字体链路不可控） | `services/charts/render.py` |
| D2 | 实现载体 | **documents 插件内** `services/charts/` 子模块 + `routers/charts.py`，不建独立插件 | 唯一消费方是文档正文；模型 / 权限 / 导出全在 documents 域内，独立插件只增加注册面 | 独立 `charts` 插件（单一消费方，跨插件依赖反而加复杂度）；并入 analytics（分析图表是另一套口径，混用语义） | `plugins/documents/services/charts/` |
| D3 | 两级管理的落库形态 | **类别 / 模板 = 代码注册表**（只读、随版本演进）；**用户自定义 = 实例行**（template_key + config）；不开放用户自建模板 | C2 / C3；模板即「带 schema 的渲染函数」，代码内置才能保证 I1 / I6；用户自建模板等于开放任意绘图代码，安全与兼容成本不成比例 | 用户自建模板存库（需 DSL + 沙箱校验，首期无此诉求）；类别允许用户改名（两级结构会被实例引用，改名需迁移语义） | `services/charts/registry.py`、`models.py` |
| D4 | 引用语法 | **`{{chart:<id>}}` 独占段落**，与 `{{table:…}}` 同构（段落级、数字 ID、前后端同构正则） | C5；I3；复用切片 / 插入 / 降级全套既有心智与代码路径 | Markdown 图片语法扩展 `![](chart:1)`（与站内图片 `file:` 引用纠缠，切片层耦合图片归档逻辑）；行内混排（表引用已证明段落级独占是正确边界） | `chartRef.ts`、`export/chart_refs.py` |
| D5 | 设计器实时预览 | **走 `POST /charts/render-preview`**（不落库、成员可用、前端 300ms 防抖） | I1：预览必须与最终渲染同源；本地渲染服务延迟可接受 | 前端本地即时渲染（违反 I1 双源）；预览也落库（产生垃圾实例） | `routers/charts.py`、`ChartDesignerModal.tsx` |
| D6 | 导出形态 | **md = SVG 资产归档**（zip `assets/chart-<id>.svg`）；**docx / pdf = PNG（2 倍分辨率）** 走既有图片通道 | #5 通道现成；SVG 保矢量可再编辑（对齐参考 HTML「导出 SVG 可在 Word / AI 继续编辑」）；Word / PDF 端 PNG 兼容性最稳 | 三格式全 SVG（python-docx 不支持 SVG 图片部件；reportlab 无 SVG 渲染）；全 PNG（md 失去矢量价值） | `export/chart_refs.py`、`export/images.py` |
| D7 | 失效降级 | **`[图表引用无效：图表 #N 不存在或无访问权限]`**，单段降级、导出继续 200；不区分不存在 / 无权限 | I4 / I5；与 ADR 0045 D6 / ADR 0003 I6 口径一致 | 抛 4xx（一张图被删导不出整篇）；静默丢段（读者无从判断缺失） | `chart_refs.py`、`ChartEmbed.tsx` |
| D8 | 权限 | 读（列表 / 渲染 / 引用）= 工作区成员；写（CRUD）= owner / editor；导出按发起人 | C8；图表是工作区资产，与数据表同档；不进文档修改申请链路（正文只是占位符文本，双轨写入天然覆盖） | 实例级细粒度权限（首期无诉求，表 / 视图先例也是工作区档） | `routers/charts.py` |
| D9 | 游客分享 | **免登录渲染**：新增 `GET /documents/share/{token}/charts/{id}/render`，token 有效且图表 ID 在该分享文档正文引用集合内才放行；需求方 2026-10-27 确认「分享页允许免登录可见」 | 图表随分享文档分发；引用集合白名单不给 token 命名空间外的枚举能力 | 全工作区图表匿名可渲染（游客可探测任意图表 ID，越权面过大）；维持不渲染（与需求方结论相悖） | `routers/public.py`、`PublicSharePage.tsx`、`ChartEmbed.tsx`（public 变体） |
| D10 | 渲染结果缓存 | **不落库缓存**：接口侧 ETag（`updated_at + 模板代码指纹`）304；导出即席渲染 | 实例规模小、渲染毫秒级；落缓存引入失效链（参考帮助图示的指纹重建是为「代码变更自动刷新」，ETag 已覆盖） | 存渲染快照列（失效链复杂，与 I6 演进语义冲突） | `routers/charts.py` |
| D11 | 图注动态 token | **渲染期求值**：`{cagr}` 等有限 token 白名单，`layout` 计算后替换；未知 token 原样保留 | 对齐参考 HTML 的图注联动；白名单防模板注入 | 完整模板引擎（图注是短文案，收益不成比例） | `render.py` |
| D12 | 实例删除语义 | **物理删除 + 引用降级**，无回收站 | 与表 / 视图删除先例一致；引用降级已有 I5 兜底 | 软删除（documents 文档树有回收站是因为树结构，实例是平铺资产，无此结构诉求） | `routers/charts.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：文档获得「数据 + 模板 → 图形」的表达能力，参考 HTML 的规划类图表（趋势 / 构成 / 目标对比）可全流程在平台内制作、复用与分发；预览 / 导出同源，杜绝「网页好看、导出变形」；模板随代码演进，全部实例自动获得修复与增强（I6 + ETag）。
- **负向**：渲染管线（图元层 + 双写端）是新的自研复杂度；新增一张表、一组 CRUD 端点与一个设计器弹窗，前端表单按 schema 生成的通用性有限（首批 3 模板 schema 人工对齐）；导出链路再增一段解释器。
- **风险与缓解**：双写端视觉漂移 → 共享图元层 + 一致性测试（同批图元同文本集合）；模板 schema 表达力不足 → schema 版本化字段预留，首期锁定 3 模板；游客匿名面扩大 → D9 白名单（仅渲染该文档引用的图表）+ 复用 ADR 0017 token 校验链路；实例被删后文档信息缺失 → 降级占位文字显式可见，不静默。

## 行业对照（可选）

无。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 插入入口位置 | `MarkdownToolbar` 可选回调 | 「插入图表」按 ADR 0042 模式追加，不改既有按钮 | ADR 0042 |
| 导出占位符解释 | `export/table_refs.py` 范式 | `chart_refs.py` 平移其「解释器 + 记忆化 + 降级」结构 | ADR 0045 |
| 服务端 SVG 先例 | `help/services/figures/` | SVG 生成与前端内联清洗复用该链路（含主题 token 跟随） | ADR 0030 |
| 离线依赖边界 | `pyproject.toml` | 渲染零新增依赖（Pillow 为 reportlab 既有间接依赖） | ADR 0008 |
| Chrome 81 基线 | `frontend/src/compat/` | 渲染产物只用基线内 SVG / DOM 特性 | ADR 0026 |
| 游客只读边界 | 公开分享路由 | 图表免登录渲染（D9）：token 有效 + 正文引用集合白名单，否则 404 降级占位 | ADR 0017 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 后端地基 | 已落地 | `src/cndb/plugins/documents/models.py`、`src/cndb/alembic/versions/e0f1a2b3c4d5_add_documents_chart.py`、`src/cndb/plugins/documents/services/charts/registry.py`、`src/cndb/plugins/documents/services/charts/render.py`、`src/cndb/plugins/documents/services/charts/svg.py`、`src/cndb/plugins/documents/services/charts/raster.py`、`src/cndb/plugins/documents/routers/charts.py`、`src/cndb/plugins/documents/schemas/__init__.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/workspaces/routers/workspaces.py` | `tests/test_documents_charts_registry.py`、`tests/test_documents_charts_render.py`、`tests/test_documents_charts_api.py`、`tests/test_documents_charts_migration.py`、`tests/test_documents_charts_backup.py` | `dd6d6e5c` |
| P1 前端引用与设计器 | 已落地 | `frontend/src/api/charts.ts`、`frontend/src/components/Document/chartRef.ts`、`frontend/src/components/Document/ChartEmbed.tsx`、`frontend/src/components/Document/MarkdownPreview.tsx`、`frontend/src/components/Document/MarkdownToolbar.tsx`、`frontend/src/pages/documents/InsertChartModal.tsx`、`frontend/src/pages/documents/ChartDesignerModal.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/test/msw.ts` | `frontend/src/components/Document/chartRef.test.ts`、`frontend/src/components/Document/ChartEmbed.test.tsx`、`frontend/src/components/Document/MarkdownToolbar.test.tsx`、`frontend/src/pages/documents/InsertChartModal.test.tsx`、`frontend/src/pages/documents/ChartDesignerModal.test.tsx`、`frontend/src/pages/documents/DocumentEditorPage.test.tsx` | `dea91e46` |
| P2 导出与游客分享 | 已落地 | `src/cndb/plugins/documents/services/export/chart_refs.py`、`src/cndb/plugins/documents/services/export/__init__.py`、`src/cndb/plugins/documents/services/export/docx.py`、`src/cndb/plugins/documents/services/export/pdf.py`、`src/cndb/plugins/documents/services/charts/__init__.py`、`src/cndb/plugins/documents/routers/public.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/routers/charts.py`、`frontend/src/api/publicShare.ts`、`frontend/src/components/Document/ChartEmbed.tsx`、`frontend/src/components/Document/chartRef.ts`、`frontend/src/components/Document/MarkdownPreview.tsx`、`frontend/src/pages/public/PublicSharePage.tsx`、`frontend/src/pages/help/content/tutorials.tsx` | `tests/test_document_export_chart_refs.py`、`tests/test_document_public_share.py`、`frontend/src/components/Document/chartRef.test.ts`、`frontend/src/components/Document/ChartEmbed.test.tsx`、`frontend/tests/e2e/critical/document-chart-embed.spec.ts` | `358864b8` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0 / P1 / P2 全部落地（commit `dd6d6e5c` / `dea91e46` / `358864b8`）；待人工确认 `Status` 是否改 `Implemented`
- 已完成：模型 + 迁移 e0f1a2b3c4d5（幂等 + downgrade）、两级注册表（3 类 × 3 模板含默认配置）、渲染管线（图元层 + SVG/PNG 双写端 + 空行回退默认）、实例 API（预览不落库 / ETag 304 / 模板下线降级）、备份 v8（导出 charts 键 + `_import_charts` 严格校验跳过记错误）；前端 chartRef 切片解析（与 table 语法互不干扰）、ChartEmbed 内联渲染（ETag 304 模块级复用 + sanitizeSvg + 失败单段降级）、MarkdownPreview 切 chart 段、工具栏「插入图表」入口、InsertChartModal 两级模板浏览与已有实例列表、ChartDesignerModal 按模板 schema 生成表单 + 300ms 防抖实时预览、编辑器接线；P2 —— 导出解释器 `export/chart_refs.py`（与前端同构解析 + `(chart_id)` 记忆化 + 降级文本）、DOCX / PDF 渲 PNG 2x 走既有图片通道、Markdown 改写 `assets/chart-<id>.svg` 并入归档（顺序「图表 → 表格 → 图片」，与 ADR 0045 叠加无占位符残留）、游客免登录渲染端点（token 有效 + 正文引用集合白名单，密码分享免密渲染）、ChartEmbed `shareToken` 匿名模式 + PublicSharePage 接线（`chartsOnly` 保持数据表引用不渲染）、帮助文档「插入图表」条目、CHANGELOG 全期条目
- 下一步：无（全期落地；`Status` 改 `Implemented` 属人工卡点，待确认）
- 已知坑：`chartRef.ts` 与 `chart_refs.py` 的解析样例要同一批；Markdown 归档顺序须「图表改写 → 表格改写 → 归档」与 ADR 0045 叠加时保持无占位符残留；`require_valid_config` 抛 `BadRequestError`（不是 `BadRequestTemplateError`），备份导入捕获前者；`resolve_color` 对 3 位短 hex 不转大写；归一把 actualCount 钳制到有效行数；ChartEmbed 的 ETag 缓存是模块级 Map（跨用例持续），单测各用例须用不同 chartId 规避 304 串扰；antd 双汉字按钮自动插空格，测试断言用 `/^取\s*消$/`；e2e 跑前须 `pnpm build` 重建 `src/cndb/static`，8000 端口被其它项目占用时用 `E2E_PORT=8010` 外部起服务器 + 临时 playwright config（`webServer: undefined`）
- 最近一次全绿：`make check-docs` + `make check-fast` + `make test`（5725 passed / 3 skipped）+ e2e `document-chart-embed.spec.ts`（两次复跑稳定）于 P2 提交时
