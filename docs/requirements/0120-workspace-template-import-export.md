# 需求卡片：工作区模板导入导出

- 编号：0120
- 来源 / 提出人：用户（2026-11-07 会话提出）
- 日期：2026-11-07
- 关联 ADR：无（S1 常规功能，方案并入本卡片「口径」）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 工作区模板，增加导入导出功能

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 增加导入导出功能 | 模板中心每个模板（含内置）提供「导出」，下载**单个 JSON 文件**；内容含格式标记 `format`、`schema_version`、`name` / `description` / `category` / `modules` / `spec` / `version`；文件名 `{模板名}.workspace-template.json`（非法文件名字符替换为 `-`） | `workspaces/routers/templates.py`、前端 `TemplatesPage.tsx` | 接口测试校验响应头与 JSON 结构；前端单测 |
| C2 | 增加导入导出功能 | 模板中心提供「导入模板」，上传单个 `.json`；前端本地解析失败 / 超限（>1MB）给出中文提示，不上送服务端 | `TemplatesPage.tsx`、导入弹窗 | 前端单测：非法文件提示 |
| C3 | 增加导入导出功能 | 服务端导入前必须走 `normalize_spec` 校验与 `normalize_modules` 归一化；非法结构返回 422 中文可读错误（含字段路径）；未知 `format` / `schema_version` 返回 422 | `workspaces/schemas/templates.py`、`services/templates/spec.py`、`routers/templates.py` | 接口测试：非法 spec / 未知格式 422 |
| C4 | 增加导入导出功能 | 导入分两步：先调用预览接口返回归一化后的 spec、模板名与统计（阶段 / 表单 / 字段 / 文档规则 / 流程），前端展示确认后再创建 | `routers/templates.py`、`TemplatesPage.tsx` | 接口测试 + 前端单测 |
| C5 | 增加导入导出功能 | 导入创建时与已有模板**同名自动重命名**：`原名（导入）`，仍冲突则 `原名（导入 2）`、`（导入 3）`…；绝不覆盖已有模板；结果名长度 ≤120 | `routers/templates.py` | 接口测试：连续导入同名模板名称递增 |
| C6 | 增加导入导出功能 | 导入产物为新模板：`is_builtin=False`、`created_by_id` 为当前用户、`version=1`（不沿用导出文件中的版本号）、落一条 revision（`change_summary="从文件导入"`） | `routers/templates.py` | 接口测试：版本 / 归属 / 历史版本 |
| C7 | 增加导入导出功能 | 权限：任意登录用户可导出（模板读权限）与导入创建；内置模板可导出，导入不会修改内置模板 | `routers/templates.py` | 接口测试：未登录 401、普通用户导入成功 |
| C8 | 增加导入导出功能 | 前端导入弹窗展示文件名 / 大小 / 模板名 / 分类 / 模块 / 规模统计，确认按钮创建；成功后刷新列表并提示最终模板名；错误在弹窗内展示 | `TemplatesPage.tsx` | 前端单测 + e2e |
| C9 | 增加导入导出功能 | 测试与实现同轮：后端接口测试（导出结构、预览、导入、422、同名重命名、权限）、前端单测、e2e 覆盖导出下载与导入创建 | `tests/test_workspace_templates.py`、`TemplatesPage.test.tsx`、`frontend/tests/e2e/` | `make flow` 全绿 |
| C10 | 增加导入导出功能 | 更新 `CONTEXT.md` 词条与 `CHANGELOG.md`；**不改数据模型、不新增迁移** | 文档 | `make check-docs` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（已核实）

| # | 受影响能力 | 位置 | 备注 |
|---|---|---|---|
| 1 | 模板 CRUD / 版本路由 | `src/cndb/plugins/workspaces/routers/templates.py` | 新增导出与导入预览 / 创建端点，复用 `_validate_spec`、`_name_conflict` |
| 2 | spec 校验与归一化 | `src/cndb/plugins/workspaces/services/templates/spec.py` | 导入必须复用 `normalize_spec`，不另写校验 |
| 3 | 请求 / 响应 schema | `src/cndb/plugins/workspaces/schemas/templates.py` | 新增导入载荷与预览响应模型 |
| 4 | 模板列表 / 卡片操作区 | `frontend/src/pages/templates/TemplatesPage.tsx` | 顶栏加「导入模板」，卡片 extra 加「导出」 |
| 5 | 前端 API 与类型 | `frontend/src/api/workspaceTemplates.ts`、`frontend/src/api/types/templates.ts` | 新增 export / importPreview / importCreate |
| 6 | 后端既有测试 | `tests/test_workspace_templates.py` | 追加导入导出用例 |

## 未决问题

- [x] 文件格式：单个 JSON 文件（需求方 2026-11-07 确认）
- [x] 同名冲突：自动重命名副本（需求方 2026-11-07 确认）
- [x] 导入前预览：需要预览再确认（需求方 2026-11-07 确认）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 需求方确认卡片后进入实现（H5，2026-11-07 确认）
