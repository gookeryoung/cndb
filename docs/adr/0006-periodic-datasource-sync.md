# ADR 0006: 周期性外部数据同步框架（Provider × SyncJob × Cursor × Normalizer）

Status: Implemented
Date: 2026-10-20
Related: `src/cndb/plugins/base.py`、`src/cndb/plugins/tables/services/importing/api_fetch.py`、`src/cndb/plugins/tables/services/importing/importer.py`、`src/cndb/plugins/tables/services/importing/api_config_loader.py`、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/services/importing/import_tasks.py`、`src/cndb/core/events.py`、`src/cndb/plugins/analytics/services/formula.py`、`src/cndb/plugins/analytics/services/recommend.py`、`docker-compose.prod.yml`
需求卡片: `docs/requirements/0006-periodic-datasource-sync.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片「需求原句」（逐字，本 ADR 不复制第二份）；约束编号沿用卡片的 C1..C5。

| C # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 定期拉取外部数据 | `datasource_sync_job.schedule`（`daily@HH:MM` / `interval` / `cron`）+ 进程内调度器 `tick()` + CLI `cndb sync run`（cron 兜底），DB 租约互斥防多副本重跑 |
| C2 | 规范化 / 幂等同步进数据表 | `Normalizer`（字段映射 + 类型归一）→ `Importer` 按 job 级 `match_keys` upsert；目标为 tables 动态表，首次可自动建表 |
| C3 | 面向时序的分析可视化 | 公式引擎补窗口函数（`prev/lag/lead`、`ma`、`rolling_*`、`cumsum`、`rank`、`pct_change` 等，带 `partition_by` + `order_by` 上下文）+ 通用分析模板（趋势 / 分布 / 占比 / 比率 / 概览） |
| C4 | 通用：股票 / 天气 / 新闻只是场景实例 | 同一套 Provider × SyncJob × Cursor × Normalizer 四者可组合；三者的调度、游标、幂等、重试、存储、出图共用同一份代码 |
| C5 | 声明式优先、适配器兜底 | `http_json` provider 以请求模板（占位符 / 分页 / 时间分片）+ 解析路径 + 字段映射声明式接入（覆盖约 80% 源）；特殊格式 / 鉴权 / 分页由 `SourceProvider` 子类封装 |

## Context

现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 对应约束 |
|---|---|---|---|---|
| 1 | 插件架构可直接复用，新插件命名 `datasource` | `src/cndb/plugins/base.py` | 无需改插件装载机制 | C4 |
| 2 | 动态数据表可作落库目标，但唯一索引不随配置生成 | `src/cndb/plugins/tables/` | 幂等只能靠应用层查重 | C2 |
| 3 | HTTP 抓取已有 SSRF 防护 / 重试 / 编码探测 / 响应处理器注册表，但**无请求模板化、无分页、无时间分片** | `src/cndb/plugins/tables/services/importing/api_fetch.py` | 每个源都要写代码 | C5 |
| 4 | `field_mapping` 只服务导入场景，未泛化到任意源 | `api_config_loader.py` | 同上 | C5 |
| 5 | 幂等 upsert 已有，但 `match_keys` 硬编码 symbol/date | `importer.py`、`core/records.py` | 只适用股票场景 | C2、C4 |
| 6 | 后台任务是**一次性**导入，无持久化任务定义、**全仓无调度器** | `importing/import_tasks.py` | 无法「定期」；`tencent_stock` 的 `query_interval` 是死配置 | C1 |
| 7 | 统一事件流可承接运行留痕 / 缓存失效 | `core/events.py` | 需新增 `datasource.sync` 动作 | C2 |
| 8 | 分析底座可用，但公式引擎**无时序窗口函数**（纯逐行 / 整列聚合） | `plugins/analytics/services/formula.py` | 均线 / 环比 / 排名算不出来 | C3 |
| 9 | `tencent_stock` 只解析实时快照，无历史日线 | `api_fetch.py` | 股票场景缺日线，是本次立项的直接诱因 | C4 |

**核心缺陷（需求要补的）**：仓库有「抓一次 → 落表」的一次性管道，缺少**任务化 + 增量游标 + 调度**这三件把管道变成周期性同步的能力；且分析侧缺窗口函数，时序数据落到表里也算不出趋势类指标。

设计目标（不变量）：

- **I1 领域无关**：调度 / 游标 / 分页 / 幂等 / 重试代码中不出现 symbol、city、stock 等领域词。
- **I2 重复运行不产生重复行**：一律走 `match_keys` upsert。
- **I3 部分失败不拖垮整体**：单参数 / 单页失败记为 `partial`，cursor 不前进到未完成区间。
- **I4 单飞**：同一 job 在任意时刻至多一个执行者（DB 租约），cron 与内置调度器可并存。
- **I5 零静默**：每次运行留 `datasource_sync_run` 与 `core_event` 记录。

## Decision

### 1. 数据模型

三张新表（单条 alembic 迁移，幂等 + downgrade 可还原，存量零迁移）：

**`datasource_sync_job`**：`id / workspace_id / name / provider / table_id / request_spec(JSON：url_template, method, headers_template, params_template, body_template, data_path, paging, time_window) / parser / entrant_keys(JSON) / match_keys(JSON) / field_mapping(JSON) / cursor(JSON：strategy, field, backfill_start) / schedule(JSON) / enabled / last_run_at / last_status / lease_owner / lease_until`。

**`datasource_sync_run`**：`id / job_id / started_at / finished_at / status(success|partial|failed) / cursor_from / cursor_to / fetched / inserted / updated / skipped / error_message / detail(JSON：逐参数逐页成败)`。

**`datasource_session`**（可选，后期）：集中管理 `{key: secret, headers}`，job 引用之；首期内联于 `request_spec`。

目标表 schema 由 provider 的 `normalizer` 默认输出 + 用户 `field_mapping` 决定，首次同步自动建表（复用 `create_table_from_json_data`）。幂等由**应用层 upsert**（先查后写，见 D8）保证，不为 `match_keys` 建复合唯一索引。

### 2. 分层与唯一入口

```
Provider（代码级适配器，注册表 PROVIDERS）  build_request / parse / normalize / params_schema / default_cursor
SyncJob（用户配置，持久化）                 Provider 引用 + 目标表 + 标的集合 + 字段映射 + 幂等键 + 调度 + 启停
Cursor（增量状态）                          上次成功位置（日期 / 时间戳 / 已见键集合）
Normalizer（落表）                          清洗 + 类型归一 → 按 match_keys upsert（复用 Importer）
```

抓取管线唯一入口：`build_request(job, cursor)` →（分页 / 时间分片循环）`fetch_json` → `parse` → `normalize` → `Importer` upsert；所有 HTTP 复用 `api_fetch` 的 SSRF 防护 / 超时 / 重试 / 编码 / 体积上限 / 限流。

游标策略内置四种：`date`（cursor = 最大日期，首跑按 `backfill_start` 回填）、`datetime`（最大发布时刻）、`key_set`（已见幂等键集合，用于无稳定时间序的源）、`none`（每次全量覆盖）。无新数据时游标不前移，与「同步失败」区分。

### 3. API 变更清单（`/api/v1/workspaces/{wid}/datasource`）

| 端点 | 变更 |
|---|---|
| `GET /providers` | 新增：可用适配器 + `params_schema`（前端动态表单） |
| `GET` / `POST` `/sync-jobs` | 新增：列表 / 新建（含预览校验、可自动建表） |
| `GET` / `PUT` / `DELETE` `/sync-jobs/{id}` | 新增：详情 / 修改（启停、调度、映射）/ 删除 |
| `POST /sync-jobs/{id}/run` | 新增：立即运行一次 |
| `POST /sync-jobs/{id}/preview` | 新增：抓一次预览（不落库，含列画像） |
| `GET /sync-jobs/{id}/runs` | 新增：运行历史 |

权限复用 `check_workspace_permission`：读 viewer，写 editor。

### 4. 边界与例外

1. 生产形态二选一：CLI + 系统 cron（默认）或内置调度器（需单副本或依赖租约）；两者共用 `scheduler.tick()`，靠 `lease_owner / lease_until` 互斥。
2. 密钥首期内联于 `request_spec`（可见性随 job 权限）；后续抽 `datasource_session`。
3. 时序全量可能超 analytics 单扫描上限 `MAX_SCAN_ROWS=20000`，分析须按区间 / 分区，不支持全量一次性扫描。
4. `match_keys` 缺省 → 退化为纯追加（仅快照类源适用）；指定时必须全部命中目标表字段，否则建 job 时校验失败（避免运行期静默退化成追加）。并发重复由 M2 的 DB 租约单飞规避（D8）。
5. `partial` 状态的 run 不推进 cursor 到未完成区间，下一轮自动补抓。

### 5. 迁移

单条 alembic 迁移建三表；新表须纳入 `backup_io` 导出 / 导入，旧备份缺该键时按空还原。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 任务列表（工作区级） | `frontend/src/pages/datasource/` | 名称 / 来源 / 目标表 / 频率 / 上次运行状态 |
| 新建向导（Provider 驱动） | 同上 | 选 provider → 动态渲染 `params_schema` → 请求模板 / 解析路径 → 抓取预览（复用 `importPreview` 与列画像）→ 字段映射（复用 `ImportDiffTable` / `SelectedFieldEditor`）→ 增量字段与幂等键 → 调度 → 保存 |
| 任务详情 | 同上 | 启停、立即运行、运行历史抽屉、错误原因 |
| 数据分析 | `frontend/src/pages/analytics/` | `AnalyticsPage` 增「一键套用通用模板」入口（复用 `RecommendationPanel`） |
| API 封装 | `frontend/src/api/datasource.ts` | 上述端点 |

### 7. 测试清单

**单测**：请求模板求值（缺参 / 转义）；分页终止条件；时间分片边界；四种游标策略（首跑 / 已最新 / 无新数据 / 时间乱序）；`match_keys` upsert 幂等；租约互斥；窗口函数数值（分区 + 排序、空值、边界）。

**集成**：`http_json` 接假 JSON 源（天气样例）→ 首次回填 → 二次增量不重复。

**e2e（前端）**：新建任务 → 运行 → 目标表有数据 → analytics 套通用模板出图。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **M1** | 通用抓取管线：拆 Provider / Parser 两层 + `http_json`（请求模板化 + 分页 + 时间分片）+ `normalize` | 中 |
| **M2** | 同步任务与调度：`sync_job` / `sync_run` 模型 + 四种游标 + `scheduler`（到期扫描 + 租约 + 退避）+ CLI + run / preview 端点 | 高 |
| **M3** | Provider 与可观测 / 前端：适配器收敛为通用 `http_json` / `llm_prompt` + 运行历史 + `core_event` + 任务页 / 向导 | 中 |
| **M4** | 分析通用化：公式引擎窗口函数 + 通用模板 + 推荐扩展 | 中 |
| **M5** | 完善：密钥会话管理、多源限流、领域模板包、天气 provider 示例 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 插件命名 | `datasource`（概念：数据源同步），路由前缀挂 workspaces | 与 tables / documents 同层级；语义覆盖「数据源」而非只服务股票 | `stock` / `sync`（领域化或过泛） | `src/cndb/plugins/datasource/plugin.py` |
| D2 | 通用优先还是专用优先 | **只保留通用适配器**：`http_json`（声明式 HTTP + JSON）与 `llm_prompt`（大模型提示词）；领域专用只做领域模板 / 参数预设，不进适配器层 | 绝大多数数据源都是 HTTP + JSON，声明式覆盖主路径；一源一适配器会让适配器层随领域线性膨胀，且模板可直接套用 | 一源一适配器（K 线 / RSS 等专用 provider，代码量与维护面线性膨胀；换个站点就要再写一个）；`RssAtomProvider`（RSS/Atom 本质是 XML 解析，用 `http_json` + 字段映射即可覆盖） | `providers/http_json.py`、`providers/llm_prompt.py`、`providers/registry.py` |
| D3 | 调度形态 | 生产 CLI + 系统 cron；开发 / 单机用内置调度器；统一 DB 租约互斥 | 与既有 `deploy/backup.sh` 的 cron 模式一致；避免多副本重复执行 | 纯内置必守单副本 / 引入外部队列（部署成本高） | `src/cndb/plugins/datasource/services/scheduler.py`、`src/cndb/cli/sync.py`、`deploy/sync.sh` |
| D4 | 增量游标 | 内置 `date` / `datetime` / `key_set` / `none` 四策略，job 级可选 | 覆盖按日、按时刻、无时序、快照四类源 | 只做 date（新闻 / 榜单接不了） | `src/cndb/plugins/datasource/services/cursor.py` |
| D5 | 分析实现 | 扩展公式引擎补窗口函数（分区分序）为主 + 通用模板 | 引擎已有逐行 / 整列聚合，加分区排序上下文改动集中 | 另建时序计算引擎（重复实现、两套口径） | `src/cndb/plugins/analytics/services/formula.py` |
| D6 | 密钥管理 | 首期内联 `request_spec`；M5 抽 `datasource_session` 集中管理，密钥**加密入库**（Fernet，`enc:v1:` 前缀，历史明文兼容） | 先跑通链路，避免过早抽象 | 首期即建密钥表（无消费方） | `src/cndb/plugins/datasource/models.py`、`src/cndb/core/crypto.py` |
| D7 | 规模 | 分析请求带 `filters`（时间区间 / 分区等值）把扫描面压到区间内；上限提为 `ANALYTICS_MAX_SCAN_ROWS` 可配但不作为首选 | 现有 analytics 为单次扫描模型，改流式代价大；过滤是零成本的正解 | 提高扫描上限（内存与响应时间不可控） | `src/cndb/plugins/analytics/services/compute.py` |
| D8 | 幂等落库怎么保证唯一 | 应用层 upsert：`Importer` 按 `match_keys` 先查后写；并发重复由 DB 租约单飞规避 | 现有 `tables` 自动建表只支持单列唯一，改 DDL 需动建表链路与存量测试；同步场景已由租约串行化 | 为 `match_keys` 建复合唯一索引（改 `ddl.py` + 建表链路 + 冲突语义，收益不足以抵成本） | `src/cndb/plugins/datasource/services/write.py`、`tables/services/importing/importer.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」。**D1-D8 已由需求方拍板采纳（2026-10-20）**；M1-M5 与遗留项全部落地后经人工确认，Status 定稿为 `Implemented`（2026-10-20）。

## Consequences

- **正向**：新增数据源从「写代码」降为「填模板」，不再为每个站点写适配器；调度 / 游标 / 幂等只实现一次；分析侧补齐时序能力后，各类数据源共用同一套出图路径。
- **负向**：多出三张表、一个调度器与一层 Provider 抽象；`request_spec` 是半结构化 JSON，校验与迁移成本高于强类型列；内置调度器与 cron 并存需要租约保证单飞，测试面扩大。
- **风险与缓解**：模板求值引入注入面（URL / header 占位符）→ 复用 `api_fetch` 的 SSRF 白名单与体积上限，占位符只做字面替换；调度器守护线程与导入任务共用进程 → 单飞靠 DB 租约而非内存锁；`MAX_SCAN_ROWS` 上限决定分析口径 → 在 M4 明确按区间 / 分区取数。

## 行业对照（可选）

| 维度 | Airbyte | n8n | 本设计 |
|---|---|---|---|
| 接入方式 | Connector（代码）+ CDK | 节点（声明式 + 代码节点） | `http_json` 声明式为主 + Provider 适配器兜底（D2） |
| 增量 | 每 connector 自定义 cursor | 节点内自管 | 内置四策略，job 级可选（D4） |
| 调度 | 平台侧 scheduler | 工作流触发器 | CLI + cron 或内置调度器，DB 租约单飞（D3） |

来源：Airbyte Docs《Connector Development》；n8n Docs《Nodes》。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| M1 通用抓取管线 | 已落地 | `src/cndb/plugins/datasource/providers/base.py`、`src/cndb/plugins/datasource/providers/template.py`、`src/cndb/plugins/datasource/providers/http_json.py`、`src/cndb/plugins/datasource/providers/registry.py`、`src/cndb/plugins/datasource/services/normalize.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/write.py` | `tests/test_datasource_template.py`、`tests/test_datasource_normalize.py`、`tests/test_datasource_pipeline.py` | `13d4c050` |
| M2 同步任务与调度 | 已落地 | `src/cndb/plugins/datasource/models.py`、`src/cndb/alembic/versions/0a1b2c3d4e5f_add_datasource_sync.py`、`src/cndb/plugins/datasource/services/cursor.py`、`src/cndb/plugins/datasource/services/schedule.py`、`src/cndb/plugins/datasource/services/scheduler.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/cli/sync.py`、`deploy/sync.sh` | `tests/test_datasource_cursor.py`、`tests/test_datasource_schedule.py`、`tests/test_datasource_scheduler.py`、`tests/test_datasource_runner.py`、`tests/test_datasource_api.py`、`tests/test_datasource_cli.py`、`tests/test_datasource_backup.py`、`tests/test_datasource_migration.py` | `fefa7c7d` |
| M3 Provider + 前端 | 已落地 | `src/cndb/plugins/datasource/providers/registry.py`、`src/cndb/plugins/datasource/providers/http_json.py`、`src/cndb/plugins/datasource/providers/llm_prompt.py`、`frontend/src/api/datasource.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/App.tsx` | `tests/test_datasource_pipeline.py`、`tests/test_datasource_llm_provider.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx`、`frontend/tests/e2e/critical/datasource.spec.ts` | `741e1d0b` |
| M4 分析通用化 | 已落地 | `src/cndb/plugins/analytics/services/formula.py`、`src/cndb/plugins/analytics/services/compute.py`、`src/cndb/plugins/analytics/services/templates.py`、`src/cndb/plugins/analytics/services/recommend.py`、`src/cndb/plugins/analytics/schemas.py`、`frontend/src/pages/analytics/FormulaPanel.tsx` | `tests/test_analytics_window_functions.py`、`tests/test_analytics_window_integration.py`、`frontend/src/pages/analytics/FormulaPanel.test.tsx`、`frontend/tests/e2e/critical/analytics.spec.ts` | `0c2a9d68` |
| M5 完善 | 已落地 | `src/cndb/plugins/datasource/models.py`、`src/cndb/alembic/versions/1b2c3d4e5f60_add_datasource_session.py`、`src/cndb/plugins/datasource/routers/sessions.py`、`src/cndb/plugins/datasource/services/domain_templates.py`、`src/cndb/plugins/datasource/providers/http_json.py` | `tests/test_datasource_session_m5.py`、`tests/test_datasource_migration.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | `df5868d5` |
| M5 遗留清理 | 已落地 | `src/cndb/core/crypto.py`、`src/cndb/core/config.py`、`src/cndb/plugins/datasource/routers/sessions.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/analytics/services/compute.py`、`src/cndb/plugins/analytics/services/formula.py`、`src/cndb/plugins/analytics/schemas.py`、`frontend/src/pages/datasource/DatasourcePage.tsx`、`frontend/src/pages/analytics/AnalyticsPage.tsx` | `tests/test_core_crypto.py`、`tests/test_analytics_scope.py`、`tests/test_datasource_session_m5.py`、`tests/test_analytics_window_functions.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx`、`frontend/src/pages/analytics/AnalyticsPage.test.tsx` | `fad103ce` |

> M1 落地范围：`http_json` 声明式接入（请求模板 / page·offset 分页 / `chunk_days` 时间分片）、
> 归一（改名 / 丢弃 / 类型归一，失败降级留痕）、管线（单请求失败记 partial、分页空页提前终止）、
> 幂等落表（复用 `Importer`，应用层先查后写，不建复合唯一索引）。
>
> M2 落地范围：`datasource_sync_job` / `datasource_sync_run` 两表与迁移；四策略游标（无新数据不推进、
> 乱序只前进）；`manual / daily / interval / cron` 四种调度与失败退避；DB 租约原子抢占的 `tick`；
> 运行编排（抓取 → 落表 → 游标 → 运行记录 + `datasource.sync` 事件，坏配置落 failed 不炸调度器）；
> providers / sync-jobs CRUD / run（租约冲突 409）/ preview / runs 端点；`cndb sync` CLI 与
> `deploy/sync.sh`；工作区备份升到 v5 携带同步任务（表名引用 + 同名表重绑）。
>
> M3 落地范围：适配器层收敛为通用 `http_json`（声明式请求模板 / 分页 / 时间分片 / 列式记录）与
> `llm_prompt`（个人大模型连接 + 提示词模板 + JSON 输出），`GET /providers` 只暴露这两项；
> 前端 `api/datasource.ts` + `pages/datasource/DatasourcePage.tsx`（任务列表 / Provider 驱动编辑抽屉 /
> 抓取预览 / 运行历史），工作区页签新增「数据源同步」并按 `workspaceType` 门控；
> 前端页面测试 + e2e（进入页签 / 新建保存落库 / 编辑回填 / 必填拦截）。
>
> M4 落地范围：公式引擎补 10 个窗口函数（`prev/lag/lead/diff/pct_change/cumsum/rank/ma/rolling_sum/rolling_std`）
> 与 `partition_by + order_by + order_desc` 上下文（行对齐列 + 前缀和/名次表，按分区预处理 O(n)；
> 无窗口公式仍走原逐行路径）；`FormulaSpec` 与模板校验透传窗口上下文；推荐侧新增
> `partition_dimension` 角色（有 time 字段时标出 symbol/city/source 等粒度列），时间趋势示例改分区叠加 + 均线、
> 新增「环比变化」示例；前端公式行检测到窗口函数即展开「分区 / 排序 / 升降序」选择器并补 10 个快捷片段。
> **未做**：图表按分区多系列渲染仍复用既有 `chart.series`（前端 `toChartConfig` 已支持），未新增图表类型。
>
> M5 落地范围：`datasource_session` 凭证会话（请求头铺底 + 密钥作模板变量、只写不回显、不随导出）；
> job 级 `rate_limit_ms` 请求限速（pipeline 只对真正发出的请求等待）；`record_mode=columns`
> 列式记录解析（支持「列名 → 数组」响应，配 `examples/datasource/weather-open-meteo.json` 天气示例）；
> 领域模板包（`http_json` 的天气日趋势）与 `GET /domain-templates`；
> 备份导出 `session_name`（不导出密钥）、导入按同名会话重绑。
>
> M5 遗留清理（本轮）：**密钥字段级加密** `core/crypto.py`（Fernet，key 由 `DATASOURCE_SECRET_KEY`
> 派生、留空回退 `JWT_SECRET`；密文 `enc:v1:<token>`、键名明文、历史明文零迁移；解密失败落 failed
> 而不是静默空密钥）；**分析取数范围** `ComputeRequest.filters / filter_logic` 透传 `list_rows`
> （时序表按「时间 >= 起点」把扫描面压到区间内），单次扫描上限提为
> `settings.ANALYTICS_MAX_SCAN_ROWS`，未知过滤字段直接 400；**会话管理 UI** 列表 + 新建 / 编辑 /
> 删除（密钥留空=不修改，删除提示解绑任务）；**`rank` 支持非数值列**（时间 / 文本按原始值排序）。
> 至此 M5 遗留清单清零。
>
> 套用对齐（本轮修复）：领域模板按 provider 默认字段名声明，任务改过 `field_mapping`
> 时原样提交会被 `normalize_config` 以「引用了不存在的字段」拒绝（前端只报笼统的
> 「字段名可能与目标表不一致」）。前端新增 `pages/datasource/domainTemplate.ts`：
> 套用前按 `field_mapping`（源名 → 目标名 / `null` 丢弃）翻译公式字段引用、
> `partition_by / order_by`、图表 `x / y / series`、汇总 `group_by / metrics / sort_by`，
> 字段被丢弃时剔除对应公式并连带剔除引用它的图表 / 指标，跳过的部件回报给用户；
> 建模板失败时直接展示后端校验文案，不再猜测原因。

## 交接（会话结束更新）

- 当前阶段：**M1-M5 与全部遗留项已落地，Status=Implemented**（2026-10-20 人工确认）。主链路闭环：抓取 → 调度 → 落表 → 时序分析 → 凭证 / 限流 / 模板包
- 已完成：需求卡片与 ADR 口径对齐；D1-D8 经人工拍板采纳；M1 抓取管线；M2 任务模型 / 迁移 / 四策略游标 / 调度与租约 / CLI / REST / 备份 v5；M3 适配器收敛为通用 `http_json` / `llm_prompt` + 前端任务页与向导 + e2e；M4 窗口函数 + 分区上下文 + 推荐扩展；M5 凭证会话 / 限速 / 列式记录 / 领域模板包 / 天气示例；M5 遗留清理（密钥加密 / 分析取数范围 / 会话管理 UI / rank 非数值列）
- 遗留：**无**（原四项已清零）
- 本轮修复：套用领域模板前按任务 `field_mapping` 对齐字段名（`frontend/src/pages/datasource/domainTemplate.ts`），字段被丢弃时剔除相关部件并回报；失败提示改为透传后端校验文案
- 本轮修复（前端建任务）：新建抽屉默认填入「同步任务 YYYY-MM-DD HH:mm:ss」；「保存并预览」后抽屉不关闭，保存时以 `job ?? savedJob` 判定——首次创建后再次保存走 PUT 更新，不再重复创建（`frontend/src/pages/datasource/DatasourcePage.tsx`，测试 2 例）
- 下一步（可选增强，非欠账，按使用反馈再定）：① job 级 / 全局并发上限（当前只有租约单飞 + `rate_limit_ms` 请求间隔）；② 密钥轮换的一键运维入口（`core.crypto.rotate_secrets` 已有函数，未接 CLI / UI）；③ 分析范围随模板保存（当前是运行时参数）；④ 图表按分区多系列的原生图表类型
- 已知坑：`Importer.analyze()` 的 `content` 是位置必填；SQLite 读回 `DateTime(timezone=True)` 丢 tzinfo（租约 UPDATE 需 `synchronize_session=False`）；SQLite 不支持 `ALTER TABLE` 加外键列（迁移按方言分支）；`ScheduleConfig.from_dict` 的 0 是合法值；窗口函数第一参数必须是字段引用、聚合仍按整列、`rolling_*` 不满窗返回 None；`rank` 现支持时间 / 文本列（全列可数值化时按数值，否则按字符串）；分析用的 filters 未知字段会 400（列表接口只 warn，别把两处口径搞混）；加密密钥一旦变更，已有密文全部解不开 → 需重新保存会话密钥或先 `rotate_secrets`
- 最近一次全绿：`make check-fast` + `make cov` + `make frontend-coverage` + datasource/analytics e2e @ `fad103ce`（2026-10-20，4809 passed / 覆盖率 98.09%；前端核心 lines 97.64%；e2e 14 条通过）
