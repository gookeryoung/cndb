# 项目功能清理（第三轮）Implementation Plan

> Status: APPROVED
> Source: user request（延续 req-05-cleanup-code-config-slimming 与 iter-02-redundancy-cleanup-round2 两轮清理）
> Mode: --deliberate（Phase 5 涉及公开 API 端点删除）
> Iterations: 2 / 3
> Author: dev-plan consensus loop
> Last updated: 2026-09-30

## Requirements summary

第三轮证据驱动清理，四个方向：① 修正 routers 层业务逻辑错位（reports 渲染器约 700 行、workspaces 备份导入 266 行违反项目分层规则）；② 消除第二轮漏网的跨文件/同文件重复（backup vs restore 逐行相同函数、members.py 两处表级管理员判断）；③ 删除确证的前端死代码（tableSettings 双实现遗留）；④ 清理前端已全量迁移至 import-file 后的 API 兼容层（import-csv 旧端点、include_data 参数）——第④项为公开 API 行为变更，设用户确认门，未确认不执行。

## Acceptance criteria

- AC-1: reports 渲染实现定居 `plugins/reports/services/`；`routers/reports.py` grep `_render_docx|_render_pdf|_render_xlsx|_render_html|_FORMAT_RENDERERS` 零命中；seed.py 导入路径不含下划线开头私有符号
- AC-2: `_import_backup_into_workspace` 实现定居 `plugins/workspaces/services/`；`routers/workspaces.py` 不再定义该函数、不含 `ddl_create` 直调
- AC-3: `_is_sqlite_url` / `_resolve_sqlite_path` 全仓库（src）仅一处定义，backup.py 与 restore.py 均从共享模块导入
- AC-4: `members.py` 中「表所有者或 WS ADMIN/OWNER」判断仅一处定义，transfer_owner 端点复用
- AC-5: 前端 `loadTableSettings|saveTableSettings|STORAGE_KEY` grep 零命中；`theme/tableSettings.test.ts` 收缩后前端测试全绿
- AC-6: （用户确认后）`/import-csv/analyze` 与 POST `/import-csv` 从代码、OpenAPI、前端 api 层零残留；`CsvAnalyzeResult|CsvImportResult` 类型零残留；旧端点测试按判据迁移完毕
- AC-7: （用户确认后）`include_data` 参数从 tables.py 移除，`mode` 参数三模式行为不变（既有表复制测试全绿）
- AC-8: 每 Phase 完成后 `make check` 全绿，覆盖率 ≥95% 不降（下降即回滚该 Phase）
- AC-9: 每个 Phase 独立 commit（中文 conventional message）；测试迁移与端点删除同一 commit

## RALPLAN-DR

### Principles

1. **行为不变优先**：Phase 1-4 保持 HTTP/CLI 契约逐字不变；行为变更仅限 Phase 5 且需用户显式确认
2. **证据驱动，存疑即弃**：只动已验证项；验证中语义存疑者（workspaces `_require_member` 的 404 掩蔽语义、`_detect_format` 输出推断 vs 输入识别）一律改判不动
3. **复用既有模式**：services 拆分对齐 tables 插件 `services/{core,importing}` 既有布局；不发明新抽象
4. **最小代码**：不为单一调用点抽公共层；功能完整、有测试、有间接消费的项（roles.py）不因「无 UI 入口」而删
5. **每 Phase 独立提交、独立回滚**，互不阻塞

### Decision drivers

- routers 层约 966 行业务逻辑（reports 700 + workspaces 266）违反分层规则，持续吸引新逻辑堆入
- 前端作为唯一 HTTP 客户端已全量迁移至 import-file 端点（`test_import_file_api.py` 19 用例覆盖），旧端点仅剩测试在消费
- 项目处 0.1.x 阶段，无对外 API 稳定承诺
- 测试安全网完备（cov ≥95% 门禁 + 既有端到端套件）

### Viable options

**Option A（选定）：全面清理 — 5 Phase**
- 分层修正（reports、workspaces）+ 重复消除（cli、members）+ 前端死代码 + API 兼容层删除（用户确认门）
- Pros：一步清完所有高证据项；API 面收敛；分层欠账一次还清
- Cons：改动面大；Phase 5 是行为变更，需用户确认；测试迁移成本（5 文件 19 处）

**Option B：仅行为不变项（Phase 1-4），API 删除另立后续需求**
- Pros：全程测试安全网内，零行为变更风险
- Cons（invalidation rationale）：「API 稳定性」论据被 0.1.x 版本承诺削弱；前端唯一客户端已迁移完毕、CLI 走 transfer 层函数不经 HTTP，证据已足够支持本轮删除；且用户诉求正是「功能清理」，推迟只增加一轮沟通成本

**Option C：仅 API/死代码删除（最小清理）**
- Pros：改动最小
- Cons（invalidation rationale）：放弃已验证的最高价值项——966 行 routers 层业务逻辑持续腐化，分层修正才是本轮主收益

## Implementation steps

### Phase 1 — reports 渲染器下沉 services 层（行为不变）

1. 新建 `src/cndb/plugins/reports/services/__init__.py` 与 `src/cndb/plugins/reports/services/rendering.py`
2. 迁入 `routers/reports.py:344-1047` 中纯渲染/数据装载逻辑：`_flatten_for_report`、`_load_table_records`(:369)、`_render_with_timeout`(:400)、`_MD_*` 正则(:433-438)、`_render_docx`(:441) 及 `_add_rich_runs`(:563)、`_cjk_font_candidates`(:593)、`_ensure_pdf_font`(:612)、`_render_pdf`(:653)、`cndb_report_header`(:771)、`_pdf_escape/_pdf_markdown_to_rml/_pdf_table_style_cmds/_make_pdf_table`(:778-808)、`_render_xlsx`(:822)、`_HTML_ESCAPE_RE/_html_escape/_html_rich_text`(:923-934)、`_render_html`(:942)、`_FORMAT_RENDERERS`(:1033)、`_render_filename`(:1048)
3. 符号公开化（去前导下划线）——seed.py:922-927 跨模块导入 `_FORMAT_RENDERERS/_jinja_env/_load_table_records/_render_with_timeout` 已证明它们是事实公共接口；seed.py 同步改公开导入路径
4. `routers/reports.py` 端点（`render_report` :1056 与预览端点）改为薄壳调用 services；`RENDER_TIMEOUT`(:37) 随迁
5. 注意：`_jinja_env` 与 PDF 字体探测为惰性缓存（模块级可变状态），迁移须保持惰性初始化语义，禁止改为 import 时初始化
6. 安全网：`tests/test_reports_plugin.py` 全量通过；`uv run cndb seed` 冒烟（渲染示例报告）

### Phase 2 — workspaces 备份导入逻辑下沉 services 层（行为不变）

1. 新建 `src/cndb/plugins/workspaces/services/__init__.py` 与 `src/cndb/plugins/workspaces/services/backup_import.py`
2. 迁入 `routers/workspaces.py:543-808` 的 `_import_backup_into_workspace`（版本校验、v4 跨表引用重映射收集器、逐表循环、视图/行导入），改公开名 `import_backup_into_workspace`
3. router 保留端点薄壳：权限校验 + 调用 services；跨插件导入（tables 的 models 与 ddl）随函数体整体迁移
4. 安全网：`tests/test_workspaces_plugin.py` 导入/导出套件全量通过

### Phase 3 — 跨模块重复消除（行为不变）

1. 新建 `src/cndb/cli/sqlite_url.py`：迁入 `_is_sqlite_url`（backup.py:102-105 = restore.py:124-127 逐行相同）与 `_resolve_sqlite_path`（backup.py:108-118 = restore.py:130-136 逐行相同），`backup.py`/`restore.py` 改导入
2. `plugins/tables/routers/members.py`：`transfer_owner` 端点（:263-274）的内联「owner 或 WS ADMIN/OWNER」查询判断改为复用 `_require_table_admin`（:24-46）——若两者入参形态有差异，以 `_require_table_admin` 为准调整调用点，403 detail 语义逐字保持
3. 安全网：`tests/test_backup*.py`、`tests/test_restore*.py`、members 相关套件全量通过

### Phase 4 — 前端死代码删除（行为不变）

1. 删 `frontend/src/theme/tableSettings.ts:31-49`：`STORAGE_KEY`、`loadTableSettings`、`saveTableSettings`（全 src 零生产引用；持久化已由 `store/tableSettings.ts` 的 zustand persist 以同一 key 接管）
2. 保留 `Density/NewRowPosition/TableSettings/DEFAULT_TABLE_SETTINGS/densityToSize`（6 个视图 + SettingsModal + gridTableSection 在用）
3. 收缩 `frontend/src/theme/tableSettings.test.ts`：删除对已删函数的用例
4. 验证：`make check`（含 frontend-check）；确认 localStorage 既有数据经 zustand persist 正常读取（同一 key，格式兼容）

### Phase 5 — API 兼容层删除（行为变更，用户确认门）

> 执行前须用户显式确认（暂停条件：删除对外 API 属高风险操作）。未确认则跳过本 Phase，其余交付不受影响。

1. **5a. import-csv 旧端点删除**：
   - 删 `routers/import_csv.py:188-279`：`AnalyzeRequest`、`ImportRequest`、`compat_router` 两端点、`__all__` re-export
   - 删 `routers/__init__.py:12` 的 compat_router 导入及 :31 的 include_router
   - 删前端 `api/importExport.ts:14-17`（`analyzeCsv`/`createFromCsv`）、`api/types.ts:361-362`（`CsvAnalyzeResult`/`CsvImportResult`）、`api/index.ts:38` 的 re-export
   - 测试迁移（5 文件 19 处：test_api_edge_cases.py、test_coverage_followup.py、test_cov_sprint.py、test_import_api_config.py、test_import_api.py、test_import_csv_api.py）：**判据**——该用例覆盖的业务规则（权限门槛 403/404、空 CSV 400、无效列名 400、建表成功路径）若 `test_import_file_api.py` 已有等价用例则删除，否则改写为 import-file 端点等价用例；迁移前后 `pytest --cov` 行覆盖对比，下降即回滚
   - 保留 `analyze_csv_columns`/`create_table_from_csv`（transfer 层，seed.py:108,154 及测试在用）
2. **5b. include_data 兼容参数删除**：
   - 删 `routers/tables.py:378`（参数）、:386（docstring 行）、:392-395（兼容分支）；前端零调用（已 grep 验证）
   - schema 中该参数定义同步删除；既有 mode 三模式测试全绿确认行为不变
3. CHANGELOG 追加 Removed 段记录两端点删除

### 明确不做（本轮验证后改判/维持）

| 项 | 结论 | 依据 |
|---|---|---|
| workspaces `_require_member`/`_require_admin` 收敛至 `check_workspace_permission` | 不动 | 语义不同：非成员前者 404 掩蔽（工作区存在性隐私），后者 403；测试 `in (403, 404)` 宽容但语义差异真实；单文件内聚 8 行，收敛收益低于行为风险 |
| roles.py 五端点 | 不动 | 功能完整、`test_roles_e2e.py` 15+ 处覆盖、members.py 间接消费 Role 模型；「无 UI 入口」≠ 死代码 |
| `_detect_format`(backup) vs `_detect_backup_format`(restore) 合并 | 不动 | 语义不同：输出路径推断（默认 directory）vs 输入源识别（先 is_dir，默认 archive） |
| seed.py 687 行 Jinja2 模板字符串 | 不动 | 内部 dev 数据、无重复、无引用耦合；拆分属可读性优化非清理（留 follow-up） |
| 前端骨架占位组件 2 处重复 | 不动 | 未达「三处相似才提取」阈值 |
| cov 测试 16 文件 | 不动 | 第二轮 AST 比对已证零重复，维持 |

## Workspace setup

- 实施前运行 `git status --short` + `git branch --show-current`（本 plan 编写时：clean + main）
- 按项目既有约定直接在 main 工作（历次迭代均 main 直接提交，不使用 worktree）；实施前若工作区变脏，按文件分批 add，不混轮次

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Phase 5 删除端点破坏未知局域网脚本消费者 | 用户确认门（暂停条件）；CHANGELOG Removed 段 + 迁移指引（import-file 等价端点）；0.1.x 无稳定承诺 |
| 渲染器迁移碰模块级可变状态（jinja env / PDF 字体缓存）导致行为或启动性能差异 | 保持惰性初始化；迁移前后 `test_reports_plugin.py` 全量 + seed 冒烟对比 |
| 测试迁移误删有效业务规则用例致 cov 下降 | 判据二值化（import-file 等价覆盖→删，否则→改写）；cov 门禁不降即回滚 |
| Phase 2 迁移中 SQLAlchemy 会话语义被破坏（原函数含 in_transaction/commit 时序注释） | 函数体整体迁移不改一行；导入/导出 e2e 套件全量验证 |
| members.py 判断合并改变 403 detail 文案 | 以 `_require_table_admin` 文案为准；既有断言测试逐字校验 |

## Verification steps

- AC-1：`grep -rn "_render_docx\|_FORMAT_RENDERERS" src/cndb/plugins/reports/routers/` 零命中；`uv run pyrefly check` 通过（seed.py 新导入路径类型正确）
- AC-2：`grep -n "_import_backup_into_workspace" src/cndb/plugins/workspaces/routers/workspaces.py` 零命中；`uv run pytest tests/test_workspaces_plugin.py -q` 全绿
- AC-3：`grep -rn "def _is_sqlite_url\|def _resolve_sqlite_path" src/` 各仅 1 处
- AC-4：members 转移所有权相关测试全绿（`tests/` 内 transfer/owner 相关 -k 筛选）
- AC-5：`grep -rn "loadTableSettings\|saveTableSettings" frontend/src` 零命中；`make check` 含 frontend-check 全绿
- AC-6/7：（用户确认后）`grep -rn "import-csv/analyze\|analyzeCsv\|CsvAnalyzeResult" src/ frontend/src/ tests/` 零命中；OpenAPI schema diff 确认端点消失；表复制测试全绿
- AC-8/9：每 Phase 后 `make check`；`git log --oneline` 确认 Phase 数量与 commit 对应
- 全量：收尾 `make check` 复核 → 按 Git 规范逐 Phase commit → `make push`

## Pre-mortem (deliberate)

1. **Scenario**：Phase 5 上线后，用户既有自动化脚本调用旧 import-csv 端点报 404，数据导入流程中断
   **Trigger**：局域网内未纳入仓库的自建脚本消费 `/api/v1/workspaces/{id}/import-csv`
   **Mitigation**：删除前用户确认门即为此设；CHANGELOG Removed 段附 import-file 迁移对照（multipart 上传替代 JSON body）；如用户确认存在脚本消费者，Phase 5 整体推迟并另立需求
2. **Scenario**：Phase 1 渲染器迁移后，PDF 导出中文乱码（字体探测缓存路径变化）
   **Trigger**：`_ensure_pdf_font` 的模块级缓存从 routers 包迁移至 services 包后初始化时序改变
   **Mitigation**：缓存逻辑随函数体原样迁移；`test_reports_plugin.py` 含中文渲染用例全量回归；seed 冒烟人工抽检导出产物
3. **Scenario**：Phase 2 导入逻辑迁移后，v4 备份跨表引用（link/lookup 重映射）静默丢失
   **Trigger**：迁移时误改 `pending_field_refs`/`pending_link_rows` 回填顺序或事务提交时序
   **Mitigation**：函数体整体搬移（零逻辑改动）；workspaces 导入 e2e（含 v4 跨表引用用例）全量通过方可提交

## Expanded test plan (deliberate)

- **Unit**：`cli/sqlite_url.py` 新增单测（sqlite 绝对/相对 URL 解析、非 sqlite scheme）；members 合并后权限判断单测（owner/ADMIN/OWNER/普通成员四分支）；reports services 渲染器函数级测试随迁移保持全绿
- **Integration**：`test_reports_plugin.py`（渲染导出四格式）、`test_workspaces_plugin.py`（导入导出 e2e 含 v4 重映射）、`test_backup*/test_restore*`（备份恢复往返）、`test_import_file_api.py`（Phase 5 迁移落点）
- **E2E**：前端导入流程手测（文件上传 → 分析 → 建表）；`uv run cndb seed` 冒烟后检查示例报告渲染
- **Observability**：无新增 metrics；API 删除记录于 CHANGELOG Removed 段；每 Phase commit message 中文 conventional 格式

## ADR

- **Decision**: 五 Phase 推进——reports/workspaces 业务逻辑下沉各自 services 层（符号公开化）、backup-restore 共享函数提取至 cli/sqlite_url.py、members 权限判断合一、前端 tableSettings 死代码删除、import-csv 兼容端点与 include_data 参数删除（用户确认门）；语义存疑项（workspaces 权限 helper、roles.py、_detect 系列）经验证后全部保留
- **Drivers**: 分层合规（routers 约 966 行业务逻辑）、前端唯一客户端已迁移（19 等价用例）、0.1.x 无 API 稳定承诺、测试安全网完备
- **Alternatives considered**: Option B（仅行为不变项）rejected——API 稳定性论据被版本承诺削弱，且未达用户核心诉求；Option C（仅 API 删除）rejected——放弃最高价值的分层修正
- **Why chosen**: 全部改动项均有 grep/调用计数/测试覆盖三级证据；行为变更收敛在单一 Phase 并设确认门，风险边界清晰
- **Consequences**: 正面——routers 层回归薄壳、API 面收敛、前端双实现消除；负面——Phase 5 删除后旧客户端（若有）断裂，须依赖 CHANGELOG 迁移指引；reports services 成为 seed.py 的正式依赖（原为私有符号跨模块导入，现为公开契约）
- **Follow-ups**: seed.py 687 行模板字符串拆分（可读性优化，另立需求）；roles 管理 UI 是否补齐（产品决策，进 `.trae/req/` 待办）

## Review trail

- Planner draft v1: Option A（全面清理）favored；Option B/C 列真候选后 invalidation
- Architect challenge v1: steelman「Phase 5 API 删除可能破坏局域网脚本消费者（req-09 证明存在局域网场景）」→ 采纳为用户确认门 + CHANGELOG 迁移指引；tension「workspaces `_require_member`（非成员 404 掩蔽）vs `check_workspace_permission`（非成员 403）语义不同，探查代理建议收敛」→ 验证测试断言 `in (403, 404)` 宽容但语义差异真实，判不收敛
- Critic verdict v1: REVISE——① 测试迁移策略「或删纯兼容用例」无二值判据；② roles.py 探查标记「前端孤儿」不成立（15+ e2e 测试、members.py 间接消费），须改判不动；③ `_detect_format` vs `_detect_backup_format` 探查称「相似」，实读后确认语义不同（输出推断 vs 输入识别），不能合并；④ backup/restore 共享函数落点未定
- Planner draft v2: 修复——迁移判据二值化（import-file 等价覆盖→删，否则→改写，cov 对比把关）；roles.py / _detect 系列 / workspaces 权限 helper 改判不动并入「明确不做」表；共享函数落点定为 `cli/sqlite_url.py`（两处使用，提取合理；不入 core 避免层级污染）
- Architect challenge v2: 确认修复；补充约束——渲染器迁移保持惰性初始化（防 CLI seed 启动变慢）、Phase 2 函数体整体搬移零逻辑改动（保事务时序）
- Critic verdict v2: APPROVED with improvements applied——迁移判据、不动项清单、惰性约束均已落文
- Final iterations: 2 / 3

## Reservations (Critic, 保留)

1. Phase 5a 的「前端是唯一 HTTP 客户端」基于仓库内证据（前端零调用、CLI 走 transfer 层）推断，局域网自建脚本无法从代码侧证伪——此即用户确认门存在的理由，执行前必须过门（见 Verification AC-6 前置条件）
2. Phase 3b members.py 合并后 403 detail 文案以 `_require_table_admin` 为准，若 `transfer_owner` 原文案与其有字面差异，既有测试若断言原文案会红——实施时以测试失败为信号核对语义而非放宽断言
