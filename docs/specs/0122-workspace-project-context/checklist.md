# Checklist 0122：工作区项目上下文

- [x] `Workspace.project_mode` 默认 `workspace`，存量工作区零回填；迁移 upgrade / downgrade 可逆且缺表时安全跳过
- [x] 项目状态表 `workspace_project_states` 按 `(workspace_id, project_row_id)` 唯一，推进只经 `lifecycle_state` / `advance_stage`
- [x] 项目门禁只统计 `scope=project` 且关联字段等于 `project_row_id` 的行；`scope=workspace` 表单不计入
- [x] 项目 A 推进不影响项目 B；跨工作区 / 跨表 / 查无项目行一律 404
- [x] 项目文档映射表 `workspace_project_documents` 与 `naming` 的 `{项目名称}` 实例化生效，且不覆盖已有正文
- [x] 文档列表 / 文档树支持 `project_id` 过滤，祖先链保留可见
- [x] `GET /projects`、`POST /project-mode/enable`、`POST /projects/{row}/documents` 权限与 404 / 409 / 422 口径符合 ADR
- [x] 数据流程与生命周期支持 `project_id`：多项目未选 422 `project_required`、零项目 409 `project_empty`
- [x] 备份升 v15，v15 往返一致，v14 旧包回落 `workspace` 模式
- [x] 前端项目清单页展示阶段 / 门禁 / 缺失项 / 初始化状态，支持逐项目与批量补文档
- [x] 前端顶部项目切换器：多项目可切换并同步 `?project=`，单项目自动选中并隐藏，工作区模式不渲染
- [x] 数据流程 / 生命周期按 `?project=` 取数，422 / 409 显示引导项目清单的空态
- [x] 单测 / 接口 / 迁移 / 备份 / 前端单测 / e2e 同轮补齐并通过
- [x] `make check-fast`、`make flow` 全绿
- [x] ADR 0122 落地状态 / 交接、ADR README、CONSTRAINTS H39-H44、CONTEXT、CHANGELOG 回填
