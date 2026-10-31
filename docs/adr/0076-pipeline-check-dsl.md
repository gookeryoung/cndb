# ADR 0076: 流水线检查系统与专用 DSL（数据表 / 文档质量检查 + 可扩展检查动作注册表）

Status: Proposed（待评审）
Date: 2026-10-31
Related: `src/cndb/plugins/tables/services/governance/detect.py`、`src/cndb/plugins/documents/services/charts/inline.py`、`src/cndb/core/events.py`、`docs/adr/0004-row-level-permission-rules.md`、`docs/adr/0020-llm-platform-capability.md`、`docs/adr/0075-workspace-full-backup.md`
需求卡片: `docs/requirements/0076-pipeline-check-dsl.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 参照 GitHub Actions 工作流形态 | DSL 采用 YAML 子集：`name` / `on`（触发器）/ `jobs`（作业 DAG：`needs` / `if`）/ `steps`（`uses:` 动作 + `with:` 参数 + `severity` / `continue-on-error`）；表达式用 `${{ }}` 白名单子集（D3） |
| C2 | 完整系统闭环 | 新插件 `src/cndb/plugins/pipeline/`：`pipeline_workflow` / `pipeline_run` / `pipeline_finding` 三表 + 后台执行器（单飞）+ REST API + 前端工作区页签「质量检查」（`/w/:wid/pipelines`） |
| C3 | 专用声明式 DSL | `pipeline/services/dsl/`：YAML 文本入库，保存期编译为校验过的 IR（JSON）；表达式为递归下降求值的白名单子集，无 eval、无任意代码 |
| C4 | 数据表检查族 | `pipeline/checks/table/`：`table/null-rate`、`table/duplicates`、`table/value-range`、`table/stale`；字段类型语义复用 `tables.field_types.default_registry`，判重归一化复用治理 `normalize_match_value` |
| C5 | 文档检查族 | `pipeline/checks/document/`：`document/broken-refs`（图表 / 数据表 / 附件引用失效）、`document/chart-blocks`（复用 `validate_document_blocks` 口径）、`document/links`（站内 wikilink 与 `file:` 引用登记） |
| C6 | 预留更多格式 | 扩展点唯一：检查动作注册表（`域/动作` 命名空间 + 输入 schema）；只读目录端点 `GET /pipelines/checks`；新格式零引擎改动接入（对标图表模板注册表与 LLM 动作目录范式） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 治理任务（重复检测 / 合并 / 清洗）是**单表单任务**模型：建 `GovernanceTask` 后台执行，报告写 `task.report`（JSON 字符串） | `src/cndb/plugins/tables/services/governance/tasks.py:55`、`models.py:595` | 只能一次跑一个动作、无编排（依赖 / 条件 / 多域混合）、结果不可按严重度过滤 | 确认：判重归一化逻辑（`governance/detect.py:44` `normalize_match_value`）被 `table/duplicates` 复用；任务模型不扩展，流水线独立建模 |
| 2 | 图表块校验（单块 32KB / 单篇 50 块 / 坏块降级）硬编码在文档保存与渲染路径 | `src/cndb/plugins/documents/services/charts/inline.py:29`、`inline.py:255` `validate_document_blocks` | 上限不可配置、不能按工作区自定义策略、无历史报告 | 确认：`document/chart-blocks` 检查复用同一常量口径并允许 `with` 覆盖；原硬校验保留（渲染兜底） |
| 3 | 导入期校验报告只在导入时刻生成一次 | `src/cndb/plugins/tables/services/importing/importer.py:172` `analyze` | 无法回答"现在这张表合不合格" | 排除：时点不同，不作为运行期检查的执行载体，仅口径参考 |
| 4 | 统一事件流 `core_event` 提供"域.动作"留痕与查询 | `src/cndb/core/events.py:139` `record_event` | 触发留痕有现成载体 | 新增：新增 `pipeline.run` 动作常量；每次运行留一条事件 |
| 5 | 行级权限有唯一判定入口，规则引用隐藏字段会被静默剔除（侧信道保护） | `src/cndb/plugins/tables/services/core/row_access.py` | 检查若按个人视角运行，结果随触发人权限漂移，质量口径不稳定 | 新增：检查按工作区视角运行（D13），finding 不携带字段值 |
| 6 | 数据源同步用 DB 租约保证同任务单飞（409） | `src/cndb/plugins/datasource/services/runner.py:125` | 并发单飞有范式可循 | 新增：workflow 级单飞沿用同一语义（P0 简化为状态检查 + 行锁，D8） |
| 7 | 工作区全量备份明确排除流水类数据（审计 / 同步运行历史等） | `docs/adr/0075-workspace-full-backup.md` | workflow 属工作区配置还是流水需定口径 | 新增：workflow 进备份（P2，backup v10），run / finding 不进（D12） |
| 8 | 工作区级功能页签（数据分析 / 数据源同步 / 文档等）由前端布局挂载 | `frontend/src/layouts/MainLayout.tsx` | 新页签有现成挂载点 | 新增：「质量检查」页签 |
| 9 | 注册表 + 目录端点范式已有两处先例（图表模板、LLM 动作） | `src/cndb/plugins/documents/services/charts/registry.py`、`src/cndb/plugins/llm/`（`GET /api/v1/llm/actions`） | 检查动作注册表可直接对标 | 新增：DSL 的 `uses:` 与目录端点复用该范式 |

**核心缺陷（需求要补的）**：现状没有任何机制能让用户**声明式地编排一套跨数据表与文档的质量检查规则并在任意时刻运行、留下结构化、可过滤的历史报告**——检查能力散落在导入 / 保存 / 渲染路径里，硬编码、不可配置、不可编排。

设计目标（不变量）：

- **I1 检查只读**：检查动作的执行上下文不暴露任何写路径 API；任何检查不得修改业务数据（自动修复不在本设计范围）。
- **I2 保存即校验**：YAML 在保存 / 更新时完整编译为 IR，未知 `uses:` / 非法 `with:` / 非法表达式即时拒绝（400）；运行期只可能出现业务数据层面的发现，不出现语法 / 结构错误。
- **I3 唯一执行入口**：手动、事件、定时三类触发全部经 `run_pipeline(...)` 一个入口，先建 `pipeline_run` 记录再后台执行。
- **I4 结论单一判定**：run / job / step 状态只由「finding 严重度 + step outcome」按 D9 的映射推导，不存在第二套判定口径。
- **I5 注册表扩展**：执行引擎不包含任何领域检查逻辑；新检测格式 = 在注册表登记新动作，DSL `uses:` 直接可用，引擎零改动。
- **I6 单飞**：同一 workflow 同时只允许一个 `running` run（重复触发 409）。

## Decision

### 1. 数据模型

新插件 `src/cndb/plugins/pipeline/`，三张表（均 `TimestampMixin` + 工作区级 `workspace_id` 外键 `ondelete="CASCADE"`）：

**`pipeline_workflow`** —— 流水线定义：

| 列 | 类型 | 说明 |
|---|---|---|
| `workspace_id` | FK(workspaces_workspace) | 工作区级，级联删除 |
| `name` | String(120) | 同工作区内唯一（`UniqueConstraint(workspace_id, name)`） |
| `content` | Text | DSL 原文（YAML），用户可读可编辑的唯一真相源 |
| `compiled` | JSON | 保存期编译出的 IR 快照（校验通过才可落库）；运行读 IR，不重新解析 YAML |
| `enabled` | bool | 关闭后事件 / 定时触发不再命中（手动仍可显式运行） |
| `created_by` | FK(accounts_user, SET NULL) | 创建人 |

**`pipeline_run`** —— 一次运行：

| 列 | 类型 | 说明 |
|---|---|---|
| `workflow_id` | FK(pipeline_workflow) CASCADE | 所属定义 |
| `workspace_id` | FK | 冗余便于工作区级过滤 |
| `trigger` | String(16) | `manual` / `event` / `schedule` |
| `trigger_payload` | JSON | 事件触发时的上下文（如 `{table_id, event}`），供 `if:` 表达式消费 |
| `status` | String(16) | `pending` / `running` / `success` / `partial` / `failed` / `canceled`，索引 |
| `stats` | JSON | 汇总：`{jobs_total, jobs_done, steps_total, findings: {error, warn, info}, duration_ms}` |
| `error_message` | Text | 引擎级错误（非 finding） |

**`pipeline_finding`** —— 结构化发现物（对标 GitHub check run 的 annotation）：

| 列 | 类型 | 说明 |
|---|---|---|
| `run_id` | FK(pipeline_run) CASCADE | 所属运行 |
| `check` | String(64) | 产生该发现的动作名（如 `table/null-rate`） |
| `severity` | String(8) | `error` / `warn` / `info`，索引 |
| `target_type` | String(16) | `table` / `document` / `field` |
| `target_id` | Integer | 表 ID / 文档 ID（定位到行级用 `locator`） |
| `locator` | JSON | 精确定位：`{field_name, row_id, block_index, ref}` 等；**不含字段值**（D7） |
| `message` | String(500) | 人类可读中文描述 |
| `detail` | JSON | 数值明细（如 `{rate: 0.08, limit: 0.05}`），不含业务数据值 |

每次运行每检查动作的 finding 上限 1000 条，超出聚合为一条 `info`（"另有 N 条同类发现被截断"，对齐数据源失败明细有界口径）。

### 2. DSL 规范与判定算法（唯一入口）

**DSL 语法（YAML 子集）**：

```yaml
name: 每日数据质量巡检
on:
  manual: true                      # P0
  events: [record.updated, document.saved, sync.finished]   # P1
  schedule: "0 6 * * *"             # P2（cron 表达式）

vars:
  max_null_rate: 0.05

jobs:
  表基础体检:                        # job id（中文可用），同 GitHub job key
    steps:
      - uses: table/null-rate        # 动作名 = 域/动作（注册表键）
        with:
          fields: all                # 或 [字段名, ...]
          max_rate: ${{ vars.max_null_rate }}
        severity: warn               # 该步产生发现的默认严重度
        continue-on-error: true      # error 也不阻断本作业
      - uses: table/duplicates
        with:
          fields: [交易日, 股票代码]

  文档引用体检:
    needs: 表基础体检                 # DAG：上游失败则本作业 skipped
    if: ${{ jobs.表基础体检.conclusion == 'success' }}
    steps:
      - uses: document/broken-refs
        with:
          scopes: [chart, table, file]
```

**编译层**（`pipeline/services/dsl/`）：

- `parse.py`：YAML → 结构校验（未知顶层键 / job 键 / step 键拒绝；`needs` 无环、引用存在的 job；`uses` 必须命中注册表；`with` 逐键对齐动作 schema——多余 / 缺失 / 类型不符拒绝）；产出 IR（JSON）。
- `expressions.py`：`${{ }}` 白名单表达式——字面量、`vars.*` / `on.*`（触发上下文）/ `jobs.<id>.conclusion`，运算 `== != < <= > >= && || !`，函数白名单 `len() contains() startswith() endswith() to_number()`；递归下降解析求值，**不用 eval / Jinja2**（D3）。求值失败按 `false` 处理并在 run 记 warning（不静默）。

**执行器**（`pipeline/services/runner.py`，I3 唯一入口 `run_pipeline(session_factory, workflow, trigger, payload)`）：

1. 单飞检查（I6）：`UPDATE ... SET status='running' WHERE id=? AND status!='running'` 抢占失败 → 409；
2. 建 run（`pending` → `running`），后台线程执行（复用治理任务的 `run_governance_task_in_background` 模式，`governance/tasks.py:148`）；
3. job 按拓扑序执行（`needs` 失败 → `skipped`）；job 内 step 顺序执行；
4. step：从注册表取动作 → 以 IR 中的 `with`（已过 schema 校验）构造上下文 → 执行（只读，I1）→ 收集 finding；
5. 结论推导（I4，D9）：step 有 `error` 级 finding 且未 `continue-on-error` → step `failed` → job `failed` → run `failed`；有 `warn` / `info` → run `partial`（若无 error）；全无 → `success`；`skipped` job 不影响结论；
6. 收尾：`stats` 汇总落库、`core_event("pipeline.run")` 留痕、WAL 收尾检查点（复用 `core/database.checkpoint_wal()`，SQLite 场景）。

**检查上下文（只读）**：`CheckContext` 只暴露 `db`（只读 session）、`workspace`、目标解析器（按 `target` 取表 / 文档）与有界扫描器（单次扫描行数上限对齐 `ANALYTICS_MAX_SCAN_ROWS` 口径，超出按采样并在 finding `detail.truncated=true` 标注）。无任何写 API。

### 3. 检查动作注册表（扩展点，I5）

`pipeline/checks/`，对标图表模板注册表（`charts/registry.py`）与 LLM 动作目录（ADR 0020）：

- `base.py`：`CheckSpec`（`name`（`域/动作`）/ `title` / `category` / 输入 schema（声明式 dict，同 `viewOptionSchema` 思路）/ 默认 `severity` / 目标类型）+ `register_check` / `iter_checks`；
- `table/`：`null-rate`（空值率）、`duplicates`（复用 `normalize_match_value`）、`value-range`（数值 / 日期区间，经 `default_registry` 类型语义）、`stale`（时间字段距今最大天数）；
- `document/`：`broken-refs`（`{{chart:}}` / `{{table:}}` / `file:` 引用解析失效，复用 `charts/inline.py` 解析器与 `content.load_content`）、`chart-blocks`（上限 / 坏块，复用 `validate_document_blocks` 口径且 `with` 可覆盖上限）、`links`（wikilink 指向软删 / 不存在文档，复用 `resolve_outgoing_links`）。

未来格式（图表素材库、附件、仪表盘、外部数据源新鲜度等）各占一个新命名空间（如 `attachment/*`），注册即接入，DSL 与引擎零改动。

### 4. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/pipelines` | 新增：列表（含最近一次 run 状态） |
| `POST /api/v1/workspaces/{wid}/pipelines` | 新增：创建（YAML 入参，保存期编译校验，失败 400 带行级错误信息） |
| `GET / PUT / DELETE /workspaces/{wid}/pipelines/{pid}` | 新增：详情（含 IR）/ 更新（重编译）/ 删除（级联 run） |
| `POST /workspaces/{wid}/pipelines/validate` | 新增：纯编译校验（不落库，编辑器实时校验用） |
| `GET /workspaces/{wid}/pipelines/checks` | 新增：只读检查动作目录（对标 `GET /api/v1/llm/actions`） |
| `POST /workspaces/{wid}/pipelines/{pid}/run` | 新增：手动触发（202，单飞冲突 409，后台执行） |
| `GET /workspaces/{wid}/pipelines/{pid}/runs` | 新增：运行历史（分页） |
| `GET /workspaces/{wid}/pipeline-runs/{rid}` | 新增：运行详情（job / step 结论树 + finding 汇总） |
| `GET /workspaces/{wid}/pipeline-runs/{rid}/findings` | 新增：发现物列表（`severity` / `target_type` / `check` 过滤，分页） |

权限（D10）：workflow CRUD 与运行触发要求 owner / editor；run 与 finding 查看为工作区成员（viewer 只读）。

### 5. 边界与例外

1. 大表扫描有界：单检查扫描行数超上限按采样执行，finding `detail.truncated=true` 标注，不静默、不无限扫。
2. 软删 / 归档文档不进检查范围（与搜索 / 分享口径一致）。
3. 表达式求值失败按 `false` 处理，run 记 warning；不中断运行。
4. 检查实现抛异常 → 该 step `failed` + `error_message`，不牵连其他 step / job（引擎级隔离）。
5. finding 有界（每检查 1000 条，超出聚合一条 `info`）。
6. `enabled=false` 的 workflow 不响应事件 / 定时触发，但显式手动运行允许（调试语义）。
7. finding 不携带字段值与单元格内容，仅字段名 / 行 ID / 计数 / 阈值（D7 侧信道口径）。
8. 不做自动修复、不做"检查失败阻断写入"（本期纯检测；阻断属独立需求另行立项）。

### 6. 迁移

单条 alembic 迁移 `y3z4a5b6c7d8_add_pipeline_plugin.py`（`down_revision = "x2y3z4a5b6c7"`）：建三张表（含索引与唯一约束），幂等；downgrade 按依赖序 DROP 三表。存量零迁移（纯新增表，无既有列变更）。

### 7. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 页签挂载 | `frontend/src/layouts/MainLayout.tsx` | 工作区页签新增「质量检查」（工作区类型 `data_doc` / `data` 显示） |
| 页面 | `frontend/src/pages/pipelines/PipelinesPage.tsx` | 流水线列表（名称 / 启用 / 最近运行状态）+ 新建 / 编辑抽屉（YAML 文本编辑 + `POST /pipelines/validate` 实时校验错误展示） |
| 运行详情 | `frontend/src/pages/pipelines/PipelineRunDetail.tsx` | job / step 结论树（GitHub Actions 运行页形态）+ finding 表（severity 筛选）+ 触发按钮（409 提示） |
| 检查目录 | `frontend/src/pages/pipelines/checkCatalog.ts` | 动作目录静态描述（`uses:` 插入辅助），数据以目录端点为准 |
| API 封装 | `frontend/src/api/pipelines.ts` | 上述端点的客户端封装 |

### 8. 测试清单

**判定层（单测）**：DSL 解析合法 / 非法样例矩阵（未知键、环 `needs`、未知 `uses`、`with` schema 不符、表达式语法错）；表达式求值（运算符、函数白名单、注入样例仅按字面量处理）；DAG 结论推导（error / continue-on-error / skipped / partial 各路径）；注册表（注册 / 查找 / 目录序列化）；四类 table 检查（构造小表数据断言 finding）；三类 document 检查（坏引用 / 超限块 / 失效 wikilink）；finding 截断与扫描上限。

**接口层**：CRUD + 校验 400 详情；手动运行 202 / 单飞 409；run 详情与 finding 过滤分页；权限（viewer 只读、非成员 403）；`enabled=false` 不响应事件触发（P1）。

**迁移 / 备份**：迁移幂等（重复执行）+ downgrade 还原；备份往返（P2：workflow 定义随工作区备份导出导入一致，run / finding 不进备份）。

**e2e（前端）**：新建流水线（YAML 校验错误可见）→ 修正保存 → 手动运行 → 详情页看到 finding 并可按严重度过滤。

### 9. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 插件骨架 + 三表迁移 + DSL 编译层 + 注册表 + `table/*` / `document/*` 检查 + 执行器（手动触发）+ 全部 API | 中（DSL 编译层与结论推导是质量重心） |
| **P1** | 前端页面（列表 / 编辑 / 运行详情）+ 事件触发（记录批量变更 / 文档保存 / 同步完成三个分发点） | 中 |
| **P2** | 定时触发（`cndb pipeline tick` + cron 部署脚本，参照 `deploy/sync.sh`）+ 备份 v10（workflow 纳入、run / finding 排除）+ finding 一键转 Issue | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | GitHub Actions 形态：声明式 YAML 流水线 + 注册表检查动作 + DAG 执行器 + 结构化 finding | 需求点名参考 GitHub；仓库已有注册表 / 后台任务 / 事件流三块地基可复用 | Great Expectations / pandera（新重量级依赖、面向 DataFrame 生命周期而非工作区内容物）；SQL 规则视图（无编排、无严重度模型）；纯代码检查（用户不可配置） | `src/cndb/plugins/pipeline/` |
| D2 | DSL 载体 | YAML 文本入 `content` 列，保存期编译 IR 入 `compiled` 列，运行读 IR | 可读性 / 注释 / 与 GitHub 形态一致；IR 快照保证运行期零语法错误（I2） | 结构化表单存储（表达力受限，无法承载 DAG + 表达式）；运行时重解析 YAML（运行结果受定义中途修改影响，不可复现） | `pipeline/models.py`、`pipeline/services/dsl/parse.py` |
| D3 | 表达式语言 | `${{ }}` 白名单子集，递归下降求值 | 覆盖 `if:` / 参数引用需求即可；沙箱安全 | Python `eval`（任意代码执行风险）；Jinja2（新依赖，模板注入面更大） | `pipeline/services/dsl/expressions.py` |
| D4 | 检查扩展机制 | `uses:` 命名空间注册表（`域/动作`）+ 声明式输入 schema，目录端点只读 | 对标既有图表模板注册表与 LLM 动作目录（ADR 0020）两处范式，团队心智一致 | DSL 内嵌检查逻辑（等于引入可编程执行，违背 I1/I5）；每格式一个硬编码页面（回到散落现状） | `pipeline/checks/registry.py` |
| D5 | 触发模型 | P0 手动；P1 事件分发点（三个既有写路径末尾）+ `core_event` 留痕；P2 cron tick | 手动先闭环价值，事件点改动可控；tick 复用 `cndb sync tick` + cron 部署范式 | 轮询 `core_event` 表作触发源（延迟高、全表扫描）；P0 直接做全量触发（写路径侵入面过大，先验证引擎） | `pipeline/services/runner.py`、`pipeline/services/triggers.py` |
| D6 | 结果模型 | `pipeline_run` 快照 + `pipeline_finding` 结构化行 + `run.stats` 汇总 | finding 需按严重度 / 目标 / 动作过滤与分页，纯 JSON 报告做不到（治理任务 `report` 列的局限）；快照汇总让列表页免聚合查询 | 纯 JSON 报告（同 GovernanceTask，不可过滤）；全量 finding 进 `core_event`（事件表语义污染，粒度不匹配） | `pipeline/models.py` |
| D7 | 只读保障与侧信道 | 检查上下文无写 API；finding 不携带字段值 / 单元格内容，仅字段名 / 行 ID / 计数 / 阈值 | I1；对齐 ADR 0004 行级权限的侧信道保护口径 | 检查携带样例值（对 viewer 泄露隐藏字段内容） | `pipeline/checks/base.py`（`CheckContext`） |
| D8 | 并发口径 | workflow 级单飞：状态条件 UPDATE 抢占，冲突 409 | 对齐数据源同步单飞语义（`runner.py:125`）；P0 无租约（检查只读、可中断性弱，无需批间续期复杂度） | 立即引入 DB 租约（过度设计，检查任务粒度短）；允许并发 run（结果交叉，stats 无意义） | `pipeline/services/runner.py` |
| D9 | 严重度与结论映射 | `error/warn/info` 三档；error 使 step 失败（`continue-on-error` 豁免）→ job 失败 → run `failed`；仅 warn/info → `partial`；全无 → `success` | GitHub Actions 的 conclusion 模型 + annotation severity 的合体；`partial` 区分"全绿"与"有告警" | 两档 error/warn（info 类截断提示无处安放）；warn 也判失败（巡检类告警不该红） | `pipeline/services/runner.py` |
| D10 | 权限口径 | workflow CRUD 与触发 owner/editor；run / finding 查看为工作区成员 | 与数据源任务（创建编辑受限）+ 治理报告（成员可见）口径一致 | 仅 owner 可看结果（质量信息对团队有普适价值）；viewer 可运行（写入口子） | `pipeline/routers/` |
| D11 | 前端入口 | 工作区页签「质量检查」，路由 `/w/:wid/pipelines` | 与数据源同步 / 数据分析同级的工作区级功能；工作区类型 `data_doc` / `data` 显示（`doc` 型无数据表检查目标） | 表级 / 文档级零散入口（检查天然跨域，应集中） | `frontend/src/pages/pipelines/` |
| D12 | 备份口径 | workflow 随工作区备份导出（P2，backup v10）；run / finding 属流水不进 | 对齐 ADR 0075 排除清单（同步运行历史同类） | run 也进备份（体量随时间无界增长） | `plugins/workspaces/` 备份序列化、恢复路径 |
| D13 | 检查的数据视角 | 工作区视角（owner 级读取，不套触发人个人行级权限） | 质量口径是表 / 文档级客观事实，随触发人漂移则结果不可比；配合 D7 的值级脱敏，侧信道风险受控 | 按触发人视角（同一 workflow 不同人跑出不同结论，违背"报告可复现"） | `pipeline/services/runner.py`、`pipeline/checks/base.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：质量检查从硬编码散点收敛为可声明、可编排、可复现的流水线；数据表与文档用同一套模型，新格式零引擎改动接入；finding 结构化后可过滤、可后续转 Issue；`compiled` IR 快照让历史 run 语义稳定（定义中途修改不影响进行中的运行读取）。
- **负向**：新增一个插件与三张表（迁移 / 备份 / 测试面扩大）；DSL 引入学习成本（用检查目录 + 校验错误提示缓解）；事件触发在三个写路径埋分发点（侵入既有代码，P1 需控制为末尾一行调用）。
- **风险与缓解**：检查扫描大表拖慢后台 → 扫描上限 + 采样标注（边界 1）；DSL 用户写错 → 保存期全量校验 + 行级错误信息（I2）；单飞误判（进程崩溃残留 `running`）→ run 启动带心跳时间戳，超时（如 30 分钟）的 `running` 视为僵死可被新运行抢占。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

| 维度 | GitHub Actions | Great Expectations | dbt tests | 本设计 |
|---|---|---|---|---|
| DSL 形态 | YAML + `${{ }}` 表达式 | Python Expectation 类 | YAML + SQL 宏 | YAML 子集 + `${{ }}` 白名单表达式（D2/D3） |
| 编排模型 | job DAG（`needs`） | Suite 内平铺 | 模型级平铺 | job DAG（对齐 GitHub，D1） |
| 扩展机制 | marketplace actions（`uses:`） | 自定义 Expectation 类 | 宏 / 包 | 命名空间注册表 `uses:`（D4） |
| 结果模型 | check run + annotation | validation result 文档 | test 结果表 | run 快照 + 结构化 finding（D6） |
| 触发 | push / 手动 / cron | 手动 / 编排器 | 构建 / 手动 | 手动 / 事件 / cron 分期（D5） |

来源：GitHub Actions 官方文档（Workflow syntax for GitHub Actions）；Great Expectations / dbt 官方文档（概念对照，非代码依赖）。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 行级权限边界 | 检查读取视角 | 工作区视角运行 + finding 值级脱敏，不改判定入口 | ADR 0076（依赖 ADR 0004 的侧信道口径） |
| 动作注册表范式 | 检查动作目录 | 复用 ADR 0020 的「注册表 + 只读目录端点」形态，不引入可编程执行端点 | ADR 0076 |
| 备份排除清单 | backup v10 | workflow 进备份，run / finding 按流水排除 | ADR 0075（排除口径）+ ADR 0076（P2） |
| 调度范式 | cron tick | `cndb pipeline tick` 对齐 `cndb sync tick` | ADR 0006（范式）+ ADR 0076（P2） |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 未开始 | — | — | — |
| P1 | 未开始 | — | — | — |
| P2 | 未开始 | — | — | — |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：设计完成，等待人工评审（卡片未决问题复核 + ADR 评审，`Proposed` → `Accepted`）
- 已完成：需求卡片 `docs/requirements/0076-pipeline-check-dsl.md`、本 ADR、索引与 CONTEXT 术语登记
- 下一步：评审通过后按 P0（插件骨架 + DSL 编译层 + 注册表 + 检查族 + 执行器 + API）启动实现
- 已知坑：alembic 当前 head 为 `x2y3z4a5b6c7`（P0 迁移 `down_revision` 锚点）；`doc` 型工作区不显示「质量检查」页签（无数据表目标）；检查执行须走只读 session（SQLite 单写者场景避免与写路径抢锁）
- 最近一次全绿：`make check-docs` @ 设计提交（2026-10-31）
