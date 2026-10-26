# 需求卡片：数据源同步落库剩余开销削减（拷贝链 / 匹配分片 / WAL 收尾 / 失败明细有界）

- 编号：0043（与 ADR `docs/adr/0043-*.md` 同号）
- 来源 / 提出人：产品负责人（对话确认「可以」，承接上一轮性能分析建议 2）
- 日期：2026-10-26
- 关联 ADR：`docs/adr/0043-datasource-write-path-overhead.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 可以

承接上下文（**非需求原文**，仅为复现指代）：上一轮「海量数据同步剩余性能瓶颈分析」的结论第 2 条 ——

> 小步确定收益：W1 拷贝链削减 + W3 chunk 调大 + O1 checkpoint 收尾，三者都语义不变、改动面小，可合并成一张需求卡。

同轮分析另列「五、一个顺带发现的鲁棒性问题」：`_NormalizeAggregate.failures` 跨全轮无上限累积，仅 `_finalize` 取前 100 条落库；海量失败源下内存无界增长，建议加计数 + 截断。本条随卡纳入。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 可以（W1 拷贝链削减） | 归一路径上对同一行数据的重复浅拷贝收敛为必要次数：`to_records` / `fill_entrant` / `apply_row_defaults` / `apply_row_filter` 在无实际改写时不复制整行，`runner.on_batch` 不再对已归一的行整批再拷一份；**每行对象仍互相独立**（不得让多个批次共享同一 dict），`setdefault` 语义（响应自带值优先）与过滤剔除口径不变 | `src/cndb/plugins/datasource/services/pipeline.py:378-458`、`src/cndb/plugins/datasource/services/runner.py:710-712` | 既有 `tests/test_datasource_runner*.py` / `test_datasource_pipeline_concurrency.py` 全绿；新增行对象身份用例（行间不共享 dict）+ 默认 vs 现路径写入结果等价用例 |
| C2 | 可以（W3 chunk 调大） | 幂等匹配查询的默认分片从 500 提到 **2000**（或经量测后取不触发绑定变量上限的值，见未决问题 Q3）；查询语义（含空键退回 `OR + IS NULL` 分支、冲突取 `min(id)`）不变，单批查询次数随之下降 | `src/cndb/plugins/tables/services/core/records.py:940-1035`（`find_rows_by_key`）、调用方 `services/importing/importer.py` | 既有 `tests/test_import_pipeline.py` 全绿；新增「同批数据在不同 chunk_size 下 `exact_map` / `conflict_map` 完全一致」用例 |
| C3 | 可以（O1 checkpoint 收尾） | 数据源同步每轮结束（成功 / 部分失败 / failed 三态）后，若方言为 SQLite 则在独立连接上执行 `PRAGMA wal_checkpoint(TRUNCATE)`；非 SQLite 方言与 `journal_mode != wal` 时跳过；checkpoint 失败或忙超时**只记日志，不得改写运行记录状态、不得使已落库批次回滚** | `src/cndb/plugins/datasource/services/runner.py:828`（`_finalize` 之后）、`src/cndb/core/database.py` | 新增用例：SQLite 下 checkpoint 执行且 WAL 回落、非 SQLite / 非 WAL 被跳过、checkpoint 抛错时 `run.status` 与 `write` 计数不变 |
| C4 | 可以（失败明细有界） | 归一失败明细的跨批聚合有界：保留失败**总计数**（供 `detail` 统计口径使用），明细只保留前 N 条（N 由 ADR 定，建议 100，与 `_finalize` 落库截断对齐）；超出部分丢弃不报错，`detail.normalize_failures` 的内容与条数口径不变（仍为前 100 条） | `src/cndb/plugins/datasource/services/pipeline.py:107-114`、`runner.py:856-874` | 新增用例：构造 >N 条失败，断言内存中明细长度为 N、计数为全量、`detail` 只含前 100 条 |
| C5 | 可以（边界） | 本卡**不放宽**任何既有口径：逐格校验与字段类型转换（ADR 0040 D5/D8）、先查后写与非唯一索引的幂等口径（ADR 0006、ADR 0034 D6）、全局请求限速（ADR 0034 D5）、批大小 10,000（ADR 0039 D4）、人工导入默认路径行为（ADR 0035 D2）全部不变；不引入多进程并行、不换存储引擎、不新增运行期依赖、不改 API / 前端 | 全仓 | `make flow` 全绿；ADR「口径」表逐条给出落点 |
| C6 | 可以（可验收） | 每条优化必须给出**同机前后对比**的性能口径（落库行/秒或单批耗时），绝对吞吐不作为 CI 门槛；若某项实测收益不显著（<3%），ADR 需记录「实测后不做」而不是默默保留 | ADR「Consequences」 | 基准脚本输出 + ADR 回填 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 归一路径重复浅拷贝 | `pipeline.py:378`（`to_records`）、`:393/:396`（`fill_entrant`）、`:415/:422`（`apply_row_defaults`）、`:439/:444/:455`（`apply_row_filter`）、`runner.py:712`（`on_batch` 再整批拷） | 5.8M 行量级下约 2,500 万次 dict 分配；`to_records`+`fill_entrant` 在无 `entrant_param` 时各自空拷一次 |
| 2 | 幂等匹配分片 | `records.py:946`（`chunk_size: int = 500`） | 1 万行批 = 20 次查询；调大可降到 5 次，但受 SQLite 绑定变量上限约束 |
| 3 | WAL 无收尾 | `runner.py`（全轮无 checkpoint 调用）、`docs/adr/0039-datasource-daily-sync-reliability.md:193` | 3.83M 行写入期间 WAL 膨胀，影响前台读、备份体积与后续批次；0039 交接已列为遗留项 |
| 4 | 归一失败明细无界 | `pipeline.py:111`（`_NormalizeAggregate.failures`）、`runner.py:860-867` | 跨全轮累积、无上限；落库只取前 100 条 |
| 5 | SQLite 连接级 pragma | `src/cndb/core/database.py:36-73` | 已有 WAL / busy_timeout=5000 / cache_size=-20000 / synchronous=NORMAL；checkpoint 需在此既有 pragma 口径下兼容 |
| 6 | 批量写不记 audit | `records.py:1133`（`_invalidate_search_cache`） | 与 C1 无冲突，仅确认拷贝收敛不改变搜索缓存失效时机 |

## 未决问题

- [x] **Q1（前置）**：ADR 0040 的端到端 155~170s 估算尚未经真源复测、10ms 限速是否触发对端风控也未观察。是否必须先完成该人工验收，再决定本卡是否执行？结论：**先验收**；本卡只做「语义不变」项，不因 0040 未达标而扩大范围。
- [x] **Q2（W2 排除）**：分析中的 W2（校验 / 归一搬进 `ProcessPoolExecutor`）是否确认排除在本卡之外？结论：**排除**（跨进程序列化可能吃掉一半收益，且批内 select 选项 prefill 的反馈语义要重设计）。
- [x] **Q3（绑定变量上限）**：`IN` 分片调大受 SQLite `SQLITE_MAX_VARIABLE_NUMBER` 约束（旧构建默认 999，3.32+ 为 32766）。结论：**按 `max_vars // 键列数` 动态封顶**，默认目标 2000，运行时探测上限后取 `min(2000, 上限 // 键列数)`，不足则回落现状 500。
- [x] **Q4（checkpoint 时机）**：`wal_checkpoint(TRUNCATE)` 需要独占写锁，可能与前台写请求或另一并行同步任务争用（`busy_timeout=5000`）。结论：**每轮都尝试（成功 / 部分失败 / failed 三态）+ 失败只记日志**，接受偶发忙超时跳过。
- [x] **Q5（N 的取值）**：C4 的明细保留条数 N 取 100（与落库截断一致）还是要让 `detail` 展示完整 N 条？结论：**取 100**（`detail` 只落 100 条，多留无常量消费方），另保留失败总计数。
- [x] **Q6（文档）**：C3 引入的 WAL 维护动作是否需要写入帮助文档「系统配置 / 数据源同步」小节（ADR 0036 已有 WAL / VACUUM 段落）。结论：**补一行**说明每轮同步收尾会做 WAL checkpoint。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-26 对话确认「按这个方案来」）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
