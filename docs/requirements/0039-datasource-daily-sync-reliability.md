# 需求卡片：股市日线同步失败修复（data\_path 候选回退 + 基金/ETF 拆任务）与落库吞吐提升

* 编号：0039（与 ADR `docs/adr/0039-datasource-daily-sync-reliability.md` 同号）

* 来源 / 提出人：产品负责人（对话提出）

* 日期：2026-10-26

* 关联 ADR：`docs/adr/0039-datasource-daily-sync-reliability.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 数据源同步，股市日线，存在大量错误：ces.pipeline 数据源请求失败 \[symbol=sh562550]: 行数组记录要求 data\_path 指向一个数组
> 2026-10-26 17:36:24,513 WARNING cndb.plugins.datasource.services.pipeline ，是否需针对性地优化。请分析数据源同步还有无提速的措施。

## 可实施约束（C1..Cn）

| #  | 需求句（原文片段）                      | 可实施约束                                                                                                                                | 涉及模块                                                                                                                                                | 验收方式                                                                                   |
| -- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| C1 | 大量错误：行数组记录要求 data\_path 指向一个数组 | `rows_array` 的 `data_path` 支持候选路径回退（`a.b\|a.c`）：按声明顺序取第一个命中数组的候选；全部候选都未命中数组才报错，错误信息列出全部候选；单路径配置行为与现状完全一致（向后兼容）                       | `src/cndb/plugins/datasource/providers/http_json.py`                                                                                                | 单测：缺 `qfqday` 回退 `day`、首候选空数组继续下一候选、全缺失报错、单路径不变                                        |
| C2 | 股市日线，存在大量错误                    | 基金/ETF 与股票拆分任务：股票任务（`sh60`/`sz00`/`sz30`/`sh68`/`sh69`）走前复权并允许回退；基金/ETF 任务（`sh5`/`sz1`）只读 `day`，来源标「腾讯不复权」、复权方式标「不复权」；同一行标注必须与实际序列一致 | `examples/datasets/工作区-数据源示例/datasource.json`、`src/cndb/cli/seed/datasource.py`                                                                     | `tests/test_seed_datasource.py` 断言任务名 / 前缀 / `data_path` / `row_defaults`；真源抽样复验失败率为 0 |
| C3 | 数据源同步还有无提速的措施                  | 落库写吞吐提升 ≥30%：流式批大小 5000 → 10000；`match_keys` 索引 DDL 每轮只执行一次；每批数据库提交次数不增加（进度 / 水位 / 续租合并为一次提交）                                        | `src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/runner.py` | 落表基准（3.83M 行同口径）≥13k 行/s；单测断言提交次数与索引 DDL 次数                                            |
| C4 | 提速措施                           | 同口径单轮（约 3.83M 行）落库耗时从实测 370s 降到 ≤270s；本次不改网络层（连接复用 / 页级并发 / DNS 缓存）                                                                  | `services/`、ADR 0039 Consequences                                                                                                                   | 基准脚本复测 + ADR「落地状态」回填实测                                                                 |
| C5 | 针对性优化                          | 不变量不变：幂等键与「先查后写」口径、字段校验、`partial` 列语义、回补水位推进、`workers` / `rate_limit_ms` 语义、双源并存；零迁移、零新增依赖、零 API 契约与前端交互变更                           | `services/write.py`、`services/runner.py`、`services/pipeline.py`                                                                                     | 既有测试全绿 + 新增等价性用例                                                                       |
| C6 | 大量错误 / 优化                      | 存量实例必须有生效路径（重跑 `cndb seed` 或前端编辑），旧 ETF 合并任务需人工清理；写入 ADR「交接」                                                                         | `src/cndb/cli/seed/datasource.py`、ADR 0039 交接                                                                                                       | 交接章节 + 人工复跑                                                                            |
| C7 | 存在大量错误                         | 回归覆盖：候选回退、拆分配置、批大小等价性、索引缓存、提交合并后的断点续跑（水位不倒退、不丢批）                                                                                     | `tests/`                                                                                                                                            | `make check` / `make cov` / e2e 既有套件                                                   |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力            | 候选位置                                                     | 备注                                         |
| - | ------------------ | -------------------------------------------------------- | ------------------------------------------ |
| 1 | `rows_array` 单路径解析 | `src/cndb/plugins/datasource/providers/http_json.py:232` | `data_path` 仅一个路径，未命中即 `ProviderError`     |
| 2 | 腾讯回补任务固定 `qfqday`  | `examples/datasets/工作区-数据源示例/datasource.json:66`、`:103`  | 基金/ETF 无 `qfqday` 序列                       |
| 3 | 回补任务前缀混合股票与基金      | `examples/datasets/工作区-数据源示例/datasource.json:79`         | `sh5` / `sz1` 含约 1,713 只基金/ETF             |
| 4 | 流式批大小              | `src/cndb/plugins/datasource/services/pipeline.py:39`    | `DEFAULT_BATCH_SIZE = 5000`                |
| 5 | 每批重建幂等索引           | `src/cndb/plugins/datasource/services/write.py:135`      | `CREATE INDEX IF NOT EXISTS` + commit 每批执行 |
| 6 | 每批多次提交             | `src/cndb/plugins/datasource/services/runner.py:710`     | 落库 / 水位 / 进度各一次提交                          |
| 7 | 运行失败明细             | `src/cndb/plugins/datasource/services/runner.py:978`     | 失败条目按请求记录，修复后应归零（除真异常）                     |

## 未决问题

* [x] 基金/ETF（约 1,713 只）是否继续纳入同步？结论：继续纳入，拆成独立任务、只读 `day` 并标「不复权」（需求方 2026-10-26 确认）。

* [x] 是否引入候选级 `row_defaults`（按命中的候选改标注）？结论：不引入，任务拆分即可让标注恒定，避免把「命中哪条路径」透传进管线。

* [x] 本次是否包含网络层提速（连接复用 / 页级并发 / DNS 缓存）？结论：不包含，本次范围收敛为 P0（正确性）+ P2（写吞吐）；写库为当前瓶颈。

* [x] 批大小 10000 是否影响断点粒度？结论：接受，进度/水位最多滞后一批（1 万行），语义不变。

## 卡点

* [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）

* [x] 未决问题全部有结论，需求方确认（2026-10-26）

