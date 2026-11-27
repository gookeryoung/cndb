# ADR 0185: 内容模板内置库（分类 → 模板两级，代码常量只读，首批「科研项目管理」）

Status: Implemented
Date: 2026-11-27
Related: `src/cndb/plugins/documents/services/content_builtins.py`、`src/cndb/plugins/documents/services/content_templates.py`、`src/cndb/plugins/documents/routers/content_templates.py`、`src/cndb/plugins/documents/models.py`、`frontend/src/pages/documents/ContentTemplatePanel.tsx`、`frontend/src/pages/documents/DocumentsPage.tsx`、`frontend/src/api/contentTemplates.ts`、`docs/requirements/0185-content-template-builtin-library.md`、`docs/adr/0152-document-export-templates.md`、`docs/adr/0177-document-template-integration.md`
需求卡片: `docs/requirements/0185-content-template-builtin-library.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号，本表只补「设计怎么落地」：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「增加内置模板」 | 内置库 = 后端代码常量（D1）：不进 `documents_contenttemplate`、不新增迁移、不进备份包；只读，无写端点。`ContentTemplate` 模型零改动 |
| C2 | 「两级（分类-模板）」 | `BUILTIN_CONTENT_CATEGORIES`（分类数组，含 key / name / description / sort_order）与每个分类下的模板数组；顺序由常量与 `sort_order` 决定（D2），前端只按接口顺序渲染 |
| C3 | 「以科研项目管理为例」 | 首批仅一个分类 `research-pm`「科研项目管理」+ 6 个模板，key / 名称 / 图标 / 绑定导出模板 / 正文骨架见需求卡片附录 A（D3）；正文常量与分类同文件 |
| C4 | 内置可用于「从模板新建」 | 前端选内置条目时直接用接口返回的 `content_markdown` + `export_template_ref` 调既有创建路径（D6）；`create_document` 契约零改动 |
| C5 | 内置只读、可另存为 | 面板对内置条目只给「另存为自定义 / 导出 JSON / 预览」；「另存为」复用 `POST /document-content-templates`，名称默认 `原名（自定义）` 并递增去重（D5） |
| C6 | 自定义能力不变 | 自定义模板的模型、端点、`{items,total}`、`PUT`+`PATCH`、副本、导入导出、拖拽、备份逐项不变（D7 / I1） |
| C7 | 文档与门禁 | 同轮补测与文档（D9、测试清单）；同步修订 `CONTEXT.md`、`docs/USER_DOC_MAP.md`、帮助教程与 ADR 0177 I1 的「无内置行」表述 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `ContentTemplate` 只有工作区行，无分类 / 来源列 | `src/cndb/plugins/documents/models.py:480` | 内置若入库需加列 / 迁移 / 每工作区播种，且与「名称工作区内唯一」语义打架 | 确认：内置不入库（C1） |
| 2 | 列表端点只返回自定义行，`{items, total}` | `src/cndb/plugins/documents/routers/content_templates.py:47`、`services/content_templates.py:36` | 内置若混进 `items`，`id` 会从 `int` 变字符串，破坏既有前端与测试 | 确认：新增独立只读端点（D4） |
| 3 | 服务层 `_serialize` 输出数字 `id`，`_get` 按数字 id 取 | `services/content_templates.py:170` | 内置不能复用 `_get` / CRUD 路径 | 确认：内置走独立只读函数 |
| 4 | 前端面板左清单平铺自定义行，选中态 `selectedId: number` | `frontend/src/pages/documents/ContentTemplatePanel.tsx:88` | 内置无数字 id，选中态需改为 ref | 确认：`selectedRef` 取代 `selectedId`（D6） |
| 5 | 「从模板新建」选择器只拉自定义列表，平铺渲染 | `frontend/src/pages/documents/DocumentsPage.tsx:1660` | 内置不可选；且无分组 | 确认：选择器两级分组（D6） |
| 6 | 备份 `content_templates[]` 只序列化 DB 行 | `src/cndb/plugins/workspaces/services/workspace_backup.py:664` | 内置入库会污染备份；常量库天然不受影响 | 确认：零改动（I1） |
| 7 | 导出模板内置 6 套为代码常量、`builtin:<key>` 引用 | `src/cndb/plugins/documents/services/export/templates.py:578` | 可沿用同一「内置只读 + 代码常量」范式与 ref 前缀 | 确认：范式复用（D1 / D2） |
| 8 | ADR 0177 I1 / CONTEXT 写「内容模板无内置行、无默认锚点」 | `docs/adr/0177-document-template-integration.md:51`、`CONTEXT.md` 内容模板行 | 新增内置库后该句字面易被误读为「不能有内置」 | 新增：修订表述（无内置**行**仍成立，新增只读**库**） |

**核心缺陷（需求要补的）**：新工作区的内容模板是空清单，「从模板新建」必须先自己写一套骨架；而导出模板早已有只读预设。内容模板缺少**随应用提供、带领域知识、按分类组织**的起步库。

设计目标（不变量）：

- **I1 内置只读且不入库**：`documents_contenttemplate` 只存自定义行；内置库由代码常量提供，无写端点、无迁移、无备份字段；备份 / 恢复往返与既有字段逐项不变。「无内置行 / 无默认锚点」继续成立（内置库不产生默认模板）。
- **I2 两级结构稳定**：分类 → 模板，两级各有稳定 `key` 与 `sort_order`；同一 key 全库唯一（分类内不得重复、跨分类也不得重复模板 key）；前端不重排，接口顺序即展示顺序。
- **I3 引用格式唯一**：内置内容模板一律用 `builtin:<key>`；该前缀与导出模板 ref 前缀相同，但两边 key 集合不得有交集（守卫测试），避免 `/documents/templates` 与内容模板 ref 互相误解析。
- **I4 内置正文可移植**：正文不得含 `{{table:…}}`、`[[双链]]`、跨工作区 / 文档 / 用户 id 等动态引用；允许 `- [ ]` 与 `（填写）` 占位；保证任意工作区、任意时点新建都不产生悬空引用。

> I1–I4 的 H27 登记结论（2026-11-27 人工确认）：**I4 已登记为 H71**（`docs/CONSTRAINTS.md` 设计与前端组，来源 `ADR 0185 I4`），校验 `make test`——新增内置模板时必须满足「正文只含纯 Markdown，禁 `{{table:…}}` / `[[双链]]` / `/w/` / `documents?`」，由 `tests/test_documents_content_templates.py::TestBuiltinContentLibrary::test_content_is_portable` 断言。I1 / I2 / I3 不予登记：它们是单测直接覆盖的插件内实现约束（不入库 / key 全局唯一且有序 / ref 前缀与导出模板 key 不重叠），不构成跨需求长期口径。

## Decision

### 1. 数据模型

**不改数据模型、不加迁移**。内置库为代码常量：

```
src/cndb/plugins/documents/services/content/builtin_templates.py
    BuiltinContentTemplate(category, key, name, description, icon, sort_order,
                           export_template_ref, content_markdown)
    BUILTIN_CONTENT_CATEGORIES: tuple[BuiltinContentCategory, ...]
    BUILTIN_CONTENT_TEMPLATES: dict[str, BuiltinContentTemplate]   # key → 模板
    DEFAULT? 无（不提供默认内容模板，I1）
```

- `ref` 由 `builtin:` + key 推导（`builtin_content_ref(key)`），常量里不重复存 ref。
- 分类常量 `BuiltinContentCategory(key, name, description, sort_order)`；模板常量带 `category` 键，可校验归属。
- 正文常量集中在同文件（6 条约 20–30KB），不进前端 bundle。

### 2. 判定算法（唯一入口）

只读访问唯一入口（`services/content_templates.py`）：

```python
def list_builtin_content_templates() -> dict[str, Any]:
    """返回 {'categories': [...]}；分类与模板都已按 sort_order 排序并校验 I2/I4。"""

def builtin_content_template(key: str) -> BuiltinContentTemplate | None:
    """按 key 取内置模板（供测试 / 未来引用解析；端点一期不暴露单条）。"""
```

调用方：`routers/content_templates.py` 的只读端点；前端不自行拼装正文。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{workspace_id}/document-content-templates` | 不变（仍只返回自定义行与 `total`） |
| `GET /{workspace_id}/document-content-templates/builtin` | **新增**（成员可读）：`{"categories": [{"key","name","description","sort_order","templates":[{"ref","key","name","description","icon","sort_order","export_template_ref","content_markdown"}]}]}` |
| `POST/PUT/PATCH/DELETE` 全部既有端点 | 不变；内置无写端点 |

实现注意：

- `/builtin` 路由必须声明在 `/{template_id}` **之前**，否则 `builtin` 会被当成 `int` 解析成 422（回归用例覆盖路由遮蔽）。
- 权限复用 `_require_member`（成员可读），与自定义列表同口径（H64）；无写权限概念。
- 响应内嵌正文（不分页、不单条），一次请求完成面板与选择器渲染，避免 N+1。

### 4. 边界与例外

1. **名称冲突**：自定义模板名称唯一只约束 DB 行，**允许**与内置同名；前端用「内置 / 自定义」徽标区分，「另存为」默认 `原名（自定义）`，冲突时递增 `原名（自定义 2）…`。
2. **导出 / 导入**：内置可导出为 `kind=cndb-content-template` JSON（只含名称 / 说明 / 图标 / 正文 / 绑定）；导入后是普通自定义模板，不保留「内置」身份。
3. **另存为的绑定**：复制内置的 `export_template_ref`（可能为 `builtin:official` 等）；自定义模板保存时既有的 `validate_export_template_ref` 校验照旧，非法则 400。
4. **删除导出模板 / 内置 key 变更**：内置正文不引用其他资源，无悬空问题；导出模板内置 key 若未来改名，按 ADR 0152 / 0177 的绑定回落口径处理，本 ADR 不新增例外。
5. **未来新增分类**：只需追加常量与正文；接口与前端无需改动。分类 / 模板 key 一经发布不改名、不复用（同 H8 精神）。

### 5. 迁移

无（零迁移、零备份字段）。回归断言：备份导出 `content_templates[]` 与内置库无交集；恢复不因内置库改变。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/contentTemplates.ts` | 新增 `BuiltinContentTemplate` / `BuiltinContentCategory` / `BuiltinContentLibrary` 类型与 `contentTemplateApi.listBuiltin(wid)`；既有类型不动 |
| 面板 | `frontend/src/pages/documents/ContentTemplatePanel.tsx` | 左清单改两组：「内置模板」按分类折叠分组（只读，带「内置」徽标）与「自定义模板」（既有平铺 + 拖拽）；选中态由 `selectedId: number` 改为 `selectedRef: string`（`builtin:<key>` / `custom:<id>`）；内置详情只读展示（元数据 + Markdown 预览 + 绑定说明），动作仅「另存为自定义 / 导出 JSON」；计数 = 内置 + 自定义；空态口径改为「自定义模板为空」 |
| 选择器 | `frontend/src/pages/documents/DocumentsPage.tsx` | 「从模板新建」弹层：先按内置分类分组，再列「我的模板」；搜索同时过滤两组；选中内置时以接口返回正文 + `export_template_ref` 调既有创建；空态判断改为「内置 + 自定义都为 0」（内置常非空，引导语自然不再出现） |
| 样式 | `frontend/src/index.css` | 分组标题 / 徽标沿用既有 token 与 1px 口径（H24 / H25 / H29）；不新增主题变量 |
| 帮助 | `frontend/src/pages/help/content/tutorials.tsx` | 「内容模板」小节补：内置库（分类 → 模板）、只读、另存为、从内置新建 |

### 7. 测试清单

**常量层（单测）**：

- 分类与模板 key 唯一（跨分类也不重复）；`category` 归属存在；`sort_order` 决定顺序。
- `ref` 前缀 `builtin:` 且与 `BUILTIN_TEMPLATES`（导出模板）key 集合无交集（I3）。
- 6 个内置模板正文非空、以 `##` 起、无一级标题；不含 `{{table:` / `[[` / `/w/` / `documents?` 等动态引用（I4）。
- 首批模板章节标题断言（每模板至少 3 个关键 H2）。

**接口层**：

- `GET /builtin` 成员 200，`categories` 结构 / 顺序 / 正文与常量一致；非成员按既有门控拒绝。
- `/builtin` 不被 `/{template_id}` 遮蔽（不返回 422）。
- 自定义列表端点载荷与计数不变（内置不出现在 `items` / `total`）。
- 创建 / 更新 / 删除对内置 key 无副作用（无对应端点；`GET /{id}` 用 `builtin:xx` 时按非法 id 处理）。

**迁移 / 备份**：无迁移；备份导出不含内置条目、既有备份往返用例零改动通过。

**前端单测**：

- API 客户端调用新端点；面板分组渲染（分类标题 + 内置徽标）、内置只读（无保存 / 删除 / 副本）、「另存为」调用 create 且名称去重、内置可导出 JSON、预览只读。
- 选择器分组渲染、搜索过滤两组、选内置后创建请求的 `content` / `export_template_ref` 正确。
- 自定义能力回归：既有 `ContentTemplatePanel.test.tsx` / `DocumentsPageContentTemplate.test.tsx` 逐项通过。

**e2e（前端）**：`critical/document-template-integration.spec.ts` 追加或新增用例——内容模板页可见「科研项目管理」分类 → 选内置「项目周报」→「从模板新建」→ 新建文档正文含「本周进展」→ 另存为后出现同名「（自定义）」条目且可编辑。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 后端：`builtin_templates.py` 常量（分类 + 6 套正文）+ 只读服务入口 + `GET .../builtin` + 常量 / 接口测试 | 低（纯新增只读面） |
| **P1** | 前端：API 类型、面板分组 / 只读 / 另存为、`selectedRef` 改造 + 面板单测 | 中（选中态与既有自定义交互回归） |
| **P2** | 前端选择器两级分组 + e2e + 文档回填（`CONTEXT.md` / `USER_DOC_MAP` / 帮助 / ADR 0177 I1 表述） | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 内置库载体 | 后端代码常量，不入库、不迁移、不进备份 | 只读且全工作区一致；沿用 ADR 0152 内置导出模板范式；避免每工作区播种与「名称唯一」冲突 | ① 入库 + `is_builtin` 列：需迁移 / 播种 / 备份排除，且用户可删可改要额外守卫；② 前端常量：正文进 bundle、无法被 API 复用，H31 / H32 预算风险 | `services/content/builtin_templates.py` |
| D2 | 两级结构与 ref | 分类常量 + 模板常量；`ref = builtin:<key>`，key 扁平且全局唯一，分类只是元数据 | 模板移动到别的分类不影响引用；与导出模板 `builtin:<key>` 同形 | `builtin:<category>/<key>`：分类进入引用后，分类调整即断引用 | 同上 |
| D3 | 首批内置范围 | 仅一个分类 `research-pm`「科研项目管理」，6 个模板（附录 A） | 需求明确以该领域为例；6 条覆盖立项 → 执行 → 结题 | 一次铺多个分类：正文质量与评审成本不可控，先以一个领域验证结构 | 同上 |
| D4 | 内置如何暴露给前端 | 新增只读端点 `GET .../builtin`，自定义列表端点不变 | 保持 `id: int` 契约与既有测试；内置与自定义来源清晰 | 混入列表 `items` + `source` 字段：`id` 类型必须变字符串，破坏既有前端 / 测试；`?include_builtin=` 参数：两套载荷形状，前端分支更多 | `routers/content_templates.py` |
| D5 | 只读出口 | 内置仅「另存为自定义 / 导出 JSON / 预览」；另存为复用 create，名称默认 `原名（自定义）` 并递增 | 与导出模板「内置只读 + 另存为」一致；不给用户留无法保存的编辑态 | 允许「编辑内置」（改常量不改库）：无法持久化；复制为同名（不加后缀）：与内置同名易混淆 | `ContentTemplatePanel.tsx` |
| D6 | 前端选中态与正文来源 | `selectedRef`（`builtin:<key>` / `custom:<id>`）；正文一律来自接口，不在前端拼装 | 一套选中语义同时容纳两种来源；正文只维护一份 | 继续用数字 id + 负数伪 id：与 DB id 空间混淆，易写出越界分支 | 面板 / 选择器 / `contentTemplates.ts` |
| D7 | 自定义模板是否加分类 / 内置标记 | 不加，保持平铺与既有字段 | C6 能力不变；分类只对内置有意义 | 给自定义加 `category` 列：迁移 + UI + 备份全链路，需求未要求 | `models.py`（不改） |
| D8 | 同名策略 | 允许自定义与内置同名，来源徽标区分；另存为自动加「（自定义）」 | DB 唯一键只对自定义行生效；改名内置常量不可行 | 禁止同名：需在 create 校验常量，且用户无法复用常见名称，体验差 | `content_templates.py` |
| D9 | 正文约束 | 纯 Markdown + `（填写）` / `- [ ]`；禁动态引用与工作区 id | 任意工作区新建都不产生悬空链接 / 表格引用（I4） | 允许 `{{table:…}}`：新工作区无该表，创建即断链 | `builtin_templates.py`、测试 |
| D10 | 落库与门禁 | 二期各一提交；P2 收尾回填 `CONTEXT` / `USER_DOC_MAP` / 帮助与 ADR 0177 表述 | H2 / H5 / H12 | 三期混一个提交：评审与回滚粒度差 | — |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：新工作区「从模板新建」立即有领域化骨架；分类结构可平滑扩到其他领域；只读常量库零迁移、零备份成本；正文单一来源（后端），前端 bundle 不增。
- **负向**：内置正文改动要发版（不能在工作区里改）；分类 / 模板 key 与正文质量成为发布内容；面板选中态从 id 改 ref，有一轮回归成本。
- **风险与缓解**：内置与自定义同名会造成清单视觉重复 → 来源徽标 + 另存为后缀；正文含动态引用会造成悬空 → I4 断言；`/builtin` 路由被 `/{template_id}` 遮蔽 → 路由顺序回归用例。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 内置只读范式 | 导出模板常量 | 内置不入库、`builtin:<key>`、可另存为自定义 | ADR 0152 |
| 内容模板模型 | `documents_contenttemplate` | 表结构 / 名称唯一 / 绑定 / 备份口径不变 | 需求 0169、ADR 0177 |
| 「无内置行 / 无默认锚点」 | 内容模板不变量 | 仍成立（内置库不落行、不产生默认）；表述按本卡 C7 修订 | ADR 0177 I1 |
| 模板页单页双区 | `/documents/templates?kind=` | 入口与分区开关不变 | ADR 0177 D4 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/documents/services/content_builtins.py`、`src/cndb/plugins/documents/services/content_templates.py`、`src/cndb/plugins/documents/routers/content_templates.py` | `tests/test_documents_content_templates.py` | `0ae4205e` |
| P1 | 已落地 | `frontend/src/pages/documents/ContentTemplatePanel.tsx`、`frontend/src/api/contentTemplates.ts` | `frontend/src/pages/documents/ContentTemplatePanel.test.tsx` | `0ae4205e` |
| P2 | 已落地 | `frontend/src/pages/documents/DocumentsPage.tsx`、`frontend/src/pages/help/content/tutorials.tsx` | `frontend/src/pages/documents/DocumentsPageContentTemplate.test.tsx`、`frontend/tests/e2e/critical/document-template-integration.spec.ts` | `0ae4205e` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：已落地并提交（`0ae4205e`），`Status` 经人工确认置 `Implemented`（2026-11-27）
- 已完成：P0 后端常量 `services/content_builtins.py`（分类 `research-pm` + 6 套正文）+ 只读入口 `list_builtin_content_templates` + `GET .../document-content-templates/builtin`（声明在 `/{template_id}` 之前）+ 常量 / 接口 / 备份回归测试；P1 前端 API 类型与 `contentTemplateApi.listBuiltin`、面板两组清单（内置按分类折叠 / 自定义平铺）、`selectedRef` 选中态、只读详情（另存为 / 导出 / 预览）与另存为名称递增；P2 选择器两级分组 + 搜索过滤两组 + 空态口径改「内置 + 自定义都为 0」、e2e 用例、`CONTEXT.md` / `docs/USER_DOC_MAP.md` / 帮助教程 / ADR 0177 I1 表述 / `CHANGELOG.md`
- 下一步：推送到远端（`make push`，H4）；如需把内置库扩展到第二个领域，只追加常量与正文（受 H71 约束），接口与前端无需改动
- 已知坑：`GET .../builtin` 必须声明在 `/{template_id}` 之前（否则 `builtin` 被当 int 解析 422，回归用例已覆盖）；面板选中态是 `builtin:<key>` / `custom:<id>` 两套 ref，别再退回数字 id；内置正文禁动态引用（I4，测试 `test_content_is_portable` 断言）；面板默认选中要求「两个查询都成功」后才决策，否则选中态会随返回顺序抖动
- 最近一次全绿：`make check-fast` / `make flow`（7852 passed / 17 skipped）/ `make check-frontend`（核心集合 lines 97.66% / branches 100%，全局 84.02%）/ `pnpm test`（293 文件 / 3651 passed）/ e2e `document-template-integration.spec.ts` 3 passed / `make frontend-build`（预算内）@ 2026-11-27
