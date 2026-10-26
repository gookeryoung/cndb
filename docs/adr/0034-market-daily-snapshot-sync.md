# ADR 0034: 全市场股票日线增量同步（快照秒级增量 + 按标的回补水位）

Status: Implemented（2026-10-27 人工评审通过）
Date: 2026-10-25
Related: `src/cndb/plugins/datasource/`（models / runner / pipeline / cursor / scheduler / providers）、`src/cndb/plugins/tables/services/core/`（ddl / records）、`src/cndb/alembic/`、`src/cndb/cli/seed/datasource.py`、`examples/datasets/工作区-数据源示例/`；上游 ADR 0006（适配器收敛）、0033（http_json 通用解析扩展）、0008 邻例（分期与迁移范式）
需求卡片: `docs/requirements/0034-market-daily-incremental-sync.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C4），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 参照 stock-strategy 的同步架构 | 复刻其两条路径为声明式配置：①新浪全市场快照（`getHQNodeData` 翻页）承担标的清单与当日行情；②腾讯日线（end 锚点 + 800 根/页）承担历史回补；全程 `http_json` 既有与新增声明能力，不新增 provider、不引入依赖 |
| C2 | 全市场约 7044 只拉取到本地（10 年） | 「数据源示例」工作区 4 条 seed 任务：标的清单（快照翻页）+ 当日快照（增量主路径）+ 历史回补 ×2（主板/创业板/ETF 与科创板，量纲不同拆配置）；回补至 2016-01-01，约 1700 万行 / 372MB |
| C3 | 增量拉取，并非每次全量 | 双层增量：日常 = 快照只写当日 K 线（`row_defaults` 的 `{today}` 模板），秒级完成、无逐股请求；回补 = 按标的回补水位（新游标 `backfill_date`），已补满标的自动跳过，多轮 run 断点收敛 |
| C4 | 数据库膨胀给出更好方式 | 结论：372MB（含索引约 500MB）直存 SQLite 宽表可承受，配套幂等键复合索引（修写入性能）、WAL checkpoint / 低峰 VACUUM / 备份体积说明（帮助文档）；不换存储引擎（否决项见决策记录 D7） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 管线全量攒内存：`run_pipeline` 把所有请求行累积进 `raw_rows`，`execute_job` 末尾一次性 `upsert_rows` | `src/cndb/plugins/datasource/services/pipeline.py:62-120`、`services/runner.py:84-165` | 1700 万行回补内存不可承受；单次大事务也不利断点续跑 | 确认（C2/C3 需要流式分批落表） |
| 2 | 游标仅 job 级单值：`date` / `datetime` / `key_set` / `none` 四策略，水位存 `datasource_sync_job.cursor` JSON | `src/cndb/plugins/datasource/services/cursor.py` | 表达不了「每只标的各自补到哪天」；腾讯接口只有 end 锚点，须按标的给锚点 | 确认（C3 需要按标的回补水位） |
| 3 | `entrant_keys` 为静态 JSON 列表（当前示例 2 只股） | `src/cndb/plugins/datasource/models.py:73-128`（`entrant_keys` 列）、`services/runner.py:build_job_spec` | 7044 只不宜硬编码；新上市标的要随清单自动纳入 | 确认（C2 需要标的动态来源） |
| 4 | 请求串行执行（`for plan in plans: fetch()`），`rate_limit_ms` 为请求间 sleep | `services/pipeline.py:62-120` | 回补 2.1 万请求、快照 75 页并发拉取均无法提速 | 确认（C1 对标 stock-strategy 10 线程需并发能力） |
| 5 | 动态表无幂等键复合索引：`find_rows_by_key` 按每 500 行批 OR 查询 | `src/cndb/plugins/tables/services/core/records.py:883-913`、`services/core/ddl.py:98-148`（`build_sa_table` 不建业务索引） | 千万行表上批量 OR 查询退化为全表扫描，落表极慢 | 确认（C2/C4 写入性能） |
| 6 | 租约 TTL 300s、无续期；手动「立即运行」HTTP 同步执行 | `src/cndb/plugins/datasource/services/scheduler.py:30,134-164`、`routers/sync_jobs.py:217` | 长回补 run（30~60 分钟）会被判死锁遭抢占；HTTP 侧必超时 | 确认（C2 需要批间续租 + CLI 执行口径） |
| 7 | `row_defaults` 为纯静态常量（ADR 0033） | `services/pipeline.py`（`apply_row_defaults`）、`providers/http_json.py` | 快照写当日 K 线需要 `日期 = {today}` 动态值 | 确认（C3 快照路径） |
| 8 | 无行级过滤能力（归一后全量 upsert） | `services/pipeline.py` | 停牌 / 零值快照行会写成 0 价格 K 线（stock-strategy 以 price≤0 剔除） | 确认（C3 数据质量） |
| 9 | 0033 已交付能力：`rows_array` / `data_path={entrant}` / `row_defaults` / `scale` / `fill_entrant` | `providers/http_json.py:96-228`、`services/pipeline.py:111-139` | 腾讯行数组、按标的嵌套、来源常量、量纲换算全部现成；本 ADR 只补「per-entrant 的 end 锚点模板变量」 | 确认（C1 直接复用） |
| 10 | seed 注入按 `(workspace_id, name)` 幂等，只增不删 | `src/cndb/cli/seed/datasource.py:40-117` | 旧 2 条示例任务须由本 ADR 显式从 `datasource.json` 移除（文件级移除，存量库残留由需求方清理，口径同 0033 C4） | 确认（C2 任务重组） |
| 11 | seed 结构测试锁「2 llm_prompt + 2 http_json」任务清单 | `tests/test_seed_datasource.py:170-199` | 任务重组后须同步改断言 | 确认（测试面） |
| 12 | 分页空页即停（`stop_pages`）按 (entrant, window) 分组 | `services/pipeline.py:109-110` | 新浪快照翻页（page 递增到空页停）直接复用 | 确认（C1 清单/快照翻页） |
| 13 | 时间窗口展开 `iter_windows` 为 job 级统一起点 | `services/pipeline.py`（`iter_windows`）、`providers/http_json.py:65-84`（`build_requests`） | 回补需要 per-entrant 锚点（各标的水位不同），展开层须支持映射注入 | 确认（C3 与 #2 同源） |
| 14 | 视图校验白名单两处同口径 | `src/cndb/plugins/tables/routers/views.py`、`src/cndb/cli/seed/views.py` | 新视图只用既有形态与字段键则不动白名单 | 排除（预计无需改动，落地时复核） |
| 15 | 帮助文档已有数据源示例清单 | `src/cndb/plugins/help/services/examples.py` | 大表维护口径（VACUUM / 备份体积）需补帮助文档 | 确认（C4） |

**核心缺陷（需求要补的）**：同步引擎是「小任务」形态——静态标的集、单值游标、串行请求、全量攒内存、无幂等索引；表达不了「全市场标的动态集 + 按标的回补水位 + 并发限速 + 千万行流式落表」的大规模形态。

设计目标（不变量）：

- **I1 领域无关**：引擎扩展（游标 / 流式 / 并发 / 动态标的 / 行过滤 / 索引）不出现股票语义；`providers/`、`services/` 无 symbol / 快照 / K 线等领域词，股票配置只存在于 `examples/datasets` 的 JSON（守住 ADR 0006 D2）。
- **I2 幂等可重跑**：任意 run 中断重跑，已落库批次保留且幂等键命中只更新；游标水位**只向更早日期前进、不后退**；已补满标的零请求。
- **I3 失败留痕不拖垮**：单请求失败（限流 / WAF / 格式）记 `failures`，不中断整轮 run；partial 结果照常落库推进（沿用 ADR 0006 I3）。
- **I4 并发下限速语义**：`rate_limit_ms` 升级为**全局相邻请求最小出发间隔**（workers 并发时同样成立）；`workers=1` 时行为与现状完全一致（默认值不变，旧任务零影响）。
- **I5 存量兼容**：旧任务（无 `entrant_source` / `workers` / `row_filter`，`cursor` 为旧四策略）行为不变；迁移可 downgrade。
- **I6 引用完整性**：`datasource_entrant_cursor` 随 job 删除级联清理；标的来源表被删时 run 落 `failed`（不静默空跑）。

## Decision

### 1. 数据模型

一次迁移（`src/cndb/alembic/versions/`，down_revision = `f2b3c4d5e6a7`）：

| 对象 | 变更 | 说明 |
|---|---|---|
| 新表 `datasource_entrant_cursor` | PK `(job_id, entrant)`；`cursor_value: str`；`updated_at` | 按标的回补水位（ISO 日期串）；`job_id` FK → `datasource_sync_job` ON DELETE CASCADE |
| `datasource_sync_job` | 新列 `entrant_source: JSON NULL` | 结构 `{"table": "<表名>", "field": "<字段名>", "prefix_in": ["sh6", ...]?}`；NULL = 仅静态 `entrant_keys`（旧行为） |

`request_spec` / `cursor` JSON 内新增**声明键**（无 schema 变更，向后兼容）：

| 声明位置 | 新键 | 语义 |
|---|---|---|
| `request_spec` | `workers: int`（默认 1） | 请求并发数；>1 时 plans 线程池并发执行 |
| `request_spec` | `row_filter: {field, op, value}`（可选单个） | 归一后按数值条件过滤行（op ∈ `>` `>=` `<` `<=` `==` `!=`；字段非数值 / 缺值 → 剔除该行） |
| `request_spec` `url`/`param` 模板 | `{end}` 变量（per-entrant） | 回补请求的 end 锚点按该标的当前水位注入（水位−1 天）；`{today}` 亦可用于 URL |
| `row_defaults` 值 | `{today}` 等内置变量渲染 | `apply_row_defaults` 先经 `render_text` 再 setdefault（变量：`today`；`{entrant}` 已有机制沿用） |
| `cursor` | `strategy: "backfill_date"`；`field`；`backfill_start` | 按标的回补水位（详见 §2） |

### 2. 判定算法（关键机制）

**backfill_date 游标**（`services/cursor.py`）：

1. **准备**（run 开始）：对每个 entrant 读 `datasource_entrant_cursor`，得 `watermark(e)`；无水位标的初值 = 「今天」的昨日（即首轮只拉最近一段）；`watermark(e) <= backfill_start` 的标的**跳过**（零请求）。
2. **请求展开**：`build_requests` 对每个活跃 entrant 生成 1 个请求，模板变量 `end = watermark(e) − 1 天`（`n=800` 固定在 URL/param 里）；`SyncJobSpec` 新增 `entrant_ends: Mapping[str, str]`。
3. **响应→水位推进**：该 entrant 返回行中**最早日期** `d_min(e)`；新水位 = `max(d_min(e), backfill_start)`，且**只前移不后退**（`min(旧, 新)` 向更早方向）；空响应不推进（该标的已到头或停牌）。落库与水位推进**同批事务边界**（先 persist 批次，成功后写水位）。
4. **收敛**：多轮 run（手动或 interval 调度）水位逐轮向 `backfill_start` 前推，全部达标后 run 变零请求空转（记 `skipped`）。

**流式落表**（`services/pipeline.py` + `services/runner.py`）：

- `run_pipeline` 增加回调形态 `on_batch(rows)`：抓取循环内攒满 `batch_size`（默认 5000）行即回调；runner 侧回调执行 `upsert_rows`（既有 Importer 幂等路径）+ 逐标的水位推进 + 批间 `renew_lease`；run 计数跨批累积。
- 中途失败：已 persist 批次保留（幂等重跑安全），水位停在最后成功批，异常照旧落 failed run 留痕（I3 口径：单请求失败继续、致命异常终止）。
- `preview_job` 保持原「小路径」全量内存形态（预览量小，不动）。

**并发与限速**（`services/pipeline.py`）：

- `workers > 1`：`ThreadPoolExecutor`，plans 按提交顺序并发执行；同 (entrant, window) 分组的分页**组内串行**（保 `stop_pages` 语义：前页空则丢弃后续页）。
- `rate_limit_ms`：全局锁 + 下一允许出发时间戳，任意线程出发前等待（I4）；`workers=1` 时即退化为现状的顺序 sleep，行为不变。
- fetcher 线程安全前提：`http_json` 的 fetch 为无共享态 HTTP 调用（`src/cndb/core/http.py` 每请求独立会话），并发安全；`llm_prompt` 不声明 `workers`（>1 时引擎告警并按 1 执行，避免打爆 LLM 配额）。

**标的动态来源**（`services/runner.py:build_job_spec`）：

- 解析 `entrant_source`：查同工作区 `DataTable`（按名）→ 目标字段 distinct 非空值 → 可选 `prefix_in` 前缀过滤；与静态 `entrant_keys` **并集去重**。
- 表 / 字段不存在 → run 落 `failed`（错误信息指明来源配置），不静默空跑（I6）。

**幂等键复合索引**（`services/write.py`）：

- 首次落表前（或 job 首次执行时）`CREATE INDEX IF NOT EXISTS ix_<table>_<cols> ON <物理表> (<db_column_name 列序>)`；非唯一、幂等；列取 `match_keys` 对应 `DataField.db_column_name`。

**租约续期**（`services/scheduler.py`）：

- 新函数 `renew_lease(session, job_id, owner)`：校验 `lease_owner == owner` 后刷新 `lease_until = now + TTL`；`execute_job` 每批 persist 后调用；续期失败（租约易主）→ 抛 `LeaseLost` 终止 run 留痕。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST/PUT /workspaces/{wid}/datasource/jobs` | 无 schema 改动（`request_spec` / `cursor` 本为自由 JSON，新声明键随 payload 透传）；可选后续在前端向导补只读展示 |
| `POST .../jobs/{id}/run` | 语义不变；文档注明大规模回补任务建议 CLI `cndb sync tick` 执行（HTTP 等待有超时） |

### 4. 边界与例外

1. 腾讯接口 `start` 参数不生效（stock-strategy 实测），回补请求 param 的 start 位**留空**，仅 end 锚点 + 800 根生效；水位推进依赖响应内最早日期。
2. 腾讯返回空序列（标的已退市 / 停牌超窗口）：不报错、不推进水位，行数 0 记 `skipped`——避免每轮空转重试同一请求由水位卡住（`backfill_date` 达 `backfill_start` 才跳过；长期停牌标的每轮 1 次空请求属可接受开销）。
3. 新浪快照零值行（停牌）：`row_filter`（如「最新价 > 0」）剔除；被剔除行计入 run 的 `filtered` 计数（新增计数字段值，落 `stats` JSON，不改表结构——`datasource_sync_run` 的计数列既有口径沿用，过滤数进 `detail`/`stats` 留痕）。
4. 快照（不复权原价）与回补（腾讯 qfq 前复权）当日口径天然不同：幂等键含「来源」，两口径并存不互覆；已知局限——腾讯 qfq 为等差前复权，超长期高分红标的历史价可能失真（与 stock-strategy 全市场回补同口径，其仅对自选股做 hfq+等比修复，全市场不做）。
5. 成交量单位：目标表统一**股**；新浪快照原值（股）、腾讯主板/创业板/ETF `scale=100`（手→股）、科创板（sh68/sh69）腾讯原值即股（`scale` 不声明）——量纲差异用两条回补任务（`prefix_in` 互斥）表达，不引入启发式换算。
6. `row_filter` 仅数值比较、单个条件；复杂过滤属分析层职责（分析范围 Scan Scope 已有），同步层只做最小剔除。
7. `entrant_source` 指向的表无行（如清单尚未首拉）：并集后为空 → run 零请求记 skipped（清单任务先行，属正常启动顺序，不判 failed）。
8. ETF 的腾讯成交量单位与个股不同属潜在口径风险（stock-strategy 未对 ETF 特判）：首轮回补后抽样核对，若不一致按 §5 同款拆任务修正（配置级改动）。

### 5. 种子任务设计（examples/datasets/工作区-数据源示例/datasource.json）

移除旧 2 条股市日线任务（新浪 2 只 / 腾讯 2 只，0033 产物；引擎能力保留，示例任务演进），新增 4 条：

| 任务 | 接口 / 形态 | 目标表 / 幂等键 | 关键声明 |
|---|---|---|---|
| ① 全市场标的清单 | 新浪 `getHQNodeData`（`node={entrant}`，hs_a + etf_hq_fund 两 entrant，page 翻页 num=100 空页停） | 「股票清单」/ `[代码]` | `entrant_keys=["hs_a","etf_hq_fund"]`；映射 symbol→代码、name→名称等；`schedule=manual`（文档指导改 daily） |
| ② 股市日线·当日快照 | 同①（快照行情写当日 bar） | 「股市日线」/ `[股票代码, 日期, 来源]` | `row_defaults={"日期":"{today}","来源":"新浪快照"}`；`row_filter` 收盘>0（归一后目标字段）；`fill_entrant` 补股票代码；`cursor=none`；`workers=2`（两节点组间并发） |
| ③ 股市日线·历史回补（主板/创业板/ETF） | 腾讯 `proxy.finance.qq.com` fqkline（`param={entrant},day,,{end},800,qfq`，`data.{entrant}.qfqday`，rows_array） | 同上 | `entrant_source={"table":"股票清单","field":"代码","prefix_in":["sh60","sz00","sz30","sh5","sz1"]}`（与④的 sh68/sh69 互斥，前缀精确到板块段——`sh6` 会误吞科创板）；`cursor={"strategy":"backfill_date","field":"日期","backfill_start":"2016-01-01"}`；`row_defaults={"来源":"腾讯前复权"}`；成交量 `scale=100`；`workers=6`、`rate_limit_ms=150`；`schedule=manual` |
| ④ 股市日线·历史回补（科创板） | 同③ | 同上 | `prefix_in=["sh68","sh69"]`；无 `scale`（腾讯对科创板返回股）；其余同③ |

配套：`fields.json` 新增「股票清单」表（代码/名称/类型/最新价/成交额/市值/换手率/更新日期）、「股市日线」表补「成交额」字段；`views.json` 「股市日线」两条来源筛选视图对齐新来源值（新浪快照 / 腾讯前复权，既有 filter 形态，不动白名单）；「股市日线.csv」「股票清单.csv」示例行与新任务来源口径一致，保持 seed 幂等。

### 6. 迁移

见 §1。upgrade：建表 + 加列（nullable，无默认值回填）；downgrade：drop 表 + drop 列（列数据丢弃属预期——水位可重算）。迁移测试：幂等 + downgrade 往返（`tests/test_migrations.py` 既有链路）。

### 7. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 数据源任务详情（只读展示） | `frontend/src/pages/datasource/`（详情/描述组件） | `cursor.strategy=backfill_date`、`entrant_source`、`workers`、`row_filter` 的只读渲染兼容（未知键不报错）；不做配置 UI |
| 向导 | 同上 | `HTTP_JSON_PARAMS_SCHEMA` 不扩（新键属配置文件级能力，与 0033 口径一致） |

### 8. 测试清单

**判定层（单测）**：
- `backfill_date` 游标：初值 / 跳过已达标标的 / 水位只前移不后退 / 空响应不推进 / `max(d_min, backfill_start)` 截断
- `entrant_ends` 注入：`build_requests` 对 per-entrant `{end}` 模板渲染；旧任务（无映射）回归不变
- `row_filter`：数值比较保留/剔除、非数值/缺值剔除、无声明零影响
- `row_defaults` 模板：`{today}` 渲染、响应自带值优先、静态值回归
- 限速器：并发下相邻出发间隔 ≥ `rate_limit_ms`（用假 fetch 记录时间戳断言）；`workers=1` 行为不变
- 索引：`CREATE INDEX IF NOT EXISTS` 幂等（跑两次不报错）、列序 = match_keys
- `renew_lease`：持租约续期成功、易主后抛 `LeaseLost`

**接口层 / 集成**：
- `execute_job` 假 fetch 桩（stock-strategy 真实响应样例截取）：①清单翻页空页停；②快照写当日 bar（日期={today}、零价行被滤）；③回补两轮：首轮水位推进 + 行落库，kill 模拟（首轮批间抛异常）后重跑**只补缺口**（已落库行不重复、inserted≈0、水位不回退）；④全部达标后 run 零请求
- 流式：batch_size=小值注入，断言多批 upsert、批间续租被调用、中途失败已落批保留
- `entrant_source`：清单表 distinct + prefix 过滤 + 静态并集；表缺失 → failed run
- 迁移：upgrade/downgrade 往返 + job 级联清理水位行
- seed：`test_seed_datasource.py` 改锁 4 条新任务（2 llm_prompt + 4 http_json）；清单/日线表字段与任务声明自洽校验

**e2e（前端）**：无新增（只读展示兼容由单测覆盖；不新增页面/视图形态）

### 9. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 本 ADR + 需求卡片评审（人工卡点） | 低 |
| **P1** | 引擎能力：迁移 + `backfill_date` + `entrant_source` + 流式落表 + 并发限速 + `row_filter`/`{today}` + 复合索引 + 续租 + 判定层/集成单测 | 高（流式与并发改造触及管线主干，须保 I4/I5 兼容） |
| **P2** | 种子落地：4 条任务 + fields/views/CSV + 前端只读兼容 + seed 测试 | 中（配置与 seed 校验口径逐项对齐；真实接口格式验证） |
| **P3** | 真源 smoke（3 只标的）→ 全量回补演练（轮数/耗时/库体积记录）+ 帮助文档大表维护节 + `make flow` 全绿收尾 | 中（第三方接口限流 / 格式漂移；演练须真实联网） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 大规模回补的内存形态 | 流式分批落表（batch 5000）：抓取与落库交错，批粒度推进水位 + 续租，中途失败已落批保留 | 1700 万行全量攒内存不可行；批粒度 = 最小安全断点 | ① 分 run 全量（单轮太长、失败全弃）；② 响应驱动无限流式生成器（分页语义复杂化，收益小） | `services/pipeline.py`、`services/runner.py` |
| D2 | 按标的增量表达 | 新游标 `backfill_date` + 新表 `datasource_entrant_cursor`；腾讯「end 锚点 + n 根」语义与水位天然对齐，多轮 run 收敛 | job 级单值游标表达不了 per-entrant 水位；stock-strategy 同构（end 锚点前推 + cursor 断点） | ① 每标的独立 job（7000+ job 管理不可接受）；② 响应内日期推导窗口（腾讯 start 不生效，无法表达） | `services/cursor.py`、`models.py`、迁移 |
| D3 | 标的集合维护 | `entrant_source` 动态来源（查清单表 distinct + prefix 过滤）与静态 `entrant_keys` 并集 | 7044 只硬编码不可维护；新上市自动纳入；prefix 过滤承载量纲分组（科创板拆任务） | ① 全静态列表（更新靠人工）；② 引擎内置全市场清单（领域词进引擎，违反 I1） | `models.py`（新列）、`services/runner.py` |
| D4 | 当日增量路径 | 快照直写当日 bar：`row_defaults={"日期":"{today}"}` + `row_filter` 滤零值，非逐股请求 | stock-strategy 实测秒级（75 页并发 vs 7000 请求）；停牌零值行必须剔除 | ① 逐股拉当日（7044 请求，违背 C3 初衷）；② 快照另建当日表（同表幂等键含来源已可并存，多表徒增复杂度） | `services/pipeline.py`（模板/过滤）、种子② |
| D5 | 请求提速 | `request_spec.workers` 并发 + `rate_limit_ms` 升级全局最小出发间隔 | 回补 2.1 万请求 / 快照 75 页，串行过慢；stock-strategy 10 线程先例；限流是腾讯 501 防线 | ① 保持串行（全量回补小时级不可接受）；② 无限并发（必被限流封禁） | `services/pipeline.py` |
| D6 | 大表写入性能 | 按 `match_keys` 建非唯一复合索引（任务首跑幂等创建） | 无索引时千万行表批量 OR 查询全表扫描；非唯一不改变应用层幂等口径（ADR 0006 否决的是唯一约束） | ① 唯一索引 + `ON CONFLICT`（改写幂等路径，动摇 0006 口径）；② 不建索引（落表性能不可接受） | `services/write.py` |
| D7 | 372MB 存储结论 | 直存 SQLite 宽表；配套 D6 索引 + WAL checkpoint / 低峰 VACUUM / 备份体积文档 | SQLite 单库 TB 级容量，372MB（含索引~500MB）远在安全区；保住表格/视图/K 线全链路能力 | ① 外部文件（CSV/parquet + 路径引用，丧失全部表格能力）；② 按年分表（DataTable 无分区语义）；③ 独立库文件（连接层架构改动） | 帮助文档（P3） |
| D8 | 旧示例任务处置 | 移除 0033 的 2 条 2 只股示例任务，演进为 4 条全量任务；引擎能力全保留；存量库旧任务残留由需求方清理（口径同 0033 C4） | 示例要示范的就是全量形态；2 只股示例已被覆盖无保留价值 | 保留旧任务（4+2 并存徒增演示噪音） | `examples/datasets/工作区-数据源示例/datasource.json` |
| D9 | 双口径并存与量纲 | 幂等键含「来源」；快照=不复权原价、腾讯=前复权并存；成交量统一股（主板 scale=100 / 科创板无 scale 拆任务） | 沿用 0033 D5 先例；腾讯 qfq 等差复权局限记录在案；量纲拆任务是纯配置表达 | ① 同步层价格换算（需除权因子，超职责）；② 启发式按代码段换算（引擎进领域词，违反 I1） | 种子③④ |
| D10 | 长任务执行方式 | 回补走 CLI `cndb sync tick`（或 interval 调度），批间 `renew_lease`；「立即运行」HTTP 入口保留但不承诺长任务 | HTTP 同步等待必超时；租约 300s 无续期会被误抢占 | ① 调大 TTL（治标，仍有无界长任务）；② 后台任务队列（新基建，超出本卡范围） | `services/scheduler.py`、`services/runner.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：同步引擎获得「大规模任务」形态（动态标的集 / 按标的水位 / 并发限速 / 流式断点 / 幂等索引），任何同类大规模 API（不限股票）可用配置接入；「数据源示例」升级为全市场可运行链路，日常增量秒级；大表写入性能与库体积口径有明确文档。
- **负向**：管线主干从「攒全量」改「流式回调」，runner/pipeline 复杂度上升；多一张游标水位表与一个 job 列（迁移面）；`backfill_date`/`entrant_source`/`workers`/`row_filter` 四个新声明键的认知成本。
- **风险与缓解**：① 腾讯限流（501）→ workers=6 + rate_limit_ms=150 保守起步，失败留痕下轮续跑（D2 天然断点）；② 真实接口格式漂移 → P2 首步真源验证，配置级可改；③ 首轮全量回补 30~60 分钟属预期 → CLI 执行 + 文档说明；④ ETF 量纲待抽样核对（§4.8）。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

无（不引入新领域模型；股票语义全在示例配置层）。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 适配器边界 | `providers/registry.py` 仅两 provider | 本 ADR 不触碰注册表；全部能力落在引擎服务层与 `http_json` 声明键 | ADR 0006 D2 |
| http_json 声明能力 | `rows_array` / `data_path` / `row_defaults` / `scale` | 全部复用；本 ADR 只加 `{end}` per-entrant 变量与 `{today}` 模板 | ADR 0033 |
| 股市示例口径 | 「数据源示例」工作区 | 2 只股双源示例演进为全市场 4 任务；幂等键「来源入键」口径不变 | ADR 0033 D5/D8 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `docs/requirements/0034-market-daily-incremental-sync.md`、`docs/adr/0034-market-daily-snapshot-sync.md` | `tests/test_seed_datasource.py` | `0d61f94b` |
| P1 | 已落地 | `src/cndb/alembic/versions/a9d4e8f1c2b6_add_datasource_entrant_cursor.py`、`src/cndb/plugins/datasource/services/cursor.py`、`src/cndb/plugins/datasource/services/entrant_state.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/services/scheduler.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/providers/base.py`、`src/cndb/plugins/datasource/providers/http_json.py`、`src/cndb/plugins/datasource/models.py` | `tests/test_datasource_cursor_backfill.py`、`tests/test_datasource_pipeline_concurrency.py`、`tests/test_datasource_runner_streaming.py`、`tests/test_datasource_migration.py` | `0d61f94b` |
| P2 | 已落地 | `examples/datasets/工作区-数据源示例/datasource.json`、`examples/datasets/工作区-数据源示例/股票清单.csv`、`examples/datasets/工作区-数据源示例/股市日线.csv`、`examples/datasets/工作区-数据源示例/fields.json`、`examples/datasets/工作区-数据源示例/views.json`、`src/cndb/cli/seed/datasource.py`、`frontend/src/api/datasource.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx` | `tests/test_seed_datasource.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | `0d61f94b` |
| P3 | 已落地 | `frontend/src/pages/help/content/configuration.tsx`、`src/cndb/plugins/help/services/examples.py` | `tests/test_help_examples_api.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | `0d61f94b` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P1–P3 全部落地，`Status` 已于 2026-10-27 经人工评审确认改 `Implemented`
- 已完成：引擎全量能力（backfill_date 水位 / entrant_source 动态标的 / 流式落表 / workers 并发 + 全局限速 / row_filter + {today} 模板 / 幂等键复合索引 / 批间续租）；种子 4 条全市场任务替换旧 2 条；前端只读兼容 + 编辑保留声明键；帮助文档「大规模同步与增量」「大表与库体积维护」两节
- 真源演练结论（2026-10-25，3 只股 + 全市场快照）：清单单轮 7289 只入库；动态标的拆分 6319（主板/创业板/ETF）+ 617（科创板）；当日快照 7286 行、停牌零值 3 行被 `row_filter` 剔除、二轮重跑 0 新增全 update（幂等）；腾讯回补每轮每标的 800 根，水位 2023-07-05 → 2020-03-18 逐轮前推，断点续跑语义验证通过
- 已知坑：① `_advance_backfill` 取标的列必须用 field_mapping 映射后的**目标列名**（源键归一后已被重命名，测试须覆盖映射路径）；② 回补前缀必须精确到板块段（`sh6` 会误吞科创板 sh68x，正确为 `sh60`）；③ 新浪 hs_a 节点含北交所（bj 前缀），回补前缀天然排除，快照当日行会包含（可接受口径）；④ `make check` 的 ruff format 是全仓扫描，他人未格式化文件会挡 lint（本次 documents/importers/docx.py、html.py 属并发会话，只 stage 自己文件提交）
- 下一步：无（功能完结）；存量实例需清理旧 2 条任务后重跑 `cndb seed`（口径同 0033 C4）；全量十年回补首跑约 30~60 分钟（CLI `cndb sync tick` 驱动，多轮收敛）
- 已修复（提交后检查 @ 2026-10-26）：全部标的补满后 `entrant_values` 为空，`build_requests` 的 `or (None,)` 回退会发一条空标的伪请求，`{end}` 无锚点注入 → `ProviderError` → 每次运行落 `failed`（违背 D2「补满自动零请求」）。现由 `SyncJobSpec.entrants_exhausted` 显式区分「解析后为空」与「未声明标的」，`preview_job` 同时补上水位锚点注入（预览与执行同口径）。回归锚点：`tests/test_datasource_pipeline.py::test_exhausted_entrants_make_zero_plans`、`tests/test_datasource_runner_streaming.py::test_preview_injects_watermark_anchor` / `test_watermark_truncated_to_backfill_start`
- 最近一次全绿：`make test` 5422 passed / 3 skipped、`make cov` 97.03%（门槛 95%）@ 2026-10-26；前端门禁本沙箱因 corepack 缓存缺失（`pnpm@12.4.2`）无法执行，非本次改动引起
