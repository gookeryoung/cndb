# 行任务分发与审批（row-task-approval）Implementation Plan

> Status: APPROVED
> Source: user request（2026-09-23 澄清：行填写/修改任务 + 单级审批 + 三级冲突校验 + 格式预设三层复用）
> Mode: (default)
> Iterations: 2 / 3
> Author: zhou
> Last updated: 2026-09-23

## Requirements summary

在 cndb 中为数据表行的新增/修改引入"任务"机制：有权限者将行级填写/修改任务分派给用户（任务绑定具体行或新行模板，附填写说明与格式预设），被分派人在任务面板填写提交；提交不直接落库，进入单级审批队列，审批通过时按"乐观锁版本号 → 字段级合并 → 审批二次校验"三级冲突策略写库；拒绝则退回重填。格式预设分三层：复用字段既有 `validate_value` 约束、可配置预设模板（regex/枚举白名单/默认值，绑定到任务）、任务级填写说明（软约束）。

## Acceptance criteria

- AC-1：用户可在某表上创建"新增行任务"或"修改行任务"，指定被分派人、填写说明、格式预设；被分派人收到任务并在任务面板看到它。
- AC-2：被分派人提交后行数据**不落库**；任务变为 submitted；审批人（创建任务者或工作区 ADMIN/OWNER，且不得是提交人本人）可 approve 或 reject（附意见）。
- AC-3：approve 时落库成功的前提是行 `version` 与提交基线一致；不一致时进入字段级合并——仅双方都改的同一字段才判冲突，冲突任务置为 conflict 状态等待人工处理，不丢数据。
- AC-4：行表带 `version` 列；常规 PATCH /records 可选携带 `expected_version`，不匹配返回 409（不传则兼容旧行为）。
- AC-5：提交与审批展示两个时机都执行字段校验：字段类型 `validate_value` + 任务绑定预设模板（regex/枚举白名单/默认值）；预设校验失败给出字段级错误明细（400）。
- AC-6：全部公共 API 有 Pydantic schema、前端 `src/types` 同步、后端 pytest 覆盖、`make check` 通过。

## RALPLAN-DR

### Principles

- 最小可行：任务只做"行级 + 单级审批"，不引入多级审批链、不建通知系统（用现有前端轮询/入口刷新即可）。
- 落库必须复用 `create_row`/`update_row`，不另写第二条写库路径——保证字段规范化、audit、link 处理单一来源。
- 冲突策略分级而非二值：先乐观锁、再字段级合并、最后人工兜底，避免"一冲突就全拒"的体验。
- 格式预设不重复造校验：预设模板是 `validate_value` 之上的**附加层**，输出同一错误结构。
- 权限复用 `check_action`，新增动作尽量映射既有 TableAction，不扩枚举。

### Decision drivers

- 数据一致性优先于吞吐（审批落库是低频操作，可承受逐字段比较开销）。
- 与现有插件架构一致（plugin_registry + routers/services/models 分层）。
- 前端复用现有编辑控件与 React Query 模式，避免新状态库。

### Viable options

**Option A：独立 `plugins/record_tasks` 插件（chosen）**
- 实现思路：新建插件承载任务/提交/预设三张表与路由，落库时调用 tables 插件的 records service；行表加 `version` 列。
- 改动文件：`src/cndb/plugins/record_tasks/*`（新）、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/models.py`、`src/cndb/plugins/tables/routers/records.py`、alembic 迁移 ×1、`frontend/src/*`（任务面板 + GridPage 409 处理）。
- Pros：职责清晰，tables 插件不被任务概念污染；与 workspaces/tables/reports 插件结构对称；后续扩展（多级审批、通知）有独立落点。
- Cons：新增一个插件目录与注册成本；跨插件调用 records service 需要显式 import（项目内已有先例）。

**Option B：并入 tables 插件（rejected）**
- 实现思路：任务/审批模型直接加进 `plugins/tables/models.py`，路由加在 tables 下。
- Pros：无跨插件调用，落库最近。
- Cons：tables 插件已承载 schema/views/records/permissions，再塞任务审批会显著膨胀；`access.py` 的 check_action 语义会被任务态搅浑。
- Invalidation rationale：违背"表结构与任务编排分层"的既有插件边界，维护成本高于 A 的注册成本，砍掉。

**Option C：复用 workflows 插件节点图表达审批流（rejected）**
- 实现思路：把"分派→提交→审批"建成 workflow node。
- Pros：理论上零新表。
- Invalidation rationale：workflows 是通用节点自动化引擎，无任务态机（pending/submitted/approved/rejected/conflict）、无字段级 diff，强行映射需给 workflows 加大量特化逻辑，比 A 更重且污染其通用性。用户明确选了单级审批，C 过度设计。

### Implementation steps（基于 Option A）

**后端**

1. 行表乐观锁 — `src/cndb/plugins/tables/models.py` 行模型加 `version = Column(Integer, nullable=False, server_default="1")`；新增 alembic 迁移（`alembic/versions/`，down_revision 指向当前 head，含 `version` 列 + 数据回填 `1`）。
2. `update_row` 支持乐观锁 — `src/cndb/plugins/tables/services/core/records.py:381-423`：签名加 `expected_version: int | None = None`；WHERE 追加 `version == expected_version`，SET `version = version + 1`；命中 0 行且行存在时返回显式冲突信号（新增 `RowVersionConflict` 异常或 `(row, conflict: bool)` 返回，二选一以现有异常模式为准）。
3. PATCH 路由可选 version — `src/cndb/plugins/tables/routers/records.py:168-186`：schema 加 `expected_version: int | None`；冲突映射为 409（detail 含当前 version），业务 400/409 映射集中在路由层。
4. 新插件骨架 — `src/cndb/plugins/record_tasks/`：`models.py` 定义三张表：
   - `record_tasks_task`：`workspace_id/table_id/mode(create|update)/target_row_id?(update 必填)/assignee_id/created_by/title/instructions(Text)/field_preset_id?/base_row(JSON 快照，含 version)/status(pending|submitted|approved|rejected|conflict|cancelled)/created_at/updated_at`。
   - `record_tasks_submission`：`task_id/payload(JSON，字段级 diff，只含被改字段)/note/base_version/status(approved|rejected)/reviewer_id/review_note/reviewed_at`。
   - `record_tasks_field_preset`：`table_id/name/config(JSON: fields→{regex, enum_whitelist, default_template, required_hint})/created_by`，一表可多预设，任务引用其一。
5. 预设校验服务 — `src/cndb/plugins/record_tasks/services/presets.py`：`validate_payload_against_preset(payload, preset, fields) -> list[FieldError]`，在字段 `validate_value` 之后追加执行；错误结构对齐现有 400 detail 格式。
6. 任务服务 — `src/cndb/plugins/record_tasks/services/tasks.py`：
   - `create_task`（校验：table `check_action(EDIT_RECORDS)`；update 模式校验 target_row 存在并快照 `base_row` 含 version；assignee 必须是工作区成员）；
   - `submit`（assignee 本人；重新以当前行 version 做一次快读比对，若行已删/版本漂移仅记录不阻断，真正裁决在审批时；预设+字段校验失败 400）；
   - `approve`（审批人 = created_by 或工作区 ADMIN/OWNER，且 ≠ 提交人；落库算法见下）；
   - `reject`（写 review_note，任务回 pending 可重提交，保留上次 submission 历史）。
7. 审批落库三级冲突算法 — `services/tasks.py` 内纯函数 `resolve_merge(base_row, payload, current_row)`：
   - ① 行不存在 → 任务置 conflict（新增行被删）；
   - ② `current.version == base_version` → 快路径，整包直接走 `create_row`/`update_row`；
   - ③ 版本漂移 → 逐字段：`current[field] == base_row[field]` 或 `field 不在 payload` → 可写；`current[field] != base_row[field]` 且在 payload → 冲突字段集非空则任务置 conflict、detail 列出冲突字段，否则只写安全字段；
   - 落库统一经 `update_row(expected_version=current.version)`，写库前 version 再变由 DB 层乐观锁兜底（竞态兜底）。
8. 路由 — `src/cndb/plugins/record_tasks/routers/tasks.py` + `presets.py`，全部 `async def` + `response_model`：
   - `POST /workspaces/{wid}/tables/{tid}/record-tasks`（分发，支持单任务单 assignee，批量后续再说）
   - `GET .../record-tasks?status=&mine=assigned|created`
   - `POST /record-tasks/{id}/submit|approve|reject|cancel`
   - `POST/GET/DELETE /workspaces/{wid}/tables/{tid}/field-presets`
   - 异常→HTTP 映射全部在路由层，服务层抛业务异常。
9. 插件注册 — 仿照 `plugins/reports/plugin.py` 在 plugin_registry 挂载；`src/cndb/app.py` 无需改（若注册是自动发现则确认即可）。

**前端**

10. 类型契约 — `frontend/src/types/` 新增 `recordTasks.ts`（Task/Submission/FieldPreset/冲突明细 schema），与后端 Pydantic 对齐。
11. API client — 现有 api 目录加 `recordTasks.ts`。
12. 任务面板 — 新增 `TasksPage`（我的任务 / 我分派的 两个 tab，AntD Table + Tag 状态），路由级 `React.lazy`（遵守体积门禁，禁 manualChunks）。
13. 任务填写页 — 任务详情内嵌表单：按字段类型复用 GridPage 现有编辑控件渲染；预设/字段校验错误逐字段显示；提交前显示与 `base_row` 的 diff 摘要。
14. 审批对话框 — diff 三栏：baseline vs 提交值 vs 当前行值；冲突字段红色标注 + "以当前行为准跳过该字段"快捷操作（重提交 payload 去掉该字段）；approve/reject 必填意见仅 reject。
15. GridPage 409 处理 — `frontend/src/pages`（grid 目录）updateRow mutation 错误分支：409 时提示"行已被他人修改"并提供刷新对比；提交 PATCH 携带行 version（行数据从列表接口带出）。
16. records 列表接口透出 version — 后端行序列化加 `version` 字段（`src/cndb/plugins/tables` schemas + `src/types` 同步）。

**Workspace setup**

- 实施前运行 `git status --short` 与 `git branch --show-current`。
- 工作树干净且本计划将改代码/配置/测试：先询问用户是否建 worktree（`git worktree add -b codex/row-task-approval ../cndb-row-task-approval`）。
- 当前若在 `main`/`release/*`，默认推荐 worktree；若已 dirty，先保护现有改动，不混入本计划改动。

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| version 列迁移对存量数据回填 | 迁移内 `server_default='1'` + UPDATE 回填，SQLite/PG 双兼容写法；迁移后跑 seed 验证 |
| 审批落库与直编辑并发竞态（读 version 后、写库前行又变） | `update_row` WHERE 带 expected_version，DB 层兜底；冲突置 conflict 不丢数据 |
| 字段级合并语义被误读（用户以为全部自动合并） | AC-3 明确"仅双方都改的同一字段才冲突"；审批对话框对每个字段显示三方值，合并透明可见 |
| 新增插件跨插件 import 形成循环依赖 | record_tasks 只单向 import tables services；tables 不反向 import record_tasks；pyrefly 检查 |
| 任务面板新增 chunk 超体积门禁 | 路由级 React.lazy；完成后跑 `pnpm bundle:budget`，若超限同步更新 BASELINES 并注明原因 |
| 预设 regex 配置出错（非法表达式） | 保存预设时预编译校验，400 拒绝非法 regex |
| 提交人行数据在等待审批期间表结构变更（字段删除/改类型） | resolve_merge 时按当前 schema 重新 `validate_value`，校验失败置 conflict 而非静默丢字段 |

## Verification steps

- AC-1/2：后端 pytest 新增 `tests/`（record_tasks 目录）：create→submit→approve 全链路、非 assignee 提交 403、提交人自审 403、reject 后重新提交。
- AC-3：pytest 并发用例：基线漂移后审批（安全字段合并成功 / 冲突字段置 conflict）；行被删后审批置 conflict。
- AC-4：pytest：PATCH 带 `expected_version` 旧值返回 409 且 detail 含当前 version；不传行为与旧版一致（既有 2181 用例回归）。
- AC-5：pytest：预设 regex 不匹配、枚举越界各返回 400 字段级明细；submit 与 approve 两时机均触发。
- 前端：`pnpm check` + `pnpm test:coverage` + `pnpm build` + `pnpm bundle:budget`；新增任务面板组件测试（状态渲染、409 提示）。
- e2e：新增 `tests/e2e/` 用例走 分派→填写→提交→审批→行落库 全链路（复用 auth fixtures，test.skip setup/chromium-anon）。
- 全量：仓库根 `make check`（ruff + pyrefly + 后端覆盖率 95% + frontend-check）。

## Open questions

- 冲突（conflict 状态）的人工处理 UI 形态：复用审批对话框三栏 diff 让人手动裁决，还是先做"仅通知 + 重新发起任务"？**待用户复核**，默认决策：复用三栏对话框手动改 payload 后重新提交。
- 任务是否需要站内通知（铃铛/角标）：本计划用任务面板入口 + 数量徽标兜底，独立通知系统列为 Follow-up。

## ADR

- **Decision**：采用独立 `plugins/record_tasks` 插件 + 行表 version 乐观锁 + 三级冲突策略（乐观锁→字段级合并→conflict 人工兜底）+ 三层格式预设（字段 validate_value / 任务绑定预设模板 / 填写说明），落库统一走 records service。
- **Drivers**：数据一致性优先；与既有插件架构对称；前端复用编辑控件。
- **Alternatives considered**：Option A chosen；Option B（并入 tables）rejected——插件边界与膨胀；Option C（复用 workflows 节点图）rejected——无任务态机，特化成本高于新建。
- **Why chosen**：A 在职责隔离、可测试性、后续扩展空间上均优于 B/C，且跨插件调用落库复用保证了字段规范化与 audit 单一来源。
- **Consequences**：tables 插件新增 version 列（对所有行写路径可见，PATCH 语义向后兼容）；新增插件目录带来注册与迁移成本；审批落库延迟落库窗口内存在数据漂移，需依赖 conflict 兜底而非消灭它。
- **Follow-ups**：站内通知系统；批量分发（多 assignee）；conflict 任务批量裁决；预设模板库跨表复用。

## Review trail

- Planner draft v1：Option A favored；三级冲突 + 三层预设直接映射用户澄清答案。
- Architect challenge v1：steelman——"三级冲突比乐观锁全拒复杂 3 倍，是否值得？"→ 用户显式勾选三个口径，保留但要求合并算法抽纯函数 + DB 层 version 兜底；tension：落库延迟 vs 一致性——以 conflict 状态兜底而非消灭漂移；指出 v1 缺"表结构变更后提交"场景，补入 risks。
- Critic verdict v1：REVISE——①AC 无 conflict 处理闭环的 AC 项；②open question 的默认决策未标注"待用户复核"；③提交时机的版本快读语义含糊。
- Planner draft v2：补 AC-3 conflict 状态与不丢数据断言；提交时机语义改为"仅记录不阻断，裁决在审批时"；open question 标注待用户复核。
- Architect challenge v2：无新增 tension，认可纯函数 `resolve_merge` 可测性。
- Critic verdict v2：APPROVED，reservations 见下。
- Final iterations: 2 / 3

### Critic reservations（APPROVED 但保留）

- 步骤 2 `update_row` 冲突返回形态（异常 vs 元组）留了二选一，实施时需先看现有异常模式定案，避免半途混用两种风格（`src/cndb/plugins/tables/services/core/records.py`）。
- 批量分发未做但"分发"一词常隐含批量，若实施中发现分派体验明显不便，应回到本计划而非临场加接口。
- conflict 状态无过期/清理策略，长期堆积任务面板会变垃圾场；建议 Follow-up 加 cancelled-by-staleness 规则。
