# 需求卡片：工作区模板结构化编辑模式

- 编号：0121
- 来源 / 提出人：用户（会话 2026-11-07）
- 日期：2026-11-07
- 关联 ADR：0121（S2：前端编辑架构存在实质分叉，并新增无状态校验端点）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 工作区模板，编辑模板，对于复杂的模板，编辑全部的JSON非常难，请结合当前设计制定更科学的编辑模式。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「编辑全部的JSON非常难」 | 复杂模板的默认编辑入口改为**结构化编辑**，不再要求用户直接阅读 / 修改全量 JSON；保存前仍由服务端 `normalize_spec` 统一校验 | `frontend/src/pages/templates/` | 组件测试：不进入 JSON 页签也能完成新增阶段 / 表单 / 字段 / 文档 / 流程并保存 |
| C2 | 「编辑模板」 | 结构化编辑覆盖模板全量可编辑范围：名称 / 说明 / 分类 / 模块，以及 `spec` 的 `forms[]`（字段、类型、配置、`flow`）、`documents[]`、`stages[]`、`flows[]` | `frontend/src/pages/templates/`、`frontend/src/api/types/templates.ts` | 组件测试逐类实体新增 / 编辑 / 删除 / 排序；序列化结果通过 `normalize_spec` |
| C3 | 「结合当前设计」 | 复用模板中心双栏、`TemplatePreviewPanel` 的 diff / 影响展示、字段管理配置组件、模块选型卡片与 `--cn-*` 设计标尺；不新增第二套视觉或字段配置口径 | `TemplatesPage.tsx`、`TemplatePreviewPanel.tsx`、`pages/fields/FieldManager/`、`components/ModuleCheckCards.tsx` | 前端单测 + 设计标尺门禁（H24 / H25 / H29 / H30） |
| C4 | 「更科学的编辑模式」 | 编辑器为**全屏抽屉**（桌面三栏：目录 / 编辑 / 检查与预览；窄屏单列降级）；关闭时若有未保存修改必须二次确认；按 H31 懒加载 | `TemplateEditorDrawer.tsx`（新增）、`TemplatesPage.tsx` | 组件测试：打开 / 关闭守卫 / 窄屏布局；静态门禁校验懒加载 |
| C5 | 「编辑全部的JSON非常难」 | 保留 **JSON 高级页签**：结构化编辑为主，JSON 用于批量修改、跨版本迁移与排障；JSON 内容必须显式「应用」后才写入草稿，解析或校验失败不得覆盖当前结构化状态 | `TemplateJsonTab.tsx`（新增）、`templateDraft.ts`（新增） | 单测：合法 JSON 应用成功、非法 JSON 不改变草稿、应用后可继续结构化编辑 |
| C6 | 「更科学的编辑模式」 | 分层校验与定位：本地即时结构校验（必填、重复、引用、孤儿、顺序）+ 服务端权威校验（新增无状态 `POST /api/v1/workspace-templates/validate`，复用 `normalize_spec`）；错误返回 `path` 并可定位到具体实体 / 字段 | `templateDraft.ts`、`workspaces/routers/templates.py`、`workspaces/schemas/templates.py` | 单测：错误 path 映射；接口测试：合法 / 非法 spec、422 路径、权限 |
| C7 | 「更科学的编辑模式」 | 引用完整性：实体 key 创建后自动生成并保持稳定（改名不改 key）；阶段 / 流程 / 文档引用一律用选择器；删除被引用对象时确认并级联清理引用；不允许产生孤儿表单 / 文档 | `templateDraft.ts`、阶段 / 流程 / 文档编辑组件 | 单测：删除表单后阶段与流程引用同步清理；孤儿校验与后端一致 |
| C8 | 「工作区模板」 | 保存链路完全复用现状：`preview` 的 diff + 已有数据影响、breaking 需 `force`、非破坏增量同步；**不改变 spec JSON 契约、不新增迁移、不改变导入导出格式** | `routers/templates.py`、`services/templates/` | 现有 `tests/test_workspace_templates.py` 全绿；新增校验端点测试；迁移零改动 |
| C9 | （工程口径） | 测试与实现同轮：草稿模型单测、编辑器组件测试、校验端点接口测试、模板编辑 e2e；更新 `CONTEXT.md` / `CHANGELOG.md` / ADR 交接 | `frontend/src/pages/templates/`、`tests/test_workspace_templates.py`、`frontend/tests/e2e/` | `make flow` 全绿 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 模板编辑器为 860px 弹窗 + 全量 JSON 文本框 | `frontend/src/pages/templates/TemplateEditorModal.tsx:161`、`:186-193` | 复杂模板空间不足，JSON 手写成本高 |
| 2 | 保存前强制预览 diff / 影响 | `frontend/src/pages/templates/TemplateEditorModal.tsx:123-150` | 该链路应原样保留，仅更换编辑承载 |
| 3 | 前端 JSON 解析只做浅层结构判断 | `frontend/src/pages/templates/templateSpec.ts:5-24` | 缺字段级定位，错误多依赖服务端 422 |
| 4 | 模板详情已是结构化只读视图 | `frontend/src/pages/templates/TemplatesPage.tsx:66-172` | 可抽成 `TemplateDetail` 供编辑器预览复用 |
| 5 | 字段配置 UI 与 `wid` / `tid` / `target_table_id` 强绑定 | `frontend/src/pages/fields/FieldManager/FieldConfigPanel.tsx:46`、`typeConfigPanel.tsx:322` | 模板字段的 link / lookup 使用 `config.target_form`，需适配而非复制 |
| 6 | 前端 spec 类型缺 `form.flow` / `flows[].stage` | `frontend/src/api/types/templates.ts:15-52` | 结构化编辑会丢字段，需补全类型 |
| 7 | 服务端只有写路径校验，没有无状态校验端点 | `src/cndb/plugins/workspaces/routers/templates.py:100-104`、`:267-346` | 新建模板在保存前无法得到权威校验结果 |
| 8 | 导入 / 导出与复制仍以 JSON 为交换格式 | `TemplateImportModal.tsx`、`TemplatesPage.tsx:263-274` | 必须保持兼容，JSON 高级页签可承接同类场景 |
| 9 | 拖拽与设计原语已具备 | `frontend/package.json`（`@dnd-kit/*`）、`frontend/src/index.css` | 排序 / 分组可直接复用，不新增依赖 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。

## 未决问题（已确认）

- [x] 编辑容器：**全屏抽屉**（用户 2026-11-07 确认），不新增路由。
- [x] JSON 定位：**保留为高级页签**（用户 2026-11-07 确认），显式应用后重新校验。
- [x] 编辑范围：**全量 spec**（用户 2026-11-07 确认），含阶段 / 表单 / 字段 / 文档 / 流程 / `form.flow`。
- [x] 服务端权威校验：新增无状态 `validate` 端点，复用 `normalize_spec`（ADR 0121 D5）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-11-07）
