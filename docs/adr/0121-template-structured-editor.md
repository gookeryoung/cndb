# ADR 0121: 工作区模板结构化编辑模式（结构化为主 + JSON 高级页签）

Status: Accepted
Date: 2026-11-07
Related: `frontend/src/pages/templates/TemplateEditorModal.tsx`、`frontend/src/pages/templates/TemplatesPage.tsx`、`frontend/src/pages/templates/TemplatePreviewPanel.tsx`、`frontend/src/pages/templates/templateSpec.ts`、`frontend/src/pages/fields/FieldManager/FieldConfigPanel.tsx`、`frontend/src/pages/fields/FieldManager/typeConfigPanel.tsx`、`frontend/src/api/types/templates.ts`、`src/cndb/plugins/workspaces/services/templates/spec.py`、`src/cndb/plugins/workspaces/routers/templates.py`、`src/cndb/plugins/workspaces/schemas/templates.py`、`docs/adr/0094-workspace-configurable-templates.md`
需求卡片: `docs/requirements/0121-template-structured-editor.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「编辑全部的JSON非常难」 | 模板编辑默认进入结构化工作台；JSON 仅作为高级页签，不再承担日常编辑 |
| C2 | 「编辑模板」 | 单一 `TemplateDraft` 覆盖元信息 + `forms[].fields[] / flow` + `documents[]` + `stages[]` + `flows[]`，序列化后仍交给 `normalize_spec` |
| C3 | 「结合当前设计」 | 模板中心继续作为入口；编辑器复用 `TemplatePreviewPanel`、字段配置组件、`ModuleCheckCards` 与 `--cn-*` 标尺；只读详情抽成 `TemplateDetail` 共用 |
| C4 | 「更科学的编辑模式」 | 全屏抽屉（桌面三栏 / 窄屏单列），懒加载；关闭时拦截未保存修改 |
| C5 | 「编辑全部的JSON非常难」 | JSON 高级页签显式「应用」；解析 / 校验失败保持结构化状态不变 |
| C6 | 「更科学的编辑模式」 | 本地即时校验 + 服务端无状态 `validate`（复用 `normalize_spec`）；错误带 `path` 可定位 |
| C7 | 「更科学的编辑模式」 | key 自动生成且改名稳定；引用用选择器；删除被引用对象确认后级联清理引用 |
| C8 | 「工作区模板」 | 保存链路、spec 契约、数据库、导入导出格式全部不变；仅新增只读校验端点 |
| C9 | （工程口径） | 草稿单测 + 组件测试 + 接口测试 + e2e，`make flow` 全绿 |

## Context

现状逐条核对：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 编辑入口是 `width=860` 的 Modal，核心控件是 12–24 行 JSON 文本框 | `frontend/src/pages/templates/TemplateEditorModal.tsx:161`、`:186-193` | 复杂模板（多表单 / 多阶段 / 多流程）无法在弹窗内建立结构心智，字段引用只能靠肉眼核对 | 确认 C1 |
| 2 | 保存前已强制预览 diff + 影响，409 也回填预览 | `frontend/src/pages/templates/TemplateEditorModal.tsx:123-150` | 这是既有安全网，必须保留；问题只在「怎么改」而不在「怎么保存」 | 确认 C8 |
| 3 | 前端 JSON 解析只判断三大数组存在，字段级错误依赖服务端 | `frontend/src/pages/templates/templateSpec.ts:5-24` | 用户往往在保存时才看到第一条 422，且无法定位到具体字段 | 确认 C6 |
| 4 | 模板详情已有阶段 / 表单 / 流程 / 文档四个结构化页签，但定义在页面文件内且未导出 | `frontend/src/pages/templates/TemplatesPage.tsx:66-172` | 可在编辑器中复用为「结构预览」，避免再写一套只读视图 | 新增 C3 |
| 5 | 字段配置组件与真实工作区 / 数据表强绑定：`wid` / `tid` / `tables` / `config.target_table_id` | `frontend/src/pages/fields/FieldManager/FieldConfigPanel.tsx:46`、`typeConfigPanel.tsx:322` | 模板字段没有物理表 id，link / lookup 使用 `config.target_form`；直接复用会传假 id 或丢配置 | 确认 C2 / C7 |
| 6 | `TemplateSpecForm` 无 `flow`，`TemplateSpecFlow` 无 `stage`，`order` 也缺省 | `frontend/src/api/types/templates.ts:15-52` | 结构化编辑器若不补类型，序列化会丢掉后端已支持的配置 | 新增 C2 |
| 7 | 服务端只在创建 / 更新 / 预览 / 导入时调用 `normalize_spec`，没有无状态校验入口 | `src/cndb/plugins/workspaces/routers/templates.py:100-104`、`:267-346` | 新建模板无法在保存前得到权威校验结果 | 新增 C6 |
| 8 | `normalize_spec` 首次错误即抛出，错误文本形如 `forms[0].fields[1].type：未知字段类型` | `src/cndb/plugins/workspaces/services/templates/spec.py:485-507` | 可直接解析路径做定位；不要求一次性返回全部错误 | 确认 C6 |
| 9 | `target_form` 在实例化时解析为 `target_table_id` | `src/cndb/plugins/workspaces/services/templates/engine.py:73-80`、`:255-270` | 模板编辑期只能选表单 key，不能选真实表 | 确认 C7 |
| 10 | 导入 / 导出、复制均以 JSON 为交换格式 | `frontend/src/pages/templates/TemplateImportModal.tsx`、`TemplatesPage.tsx:263-274` | JSON 必须继续可读可写；高级页签与文件通道并存 | 确认 C5 / C8 |
| 11 | `@dnd-kit` 与页面方盒 / 双栏原语已具备 | `frontend/package.json`、`frontend/src/index.css` | 排序与布局无需新增依赖 | 确认 C3 / C4 |
| 12 | 当前 `TemplateEditorModal` 被 `TemplatesPage` 静态引入 | `frontend/src/pages/templates/TemplatesPage.tsx:25`、`:472-477` | 新编辑器体积更大，按 H31 必须改为按需懒加载 | 新增 C4 |

**核心缺陷（需求要补的）**：模板 spec 已经是结构化 JSON，但编辑界面只有「全量文本」一个入口；编辑成本与模板复杂度成正比，引用关系和校验结果都被推迟到保存之后。

设计目标（不变量）：

- **I1 单一草稿**：结构化视图与 JSON 页签读写同一份 `TemplateDraft`，不存在两套可变状态；JSON 应用是显式事务，失败不覆盖草稿。
- **I2 key 稳定**：实体 key 在创建时生成，改名不改 key；已在模板中的实体 key 在结构化视图中只读，保证 `template_state` 的 `form key → table id` / `doc key → doc id` 映射不破。
- **I3 服务端权威**：前端校验只负责即时提示与定位，最终以 `normalize_spec` 为准；保存前必须经过服务端校验 / 预览。
- **I4 保存链路不变**：diff / impact / `force` / 非破坏增量同步完全复用 ADR 0094，不新增第二套保存语义。
- **I5 配置不丢**：字段 `config` 内结构化编辑器未识别的键原样保留；旧模板中未展示的合法配置不因编辑其他属性而被清空。

## Decision

### 1. 数据模型

无数据库迁移，无 spec 契约变更。前端新增内存草稿模型（不落库）：

```
TemplateDraft = {
  meta: { name, description, category, modules },
  forms: [{ uid, key, name, description, fields: [DraftField], flow: DraftFormFlow }],
  documents: [{ uid, key, title, required, naming, content }],
  stages: [{ uid, key, name, description, forms: string[], documents: string[] }],
  flows: [{ uid, key, name, description, stage: string | null, steps: [DraftStep] }],
}
DraftField = { uid, name, type, required, is_unique, hidden, default_value?, config }
```

- `uid` 仅用于 React 列表 key 与定位，不进入 spec；`draftToSpec` 丢弃。
- 阶段顺序由数组顺序决定，序列化时重排为 `order = index + 1`；字段 / 流程步骤顺序同理，不暴露裸 `order` 输入。
- `modules` 复用 `ModuleCheckCards` 与 `normalizeModules`。

### 2. 判定算法（唯一入口）

前端纯函数（`frontend/src/pages/templates/templateDraft.ts`）：

- `draftFromTemplate(template)` / `draftFromSpec(spec)`：把已保存 spec 转为草稿，保留字段 `config` 原值。
- `draftToSpec(draft)`：唯一序列化入口，按数组顺序生成 `order`，剔除 `uid`。
- `validateDraft(draft)`：返回 `{ path, scope, uid, message, severity }[]`；覆盖必填、key / 名称重复、字段类型白名单、阶段顺序、表单 / 文档 / 流程引用存在性、孤儿表单 / 文档。前端校验只用于即时提示，不替代服务端。
- `applyJsonToDraft(text, draft)`：先 `JSON.parse` 再 `draftFromSpec` 并 `validateDraft`；任一步失败返回错误且**不修改**当前草稿。
- `collectFieldTypeIssues`：字段类型取自 `FIELD_TYPE_OPTIONS`（`frontend/src/utils/fieldTypeMeta.ts`），与后端 `default_registry` 对齐。

服务端（复用既有入口，不复制规则）：

- `POST /api/v1/workspace-templates/validate` 内部只调用 `normalize_spec` + `spec_counts`；成功返回归一化 spec 与规模，失败返回 422。
- 422 响应体为 `{ path, message }`：路由层把 `TemplateSpecError` 文本按首个「：」拆为路径与消息，供前端定位；既有创建 / 更新 / 预览端点响应格式不变。
- `preview`、`diff_specs`、`preview_impact`、`apply_spec_to_workspace` 均不改。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /api/v1/workspace-templates/validate` | 新增：请求 `{ spec }`，成功 `{ spec, counts }`，非法 422 `{ path, message }`；只读、不落库、不要求模板 id |
| 其余模板 / 生命周期端点 | 无变更 |

### 4. 边界与例外

1. **草稿允许不完整**：新建时可先有阶段没有表单，或表单字段未填完；检查面板列出问题，保存与预览按钮在有错误时禁用。
2. **key 策略**：新建实体自动生成 `form_1` / `stage_1` / `doc_1` / `flow_1` 形式；已保存实体的 key 在结构化视图只读。JSON 高级页签仍可改 key，但预览会显示为「移除 + 新增」，并提示旧表 / 旧文档映射会断开。
3. **重命名字段**：允许修改字段名，但提示「等于移除旧字段 + 新增字段，旧列与数据保留、新列无历史值」；diff 预览仍是最终依据。
4. **删除被引用实体**：删除表单 / 文档 / 阶段时先确认，再级联清理 `stages[].forms/documents`、`flows[].steps[].form/documents`、`flows[].stage` 中的引用；不产生孤儿。
5. **最后一个表单 / 文档**：允许在草稿中删到零，但 `normalize_spec` 要求至少一个表单或文档，检查面板据此阻断保存。
6. **阶段顺序**：拖拽后自动重排 1..n；不提供重复 order 的输入入口。当前阶段被删仍由服务端标 breaking，前端只展示预览。
7. **字段类型变更**：结构化编辑器允许切换类型，但保留「需人工迁移」提示；不触发 DDL。
8. **表单流程配置**：`list_fields` / `search_fields` 只能选当前表单字段；`form_groups` / `detail_groups` 未分组字段由服务端补「其他信息」，编辑器显示该提示但不写入冗余空组。
9. **JSON 高级页签**：离开页签时若未「应用」则丢弃输入并提示；应用成功后结构树、检查面板与预览全部失效重算。
10. **窄屏**：≤767.98px 时目录、编辑、检查改为单列分段切换；不隐藏任何编辑能力。

### 5. 迁移

无。spec 结构、数据库表、revision、导入导出格式均不变；新增端点不读写数据库。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 页面 | `frontend/src/pages/templates/TemplatesPage.tsx` | 「编辑模板」改为懒加载打开全屏抽屉；沿用复制 / 导入 / 导出 / 删除 |
| 组件 | `frontend/src/pages/templates/TemplateEditorDrawer.tsx`（新增） | 编辑器外壳：三栏布局、脏状态关闭确认、保存 / 预览 / force |
| 组件 | `frontend/src/pages/templates/TemplateOutline.tsx`（新增） | 左侧目录：概览 / 阶段 / 表单 / 文档 / 流程 / JSON，带数量与错误徽标、搜索定位 |
| 组件 | `frontend/src/pages/templates/TemplateMetaPanel.tsx`（新增） | 名称 / 说明 / 分类 / 模块（`ModuleCheckCards`） |
| 组件 | `frontend/src/pages/templates/StageEditor.tsx`（新增） | 阶段卡片、拖拽排序、表单 / 文档引用多选、阶段说明 |
| 组件 | `frontend/src/pages/templates/FormEditor.tsx`（新增） | 表单基本信息、字段表格、字段增删与排序 |
| 组件 | `frontend/src/pages/templates/TemplateFieldDrawer.tsx`（新增） | 字段编辑；非关联类型复用既有配置分区，link / lookup 用 `target_form` 选择器 |
| 组件 | `frontend/src/pages/templates/FormFlowEditor.tsx`（新增） | 列表 / 搜索字段、表单 / 详情分组、提示、默认值、操作开关、默认排序、空态文案 |
| 组件 | `frontend/src/pages/templates/DocumentRuleEditor.tsx`（新增） | 文档规则列表与编辑（标题 / 是否必需 / 命名 / 初始正文） |
| 组件 | `frontend/src/pages/templates/FlowEditor.tsx`（新增） | 端到端流程卡片、步骤增删排序、绑定表单 / 文档、审批节点说明 |
| 组件 | `frontend/src/pages/templates/TemplateJsonTab.tsx`（新增） | 高级 JSON：格式化、错误行提示、应用 / 放弃，失败不覆盖草稿 |
| 组件 | `frontend/src/pages/templates/TemplateCheckPanel.tsx`（新增） | 错误清单（点击定位）+ 复用 `TemplatePreviewPanel` 展示 diff / impact + force 勾选 |
| 组件 | `frontend/src/pages/templates/TemplateDetail.tsx`（新增） | 从 `TemplatesPage` 抽出的只读详情，供详情栏与编辑器「结构预览」共用 |
| 工具 | `frontend/src/pages/templates/templateDraft.ts`（新增） | 草稿模型、序列化、校验、JSON 应用、key 生成、错误路径映射 |
| 工具 | `frontend/src/pages/templates/templateSpec.ts` | 保留解析 / 摘要；补错误 path 与 JSON 行号提示的纯函数 |
| 类型 | `frontend/src/api/types/templates.ts` | 补 `TemplateSpecForm.flow`、`TemplateSpecFlow.stage`，新增 validate 请求 / 响应类型 |
| API | `frontend/src/api/workspaceTemplates.ts` | 新增 `validate(spec)` 调用 |
| 复用 | `frontend/src/pages/fields/FieldManager/typeConfigPanel.tsx` | 增加模板字段的关联目标适配（`target_form`），避免复制整套字段配置 UI |
| 样式 | `frontend/src/index.css` | 新增编辑器三栏 / 目录树 / 错误徽标样式，全部走 `--cn-*` 与设计标尺 |

交互结构：

```
┌ 模板编辑抽屉（全屏） ─────────────────────────────────────────────┐
│ 名称 / 分类 / 变更说明                          [检查] [保存并同步] │
├──────────────┬──────────────────────────────┬────────────────────┤
│ 目录          │ 编辑区                        │ 检查与预览          │
│ 概览          │ 当前实体结构化表单             │ 错误清单（可定位）  │
│ 阶段 (3) ⚠2   │ - 字段表格 / 拖拽排序          │ 变更 diff           │
│ 表单 (4)      │ - 引用选择器                  │ 已有数据影响         │
│ 文档 (5)      │ - 分组 / 提示 / 默认值         │ force 确认           │
│ 流程 (2)      │                              │ 结构预览（只读）     │
│ JSON（高级）  │                              │                    │
└──────────────┴──────────────────────────────┴────────────────────┘
```

### 7. 测试清单

**判定层（单测）**：

- `frontend/src/pages/templates/templateDraft.test.ts`：`spec → draft → spec` 往返不丢 `flow` / `stage` / 字段 `config`；key 生成与稳定性；阶段 / 字段 / 步骤排序重编号；重复 key / 名称、未知类型、缺失引用、孤儿表单 / 文档的 `path` 与 `uid`；删除表单 / 文档 / 阶段的引用级联；JSON 应用成功与失败不覆盖草稿；错误路径映射到目录节点。
- `frontend/src/pages/templates/templateSpec.test.ts`：保留现有解析 / 摘要用例，补 JSON 错误定位。

**组件层（前端单测）**：

- `TemplateEditorDrawer.test.tsx`：新建 / 编辑打开、脏状态关闭确认、保存前预览、breaking 勾选 force、保存成功刷新。
- `StageEditor.test.tsx` / `FormEditor.test.tsx` / `FlowEditor.test.tsx` / `FormFlowEditor.test.tsx`：新增 / 编辑 / 删除 / 排序、引用选择、删除级联确认。
- `TemplateJsonTab.test.tsx`：非法 JSON 提示、应用后切回结构化、放弃不生效。
- `TemplatesPage.test.tsx`：编辑入口打开抽屉、详情只读预览复用、导入导出不回归。

**接口层**：

- `tests/test_workspace_templates.py`：`validate` 合法 spec 返回归一化结果与 counts；非法 spec 422 且 detail 含 `path` / `message`；未登录 401；不落库、不产生 revision。

**迁移 / 备份**：无变更；现有模板与备份测试全量回归。

**e2e（前端）**：

- `frontend/tests/e2e/critical/template-structured-edit.spec.ts`：复制内置模板 → 修改元信息 → 新增阶段 / 表单字段 → 拖拽阶段顺序 → 绑定流程步骤 → 切 JSON 页签查看并应用 → 预览 diff / 影响 → 保存 → 详情栏展示新结构。另覆盖非法 JSON 与未保存关闭确认。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 草稿模型 + 抽屉骨架 + 目录导航 + 元信息 + 阶段 / 表单 / 字段基础属性 + 文档 + 流程步骤 + JSON 高级页签 + 复用既有预览保存 | 中 |
| **P1** | 字段类型专属配置适配（含 link / lookup 的 `target_form`）+ `form.flow` 结构化配置 + 引用级联 + 服务端 `validate` 端点与错误定位 | 中 |
| **P2** | 大模板可用性（目录搜索 / 折叠 / 错误跳转 / 本地草稿恢复）+ e2e + 帮助文档 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 编辑容器 | 模板中心内全屏抽屉，桌面三栏 / 窄屏单列 | 复杂模板需要空间；不新增路由与刷新态，入口上下文不丢 | 独立路由（需处理深链 / 返回 / 刷新守卫） / 加宽弹窗（空间仍不足） | `TemplateEditorDrawer.tsx` |
| D2 | 主编辑方式 | 结构化为主，JSON 为高级页签 | 直接解决「全量 JSON 难」；保留批量修改与迁移能力 | 纯 JSON（现状问题） / 纯结构化无 JSON（跨版本迁移与排障受限） | `TemplateJsonTab.tsx`、`templateDraft.ts` |
| D3 | 覆盖范围 | 全量 spec 与元信息 | 用户确认；避免半结构化后仍需改 JSON | 只做表单 / 字段（阶段与流程仍难改） / 分阶段但目标仍全量 | `frontend/src/pages/templates/` |
| D4 | 状态模型 | 单一 `TemplateDraft`；JSON 显式应用 | 防止结构化与文本双写导致覆盖；失败可回退 | 双状态实时同步（互相覆盖、难测试） | `templateDraft.ts` |
| D5 | 校验位置 | 本地即时校验 + 服务端 `validate` 权威校验 | 前端即时定位，服务端复用 `normalize_spec` 保持唯一口径 | 纯前端复制规则（易漂移） / 仅保存时校验（错误暴露太晚） | `templateDraft.ts`、`routers/templates.py` |
| D6 | key 稳定性 | 自动生成；已存实体结构化视图只读；JSON 可改但预览提示断链 | 保护 `template_state` 映射与已有工作区 | 允许随意改 key（旧表变孤儿且用户无感） / 用名称当 key（改名即断链） | `templateDraft.ts` |
| D7 | 删除引用对象 | 确认后级联清理引用，不产生孤儿；最后一个表单 / 文档阻断保存 | 与 `normalize_spec` 孤儿校验一致，减少保存失败 | 禁止删除（用户需先手动逐条解绑） / 静默删引用（风险不可见） | 阶段 / 流程 / 文档编辑器 |
| D8 | 字段配置复用 | 抽取配置适配层，普通字段复用既有分区；link / lookup 使用 `target_form` 选择器 | 避免两套字段配置 UI 与校验口径 | 复制一份模板专用字段 UI（维护双份） / 只做基础属性（复杂字段仍改 JSON） | `typeConfigPanel.tsx`、`TemplateFieldDrawer.tsx` |
| D9 | 错误定位 | 统一 `path → uid` 映射，检查面板点击跳转 | 服务端错误文本已带路径；可渐进增强 | 仅弹 toast（无法定位） | `templateDraft.ts`、`TemplateCheckPanel.tsx` |
| D10 | JSON 应用 | 显式「应用」；失败不覆盖当前草稿 | 避免边输边解析导致结构跳变 | 实时双向同步（输入中间态破坏草稿） | `TemplateJsonTab.tsx` |
| D11 | 加载方式 | 抽屉按 H31 懒加载 | 编辑器代码与字段配置体积较大，不应进模板中心首屏 | 静态引入（增大受控 chunk） | `TemplatesPage.tsx` |
| D12 | 本地草稿 | P2 用 `localStorage` 按模板 id + 版本暂存；抽屉提供「保存草稿」显式按钮（不依赖校验结果，允许保存未完成 / 有问题的大模板），保存成功清除 | 复杂模板编辑耗时长，防误关丢失；不影响服务端权威 | 不提供草稿恢复（误关即丢） | `TemplateEditorDrawer.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：复杂模板可在结构层面编辑，引用关系与错误即时可见；保存前仍保留 diff / 影响预览与非破坏保障；JSON 能力不丢失，导入导出与旧模板完全兼容。
- **负向**：前端新增约 10 个编辑器组件与草稿模型，维护面扩大；字段配置需要一层模板适配，短期内要改 `typeConfigPanel` 的耦合点。
- **风险与缓解**：结构化与 JSON 双入口可能行为不一致 → 单一草稿 + JSON 显式应用 + 两端共用纯函数；服务端首错即抛导致一次只报一条 → 前端先做本地全量检查，服务端错误仅作权威兜底；大模板渲染卡顿 → 目录折叠、按实体分区渲染、字段表格虚拟化按需引入。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 模板与保存链路 | `spec` / `normalize_spec` / `preview_impact` | 保存、diff、force、非破坏同步完全复用，不新增语义 | ADR 0094 |
| 表单流程配置 | `form.flow` | 结构化编辑器覆盖既有配置项，校验仍由 `spec.py` 统一执行 | ADR 0095 |
| 端到端流程 | `spec.flows[]` | 流程步骤编辑与阶段解耦，不改变门禁 | ADR 0097 |
| 导入导出 | `.workspace-template.json` | 文件通道与 JSON 高级页签并存，格式不变 | 需求 0120 |
| 工作区模块 | `modules` | 复用 `ModuleCheckCards` / `normalizeModules` | ADR 0080 |
| 前端视觉与性能 | `--cn-*` / H31 | 三栏布局走设计标尺；抽屉懒加载 | `docs/DESIGN_SYSTEM.md`、H29 / H31 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/templates/TemplateEditorDrawer.tsx` `frontend/src/pages/templates/templateDraft.ts` `frontend/src/pages/templates/TemplateEditorSections.tsx` `frontend/src/pages/templates/TemplateJsonTab.tsx` `frontend/src/pages/templates/TemplateCheckPanel.tsx` `frontend/src/pages/templates/TemplateDetail.tsx` | `frontend/src/pages/templates/templateDraft.test.ts` `frontend/src/pages/templates/TemplateEditorDrawer.test.tsx` `frontend/src/pages/templates/TemplatesPage.test.tsx` | 未提交 |
| P1 | 已落地 | `frontend/src/pages/templates/TemplateEditorSections.tsx` `frontend/src/api/workspaceTemplates.ts` `src/cndb/plugins/workspaces/routers/templates.py` `src/cndb/plugins/workspaces/schemas/templates.py` | `tests/test_workspace_templates.py` | 未提交 |
| P2 | 已落地 | `frontend/src/pages/templates/TemplateEditorDrawer.tsx` `frontend/src/index.css` `frontend/src/pages/help/content/tutorials.tsx` | `frontend/src/pages/templates/TemplateEditorDrawer.test.tsx` `frontend/tests/e2e/critical/template-structured-edit.spec.ts` `frontend/src/pages/help/HelpDocsPage.test.tsx` | 未提交 |

## 交接（会话结束更新）

- 当前阶段：P0 / P1 / P2 均已实现；本地 `make flow`、`pnpm vitest run src/pages/templates src/pages/help` 与结构化编辑 e2e 全绿。
- 已完成：草稿模型与唯一序列化入口 `draftToSpec`；全屏三栏抽屉（目录 / 编辑 / 检查预览）；元信息、阶段、表单与字段（含类型配置、`form.flow`）、文档、流程步骤结构化编辑；JSON 高级页签显式应用、失败保留草稿；引用级联删除；服务端无状态 `validate` 端点与 `{path, message}` 错误定位；目录按名称 / key 搜索与分组折叠；按「模板 id + 版本」把未保存草稿暂存 localStorage（打开时恢复、保存成功 / 回到初始态清除），抽屉头部提供「保存草稿」显式按钮，未通过结构校验或未填完的复杂模板也可立即暂存，关闭确认改为「放弃修改会清除本机草稿」；帮助中心「结构化编辑模板」小节；e2e `template-structured-edit.spec.ts` 覆盖新建 → 结构化新增字段 → 大纲搜索 / 无匹配 → JSON 页签确认 → 保存 → 详情展示。
- 下一步：本轮无必做项；若继续演进，可推进目录键盘导航、历史版本 diff 与跨设备草稿同步，并在改动 `TemplateEditorDrawer.tsx` 时同步 `TemplateEditorDrawer.test.tsx` 与 e2e。
- 已知坑：`normalize_spec` 首错即抛，服务端一次只回一条，前端需先跑本地全量校验；字段重命名等于删旧增新；`localStorage` 不可用时静默降级；e2e 依赖 `src/cndb/static` 最新构建（改前端后先 `pnpm build` 再跑）；`AntD Drawer width` 与 `Timeline items.children/dot`、`Alert message`、`Space direction` 仍为弃用告警（不影响门禁，后续统一迁移）。
- 最近一次全绿：`make flow`（6745 passed / 3 skipped）、`pnpm vitest run src/pages/templates src/pages/help`（62 例）、结构化编辑 e2e（chromium-authed）、`pnpm typecheck` / `pnpm lint`。
