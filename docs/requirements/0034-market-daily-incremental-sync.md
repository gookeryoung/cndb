# 需求卡片：全市场股票日线增量同步到本地（参照 stock-strategy）

- 编号：0034（与 ADR `docs/adr/0034-*.md` 同号，卡片存 `docs/requirements/0034-market-daily-incremental-sync.md`）
- 来源 / 提出人：用户（会话提出）
- 日期：2026-10-25
- 关联 ADR：`docs/adr/0034-market-daily-snapshot-sync.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请继续参考~/stock-strategy项目，实现7,044只股的数据拉取到本地，并且需要实现增量拉取，并非每次全量拉取。总数据量估计会达到372MB，如果涉及到数据库膨胀问题，请给出更好的方式。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | "继续参考~/stock-strategy项目" | 参照 `/root/stock-strategy`（「日线策略测试台」，已恢复）的同步架构：新浪全市场快照（`Market_Center.getHQNodeData`，`hs_a` + `etf_hq_fund` 两节点）承担标的清单与当日行情；腾讯日线（`fqkline`，end 锚点 + 单次 800 根）承担历史回补；快照与回补均幂等 upsert | datasource plugin（http_json provider / pipeline / runner） | 假源桩集成测试 + 真源 smoke |
| C2 | "实现7,044只股的数据拉取到本地" | 标的覆盖 = 在市全量（沪深 A 股 `hs_a` + 场内 ETF `etf_hq_fund`，合计约 7044 只，以接口实际返回为准，不含已退市）；历史回补至 `2016-01-01`（约 10 年）；数据落到「数据源示例」工作区本地表 | datasource plugin + cli/seed + examples/datasets | 全量演练（4 个 job 跑通，行数/库体积记录进 ADR） |
| C3 | "需要实现增量拉取，并非每次全量拉取" | 日常增量走快照路径（拉全市场快照直接写当日 K 线，秒级、无逐股请求）；历史回补用按标的回补水位（end 锚点逐轮前推，已达回补起点的标的自动跳过，断点续跑不重复拉取） | datasource plugin（cursor / pipeline / runner） | 单测 + smoke：二次运行新增请求仅覆盖缺口、已回补标的零请求 |
| C4 | "如果涉及到数据库膨胀问题，请给出更好的方式" | 给出明确存储结论与膨胀应对：约 372MB（含索引约 500MB）直存 SQLite 宽表可承受，配套幂等键复合索引、WAL checkpoint、低峰 VACUUM 与备份体积说明写入帮助文档；不因数据量更换存储引擎 | docs（帮助文档）+ tables plugin（索引） | 帮助文档断言 + 大库备份测试 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 管线全量攒内存后一次性落库 | `src/cndb/plugins/datasource/services/pipeline.py` | 千万行级回补内存不可承受，需流式分批落表 |
| 2 | 游标仅 job 级单值（date/datetime/key_set/none） | `src/cndb/plugins/datasource/services/cursor.py` | 无按标的回补水位，无法表达「每只股票补到哪天」 |
| 3 | `entrant_keys` 为静态 JSON 列表 | `src/cndb/plugins/datasource/models.py:73` | 7044 只标的不宜硬编码，需从「股票清单」表动态读取 |
| 4 | 请求串行执行，无并发 | `src/cndb/plugins/datasource/services/pipeline.py` | 对标 stock-strategy 10 线程（快照 3 秒 / 回补 40 只/秒），全量回补 2.1 万请求串行过慢 |
| 5 | 动态表无幂等键复合索引 | `src/cndb/plugins/tables/services/core/ddl.py`、`records.py` | 大表「先查后写」的批量 OR 查询退化为全表扫描 |
| 6 | 租约 TTL 300s 无续期机制 | `src/cndb/plugins/datasource/services/scheduler.py` | 长回补任务会被误判死锁遭抢占 |
| 7 | `row_defaults` 仅静态常量 | `src/cndb/plugins/datasource/services/pipeline.py`（`apply_row_defaults`） | 快照写当日 K 线需要 `日期 = {today}` 模板渲染 |
| 8 | 无行级过滤能力 | `src/cndb/plugins/datasource/services/pipeline.py` | 停牌标的快照为零值行，需按条件剔除 |
| 9 | 现有 2 只股示例 job（新浪 + 腾讯） | `examples/datasets/工作区-数据源示例/datasource.json` | 被本需求的全量 job 替换（ADR 0033 的引擎能力保留，示例任务演进） |
| 10 | seed 结构测试锁任务数 | `tests/test_seed_datasource.py` | 任务重组后须同步改断言 |
| 11 | 手动「立即运行」为 HTTP 同步执行 | `src/cndb/plugins/datasource/routers/sync_jobs.py` | 长回补任务不能走 HTTP 等待，须 CLI / 调度执行 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题（已确认，2026-10-25 需求方拍板）

- [x] 1. 历史回补深度：**约 10 年**（`backfill_start = 2016-01-01`，对应约 372MB / 1700 万行估算）。
- [x] 2. 数据源口径：**与 `/root/stock-strategy` 一致**（恢复后的项目实测：新浪全市场快照 + 腾讯日线回补，全量 3~4 分钟 / 增量 4~8 秒）。
- [x] 3. 标的范围：**在市全量**（`hs_a` + `etf_hq_fund`，约 7044 只，不含已退市；清单每日随快照自动刷新，新上市自动纳入）。
- [x] 4. 旧示例任务处置：随本需求**替换为全量任务**（方案 v2 评审通过，含 D8 任务重组）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-25 会话逐项拍板 + 方案 v2 评审通过）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
