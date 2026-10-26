# ADR 0043: 数据源同步落库剩余开销削减（行拷贝收敛 / 幂等匹配分片 / WAL 收尾 / 失败明细有界）

Status: Accepted（2026-10-26 需求方评审通过，进入实现）
Date: 2026-10-26
Related: `src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/services/normalize.py`、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/services/importing/importer.py`、`src/cndb/core/database.py`、`docs/adr/0039-datasource-daily-sync-reliability.md`、ADR 0006 / 0034 / 0035 / 0040
需求卡片: `docs/requirements/0043-datasource-write-path-overhead.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 归一路径上对同一行数据的重复浅拷贝收敛为必要次数；每行对象仍互相独立 | D2：确立「`normalize` 输出即行所有权边界」，`on_batch` 去掉整批复制；`fill_entrant` / `apply_row_defaults` / `apply_row_filter` 增 `inplace` 分支由同步管线启用（默认仍复制，公共语义不变）。每行拷贝 5 次 → 2 次（`to_records` + `apply_field_mapping`） |
| C2 | 幂等匹配查询的默认分片从 500 提到 2000（或经量测后取不触发绑定变量上限的值） | **实测后不做**（C6）：同机 10k 键 / 3 键任务下 500→2000 仅省 ~1.5ms（<0.5% 批次成本），保持 `chunk_size=500` 原样；无代码改动 |
| C3 | 每轮结束（成功 / 部分失败 / failed）后 SQLite 执行 `PRAGMA wal_checkpoint(TRUNCATE)`，失败只记日志 | D4：新增 `core/database.checkpoint_wal()`（方言判定 + journal_mode 判定 + busy 行读取 + 全异常吞掉），`execute_job` 成功与失败两条收尾路径各调一次 |
| C4 | 归一失败明细有界：保留总计数，明细只保留前 N（建议 100） | D5：`_NormalizeAggregate` 增 `failed_total` 与 100 条额度；`detail` 键集合与条数口径不变，总计数仅进日志 |
| C5 | 不放宽校验 / 幂等 / 限速 / 批大小 / 导入默认路径；不引入多进程、不换引擎、不新增依赖、不改 API / 前端 | 全 ADR 遵守；多进程并行由 D6 明确排除 |
| C6 | 每项必须给同机前后对比；收益 <3% 需记「实测后不做」 | 「Consequences」给出验收口径；P2 末的交接要求回填实测数据 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号 1..6 逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 归一路径对同一行重复浅拷贝：`to_records` 每行新建 → `fill_entrant` 再建 → `apply_row_defaults` 再建 → `apply_field_mapping` 再建 → `runner.on_batch` 整批再建 | `pipeline.py:380`、`:393`/`:396`、`:415`/`:422`、`:439`/`:444`/`:455`、`normalize.py:84`/`:90-106`、`runner.py:712` | 单行 5 次 dict 分配；3.83M 行/轮约 1,900 万次。其中 `on_batch` 那次复制发生在 `normalize` 已产出全新 dict 之后，属纯冗余 | 确认 C1 |
| 2 | 幂等匹配分片固定 500，调用方不传参 | `records.py:946`（`chunk_size: int = 500`）、`importer.py:590` | 10,000 行批 = 20 次查询；调大理论减少查询次数，但本地 SQLite 下参数绑定与结果处理占主导 | 确认 C2，**实测后不做**（见 D3） |
| 3 | 全轮无 WAL checkpoint；0039 交接已列为遗留项 | `runner.py:828-899`（`_finalize` / `_update_job_state` 后无收尾）、`docs/adr/0039-*.md:193`、`core/database.py:36-73`（连接级 pragma 已有 WAL / sync=NORMAL） | 3.83M 行写入期间 WAL 持续膨胀，前台读、备份体积与后续批次都受牵连 | 确认 C3 |
| 4 | 归一失败明细跨全轮累积无上限 | `pipeline.py:111`（`_NormalizeAggregate.failures`）、`runner.py:860-867`（`_finalize` 只取前 100） | 大面积类型不匹配的源会让内存随行数线性增长；保留的绝大多数明细无消费方 | 确认 C4 |
| 5 | 连接级 pragma 已含 `journal_mode=WAL` / `busy_timeout=5000` / `cache_size=-20000` / `synchronous=NORMAL` | `core/database.py:55-70` | checkpoint 必须与此既有口径共存：忙时返回 busy 行而非抛错，`busy_timeout` 仍生效 | 确认（C3 前置条件） |
| 6 | 批量写不逐行记 audit，只清搜索缓存 | `records.py:1129`/`:1133` | 与 C1 无冲突；确认拷贝收敛不改变搜索缓存失效时机 | 排除（无改动） |
| 7 | `RowValidator` 的字段写回只改它自己的 `effective_row`（`_apply_mapping` → `remap_row` 新建 dict） | `row_validator.py:147-176`、`:238`/`:250` | 是 D2「去掉 `on_batch` 复制」安全性的前提：校验阶段不会反写管线行 | 新增（C1 依据） |
| 8 | `preview_job` 的 `normalize_failures` 已按 50 条截断，与运行记录的 100 条不同源 | `runner.py:419-426` | 两个出口各自截断，C4 只改运行侧聚合，预览侧不动 | 新增（C4 边界） |

**核心缺陷（需求要补的）**：ADR 0035/0039/0040 已把 SQL 形态与二次归一压缩到「SQL 写仅占批次的几十分之一」，剩余成本集中在**应用层重复的整行拷贝与无界的诊断累积**——这些既不是校验语义，也不是幂等语义，属可无损削减的纯开销；同时大表写入缺少 WAL 收尾，使同轮次的磁盘与读路径成本随行数放大。

设计目标（不变量）：

- **I1 行独立性**：任何两行不得共享同一 dict；管线交出某一批行后不再改写该批对象（保证落库与预览拿到的行不会被后续批次污染）。
- **I2 写入等价**：同一输入批次，优化前后写入的行集合与 `inserted / updated / skipped / fetched` 计数完全一致；`setdefault` 语义（响应自带值优先）、`row_filter` 剔除口径、未知列与必填判定均不变。
- **I3 查询等价**：任意 `chunk_size` 下 `find_rows_by_key` 返回的 `exact_map` / `conflict_map` 完全一致（含空键 `IS NULL` 分支与 `min(id)` 冲突口径）。
- **I4 收尾不侵入**：checkpoint 在任何情况（忙、锁、异常、非 WAL、非 SQLite）都不得改变运行记录状态、不得回滚已落库批次、不得向外抛错。
- **I5 边界不变**：不放宽逐格校验（0040 D5/D8）、不引入唯一索引或 `ON CONFLICT`（0006 / 0034 D6）、不改全局限速（0034 D5）、不改批大小 10,000（0039 D4）、不改人工导入默认路径（0035 D2）；零迁移、零 API、零前端、零新增依赖。

## Decision

### 1. 数据模型

无。不新增表 / 列 / 索引，不改枚举。

### 2. 判定算法（唯一入口）

**(a) 行所有权边界与就地改写**（`pipeline.py`、`runner.py`）

- **所有权边界定义**：一次同步里，每行只允许在 `to_records()`（`:378`）与 Provider 归一（`normalize.apply_field_mapping`，`normalize.py:84`/`:90-106`，即使映射为空也新建 dict）两处新建对象；两处之间与之后一律就地改写同一对象。
- **就地分支**：`fill_entrant(rows, entrant_param, entrant, *, inplace: bool = False)`、`apply_row_defaults(rows, defaults, *, variables=None, inplace: bool = False)`、`apply_row_filter(rows, row_filter, *, inplace: bool = False)`：
  - `inplace=False`（默认）保持现有「返回新 dict 列表」行为，外部调用方与既有用例零改动；
  - `inplace=True` 时直接对传入 dict 执行 `setdefault` / 就地返回原引用集合（过滤只决定保留哪些引用，不复制），供 `_run_group`（`:299-305`）与 `_BatchSink._process`（`:364-375`）启用。
- **`on_batch` 去拷贝**：`_StreamingState.on_batch`（`runner.py:710-712`）把 `batch = [dict(row) for row in rows]` 改为浅列表拷贝 `list(rows)`（保留 `list` 契约与计数口径），不再复制行 dict —— 依据 Context #1（`normalize` 已产出全新对象）与 #7（`RowValidator` 不反写入参）。
- **交付后不再改写**：`_BatchSink.flush` 交出 `chunk` 后即从 `_buffer` 删除（`:358-362`），`_process` 交出 `kept` 后不再触碰；`outcome.rows`（无回调模式）只追加不再原地改。

**(b) 幂等匹配分片上限**（`records.py`）—— 实测后不做

- **结论**：`find_rows_by_key` 保持 `chunk_size = 500` 原样，不改代码（D3、C6）。
- **实测**（同机临时 SQLite 表：20k 行 / 3 键复合索引，10k 唯一键半命中，各跑 3~5 轮取最佳）：

  | 分片 | 耗时 | SELECT 次数 |
  |---|---|---|
  | 500（现状） | 41.6 / 41.9 / 42.4 ms | 20 |
  | 1000 | 40.7 / 41.2 / 41.4 ms | 10 |
  | 2000 | 40.1 / 40.7 / 40.5 ms | 5 |

  相对收益约 **2~4%**，绝对只省 **约 1.5ms / 万行**。而 0040 基准里一个 1 万行批的端到端成本是
  **0.3s（去重归一）~2s（落库）**——1.5ms 占比 **<0.5%**，属噪声级；本地 SQLite 下
  SQLAlchemy 参数绑定与结果集处理占主导，减少查询次数不转化为可观吞吐。
- **重开条件**：切到 PostgreSQL 或目标库跨网络（查询往返成本量级变化）时，再按 C2 原设计
  （`max_vars // 键列数` 封顶）重新评估。

**(c) WAL 收尾检查点**（`core/database.py`、`runner.py`）

- 新增 `checkpoint_wal(target_engine: Any, *, mode: str = "TRUNCATE") -> bool`：
  1. `dialect.name != "sqlite"` → 返回 `False`（不报错）；
  2. 独立连接（`with target_engine.connect() as conn`）读 `PRAGMA journal_mode`，非 `wal` → 返回 `False`；
  3. 执行 `PRAGMA wal_checkpoint({mode})` 并读回 `(busy, log_pages, checkpointed)`；`busy != 0` → 记 `info` 并返回 `False`；
  4. 任何异常（含 `database is locked`）→ 记 `warning`、返回 `False`，不上抛。
- `runner.execute_job` 在**成功路径**（`_finalize` → `_update_job_state` → `_record_event` → `_record_llm_run` 之后、`return` 之前）与**失败路径**（`except` 内 `_update_job_state` → `_record_event` → `_record_llm_run` 之后）各调用一次 `_checkpoint_wal(db)`，内部取 `db.get_bind()` 并吞掉所有异常。
- `preview_job`、CLI `sync list`、调度 tick 的其它任务不额外 checkpoint（每轮执行结束已覆盖）。

**(d) 归一失败明细有界**（`pipeline.py`、`runner.py`）

- `_NormalizeAggregate` 增字段 `failed_total: int = 0`，并增类常量 `MAX_KEPT_FAILURES = 100`；`_BatchSink._process` 改为调用 `aggregate.add_failures(normalized.failures)`：先累加 `failed_total`，再在剩余额度内保留明细（超出丢弃、不报错）。
- `_finalize`（`runner.py:856-874`）继续保持 `"normalize_failures": normalized.failures[:100]` 不变（此时长度已 ≤100），`detail` 键集合不变；另在日志里输出 `normalize_failed_total`（不留痕、不加字段），供排障观察量级。
- `preview_job` 的 `[:50]` 截断不动（Context #8）。

### 3. API 变更清单

无。`detail` 键集合与取值口径不变，`datasource_sync_run` 列不变，前端无需改动。

### 4. 边界与例外

1. `inplace=True` 只允许在「对象已由本链路拥有」处启用；任何从外部（Provider 缓存、测试注入的共享行）传入的行，必须先经 `to_records` 或 `apply_field_mapping` 获得所有权，否则退化为默认（复制）路径。
2. 分片项已实测后不做：`chunk_size=500` 与 `find_rows_by_key` 行为完全不变，不引入方言探测与参数上限回落逻辑。
3. `journal_mode` 非 `wal`（切换失败的降级连接）不 checkpoint；回滚日志模式保持原行为。
4. checkpoint 在存在并行同步任务或前台写事务时可能返回 `busy`：按 I4 只跳过，不重试、不等待超过既有 `busy_timeout`。
5. 无回调（全量）模式与 `llm_prompt` 任务同样受益于 (a)(c)(d)，但 (a) 的行所有权约定对 `llm_prompt` 的 `auto_landing` 路径同样成立（`ensure_job_table` 不持有行引用）。
6. 同步链路丢弃的明细（超出 100 条）不再参与任何统计；若将来需要完整明细，另立需求（写文件或独立表）。

### 5. 迁移

无。

### 6. 前端

无。

### 7. 测试清单

**判定层（单测）**：

- `tests/test_datasource_row_ownership.py`（新增，已落地）：`to_records` 后各行独立；
  `inplace=True` 返回同一对象且 `setdefault` 口径不变；`inplace=False` 仍复制且不改入参；
  管线两批行 `id()` 互不相同；`_StreamingState.on_batch` 转发行对象不复制。
- 新增 `tests/test_datasource_normalize_failures_bound.py`：构造 >100 条归一失败，断言聚合明细长度 100、`failed_total` 为全量、`detail["normalize_failures"]` 长度 ≤100 且键集合不变。
- 新增 `tests/test_core_database_wal_checkpoint.py`：SQLite/WAL → 返回 `True` 且 `-wal` 文件回落到 0；非 WAL → `False`；非 SQLite 方言 → `False`；`busy` 位非 0 → `False`；执行异常 → `False` 且无外泄；非法 mode → `False`。
- `tests/test_datasource_runner.py` 增补（`TestWalCheckpointOnRunEnd`）：成功 / 失败两条路径各调一次 checkpoint；checkpoint 抛错时 `run.status = success`、`inserted / fetched` 与落库行数不变。

**接口层**：`tests/test_datasource_api.py`、`tests/test_datasource_cli.py`、`tests/test_datasource_llm_provider.py` 全绿（响应模型与 `detail` 键不变）。

**迁移 / 备份**：`tests/test_datasource_backup.py`、`tests/test_datasource_migration.py` 全绿（无迁移）。

**e2e（前端）**：无前端改动，发布前回归现有 datasource e2e 套件。

**性能验收（人工）**：同机、同库、同任务（腾讯日线回补，3.83M 行量级）前后对比落库行/秒与单批耗时；逐项记录，收益 <3% 的项在 ADR「Consequences」标「实测后不做」并回滚该改动（C6）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 行所有权约定 + `inplace` 三分支 + `on_batch` 去拷贝 + 身份/等价用例 | 中（触碰公共 helper 签名；靠默认 `inplace=False` 保持外部语义） |
| **P1** | ~~`find_rows_by_key` 自动分片~~ → **实测后不做**（见 (b)），无代码改动 | — |
| **P2** | `checkpoint_wal` + 两条收尾路径接入 + 失败明细有界 + 帮助文档一行 + 用例 + 同机基准回填 | 低（全部 best-effort，异常吞掉） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 在「语义不变」边界内做三项纯开销削减（行拷贝、匹配分片、WAL 收尾）+ 一项鲁棒性修复（失败明细有界），不做架构级改造 | SQL 形态已在前序 ADR 压到批次 5% 以内，剩余成本全在应用层重复拷贝与无界累积；三项均不动校验与幂等 | ① 多进程校验并行（见 D6）；② 换存储引擎（ADR 0034 D7 已否决）；③ 重开复合唯一键 + `ON CONFLICT`（ADR 0006 D5 / 0035 D5 已否决） | 见 D2-D5 |
| D2 | 行拷贝收敛方式 | 以「归一输出即所有权边界」为准：`on_batch` 去整批复制，`fill_entrant` / `apply_row_defaults` / `apply_row_filter` 增 `inplace` 分支（默认仍复制） | Context #1 显示 5 次拷贝中 3 次发生在归一之后或本可原地 `setdefault`；#7 证明校验阶段不反写入参，去拷贝安全；同机实测 20 万行 377ms → 259ms（**-31%**，即 1.45 倍） | ① 把三个公共 helper 默认改为就地（改变外部语义，影响导入与预览调用方）；② 用不可变映射代理行（每行多一层对象，反而增加开销）；③ 直接在 Provider 里复用同一 dict 不拷贝（违反行独立性 I1） | `pipeline.py:299-305`、`:378-458`、`runner.py:710-712` |
| D3 | 匹配分片大小 | **实测后不做**：保持 `chunk_size=500`，不改代码 | 同机实测 10k 键（3 键任务）：500 = 41.6~42.4ms/20 次查询，2000 = 40.1~40.7ms/5 次查询 → 绝对只省 ~1.5ms，占 1 万行批端到端 0.3~2s 的 <0.5%，属噪声级；本地 SQLite 下参数绑定与结果集处理占主导 | ① 自动封顶 `min(2000, max_vars // 键列数)`（原本设计，实测收益不足以抵消新增方言探测分支）；② 固定 2000（旧 SQLite 构建上限 999 不安全）；③ 固定 1000（收益同样噪声级）；④ 改回巨型 `OR`（ADR 0037 D2 已否决） | 无（`records.py:946` 保持原样） |
| D4 | WAL 收尾时机与语义 | 每轮三态（success / partial / failed）收尾各执行一次 `wal_checkpoint(TRUNCATE)`；忙或异常只记日志、返回 False | 0039 交接遗留项；同机实测 20 万行写入后 WAL 3.0MB → checkpoint 后 **0.0MB**；TRUNCATE 让 WAL 文件回落，代价是一次独立连接 | ① 仅成功态执行（失败轮同样产生膨胀，下一轮继续受害）；② 放到 cron `deploy/sync.sh`（容器内触发不便、且预览/CLI 路径漏掉）；③ `VACUUM`（全表重写，成本与锁窗口远大于收益，0043 不做） | `core/database.py`（新增 `checkpoint_wal`）、`runner.py`（`_checkpoint_wal` + 两条收尾路径） |
| D5 | 失败明细上界与总计数去向 | 明细保留 100 条、另存 `failed_total` 总计数，只进日志，`detail` 键与条数口径不变 | 现 `detail` 只落前 100 条，无消费方读取更多；前端消费的是预览侧 `[:50]`；总计数足以支撑排障 | ① `detail` 新增 `normalize_failed_total` 键（改响应口径，收益仅是展示优化）；② 完全不截断（内存无界，正是本项要修的问题）；③ 截断到 50 与预览对齐（运行侧诊断信息反而变少） | `pipeline.py:107-114`、`runner.py:856-874` |
| D6 | 是否并行化校验 / 归一 | 不做（排除在本需求外） | 跨进程 pickle 行 dict 的开销可能吃掉一半收益；批内 `prefill_select_options_from_rows` 会改写 config，跨进程失效口径需重设计；等价性用例成本高 | 单独立项做 `ProcessPoolExecutor` 预校验（等 0040 真源复测确认仍不达标再评估） | — |
| D7 | 依赖 / API / 前端 / 迁移边界 | 全部为零：不新增依赖、不改端点与响应、不改前端、无迁移 | 三项优化均在应用内部；`detail` 与运行表形态不变 | 引入 `orjson` / `msgspec`（0040 D6 已否决）；新增字段落库 WAL 指标（无消费方，纯写放大） | — |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**（同机实测）：
  - 拷贝链：20 万行 × 4 列 377ms → 259ms（**-31%**），单行拷贝 5 次 → 2 次；
  - WAL 收尾：20 万行写入后 WAL 3.0MB → **0.0MB**（TRUNCATE 后回落）；
  - 失败明细：大面积归一失败场景内存从「随行数线性增长」变为 100 条常数上界；
  - 零迁移、零 API、零前端、零新增依赖，旧配置与旧数据库直接生效。
- **负向**：
  - 三个公共 helper 多一个 `inplace` 开关，签名变宽；靠默认 `False` 保证外部语义不变，但需要用例锁定两种模式。
- **实测后不做（C6）**：
  - 幂等匹配分片 500 → 2000：10k 键仅省 ~1.5ms（占批成本 <0.5%），保持原样，代码未改；
  - 校验 / 归一多进程并行（D6）：排除在本需求外。
- **风险与缓解**：
  - 就地改写若在某条路径上丢失所有权 → 跨批串行污染 → 用行身份用例（`id()` 断言 + 跨批不共享）锁死；
  - `checkpoint_wal` 与前台写 / 并行任务争锁 → 忙即跳过（I4），不重试不阻塞；
  - 收益低于预期（<3%）→ 按 C6 标记「实测后不做」并回滚该改动，不留半成品。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 校验语义 / 归一复用 | `Importer.analyze(light=…, preview=…)`、`bulk_update_rows(reuse_normalized=…)` | 不放宽逐格校验，二次归一已于 0040 消除 | ADR 0040 D5/D8（本 ADR 沿用） |
| 幂等口径 | 先查后写 + 非唯一复合索引 | 不引入唯一索引 / `ON CONFLICT`；分片只改批量查询粒度 | ADR 0006 D5、ADR 0034 D6、ADR 0037 D2（本 ADR D3 沿用） |
| 批大小 / 限速 | `DEFAULT_BATCH_SIZE=10000`、`rate_limit_ms` 全局限速 | 均不改 | ADR 0039 D4、ADR 0034 D5 |
| 轻量落表 | `upsert_rows(light=True)` | 保持 | ADR 0035 D2 |
| WAL 维护 | 连接级 pragma（WAL / busy_timeout / cache_size / sync=NORMAL） | 既有 pragma 不动，仅新增轮末 checkpoint 收尾 | 本 ADR D4（承接 ADR 0039 交接遗留项） |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/datasource/services/pipeline.py`（add_failures / 三 helper inplace / _run_group / _BatchSink._process）、`src/cndb/plugins/datasource/services/runner.py`（on_batch 去行复制） | `tests/test_datasource_row_ownership.py` | 2dde49a7 |
| P2 | 已落地 | `src/cndb/core/database.py`（checkpoint_wal）、`src/cndb/plugins/datasource/services/runner.py`（_checkpoint_wal + 成功 / 失败两条收尾路径、失败总量日志）、`frontend/src/pages/help/content/configuration.tsx`（WAL 收尾一行） | `tests/test_core_database_wal_checkpoint.py`、`tests/test_datasource_normalize_failures_bound.py`、`tests/test_datasource_runner.py` | 2dde49a7 |

> P1（幂等匹配分片）已由 D3 判定「实测后不做」，不在本表登记。

## 交接（会话结束更新）

- 当前阶段：已实现完成（P0 与 P2 落地、P1 实测后不做），待 `make flow` 全绿后提交
- 已完成：需求卡片 0043、ADR 方案与决策记录、P0 行拷贝收敛（-31%）、P2 WAL 收尾（3.0MB → 0.0MB）与失败明细有界、帮助文档一行
- 下一步：`make check-fast` → `make test` → `make cov` → 提交；真源 3.83M 行端到端复测（ADR 0040 遗留）单独安排
- 已知坑：① `inplace=True` 只可在已拥有行对象处启用，外部共享行必须先经 `to_records` / `apply_field_mapping`；② `wal_checkpoint(TRUNCATE)` 忙时返回结果行而非异常，必须读 `busy` 位；③ 本 ADR 不改 `preview_job` 的 `[:50]` 截断，别把两处截断混改；④ 分片项已否决，别再顺手把 `chunk_size` 调大；⑤ `detail` 只落前 100 条，失败总量只在日志里
- 最近一次全绿：`make check-fast` / `make test` @ 2026-10-26
