# 数据清洗与重复合并 实施计划

> Status: APPROVED
> Source: .claude/artifacts/designs/data-cleaning-merge.md（Status: ALIGNED）
> Mode: --deliberate（数据迁移 + 不可逆破坏性操作，自动升级）
> Iterations: 1 / 3
> Author: user
> Last updated: 2026-10-08

## Requirements summary

对已存表提供数据治理能力：重复检测（精确匹配）→ 人工确认 → 合并（字段级融合 + link 引用迁移 + 回收站）、in-place 清洗（复用导入侧 4 动作），并新增表级动作 MANAGE_DATA 纳入现有权限链路。所有治理操作异步任务化、强制预览确认、全量审计。

## Acceptance criteria

继承 spec AC-1 ~ AC-7（检测分组/合并融合与 link 迁移/清洗预览一致/权限 403/自定义 Role/10 万行 < 60s/make check 全绿），补充分解为可执行验证见「Verification steps」。

## RALPLAN-DR

### Principles

- 最小代码：只做 spec In scope，清洗动作只复用现有 4 种，不新增
- 复用现有抽象：回收站（trash_row）、link 物理表、AuditLog、线程任务模式、get_table_or_404 权限链
- 治理操作全部任务化 + 人工确认，无免确认自动模式
- 跨 DB（SQLite/PostgreSQL）语义一致：归一化在 Python 层做，不依赖方言函数

### Decision drivers

1. 数据安全（不可逆操作 → 预览 + 组内事务原子 + 回收站 + 审计）——决定性
2. 规模目标 50 万行 → 异步任务 + 分批扫描
3. 与现有权限体系一致（TableAction/Role/TablePermission 零破坏扩展）
4. 覆盖门禁 95% → 新增代码必须配测试

### Viable options

**Option A：独立治理模块（选定）**
- 新建 `services/governance/`（detect/merge/clean/tasks）+ `GovernanceTask` 表 + `routers/governance.py`；复用 records/links/audit 服务；从导入 cleaning.py 抽纯变换函数到共享层
- Pros：导入链路零风险；治理状态机独立演进；符合现有插件分层
- Cons：线程执行器与状态转换逻辑与 import_tasks.py 有约 60 行结构重复

**Option B：扩展 ImportTask 通用化**
- ImportTask 加 kind 列，import_tasks.py 执行器泛化承担治理任务
- Pros：无重复基础设施
- Cons：ImportTask 携带大量导入专属字段（file_content/match_keys/cleaning_actions），治理混入污染语义；需改动热路径（导入），迁移风险更高；状态机转换矩阵需重写兼容两种 kind

**Option C：同步 API 无任务表**
- 淘汰（invalidation rationale）：50 万行检测远超请求超时，无法进度轮询，违反 Decision driver 2；spec 明确异步任务

### Architect challenge（Steelman + Tensions）

**Steelman against A**：两套任务状态机（import_tasks `_VALID_TRANSITIONS` 与 governance 状态机）并行漂移，后续修 bug 要改两处。若反驳成立应改为 B。
**回应**：B 需改动导入热路径 + 对已有表做列迁移，风险不对称；重复的 60 行是结构模板而非业务逻辑，且项目规则「三处相似才提取」——等第三个任务型需求出现再统一执行器（记入 Follow-ups）。

**Tradeoff tension 1 —— 统一任务化 vs 小表同步清洗**：小表（<1k 行）清洗同步返回更简单。取舍：统一任务化，理由是审计/进度/失败重试语义一致，且执行器已存在，边际成本低。

**Tradeoff tension 2 —— 预览精确性 vs 性能**：合并预览（组成员+键值）来自检测报告，精确；清洗预览受影响行数若全表统计则大表慢。取舍：清洗受影响计数用分批扫描累计（与执行同一路径），预览样例仅取前 3 条，不做全表预计算。

**Synthesis**：A 为主体 + 从 import_tasks.py 提取的执行器骨架以复制-适配方式落地（不反向改动导入模块）。

### Critic verdict

| 维度 | 状态 | 备注 |
|---|---|---|
| Principle consistency | ✓ | A 与全部 4 条 principles 一致 |
| Alternative exploration | ✓ | C 有显式淘汰理由，B 有真实 tradeoff 非陪跑 |
| Risk mitigation clarity | ✓ | 每条 risk 有对应 mitigation 行 |
| AC testability | ✓ | AC-1~7 均二值可验证 |
| Verification concreteness | ✓ | 验证命令具体到测试文件 |
| File/line coverage | ✓ | 步骤 100% cite 具体文件 |

### Verdict: APPROVED（2 条 Reservation 已合入实施步骤 5/9）

Reservations：
- 「同一张表并发多个治理任务会互相踩踏」→ 已加入步骤 5（同表同时仅允许一个 active 任务，创建时校验）
- 「检测后被外部修改的行如何判定」→ 已明确为合并时重读行校验判重键值仍相等，不等则跳过该组并写入报告

## Implementation steps

分 4 个阶段交付（每阶段独立通过 make check）。

### 阶段 1：权限与数据模型

1. Alembic 迁移 — 新增 revision（参照 [f3a4b5c6d7e8_add_import_task_cleaning_actions.py](file:///f:/Dev/cndb/alembic/versions/f3a4b5c6d7e8_add_import_task_cleaning_actions.py) 模板）：`tables_tablepermission` 加 `manage_data_role String(16) NOT NULL DEFAULT ""`；新建 `tables_governancetask`（table_id FK CASCADE / user_id FK SET NULL / kind String(16) detect|merge|clean / status String(32) index / progress Integer / config JSON / report Text / error_message Text / total_groups Integer / done_groups Integer）
2. 模型 — [models.py:290-293](file:///f:/Dev/cndb/src/cndb/plugins/tables/models.py#L290-L293) TablePermission 加 `manage_data_role` 列；同文件 ImportTask 之后新增 `GovernanceTask` 声明式模型并加入 `__all__`
3. 动作枚举 — [access.py:20-27](file:///f:/Dev/cndb/src/cndb/plugins/tables/services/core/access.py#L20-L27) `TableAction` 加 `MANAGE_DATA = "MANAGE_DATA"`；[access.py:30-35](file:///f:/Dev/cndb/src/cndb/plugins/tables/services/core/access.py#L30-L35) `_ACTION_PERMISSION_FIELD` 加映射；[access.py:38-43](file:///f:/Dev/cndb/src/cndb/plugins/tables/services/core/access.py#L38-L43) `_ACTION_DEFAULT_ROLE[MANAGE_DATA] = WorkspaceRole.ADMIN`
4. 角色权限位 — [workspaces/models.py:23-28](file:///f:/Dev/cndb/src/cndb/plugins/workspaces/models.py#L23-L28) `ACTION_KEYS` 追加 `MANAGE_DATA`；[workspaces/models.py:31-36](file:///f:/Dev/cndb/src/cndb/plugins/workspaces/models.py#L31-L36) `ACTION_LABELS` 加 `"MANAGE_DATA": "数据治理（合并/清洗）"`；Role.ensure_permissions 自动补位，无需改

### 阶段 2：治理服务层

5. 任务执行器 — 新建 `src/cndb/plugins/tables/services/governance/tasks.py`：`GovernanceTaskError` / `create_governance_task`（校验同表无 active 任务，违反返回 400 语义）/ `_transition_status`（状态机 pending → running → done/failed）/ `run_governance_task_in_background`（复制-适配 [import_tasks.py:423-452](file:///f:/Dev/cndb/src/cndb/plugins/tables/services/importing/import_tasks.py#L423-L452) 的线程 + session factory 模式）
6. 检测 — 新建 `governance/detect.py`：`DuplicateDetector` 协议（`detect(table, fields, options) -> 报告`）+ `ExactMatcher` 实现；按 id 分页扫描（每批 5000 行），Python 层归一化判重键（casefold + strip，可选项控制），dict 分组只存键与行 id（不持有全行）；产出报告 JSON（组列表：member_row_ids + match_key_values），写 task.report；策略接口预留模糊扩展
7. 合并 — 新建 `governance/merge.py`：`execute_merge_task` 逐组执行——(a) 重读组内行校验判重键值仍相等，不等则跳过并记入报告；(b) 保留行按 SurvivorshipRule（non_empty_first/latest/oldest/manual）融合非判重字段（复用 records.update_row 的写路径语义）；(c) 其余行复用 [records.py trash_row 语义](file:///f:/Dev/cndb/src/cndb/plugins/tables/services/core/records.py#L537-L559) 置 `_trashed`；(d) link 迁移：遍历全工作区引用该表的 link 字段物理表，`UPDATE {link_table} SET target_row_id = survivor WHERE target_row_id = merged_id`（批量、复用 [links.py conn 复用模式](file:///f:/Dev/cndb/src/cndb/plugins/tables/services/core/links.py#L45-L80)；组内自引用不迁移）；(e) 单组事务原子（组内失败整组回滚，任务级继续下一组）；(f) 每组 [audit log_action](file:///f:/Dev/cndb/src/cndb/plugins/tables/services/core/audit.py) action=merge 记录配置快照
8. 清洗共享层 — 新建 `src/cndb/plugins/tables/services/cleaning_core.py`：从 [cleaning.py:227-381](file:///f:/Dev/cndb/src/cndb/plugins/tables/services/importing/cleaning.py#L227-L381) 抽出 `_apply_trim`/`_apply_coerce`（含 `_coerce_value`）/`_apply_fill_null` 值变换为纯函数；[cleaning.py](file:///f:/Dev/cndb/src/cndb/plugins/tables/services/importing/cleaning.py) 改为导入复用（导入链路行为不变）
9. 已存表清洗 — 新建 `governance/clean.py`：对选定列做分批统计（fill_null 的 mean/median、drop_outliers 的 IQR 阈值实时计算）→ 生成预览样例（前 3 条 before/after）→ 确认后按 id 分批 SELECT → cleaning_core 变换 → 仅 UPDATE 值变化的行 → audit action=clean
10. Pydantic schemas — 新建 `src/cndb/plugins/tables/schemas/governance.py`：DetectRequest（match_fields: list[str]，ignore_case/ignore_whitespace: bool）/ MergeRequest（groups: 每组 survivor_row_id + 字段策略）/ CleanRequest（actions: 复用 cleaning_actions 结构）/ GovernanceTaskOut（含 response_model）

### 阶段 3：API 与前端

11. 路由 — 新建 `src/cndb/plugins/tables/routers/governance.py`：前缀 `/{workspace_id}/tables/{table_id}/governance`，端点 `POST detect` / `POST merge` / `POST clean`（均为建任务 + 后台执行）/ `GET tasks/{task_id}`（状态/进度）/ `GET tasks/{task_id}/report`（重复组分页 + 清洗结果）；全部经 [get_table_or_404(action=MANAGE_DATA)](file:///f:/Dev/cndb/src/cndb/plugins/tables/services/core/access.py#L152-L185) 校验；在 tables 插件 [plugin.py](file:///f:/Dev/cndb/src/cndb/plugins/tables/plugin.py) 注册 router
12. 权限设置 API — [routers/permissions.py](file:///f:/Dev/cndb/src/cndb/plugins/tables/routers/permissions.py) 的读写 schema 加 `manage_data_role` 字段（沿用既有模式）
13. 前端类型 — [frontend/src/api/types.ts](file:///f:/Dev/cndb/frontend/src/api/types.ts) 加 GovernanceTask/DetectRequest/MergeRequest/CleanRequest 接口；[frontend/src/api/tables.ts](file:///f:/Dev/cndb/frontend/src/api/tables.ts) 或新建 governance.ts 加 API 封装
14. 前端页面 — `frontend/src/components/` 或 `pages/` 下新增「数据治理」面板：检测配置（判重字段多选 + 忽略选项）→ 重复组确认（组列表 + 保留行选择 + 字段策略）→ 清洗配置（4 动作勾选 + 预览）→ 进度轮询（复用导入任务轮询 hook 模式）；表工具栏加入口；权限设置面板加「数据治理」角色阈值下拉

### 阶段 4：测试与文档

15. 后端测试 — 新建 `tests/test_governance_detect.py`（分组正确性/忽略选项/空表）/ `test_governance_merge.py`（融合策略 4 种/link 迁移/回收站可恢复/组内原子回滚/键值漂移跳过）/ `test_governance_clean.py`（4 动作/预览一致）/ `test_governance_permissions.py`（403 矩阵/自定义 Role/表拥有者）
16. 设计文档 — 新建 `.trae/designs/data-governance.md`（接口定义/数据模型/状态机/权限语义/审计约定），迭代完成后与代码同步

## Workspace setup

- 实施前运行 `git status --short` 和 `git branch --show-current`
- working tree 干净时询问用户是否建 worktree：`git worktree add -b codex/data-governance ../cndb-data-governance`
- 当前若在 main 分支默认推荐 worktree；tree 脏则先保护现有改动，不混入本 plan 改动

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| 并发治理任务互相踩踏 | create_governance_task 校验同表仅一个 active 任务（步骤 5） |
| 检测后行被外部修改导致错合并 | 合并时重读行校验判重键值，漂移组跳过并记入报告（步骤 7） |
| 大表扫描内存膨胀 | 分页扫描只存键与行 id，不持有全行（步骤 6） |
| link 迁移遗漏（跨表引用） | 遍历全工作区 link 字段物理表定位入向引用（步骤 7） |
| 共享层重构破坏导入行为 | cleaning_core 只移纯函数，导入侧改导入路径；现有导入测试回归验证（步骤 8） |
| 权限迁移遗漏 | MANAGE_DATA 为纯新增动作，不改既有动作判定；测试覆盖 403 矩阵（步骤 15） |
| 回收站膨胀 | 复用既有回收站机制与清理策略，不新建清理逻辑 |

## Verification steps

- AC-1（检测）：`uv run pytest tests/test_governance_detect.py -v`——含 ignore_case 参数化用例
- AC-2（合并）：`uv run pytest tests/test_governance_merge.py -v`——覆盖融合/link 迁移/恢复/审计断言
- AC-3（清洗）：`uv run pytest tests/test_governance_clean.py -v`——预览与结果一致断言
- AC-4/5（权限）：`uv run pytest tests/test_governance_permissions.py -v`
- AC-6（性能）：`uv run python scripts/bench_10k_rows.py` 模式新建 `scripts/bench_governance_detect.py`，10 万行 PostgreSQL 检测 < 60s
- AC-7（门禁）：`make check`（lint + typecheck + cov ≥ 95%）
- 导入回归：`uv run pytest tests/ -k import` 确认共享层重构无破坏

## Pre-mortem

1. **Scenario**：合并执行到一半进程崩溃，组内一半行已 trash
   **Trigger**：部署重启 / OOM kill
   **Mitigation**：单组事务原子（步骤 7e），崩溃后该组回滚，任务标 failed 可重建；已 trash 行可从回收站恢复
2. **Scenario**：管理员把 MANAGE_DATA 阈值降到 VIEWER，普通成员批量清洗生产表
   **Trigger**：权限面板误配置
   **Mitigation**：AuditLog 全量记录 actor + 配置快照可追溯；默认阈值 ADMIN；预览确认步骤提供二次防线
3. **Scenario**：共享层重构后导入清洗行为回归
   **Trigger**：cleaning.py 改导入路径时语义偏差
   **Mitigation**：只移纯函数不改逻辑；`pytest -k import` 回归门禁（Verification 最后一条）

## Expanded test plan

- **Unit**：detect 归一化键函数、merge SurvivorshipRule 4 策略、clean 阈值计算（IQR/mean/median）纯函数级测试
- **Integration**：API 级（TestClient）全流程 detect→merge/clean，含 403 矩阵与并发任务 400
- **E2E**：Playwright 增补治理向导冒烟路径（可选，跟随现有 e2e 套件节奏）
- **Observability**：治理任务 progress/total_groups 轮询；失败写 task.error_message；audit 表可查 merge/clean 历史

## ADR

- **Decision**：采用 Option A——独立 `services/governance/` 模块 + `GovernanceTask` 表，复用回收站/link/audit/线程任务既有设施，清洗动作抽 `cleaning_core.py` 共享层
- **Drivers**：数据安全（决定性）、规模异步化、权限零破坏、覆盖门禁
- **Alternatives**：Option B（ImportTask 通用化）rejected——污染导入热路径与任务语义，迁移风险不对称；Option C（同步 API）rejected——无法满足规模与进度轮询
- **Why chosen**：导入链路零风险、治理状态机独立演进、改动面全部落在新增文件与一处枚举/权限扩展，符合最小代码与外科手术原则
- **Consequences**：+ 导入与治理互不影响，权限链路统一走 check_action；− 任务执行器存在 ~60 行结构重复（记录于 Follow-ups）
- **Follow-ups**：第三个任务型需求出现时提取通用任务执行器基座；模糊判重（DuplicateDetector 扩展）；清洗「标准化」动作（大小写/日期归一化）——均对应 spec Open questions，不随本次实现

## Review trail

- Planner draft v1：Option A/B/C 三选，A favored
- Architect challenge v1：steelman 指出双状态机漂移风险 → 以「三处相似才提取」回应并记 Follow-up；新增 2 条 tradeoff tension 及取舍
- Critic verdict v1：APPROVED + 2 reservations（并发任务防护、键值漂移校验）→ 已合入步骤 5/7
- Final iterations: 1 / 3
