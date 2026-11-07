# ADR 0114: 流水线规则版本历史（手动保存 / 恢复版本 / 两版 DIFF）

Status: Accepted（2026-11-06 用户评审通过，进入实现）
Date: 2026-11-06
Related: `src/cndb/plugins/pipeline/models.py`、`src/cndb/plugins/pipeline/routers/workflows.py`、`src/cndb/plugins/pipeline/schemas.py`、`src/cndb/core/textdiff.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/workspaces/services/workspace_restore.py`、`frontend/src/pages/pipelines/PipelinesPage.tsx`、`frontend/src/api/pipelines.ts`、`frontend/src/components/DiffView/DocumentDiffView.tsx`、`docs/adr/0076-pipeline-check-dsl.md`、`docs/adr/0113-design-version-history-and-diff.md`
需求卡片: `docs/requirements/0114-pipeline-rule-version-history.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C12），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「增加版本历史功能」 | 新增 `pipeline_workflow_version`（工作区级、随定义级联删）；`unique(workflow_id, version_number)` + `ix_pipeline_workflow_version_ws_created`；`change_type` 取 `manual` / `rollback` |
| C2 | 「编辑流水线规则」 | 新建成功落 v1（`manual`）；更新时 `content` 与当前值不同才落下一版；只改 `enabled` 不落版；落版与定义写入同一事务 |
| C3 | 「版本历史功能」 | 版本行只存 `content`（DSL 原文）；名称由 `compile_workflow` 的 `ir.name` 派生，`enabled` 与 `compiled` 不进版本 |
| C4 | 「版本历史功能」 | 新增 4 个端点：版本列表 / 单版详情 / `GET /diff` / `POST /versions/{n}/restore`；diff 返回 `unified_diff` + 增删行数 |
| C5 | 「版本历史功能」 | 恢复 = 历史原文重新编译校验 → 写回 `content` / `compiled` / `name`（保留 `enabled`）→ 落 `rollback` 新版；编译失败 400 且零写入 |
| C6 | 隐含（权限） | 版本读取沿用 `VIEWER`，保存 / 恢复沿用 `EDITOR`；定义与版本都按 `workspace_id + workflow_id` 定位，跨工作区一律 404 |
| C7 | 隐含（删除级联） | 删除定义时显式删版本行，再删运行 / 发现物与定义（与现有清理顺序一致） |
| C8 | 隐含（前端入口） | 规则行操作区新增「版本历史」图标按钮；编辑抽屉顶部动作条在编辑态再给一个入口 |
| C9 | 隐含（前端能力） | 新组件 `PipelineVersionsDrawer`：列表 → 单版原文 → 任选两版对比（复用 `DocumentDiffView`）→ editor 可恢复（二次确认），viewer 隐藏恢复 |
| C10 | 隐含（存量兼容） | 单条迁移只建表，不回填历史；幂等 upgrade / downgrade 可还原 |
| C11 | 隐含（备份口径） | 备份 `pipelines[]` 项增加可选 `versions[]`（`version_number` / `change_type` / `content` / `comment`）；导入重建版本；旧备份无 `versions` 只还原当前定义；`BACKUP_VERSION` 仍为 `13` |
| C12 | 隐含（测试与文档） | 迁移 / 接口 / 备份往返 / 前端单测 / e2e 分层覆盖；CHANGELOG 与 ADR 索引同步 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `PipelineWorkflow` 只有当前 `content` / `compiled` / `enabled`，无版本表 | `src/cndb/plugins/pipeline/models.py:62-89` | 覆盖保存即丢失历史原文，无法回看 / 对比 / 恢复 | 确认 |
| 2 | 新建直接写定义，无首版记录 | `src/cndb/plugins/pipeline/routers/workflows.py:162-186` | 需在提交前 `flush` 取得 id 后落 v1 | 确认 |
| 3 | 更新仅在 `payload.content is not None` 时重编译并覆盖，无版本 | `src/cndb/plugins/pipeline/routers/workflows.py:262-287` | 需在内容实际变化时落版，仅切 `enabled` 不落版 | 确认 |
| 4 | 删除显式清理 finding / run 后删定义 | `src/cndb/plugins/pipeline/routers/workflows.py:290-304` | 需补版本行清理 | 确认 |
| 5 | 定义响应无版本字段 | `src/cndb/plugins/pipeline/schemas.py:36-51` | 新增版本列表 / 详情 / diff DTO | 确认 |
| 6 | 备份 `pipelines[]` 只导出 `name` / `content` / `enabled` | `src/cndb/plugins/workspaces/services/workspace_backup.py:535-547` | 需补 `versions[]` | 确认 |
| 7 | 导入按 `content` 重编译并跳过同名定义 | `src/cndb/plugins/workspaces/services/backup_io.py:1045-1096` | 需在新建定义后重建版本；跳过同名时也不导入版本 | 确认 |
| 8 | 工作区恢复先删 finding / run / workflow | `src/cndb/plugins/workspaces/services/workspace_restore.py:109-116` | 需先删版本表，避免恢复后残留孤儿行 | 新增 |
| 9 | 前端规则行有运行 / 编辑 / 删除，编辑抽屉无历史入口 | `frontend/src/pages/pipelines/PipelinesPage.tsx:480-514`、`563-629` | 补版本入口与抽屉 | 确认 |
| 10 | 前端 API 无版本 / diff / 恢复封装 | `frontend/src/api/pipelines.ts:181-222` | 补类型与方法 | 确认 |
| 11 | 设计端已有版本抽屉交互与 `cn-dsl-version-*` 样式 | `frontend/src/pages/design/DesignEditorPage.tsx:742-887`、`frontend/src/index.css` | 交互与视觉直接复刻，不新造范式 | 确认 |
| 12 | `DocumentDiffView` 已支持 unified diff 渲染 | `frontend/src/components/DiffView/DocumentDiffView.tsx` | diff 展示复用，不写新渲染器 | 确认 |
| 13 | `core.textdiff.unified_diff` 是跨插件唯一 diff 入口 | `src/cndb/core/textdiff.py:13-25` | pipeline 直接复用（ADR 0113 D6） | 新增 |
| 14 | 设计版本号口径：`latest + 1`、单序列、恢复落新版 | `src/cndb/plugins/design/routers.py:197-227`、`688-735` | 只复用口径，不跨插件复用代码 | 新增 |
| 15 | 迁移 head 为 `3b5d7f9a1c2e` | `src/cndb/alembic/versions/3b5d7f9a1c2e_design_version_change_type.py:19` | 新迁移以此为 `down_revision` | 新增 |
| 16 | 流水线迁移测试校验表 / 索引 / 列与模型一致 | `tests/test_pipeline_migration.py:43-56` | 新表沿用同一断言范式 | 新增 |

**核心缺陷（需求要补的）**：`pipeline_workflow` 只保留「当前一版」，保存即覆盖；规则改坏后既看不到改了什么，也无法回到上一版。

设计目标（不变量）：

- **I1 单一落版入口**：所有版本写入只经 `services/versions.add_workflow_version`，路由层不得自行拼 `PipelineWorkflowVersion`。
- **I2 单一 diff 入口**：diff 必须走 `cndb.core.textdiff.unified_diff`，前后端不另写 diff 算法。
- **I3 版本不可变**：版本行只追加，不更新、不删除（级联删除定义时除外）。
- **I4 权限与隔离**：viewer 只读版本 / diff；editor 才可保存与恢复；定义与版本都必须按工作区 + 定义 ID 定位。
- **I5 写路径原子**：编译失败时 `content` / `compiled` / `name` / 版本行均不变化。
- **I6 存量与旧备份兼容**：迁移不回填历史；旧备份无 `versions` 时只还原当前定义，不阻断导入。

## Decision

### 1. 数据模型

新增 `pipeline_workflow_version` 表（不改存量表结构）：

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | int | PK | 版本行主键 |
| `workspace_id` | int | FK `workspaces_workspace.id` CASCADE，NOT NULL，索引 | 工作区隔离与备份按工作区取数 |
| `workflow_id` | int | FK `pipeline_workflow.id` CASCADE，NOT NULL，索引 | 版本归属定义 |
| `version_number` | int | NOT NULL | 单序列，从 1 递增 |
| `change_type` | `String(20)` | NOT NULL DEFAULT `manual` | `manual` 保存 / `rollback` 版本恢复 |
| `content` | `Text` | NOT NULL | DSL 原文快照 |
| `comment` | `String(200)` | NOT NULL DEFAULT `""` | 恢复时写「恢复自 vN」，主动保存留空 |
| `created_by_id` | int | FK `accounts_user.id` SET NULL，可空 | 操作人 |
| `created_at` / `updated_at` | datetime | `TimestampMixin` | 列表按版本号倒序，时间仅展示 |

- 常量在 `models.py`：`CHANGE_TYPE_MANUAL` / `CHANGE_TYPE_ROLLBACK` / `CHANGE_TYPE_VALUES`；schema 用 `Literal` 校验。
- 唯一键 `uniq_pipeline_workflow_version_number (workflow_id, version_number)`；索引 `ix_pipeline_workflow_version_ws_created (workspace_id, created_at)`。
- 版本只存原文：`compiled` 不落版本（恢复 / diff 均按原文重编译），`enabled` 与 `name` 是当前定义属性，不进快照。

### 2. 判定算法（唯一入口）

新增 `src/cndb/plugins/pipeline/services/versions.py`：

```python
def latest_version_number(db: Session, workflow_id: int) -> int: ...
def add_workflow_version(
    db: Session, workflow: PipelineWorkflow, user: User, *,
    content: str, change_type: str, comment: str = "",
) -> int: ...
def workflow_diff(
    db: Session, workflow: PipelineWorkflow, base: int, head: int,
) -> dict[str, Any]: ...
```

- `add_workflow_version`：`version_number = latest_version_number + 1`，`db.add(PipelineWorkflowVersion(...))`，返回新版本号；不做 commit（由调用方事务提交）。
- `workflow_diff`：按 `version_number` 取两版，缺任一 → `NotFoundError(code="pipeline_version_not_found")`；调用 `unified_diff(base.content, head.content)`；返回 `{base_version, head_version, diff, added, removed}`。
- 路由层三条写路径：
  1. `create_workflow`：编译 → `db.add(workflow)` → `db.flush()` → `add_workflow_version(..., change_type=manual)` → `commit`。
  2. `update_workflow`：`payload.content` 非空且与当前 `workflow.content` 不同 → 编译写回 → `add_workflow_version(manual)`；只改 `enabled` / 名称未变内容时**不落版**。
  3. `restore_workflow_version`：取版本 → 编译校验 → 名称唯一性检查（排除自身）→ 写回 `content` / `compiled` / `name` → `add_workflow_version(rollback, comment=f"恢复自 v{n}")` → `commit`。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /api/v1/workspaces/{wid}/pipelines` | 新增行为：创建成功落 v1（响应不变） |
| `PUT /api/v1/workspaces/{wid}/pipelines/{id}` | 新增行为：`content` 实际变化时落 `manual` 版本（响应不变） |
| `DELETE /api/v1/workspaces/{wid}/pipelines/{id}` | 新增行为：一并删除版本行 |
| `GET .../pipelines/{id}/versions` | 新增：版本列表（版本号倒序，不含原文） |
| `GET .../pipelines/{id}/versions/{n}` | 新增：单版详情（含原文与备注） |
| `GET .../pipelines/{id}/diff?base=&head=` | 新增：两版文本 diff + `added` / `removed`；成员可读 |
| `POST .../pipelines/{id}/versions/{n}/restore` | 新增：按历史原文恢复并落 `rollback` 新版；editor |

响应模型：`WorkflowVersionItem`（`id` / `workflow_id` / `version_number` / `change_type` / `comment` / `created_by_id` / `created_at`）、`WorkflowVersionDetail`（+`content`）、`WorkflowVersionDiff`（`base_version` / `head_version` / `diff` / `added` / `removed`）。

### 4. 边界与例外

1. **内容未变化**：`PUT` 仅在 `payload.content != workflow.content` 时落版；重复保存相同内容不产生版本行。
2. **只切启用**：`enabled` 不入版本，切换启用 / 停用不产生版本。
3. **恢复保留启用状态**：恢复只覆盖 `content` / `compiled` / `name`（名称来自 DSL），`enabled` 保持当前值。
4. **恢复后名称冲突**：沿用 `_assert_name_available(..., exclude_id=workflow.id)`，冲突 409，零写入。
5. **恢复的 DSL 非法**：`compile_workflow` 抛错 → 400，不写定义、不落版（I5）。
6. **恢复成当前版本**：允许，仍落一条 `rollback` 版本（保留「谁在何时做了恢复」）。
7. **版本不存在**：列表外的 `{n}` / `restore` / `diff` 一侧 → 404 `pipeline_version_not_found`。
8. **删除定义**：先删版本行再删运行 / 发现物，全部在现有删除事务内。
9. **并发保存**：同一规则并发保存可能撞 `unique(workflow_id, version_number)`，由数据库约束兜底（与设计版本一致）；本期不做乐观锁。
10. **版本规模**：全量保留，不设上限、不做分页（单规则版本量级与设计文件相当）。

### 5. 迁移

单条 alembic 迁移（`revision="4c6e8a0b2d3f"`，`down_revision="3b5d7f9a1c2e"`，文件 `4c6e8a0b2d3f_pipeline_workflow_version.py`）：

1. `upgrade`：`inspect` 目标表不存在时 `op.create_table("pipeline_workflow_version", ...)`，同时建唯一键与两个索引；存在则跳过（幂等）。
2. 不写任何业务数据：存量定义不回填 v1，历史从首次保存开始。
3. `downgrade`：表存在时 `op.drop_table("pipeline_workflow_version")`，不触碰 `pipeline_workflow` / run / finding。
4. 迁移测试覆盖升级 → 降级 → 再升级幂等，以及列集合与 ORM 模型逐列一致。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/pipelines.ts` | 新增 `PipelineVersionItem` / `PipelineVersionDetail` / `PipelineVersionDiff` 类型与 `listVersions` / `getVersion` / `getVersionDiff` / `restoreVersion` 方法 |
| 版本抽屉 | `frontend/src/pages/pipelines/PipelineVersionsDrawer.tsx`（新建） | 版本列表（版本号 / 类型徽标 / 时间 / 备注）→ 单版原文 `<pre>` → 两版选择 + `DocumentDiffView` → editor 恢复（`Popconfirm`）；viewer 隐藏恢复 |
| 页面入口 | `frontend/src/pages/pipelines/PipelinesPage.tsx` | 规则行操作区加「版本历史」按钮；编辑抽屉顶部动作条在 `editing` 时加「版本历史」按钮；恢复成功后失效 `['pipelines', wid]` 查询 |
| 样式 | `frontend/src/index.css` | 复用 `cn-dsl-version-list` / `cn-dsl-version-row` / `cn-dsl-version-pre` / `cn-dsl-diff-controls` 等既有类，仅按需补 `cn-pipeline-version-*` 少量修饰 |

- 版本类型展示：`manual` →「主动保存」，`rollback` →「版本恢复」；颜色表在抽屉内本地定义，不跨页面 import 设计模块的页面级常量。
- 默认对比：选中 vN 时默认 `base = vN-1`（不存在则 `base = vN`）、`head = vN`；两版下拉选项来自版本列表。

### 7. 测试清单

**判定层（单测）**：

- `add_workflow_version` 自增版本号、`change_type` 与 `comment` 落库正确；
- `latest_version_number` 无版本时为 0、有版本时取最大；
- `workflow_diff` 正常 diff、`base == head` 空差异、版本缺失 404。

**接口层**（`tests/test_pipeline_api.py`）：

- 新建落 v1；改内容落 v2；相同内容重复保存不落版；只切 `enabled` 不落版；
- 版本列表倒序、详情含原文；`{n}` 缺失 404；
- `GET /diff` 200 载荷结构与增删行数、任一侧缺失 404；
- 恢复：写回内容 / 名称、落 `rollback`、保留 `enabled`；非法 DSL 400 且零写入；名称冲突 409；
- 权限：viewer 可读版本 / diff，viewer 保存 / 恢复 403；跨工作区 404；
- 删除定义后版本行不残留（接口 404 + 库内计数为 0）。

**迁移 / 备份**：

- 迁移升级建表 + 唯一键 + 索引；列集合与 ORM 一致；降级删表；再升级幂等；
- 备份往返：`versions[]` 原样还原（版本号 / 类型 / 原文 / 备注）；
- 旧备份无 `versions`：只导入当前定义，不报错；同名定义仍跳过。

**前端单测**：

- 规则行与编辑抽屉的「版本历史」入口可见性（新建态无抽屉入口）；
- 抽屉列表 / 单版回看 / 两版切换触发 diff；
- 恢复调用与成功后的列表刷新；viewer 不渲染恢复按钮；
- 版本为空时的空态。

**e2e（前端）**：新建规则 → 编辑保存第二版 → 打开版本历史 → 看到 v2 / v1 → 选择两版展示 diff → 恢复到 v1 → 列表出现 `rollback` 版本且规则内容回到 v1。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 模型 + 迁移 + `services/versions.py` + 新建 / 更新 / 删除落版与清理 + 单测 / 迁移测试 | 低（只新增表） |
| **P1** | 版本列表 / 详情 / diff / 恢复端点 + schema + 接口测试 | 中（恢复写路径与名称冲突） |
| **P2** | 前端 API + 版本抽屉与入口 + 备份 `versions[]` + 前端单测 / e2e + CHANGELOG | 中（备份导入与旧备份兼容） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案 | 新增独立版本表，保存落版、恢复落 rollback，diff 读时计算 | 与设计模块（ADR 0113）同范式；流水线定义以 YAML 为唯一真相源，版本只需原文 | ① 复用 `design_designversion`：跨插件耦合；② 只保留「上一版」单列：无法任选两版对比与长期回看 | `models.py`、`services/versions.py` |
| D2 | 快照范围（Q2） | 只存 DSL 原文；`enabled` / `name` / `compiled` 不进版本 | 名称由 DSL 派生；启用是运行开关不是内容；`compiled` 可由原文重编译，避免历史 IR 与注册表版本漂移 | ① 全字段快照：启用切换产生大量无意义版本；② 存 compiled：体积与兼容成本高 | `models.py` |
| D3 | 版本来源（Q1） | 仅 `manual` / `rollback` | 规则编辑低频，手动保存即里程碑；恢复需可追溯 | 增加 `auto` 自动小版本：噪音大且与设计模块的连续编辑场景不同 | `models.py`、`routers/workflows.py` |
| D4 | 版本编号 | 单序列 `max(version_number) + 1` | 与服务端恢复 / diff / 备份口径一致，前端展示简单 | 时间戳 / 哈希作版本号：无法表达「上一版」 | `services/versions.py` |
| D5 | 落版时机 | 新建落 v1；内容实际变化才落版；只切启用不落版 | 避免重复内容与开关操作污染历史 | 每次 PUT 都落版：启用切换产生噪音版本 | `routers/workflows.py` |
| D6 | 恢复语义 | 重新编译历史原文后写回定义，并落 `rollback` 新版；保留 `enabled` | 历史不可变（I3），恢复本身也是一次可追溯操作 | ① 原地覆盖当前版本：丢失恢复前内容；② 删除后续版本：不可逆 | `routers/workflows.py` |
| D7 | DIFF 粒度 | 仅文本 unified diff + 增删行数 | 版本未存 `compiled`，读时重编译历史有失败风险；规则文件小，行级 diff 已足够定位 | 结构摘要（job / step 计数）：需重编译历史且价值有限 | `services/versions.py`、`core/textdiff.py` |
| D8 | 存量处理 | 迁移不回填历史 | 迁移不写业务数据；回填的 `created_at` 失真是伪历史 | 迁移为每条定义落 v1：制造「迁移时刻」的假版本 | 迁移脚本 |
| D9 | 备份协议（Q4） | `pipelines[]` 增加可选 `versions[]`，协议仍为 v13 | 新字段是 v13 超集；旧备份无字段时按「无历史」处理 | 升 v14：为可选元数据牵动全套协议断言，收益不足 | `workspace_backup.py`、`backup_io.py` |
| D10 | 前端入口 | 规则行 + 编辑抽屉顶部动作条双入口，抽屉内完成全部操作 | 与现有「运行 / 编辑 / 删除」行操作一致；不打断编辑上下文 | ① 独立页面：离开编辑态、改动面大；② 仅抽屉入口：查看历史需先进编辑 | `PipelinesPage.tsx` |
| D11 | 删除级联 | 删除定义时显式删版本行 | 与 run / finding 的显式清理顺序一致，SQLite 外键级联不作为唯一保障 | 仅依赖 FK CASCADE：测试环境与历史数据清理不一致 | `routers/workflows.py`、`workspace_restore.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：规则改坏可回看与一键恢复；任意两版可对比；版本与定义同事务，不会出现「内容已改但历史缺失」；备份随工作区迁移。
- **负向**：定义保存路径多一次版本插入；删除 / 恢复 / 备份导入路径各增一处清理或重建逻辑；规则版本量与设计文件同量级增长。
- **风险与缓解**：并发保存撞唯一键 —— 数据库约束兜底，本期不做乐观锁；旧备份无版本 —— 只还原当前定义且不阻断导入；恢复后名称冲突 —— 复用名称唯一校验并 409 拒绝，零写入。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 流水线定义与 DSL | `pipeline_workflow.content` / `compiled` | 原文仍是唯一真相源，版本只快照原文；运行读当前 `compiled` 不变 | ADR 0076 |
| 备份口径 | `pipelines[]` | 增加 `versions[]`，运行 / 发现物仍不进备份；协议仍 v13 | ADR 0076 D12 → 0114 |
| 版本历史与 DIFF 交互 | `DocumentDiffView` + `core.textdiff` | 复刻设计端版本抽屉交互与统一 diff 算法 | ADR 0113 → 0114 |
| 工作区模块与入口 | 质量检查按域双入口 | 版本入口挂在既有规则行与编辑抽屉，不新增路由 | ADR 0080 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/pipeline/models.py`、`src/cndb/plugins/pipeline/services/versions.py`、`src/cndb/plugins/pipeline/routers/workflows.py`、`src/cndb/alembic/versions/4c6e8a0b2d3f_pipeline_workflow_version.py` | `tests/test_pipeline_api.py`、`tests/test_pipeline_migration.py` | `abc52d26` |
| P1 | 已落地 | `src/cndb/plugins/pipeline/routers/workflows.py`、`src/cndb/plugins/pipeline/schemas.py` | `tests/test_pipeline_api.py` | `abc52d26` |
| P2 | 已落地 | `frontend/src/api/pipelines.ts`、`frontend/src/pages/pipelines/PipelineVersionsDrawer.tsx`、`frontend/src/pages/pipelines/PipelinesPage.tsx`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/workspaces/services/workspace_restore.py` | `frontend/src/pages/pipelines/PipelineVersionsDrawer.test.tsx`、`frontend/src/pages/pipelines/PipelinesPage.test.tsx`、`frontend/tests/e2e/critical/pipelines.spec.ts`、`tests/test_workspace_backup_v13.py` | `abc52d26` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地并提交（`abc52d26`），Status 保持 Accepted，待人工验收
- 已完成：版本表 + 迁移、落版服务、4 个版本端点、前端抽屉与双入口、备份 `versions[]` 往返、后端 / 前单测与 e2e
- 下一步：人工验收后由人决定 `Status` 是否置 `Implemented`；本轮无后续期
- 已知坑：迁移 head 现为 `4c6e8a0b2d3f`；备份协议保持 v13，导入需兼容无 `versions` 的旧载荷并去重版本号；恢复必须排除自身做名称唯一校验；恢复保留当前 `enabled`
- 最近一次全绿：`make check-fast` / `make test` @ 2026-11-06
