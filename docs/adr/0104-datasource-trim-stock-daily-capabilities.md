# ADR 0104: 数据同步裁剪股市日线专用能力（删除 rows_array / row_defaults / row_filter / scale / url_hosts / backfill_date / workers）

Status: Implemented（2026-11-05 落地）
Date: 2026-11-05
Related: `src/cndb/plugins/datasource/providers/base.py`、`src/cndb/plugins/datasource/providers/http_json.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/cursor.py`、`src/cndb/plugins/datasource/services/entrant_state.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/services/normalize.py`、`src/cndb/plugins/datasource/models.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/core/http.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/workspaces/services/workspace_restore.py`、`frontend/src/api/datasource.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx`；上游 ADR 0006 / 0034 / 0035 / 0039 / 0043 / 0099
需求卡片: `docs/requirements/0104-datasource-trim-stock-daily-capabilities.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C6），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 删除无任何配置声明的股市日线专用声明能力 | 删除 `rows_array` 解析（含 `record_layout` 位置索引语义）、`row_defaults`、`row_filter`、`field_mapping.scale`、`url_hosts`（D2/D3）：`RequestSpec` / `SyncJobSpec` / `FieldTransform` 去掉对应字段，`pipeline` / `normalize` / `http_json` / `core/http` 去掉执行分支；旧配置命中已删除键时**显式报配置错误**（I3），不静默忽略 |
| C2 | 删除 backfill_date 游标、单轮翻页与按标的水位断点续跑 | `CursorStrategy` 收敛为 `date / datetime / key_set / none`；删除 `page_to_start` / `page_size` / `is_backfill` / `backfill_anchor` / `backfill_advance` / `min_field_value` / `validate_page_to_start`、runner 的 `_inject_backfill_ends` / `_run_streaming_passes` / `_advance_backfill` / `watermark`、`entrant_state` 的水位读写、`DatasourceEntrantCursor` 模型与表（D4/D5） |
| C3 | 删除 request.workers 并发分组执行 | `run_pipeline` 回归串行（按 plan 展开顺序逐组执行）；删除 `ThreadPoolExecutor` / `cancel` / `_resolve_workers` / `llm_prompt` 强制 1 的分支；`rate_limit_ms` 字段保留，实现简化为「串行相邻请求最小间隔」（D6） |
| C4 | 保留仍在用的能力与口径不变 | 保留 `record_mode=rows / columns`、`data_path` 单路径模板（rows 模式保留 `data / items / results` 通用键探测）、`fill_entrant`、`on_batch` 流式落表、`RequestProgress`、push 方向（ADR 0099）、`date / datetime / key_set / none` 游标、幂等 upsert、`entrant_source` 动态标的（D1/D7） |
| C5 | 按需求移除流程先清 ADR | 0033 / 0053 整体被取代 → 删文件、索引行与全仓引用；0034 / 0035 / 0039 / 0043 改写保留有效决策（D8）；`make adr-check` 通过 |
| C6 | 同步删除仅服务于被裁能力的测试 | 整删 4 个专用测试文件（host fallback / cursor backfill / pipeline concurrency / runner pages）；混合用例改写为保留能力断言；覆盖率门槛不降（D9） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号 1..8，新增条目续接 9..15。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `record_mode` 含 `rows_array` 分支，按 `record_layout` 位置索引解析「数组的数组」；`data_path` 以 `\|` 分隔候选路径 | `providers/http_json.py:109-125`、`:228-307`、`providers/base.py:96-107` | 仅腾讯日线响应形态需要；仓库内无任务声明（天气示例用 `columns`），只有单测在维护 | 确认（C1） |
| 2 | `row_defaults` / `row_filter` 贯穿 spec → pipeline → runner | `providers/base.py:108-114`、`services/pipeline.py:450-518`、`services/runner.py:337-344` | 快照补常量列 / 剔除零值行用；两能力均无配置声明 | 确认（C1） |
| 3 | `field_mapping.scale` 在归一前做数值缩放 | `providers/base.py:166-182`、`:243-269`、`services/normalize.py:99`、`:110-127` | 统一「手 / 股」量纲用；示例从未声明（ADR 0053 D8） | 确认（C1） |
| 4 | `url_hosts` + `FetchConfig.fallback_urls` + 主机不可用异常构成主机回退 | `providers/base.py:88-90`、`:135-150`、`providers/http_json.py:167-193`、`core/http.py:236-238`、`:576-606` | 腾讯 proxy 回退专用；通用抓取内核被迫携带候选主机循环 | 确认（C1） |
| 5 | `backfill_date` 游标 + 水位表 + 单轮多 pass | `services/cursor.py:30`、`:41-45`、`:66-69`、`:145-228`、`services/entrant_state.py:24-59`、`services/runner.py:85-87`、`:236-238`、`:714-816`、`models.py:177-197` | 仅历史回补任务使用；水位表随 job 级联、备份/恢复各有一条链路 | 确认（C2） |
| 6 | `request.workers` 走线程池并发；`llm_prompt` 强制 1 | `providers/base.py:115-116`、`services/pipeline.py:209-290` | 唯一示例未声明；并发使限速器 / 取消标记 / 结果聚合复杂化 | 确认（C3） |
| 7 | `rate_limit_ms` 为全局相邻请求最小间隔 | `services/pipeline.py:182-206`、`models.py:121-122` | 字段在模型 / API / 前端暴露，仍需保留；串行下实现可退化为单线程间隔 | 确认（C4） |
| 8 | `CursorConfig.page_to_start` / `page_size` 仅服务 backfill 多 pass | `services/cursor.py:41-59`、`:78-82`、`:99-100`、`routers/sync_jobs.py:133-134` | 删除 backfill 后成为死配置，且创建入口仍强制校验 `{end}` | 确认（C2） |
| 9 | `entrant_cursor` 表参与工作区备份导出、恢复与删除顺序 | `services/workspace_backup.py:520-529`、`:612`、`services/backup_io.py:959-986`、`services/workspace_restore.py:109` | 删模型后若不清理这三处，备份/恢复会 `ImportError` 或写入孤儿表 | 新增（C2 迁移面） |
| 10 | `request_spec_from_payload` 只认白名单键，未知键被静默忽略 | `services/runner.py:610-647` | 存量 `rows_array` / `url_hosts` / `row_defaults` 等配置会「跑起来但行为变了」，必须改为显式报错 | 新增（I3） |
| 11 | `data_path` 的 `\|` 候选语义由 `_rows_array_from_candidates` 独占实现；rows 模式的通用候选探测走 `_extract_array(..., True)` | `http_json.py:253-286`、`core/http.py:339-400` | 删除候选解析后，rows 模式的 `data / items / results` 探测不受影响；`\|` 语法需显式拒绝 | 新增（D3） |
| 12 | 前端类型声明 `'backfill_date'` / `'rows_array'` / `workers` / `row_filter` / `row_defaults` | `frontend/src/api/datasource.ts:19`、`:72-81` | 类型仍接受已删除配置，编辑页会把旧键原样回传；需同步收紧 | 新增（C5 前端） |
| 13 | 页面「保留未挂载声明键」逻辑会保留 `row_filter` / `workers` 等键 | `frontend/src/pages/datasource/DatasourcePage.tsx:790-805` | 旧键保留后会被后端拒绝，编辑页需给出可理解的报错并允许一键清理 | 新增（C5 前端） |
| 14 | 旧 ADR（0033 / 0034 / 0035 / 0039 / 0043 / 0053）大量描述被裁能力与示例任务 | `docs/adr/`、`docs/adr/README.md:82-92` | 不清理会让后续会话继续按失效口径实施 | 确认（C5） |
| 15 | 测试面：4 个专用文件 + 多个混合用例依赖被裁能力 | `tests/test_datasource_{host_fallback,cursor_backfill,pipeline_concurrency,runner_pages}.py` 等 | 删除能力后这些用例失去被测对象，若只删断言会留下空壳 | 确认（C6） |

**核心缺陷（需求要补的）**：管线为「腾讯日线 + 新浪快照」一次性引入了一批**无配置声明、仅靠单测维护**的声明能力；它们把通用同步内核的配置面、分支数与数据模型（水位表 / 备份链路）持续放大，却不再有任何真实消费方。

设计目标（不变量）：

- **I1 保留能力不变**：`rows` / `columns` 解析、`data_path` 模板、`fill_entrant`、`on_batch` 流式落表、请求级进度、push 方向、`date / datetime / key_set / none` 游标、幂等 upsert 的行为与计数口径完全不变。
- **I2 串行确定性**：请求按 `build_requests` 展开顺序逐条执行；`rate_limit_ms` 仍表示相邻请求最小出发间隔（首个请求不等待）。
- **I3 旧配置显式失败**：`record_mode=rows_array`、`cursor.strategy=backfill_date`、`page_to_start` / `page_size`、`url_hosts` / `row_defaults` / `row_filter` / `workers`、`field_mapping.scale`、`data_path` 含 `|` 一律在创建/更新或运行入口报清晰配置错误，不静默降级。
- **I4 存量数据不迁移**：只 drop 水位表；`datasource_sync_job.cursor` / `request_spec` JSON 原样保留，由 I3 的显式报错暴露给运维重配或删除。
- **I5 覆盖率门槛不降**：后端 95% 口径不变；删除的测试只对应被删能力，保留路径的断言不减。

## Decision

### 1. 数据模型

- 删除 ORM 模型 `DatasourceEntrantCursor`（`models.py`），`datasource_entrant_cursor` 表由一条迁移 drop（D5）。
- 不修改 `datasource_sync_job` 的列结构；`request_spec` / `cursor` / `field_mapping` 仍是 JSON，存量旧键由 I3 拒绝。
- 备份格式：不再导出 `entrant_cursors`；恢复旧备份时该键被忽略（不报错），保证旧归档可导入。

### 2. 判定算法（唯一入口）

**(a) Provider 声明面**（`providers/base.py`）

- `CursorStrategy = Literal["date", "datetime", "key_set", "none"]`。
- `RequestSpec` 删除 `url_hosts` / `row_defaults` / `row_filter` / `workers`；`record_mode: Literal["rows", "columns"]`；`record_layout` 仅保留「columns 模式目标列 → 源键」语义。
- `FieldTransform` 删除 `scale`；`normalize_field_mapping` 删除 `_optional_float`。
- `SyncJobSpec` 删除 `entrants_exhausted` / `entrant_ends` / `row_defaults` 及 `__post_init__` 回落。

**(b) http_json 解析**（`providers/http_json.py`）

- `parse` 收敛为两个分支：`columns → columns_to_rows`、其余 → `_extract_array(payload, path, True)`（rows 模式的候选键探测保留）。
- 删除 `rows_array_to_rows` / `_rows_array_from_candidates` / `_layout_positions`；`response_handler_for` 只在 `uses_custom_parse=True`（`llm_prompt`）时返回自定义 handler。
- `build_requests` 删除 `entrants_exhausted` / `entrant_end` 注入；`_variables` 删除 `entrant_end` 参数；`_build_config` 只渲染单 URL（`url=render_text(spec.url_template, variables)`）。

**(c) 游标与标的态**（`services/cursor.py`、`services/entrant_state.py`）

- `CursorConfig` 只保留 `strategy / field / backfill_start / value`；`backfill_start` 仍作为 `date / datetime` 的首跑起点（`window_start` 语义不变）。
- 删除 `page_to_start` / `page_size` / `is_backfill` / `min_field_value` / `backfill_anchor` / `backfill_advance` / `_previous_day` / `_as_int` / `validate_page_to_start`。
- `entrant_state.py` 只保留 `resolve_entrant_values`（动态标的来源），删除水位读写与 `DatasourceEntrantCursor` 依赖。

**(d) 管线串行化**（`services/pipeline.py`）

- `run_pipeline`：`groups = _group_plans(plans)` → `for group in groups: absorb(_run_group(...))`；删除线程池、`cancel`、`_resolve_workers`、`RequestProgress.add_total`（改回 `set_total`）。
- `_RateLimiter` 简化为串行版本：`last_at` 记录上次出发时刻；`wait()` 在 `last_at` 存在时补足 `gap - elapsed`，首请求不 sleep。
- `PipelineOutcome` 删除 `filtered` / `entrant_rows` / `passes` / `truncated`；`status` 只看 `plans / succeeded / failures`。
- `_run_group` 删除 `cancel` 参数与 `apply_row_defaults` 调用：`fill_entrant(to_records(rows), ..., inplace=True)` 直接返回。
- `_BatchSink._process` 删除 `apply_row_filter`：`normalized.rows` 即保留行。
- 删除 `apply_row_defaults` / `apply_row_filter` / `_row_variables` / `_FILTER_OPS`。

**(e) 运行编排**（`services/runner.py`）

- 非 `llm_prompt` 路径直接 `run_pipeline(spec, fetch=fetch, rate_limit_ms=..., on_batch=state.on_batch, batch_size=DEFAULT_BATCH_SIZE, progress=progress)`；删除 `_run_streaming_passes` / `MAX_BACKFILL_PASSES`。
- 删除 `_inject_backfill_ends`，`execute_job` / `preview_job` 不再注入锚点。
- `_StreamingState` 只保留窗口游标推进：`on_batch` 中 `if self._cursor.is_windowed: advance(...)`；删除 `_backfill` / `_watermarks` / `watermark()` / `_advance_backfill()`。
- `_finalize` 的 `detail` 删除 `filtered` / `passes` / `truncated` 三个键。
- `request_spec_from_payload`：`record_mode` 只允许 `rows / columns`；新增「已删除声明键」守卫（D2）；`data_path` 含 `|` 报错；`field_mapping_from_payload` 对 `scale` 报错；删除 `_url_hosts_from_payload` / `_scale_from_payload`。

**(f) HTTP 内核**（`core/http.py`）

- 删除 `FetchConfig.fallback_urls`、`_HOST_SWITCH_STATUS`、`_HostUnavailableError`、候选循环；`_fetch_json_from_url` 改名为单 URL 实现（保留重试 / 重定向 / SSRF / 解析语义），网络错误与 429/5xx 直接抛 `ValueError`（错误文案保持可读）。

**(g) 归一**（`services/normalize.py`）

- `apply_field_mapping` 直接 `coerce_value(value, transform.field_type)`；删除 `_apply_scale`。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /datasource/sync-jobs`、`PUT /datasource/sync-jobs/{id}` | 请求体仍是 `request_spec` / `cursor` 自由 JSON；新增 400：命中已删除声明键（`url_hosts` / `row_defaults` / `row_filter` / `workers` / `field_mapping.scale` / `record_mode=rows_array` / `cursor.strategy=backfill_date` / `page_to_start` / `page_size` / `data_path` 含 `\|`） |
| `POST /datasource/sync-jobs/{id}/preview`、运行入口 | 同上校验；预览不再注入回补锚点 |
| 响应结构 | 不变；`datasource_sync_run.detail` 少 `filtered` / `passes` / `truncated` 三个键（前端未消费） |

### 4. 边界与例外

1. `data_path` 不再支持 `|` 候选；rows 模式的 `_extract_array(..., True)` 仍会探测 `data / items / results` 等常见键，行为与 ADR 0039 之前一致。
2. `record_layout` 保留但只用于 `columns` 模式；`rows_array` 的位置索引语义随分支删除。
3. `rate_limit_ms <= 0` 时 `wait()` 直接返回；`>0` 时首个请求不等待，其后每个请求间隔不小于该值（与旧串行行为一致）。
4. `entrant_source` 动态标的、`fill_entrant`、`on_batch` 流式落表、批间租约续期全部保留；`entrant_values` 为空且未声明标的时仍发单条无标的请求（旧行为）。
5. `preview_job` 不落库、不推进游标；`backfill_date` 任务在 `CursorConfig.from_dict` 即报「未知游标策略」。
6. 工作区备份：旧归档的 `entrant_cursors` 键被忽略；新归档不再产生该键。
7. `llm_prompt` 的 `uses_custom_parse=True` 路径不变；其 `auto landing` 全量路径与 `light=True` 落表不变。
8. 删除只发生在同步插件内；tables 插件的行级权限 `row_filter`（同名不同物）与 `core/http.py` 的其它调用方不受影响。

### 5. 迁移

单条 alembic 迁移（`down_revision = 19d835337b45`）：

- `upgrade()`：`datasource_entrant_cursor` 存在则 `drop_table`（索引随表删除）；不存在则跳过（幂等）。
- `downgrade()`：重建表（`id` / `job_id` FK CASCADE / `entrant` / `cursor_value` / `created_at` / `updated_at`）与唯一索引 `uq_datasource_entrant_cursor_job_entrant`。
- 存量水位数据**不迁移**（I4）：回补能力已删除，旧任务下次运行显式失败，由运维重配或删除。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 类型 | `frontend/src/api/datasource.ts` | `SyncCursorStrategy` 删除 `'backfill_date'`；`record_mode` 删除 `'rows_array'`；`SyncJobRequestSpec` 删除 `workers` / `row_filter` / `row_defaults` |
| 同步任务页 | `frontend/src/pages/datasource/DatasourcePage.tsx` | 删除 `backfill_date` 标签与回补提示；「保留未挂载声明键」不再保留已删除键（提示用户清理后保存） |
| 前端测试 | `frontend/src/pages/datasource/DatasourcePage.test.tsx` | 删除 rows_array / row_defaults / row_filter / workers 断言；保留 record_layout / entrant_source / rate_limit_ms |

### 7. 测试清单

**判定层（单测）**：

- `tests/test_datasource_http_json.py`：`rows` / `columns` 解析、`data_path` 模板、rows 候选键探测；删除 rows_array / scale / url_hosts 用例；新增 `data_path` 含 `|` 的报错断言。
- `tests/test_datasource_pipeline.py`：串行顺序、空页停止、`rate_limit_ms` 间隔、`on_batch` 分片；删除 exhausted / workers 用例。
- `tests/test_datasource_runner.py`：`execute_job` 流式落表、窗口游标推进、预览；删除 rows_array / backfill / row_defaults / row_filter 用例。
- `tests/test_datasource_runner_streaming.py`：保留 `entrant_source` 动态标的、批间续租、失败留痕；删除 backfill / row_filter 用例。
- `tests/test_datasource_row_ownership.py`：保留行所有权断言（`fill_entrant(inplace=True)` + `on_batch` 浅拷贝）。
- `tests/test_datasource_write_throughput.py`：批大小与轻量落表断言改用 `date` / `none` 游标。

**接口层**：

- `tests/test_datasource_api.py` / `tests/test_datasource_cursor.py`（如有）：已删除声明键返回 400；`backfill_date` 返回 400。

**迁移 / 备份**：

- `tests/test_datasource_migration.py`：迁移后 `datasource_entrant_cursor` 不存在，downgrade 后重建。
- `tests/test_workspace_backup_v9.py` / `tests/test_datasource_backup.py`：备份不再包含 `entrant_cursors`，旧归档含该键仍可恢复。

**e2e（前端）**：现有同步任务编辑 / 运行用例保持通过；删除回补相关断言。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | provider / cursor / normalize / http 内核删除 + 旧配置守卫 + 模型删除 + drop 迁移 | 中（配置面收窄） |
| **P1** | pipeline 串行化 + runner / entrant_state 清理 + 备份恢复 / 路由清理 | 中（写路径改动） |
| **P2** | 测试改写 / 前端类型与页面 / ADR 与 CHANGELOG 清理 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方向：删除还是重构 / 保留最小管线 | 删除无配置声明的能力，保留领域无关内核与仍在用的声明面 | 需求方已拍板；仓库内唯一任务是天气示例（columns + date），llm_prompt 只用模板 / 标的 / 流式 | 纯内部重构（不减少维护面）；回退到最小玩具管线（会丢 entrant_source / 流式 / push 等在用能力） | `providers/`、`services/` |
| D2 | 删除范围的边界：哪些算「仅股市日线」 | 删除 `rows_array`（含位置索引与 `\|` 候选）、`row_defaults`、`row_filter`、`scale`、`url_hosts`、`backfill_date`（含多 pass / 水位）、`workers`；保留 `record_layout`（columns 用）、`data_path` 单路径、`entrant_source`、`fill_entrant`、`on_batch`、`rate_limit_ms` | 全仓 grep 无配置声明；天气示例与 llm_prompt 只依赖保留项 | 只删游标不删声明键（声明面仍留死键）；把 `row_filter` 与 tables 行级权限一起删（后者在用） | `base.py`、`http_json.py`、`pipeline.py`、`cursor.py` |
| D3 | `data_path` 候选语法的处置 | 删除 `\|` 候选；rows 模式保留 `_extract_array(..., True)` 的常见键探测 | 候选语义只服务 `rows_array`；rows 探测是通用能力（ADR 0006 既有） | 保留候选但只支持 rows（无消费方，增加解析分支） | `http_json.py`、`core/http.py` |
| D4 | 存量 `backfill_date` 任务与水位数据 | 代码层不再支持；表 drop；JSON 不迁移；旧任务下次运行显式报错 | 与 ADR 0033 C4「存量残留由需求方清理」先例一致；水位已无消费方 | 数据迁移到新结构（无目标结构）；静默忽略（用户以为仍在回补） | `cursor.py`、`models.py`、迁移 |
| D5 | 迁移形态 | 单条 drop 表迁移（幂等 + downgrade 重建），不删 job 列 | 模型删除必须处理 DDL；`request_spec` / `cursor` 是 JSON 无需列迁移 | 删 `datasource_sync_job` 列（无列可删）；保留空表（孤儿表） | `alembic/versions/` |
| D6 | 并发删除后的限速实现 | 保留 `rate_limit_ms`，`_RateLimiter` 退化为串行间隔 | 字段在模型 / API / 前端暴露，需求方倾向不动前端 | 删除限速字段（破坏 API 契约）；保留线程池（无消费方） | `pipeline.py` |
| D7 | 旧配置的处理策略 | 显式报错并列出已删除键；`data_path` 含 `\|` 同 | I3；避免「跑起来但行为变了」的隐性数据差 | 静默忽略未知键（现状，难排查） | `runner.py`、`routers/sync_jobs.py` |
| D8 | 六个 ADR 的处置 | 0033 / 0053 整体删除（文件 + 索引行 + 引用）；0034 / 0035 / 0039 / 0043 改写保留有效决策 | `.trae/rules/agent.md`「需求移除 / 变更」：整体被取代直接删，编号不复用 | 全部保留并标 Superseded（仓库约定不允许）；全部删除（会丢仍在用的流式 / 落表口径） | `docs/adr/` |
| D9 | 测试与覆盖率 | 整删 4 个专用文件；混合用例改写为保留能力断言；门槛不降 | C6；避免空壳测试 | 保留 skip 用例（无被测对象）；下调覆盖率门槛（掩盖真实缺口） | `tests/`、`frontend/` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：请求声明面从 11 个键收敛到 7 个；删除约 1,300 行代码与 4 个测试文件；水位表与备份 / 恢复链路少一条；管线从「线程池 + 取消 + 分组」回到可预测的串行执行，排障与限速语义更直观。
- **负向**：历史回补、双源常量列、零值过滤、量纲换算、主机回退五类能力从平台移除；未来若再需要，需按新需求重新立项（编号不复用 ADR 0033 / 0053）。
- **风险与缓解**：存量 `backfill_date` 任务会在下次运行失败——由「交接」明确运维动作（重配或删除）；旧备份的 `entrant_cursors` 键被忽略，不阻塞恢复。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 同步内核与 provider 分层 | `providers/base.py` | 保留四层抽象与 `SourceProvider` 协议 | ADR 0006 |
| 流式落表 / 批间续租 / 动态标的 | `services/pipeline.py`、`services/runner.py`、`services/entrant_state.py` | 保留（ADR 0034 的 D1 / D3 / D10） | ADR 0034 |
| 选项缓存 / 轻量落表 | `services/write.py`、`tables` 导入路径 | 保留（ADR 0035） | ADR 0035 |
| 批大小 10000 / 索引缓存 / 提交合并 | `pipeline.py`、`write.py`、`runner.py` | 保留（ADR 0039 的 D3 / D4） | ADR 0039 |
| 行所有权 / WAL checkpoint / 失败明细有界 | `pipeline.py`、`core/database.py` | 保留（ADR 0043 的 D2 / D4 / D5） | ADR 0043 |
| push 方向 | `services/push.py`、`routers/sync_jobs.py` | 不变 | ADR 0099 |
| 股市日线双源 / 回补 / 主机回退 | — | 整体删除（ADR 0033 / 0053 文件删除） | 本 ADR |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/datasource/providers/base.py`、`src/cndb/plugins/datasource/providers/http_json.py`、`src/cndb/plugins/datasource/services/cursor.py`、`src/cndb/plugins/datasource/services/normalize.py`、`src/cndb/core/http.py`、`src/cndb/plugins/datasource/models.py`、`src/cndb/alembic/versions/` | `tests/test_datasource_http_json.py`、`tests/test_datasource_migration.py` | `b32129ed` |
| P1 | 已落地 | `src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/services/entrant_state.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/workspaces/services/workspace_restore.py` | `tests/test_datasource_pipeline.py`、`tests/test_datasource_runner.py`、`tests/test_datasource_runner_streaming.py`、`tests/test_workspace_backup_v9.py` | `b32129ed` |
| P2 | 已落地 | `frontend/src/api/datasource.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx`、`docs/adr/README.md` | `frontend/src/pages/datasource/DatasourcePage.test.tsx` | `b32129ed` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P2 全部落地，`Status` 已改 `Implemented`
- 已完成：P0 / P1 / P2；后端声明面 / 执行链 / 迁移 / 备份恢复裁剪，前端类型与旧配置剔除，测试清理，六个 ADR 处置（0033 / 0053 删除，0034 / 0035 / 0039 / 0043 改写）
- 下一步：无（已提交 `b32129ed`）
- 已知坑：存量 `backfill_date` 任务会在下次运行报「未知游标策略」，需运维重配或删除；旧备份归档的 `entrant_cursors` 键按忽略处理；`LD_LIBRARY_PATH` 注入旧 libsqlite3 会使后端测试卡在 import，需 `unset LD_LIBRARY_PATH`
- 最近一次全绿：`make check-fast` + `make test` @ `b32129ed`（2026-11-05，后端 6656 passed / 3 skipped；adr-check 0 error）
