# 需求卡片：编辑流水线规则增加版本历史

- 编号：0114（与 ADR `docs/adr/0114-*.md` 同号）
- 来源 / 提出人：用户（会话 2026-11-06）
- 日期：2026-11-06
- 关联 ADR：`docs/adr/0114-pipeline-rule-version-history.md`（待评审）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 编辑流水线规则增加版本历史功能

## 已确认口径（2026-11-06 需求方确认）

| # | 问题 | 结论 |
|---|---|---|
| Q1 | 版本来源类型 | 手动保存 + 恢复版本（`manual` / `rollback`）；不做自动保存小版本 |
| Q2 | 快照范围 | 仅 DSL 原文；名称由 DSL `name` 派生，启用 / 停用不落版 |
| Q3 | 能力范围 | 版本列表 + 单版详情 + 恢复为新版本 + 任选两版 DIFF |
| Q4 | 保留与备份 | 全量保留，版本随工作区备份导出 / 导入 |

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「增加版本历史功能」 | 新增 `pipeline_workflow_version` 表：`workspace_id` / `workflow_id`（级联删）/ `version_number` / `change_type`（`manual` / `rollback`）/ `content` / `comment` / `created_by_id` / 时间戳；`unique(workflow_id, version_number)`，按 `workspace_id + created_at` 建索引 | `src/cndb/plugins/pipeline/models.py` | `tests/test_pipeline_migration.py`：表存在、约束生效 |
| C2 | 「编辑流水线规则」 | 保存路径落版：新建成功落 v1（`manual`）；更新且 `content` 实际变化时落下一版；`content` 未变（只切 `enabled`）不落版；落版与 `content` / `compiled` / `name` 写入同一事务 | `src/cndb/plugins/pipeline/routers/workflows.py` | `tests/test_pipeline_api.py`：新建 / 改内容 / 仅切启用 各自版本数正确 |
| C3 | 「版本历史功能」 | 版本只存 DSL 原文；名称从编译结果 `ir.name` 派生，启用状态与 `compiled` 快照不进版本（`compiled` 可在读取时按原文重编译或沿用当前快照） | `models.py`、`routers/workflows.py` | 单测：版本行字段集合固定，无 `enabled` 快照 |
| C4 | 「版本历史功能」 | 新增端点：`GET /{id}/versions`（倒序列表，不含原文）、`GET /{id}/versions/{n}`（原文 + 注释）、`GET /{id}/diff?base=&head=`（unified diff + 增删行数）、`POST /{id}/versions/{n}/restore`（编译原文后落 `rollback` 新版） | `routers/workflows.py`、`schemas.py` | `tests/test_pipeline_api.py`：列表 / 详情 / diff / 恢复各 200 与 404 |
| C5 | 「版本历史功能」 | 恢复语义：以历史原文重新编译校验，写回 `content` / `compiled` / `name`，保留当前 `enabled`；编译失败 400 且不落版；恢复本身产生新版本（`rollback`，注释「恢复自 vN」） | `routers/workflows.py` | 接口测试：恢复后内容、版本号、`change_type` 正确；非法 DSL 不落库 |
| C6 | 隐含（权限） | `viewer` 可读版本列表 / 详情 / diff；保存、恢复沿用 `editor`；跨工作区访问 404 | `routers/workflows.py` | 接口测试：viewer 只读、viewer 恢复 403、越权 404 |
| C7 | 隐含（删除级联） | 删除流水线时一并删除其版本行（与运行 / 发现物的显式清理一致） | `routers/workflows.py` | 接口测试：删除后版本查询 404 / 库内无残留 |
| C8 | 隐含（前端入口） | 规则行增加「版本历史」入口，编辑抽屉顶部动作条也提供入口（仅编辑态）；打开版本抽屉 | `frontend/src/pages/pipelines/PipelinesPage.tsx` | 前端单测：入口可见性与抽屉打开 |
| C9 | 隐含（前端能力） | 版本抽屉：倒序列表（版本号 / 类型徽标 / 时间 / 备注）→ 单版回看原文 → 任选两版对比（复用 `DocumentDiffView`）→ editor 可「恢复此版本」并二次确认；viewer 隐藏恢复 | `PipelinesPage.tsx`（或拆 `PipelineVersionsDrawer.tsx`）、`frontend/src/api/pipelines.ts` | 前端单测：列表 / 详情 / diff 切换 / 恢复调用 / viewer 只读；e2e 新增 1 条 |
| C10 | 隐含（存量兼容） | 迁移幂等且 `downgrade` 可还原；存量定义不回填历史（新表，历史从首次保存开始），当前内容仍可正常编辑 | `src/cndb/alembic/versions/` | 迁移测试：升级 / 降级 / 再升级幂等 |
| C11 | 隐含（备份口径） | 工作区备份 `pipelines[]` 项增加可选 `versions[]`（`version_number` / `change_type` / `content` / `comment`）；导入时重建版本并重编译校验；旧备份无 `versions` 时只还原当前定义；备份协议版本不变（v13 超集） | `workspace_backup.py`、`backup_io.py` | `tests/test_workspace_backup_v13.py`：往返 + 旧备份兼容 |
| C12 | 隐含（测试与文档） | 测试分层：迁移、接口、备份往返、前端单测、e2e；CHANGELOG 记条目；ADR 索引登记 | `tests/`、`frontend/`、`CHANGELOG.md`、`docs/adr/README.md` | `make flow` / `make check-docs` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 流水线定义模型（无版本表） | `src/cndb/plugins/pipeline/models.py:62-89` | 新增 `PipelineWorkflowVersion`，级联随定义删除 |
| 2 | 新建 / 更新 / 删除 | `src/cndb/plugins/pipeline/routers/workflows.py:162-186`、`262-287`、`290-304` | C2 / C5 / C7 落版与清理 |
| 3 | 定义响应 schema | `src/cndb/plugins/pipeline/schemas.py:36-51` | 新版本 DTO 与 diff 响应 |
| 4 | 工作区备份导出 | `src/cndb/plugins/workspaces/services/workspace_backup.py:535-547` | C11 `versions[]` |
| 5 | 工作区备份导入 | `src/cndb/plugins/workspaces/services/backup_io.py:1045-1096` | C11 版本重建与旧备份兼容 |
| 6 | 前端流水线 API | `frontend/src/api/pipelines.ts:181-222` | 新增版本 / diff / 恢复封装与类型 |
| 7 | 前端规则行与编辑抽屉 | `frontend/src/pages/pipelines/PipelinesPage.tsx:480-514`、`563-629` | C8 / C9 入口与抽屉 |
| 8 | 版本抽屉 / DIFF 先例 | `frontend/src/pages/design/DesignEditorPage.tsx:742-887`、`frontend/src/components/DiffView/DocumentDiffView.tsx` | 复刻交互与 `cn-dsl-version-*` 视觉语言 |
| 9 | 后端版本 / diff 先例 | `src/cndb/plugins/design/routers.py:197-227`、`622-735`、`src/cndb/plugins/design/services/diff.py`、`src/cndb/core/textdiff.py` | 版本号序列、diff 单一入口可复用 |
| 10 | 迁移 head | `src/cndb/alembic/versions/3b5d7f9a1c2e_design_version_change_type.py` | 新迁移 `down_revision` |
| 11 | 既有流水线测试 | `tests/test_pipeline_api.py`、`tests/test_pipeline_migration.py`、`tests/test_workspace_backup_v13.py` | C1 / C2 / C4 / C11 回归与新增 |
| 12 | 既有流水线 e2e | `frontend/tests/e2e/critical/pipelines.spec.ts` | C12 新增用例不破坏新建 / 编辑 / 运行流程 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题（已确认）

- [x] ① 版本来源：手动保存 + 恢复版本，不做自动小版本（2026-11-06 需求方确认，Q1）。
- [x] ② 快照字段：仅 DSL 原文，启用状态不落版（2026-11-06 需求方确认，Q2）。
- [x] ③ 能力范围：列表 + 详情 + 恢复 + 两版 DIFF（2026-11-06 需求方确认，Q3）。
- [x] ④ 保留与备份：全量保留并纳入工作区备份（2026-11-06 需求方确认，Q4）。
- [x] ⑤ 存量定义是否回填 v1：不回填，历史从首次保存开始（迁移不写业务数据，2026-11-06 按最小改动口径确定）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 需求方确认卡片后进入 ADR（S2：新增表 + 迁移 + 备份口径）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
