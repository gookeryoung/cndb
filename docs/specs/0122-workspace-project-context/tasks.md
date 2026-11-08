# Tasks 0122：工作区项目上下文

状态：已完成（P0 → P1 → P2），`make check-fast` / `make flow` 全绿，待人工确认提交。

## P0 数据模型与项目级生命周期

- [x] T01 `models.py`：新增 `Workspace.project_mode`、`WorkspaceProjectState`、`WorkspaceProjectDocument`，更新 `__all__`。
- [x] T02 alembic 迁移 `add_workspace_project_context`：新列 + 两表 + 索引 / 唯一键，downgrade 可逆。
- [x] T03 `spec.py`：`project` 顶层块 + 表单 `scope` 校验与归一化；旧模板默认 `workspace`。
- [x] T04 新模块 `services/templates/project_context.py`：配置解析、项目行校验、link 行数统计、文档标题渲染。
- [x] T05 `engine.py`：`lifecycle_state` / `advance_stage` 支持 `project_row_id`（项目门禁隔离、项目状态 upsert）。
- [x] T06 `engine.py`：`project_list`、`enable_project_mode`、`ensure_project_documents`。
- [x] T07 新路由 `routers/projects.py` 并注册：`GET /projects`、`POST /project-mode/enable`、`POST /projects/{row}/documents`。
- [x] T08 `data_flow.py`：`project_id` 参数、项目过滤计数、422/409 口径、返回 `project_id`。
- [x] T09 `lifecycle.py`：`project_id` 查询 / body 参数，透传 engine。
- [x] T10 `workspaces.py`：创建时按模板 `project` 块设置 `project_mode`；`WorkspaceResponse` 暴露 `project_mode`。
- [x] T11 单测：spec 校验、项目门禁隔离、推进互不影响、跨工作区 404、启用幂等。
- [x] T12 接口测试：projects / data-flow / lifecycle / enable / 项目文档。
- [x] T13 前端：项目上下文 hook + 顶部切换器 + 项目清单页 + DataFlow/生命周期传 `project`。
- [x] T14 前端单测 / e2e：单项目自动选中、多项目切换。

## P1 项目文档

- [x] T15 文档 `list` / `tree` 支持 `project_id` 过滤。
- [x] T16 启用接口 `generate_documents` 与项目文档补建：按 `naming` 渲染标题、不覆盖正文。
- [x] T17 备份 v15：导出 `project_mode` / `project_states` / `project_documents`，导入兼容 v14。
- [x] T18 迁移 / 备份测试：upgrade-downgrade 可逆、v15 往返、v14 回落 workspace。

## P2 清单增强

- [x] T19 清单统计列（阶段 / 门禁 / 文档缺失）与未初始化标记。
- [x] T20 批量补文档入口；删除不可落地的“提醒”项（ADR 已按无通知系统收敛）。
- [x] T21 全量门禁 `make flow`（必要时 `make check`）、ADR 落地状态 / 交接、CHANGELOG 回填。
