# ADR 0053: 数据源同步对齐 lmstock 机制（单轮翻页回补 / 主机回退）与示例单序列收敛

Status: Proposed（待评审）
Date: 2026-10-27
Related: `src/cndb/plugins/datasource/services/cursor.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/providers/http_json.py`、`src/cndb/plugins/datasource/providers/base.py`、`src/cndb/core/http.py`、`examples/datasets/工作区-数据源示例/`、`src/cndb/cli/seed/datasource.py`、`tests/test_seed_datasource.py`、`docs/requirements/0053-datasource-sync-lmstock-alignment.md`、ADR 0033 / 0034 / 0039 / 0035
需求卡片: `docs/requirements/0053-datasource-sync-lmstock-alignment.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C12），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | `backfill_date` 新增单轮翻页到顶能力 | `cursor` 新声明键 `page_to_start: true` + `page_size`（默认 800）；`execute_job` 对 backfill 任务改为「多 pass 循环」：每个 pass 重建 spec（水位已更新）→ 跑一次管线 → 依据终止条件剔除标的，直到无活跃标的或触发上限（D2） |
| C2 | `http_json` 多主机 failover | `request_spec.url_hosts: [基础 URL, ...]` + `url_template` 内 `{host}` 占位；`FetchConfig` 新增 `fallback_urls`；`core/http.py` 逐候选尝试（仅网络错误 / 连接被掐 / 429·500·501·502·503·504 切换）（D4） |
| C3 | 保留「股票清单（全市场快照）」 | 任务不动（`datasource.json` 第 4-29 行） |
| C4 | 保留「股市日线（新浪快照 · 当日）」 | 任务保留；`row_defaults` 去掉「来源 / 复权方式」，`match_keys` 改 `[股票代码, 日期]`（D6） |
| C5 | 三条板块回补合并为一条全市场回补 | 三条任务（第 58-168 行）合并为「股市日线（腾讯回补 · 全市场）」，`entrant_source` 去掉 `prefix_in`（D5） |
| C6 | 回补任务配「单轮翻页到顶」 | 合并后的回补任务 `cursor` 增 `page_to_start: true`、`page_size: 800`（D2/D3） |
| C7 | 回补主机直连 + proxy 降为 failover | `url_template` 改 `{host}/ifzqgtimg/...`；`url_hosts: ["https://web.ifzq.gtimg.cn", "https://proxy.finance.qq.com"]`；`headers_template` 带浏览器 UA / Referer（D11） |
| C8 | 数据表保留两张、非股市示例保留 | 表清单与 llm_prompt 任务不动；「股市日线」表字段随 C10 收缩（D6） |
| C9 | 回补改不复权 | `url_template` 去掉 `,qfq`（`param={entrant},day,,{end},800`），`data_path` 改 `data.{entrant}.day`（D7） |
| C10 | 单行单口径：去来源键、删两列、删来源视图 | `match_keys=[股票代码, 日期]`；`股市日线.csv` 删除「来源 / 复权方式」列并把同日两行合并为一行；`views.json` 删除两条来源筛选视图；`row_defaults` 不再产出这两列（D6） |
| C11 | 水位目标改为「补到上市首日或不足一页即停」 | 终止条件四选一：空响应 / 抓取行数 < `page_size` / 该标的本轮水位未前移 / 达 `backfill_start`（D3） |
| C12 | 直连主机优先、proxy failover，复验后可只调顺序 | 见 C7；P2 真源复验若直连仍被挑战，只调换示例 `url_hosts` 顺序（引擎不改）（D11） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `backfill_date` 每个标注一次运行只发 1 个请求（`end` = 水位 − 1 天），水位由响应最早日期单步前推；补满靠多轮 run | `services/runner.py:638-665`、`services/cursor.py:141-155`、`services/runner.py:755-785` | 2,400 根历史需 ~3 轮 × 每轮全市场请求，慢且需人工重复点运行 | 确认（C1/C6/C11 需单轮翻页） |
| 2 | 抓取只接受单 URL；`FetchConfig.headers` 已支持自定义请求头 | `core/http.py:208-239`、`core/http.py:581-582`、`providers/http_json.py:167-184` | 无法声明「直连优先、代理兜底」；请求头能力现成，零改动 | 确认（C2/C7 需主机列表；请求头只改配置） |
| 3 | 示例 7 条任务：2 llm_prompt + 5 http_json（含 3 条按板块拆分的腾讯回补） | `examples/datasets/工作区-数据源示例/datasource.json:3-307` | 回补重复三份、板块前缀仅为量纲/解析兜底而拆 | 确认（C5/C6 合并与精简） |
| 4 | seed 按 `(workspace_id, name)` 幂等，只增不删 | `src/cndb/cli/seed/datasource.py:86-93` | 合并/删除任务对存量库不生效 | 确认（C 结论：手动清理，D10） |
| 5 | seed 结构测试锁定任务清单与回补任务断言 | `tests/test_seed_datasource.py`（实时任务数断言段） | 任务合并后须同步改断言 | 确认（测试面） |
| 6 | 双源同表：幂等键含「来源」、表内有「来源 / 复权方式」两列、视图按来源筛选 | `datasource.json:38-43`、`:75-80`、`:112-117`、`:149-154`；`股市日线.csv:1`；`views.json:13-38` | 同日同标的并存两行，与 lmstock 单序列口径不同 | 确认（C9/C10 需单序列） |
| 7 | ADR 0033 记录「`web.ifzq` 对脚本流量有 WAF 挑战，须走 proxy 域名」 | `docs/adr/0033-stock-daily-dual-source-sync.md:35` | 与 C7 冲突；lmstock 实测「浏览器 UA + Referer `gu.qq.com`」可直连（`~/lmstock/src/lmstock/core/net.py:11-15,67-70`） | 修正（C7/C12；0033 该行随本 ADR 修订） |
| 8 | 帮助示例清单与 CHANGELOG 记录股市示例内容 | `src/cndb/plugins/help/services/examples.py`、`CHANGELOG.md` | 示例任务/字段变化须同步 | 确认（P2 文档面） |
| 9 | 回补取前复权（URL `,qfq`、`data_path` 候选含 `qfqday`），快照为不复权 | `datasource.json:63-75`、`:137-149` | 两口径混存是「来源」列存在的理由之一 | 确认（C9/C10 改不复权） |
| 10 | 新增：成交量单位按板块不同（主板/创业板/ETF 手→×100；科创板原值即股），靠拆任务表达 | `datasource.json:88`、`:125`、`:162`；ADR 0034 §4.5 | 合并成单任务后无法用单一 `scale` 同时正确；`field_mapping` 无按前缀缩放能力 | 新增（D8） |
| 11 | 新增：分页空页停止只对 `paging` 生效；`backfill_date` 无「页」概念，引擎不统计每标的抓取行数 | `services/pipeline.py:313-315`、`:219-222` | 短页终止需引擎提供「按标的抓取行数」 | 新增（D3） |
| 12 | 新增：`RequestProgress.set_total` 每轮覆盖总数 | `services/pipeline.py:221-222`、`:148-151` | 单轮翻页多 pass 时进度会回退到最后一 pass 的数量 | 新增（D3 附带） |

**核心缺陷（需求要补的）**：同步引擎的 `backfill_date` 只能表达「一轮一页」，无法表达「一轮内把某标的历史翻到起点」；抓取层也无法表达「同一资源有多个等价主机」。示例则把「板块拆分 + 双源并存」当作表达能力的手段，导致任务重复、字段冗余，与 lmstock「快照兜当日 + 单轮翻页 + 单序列」的形态不一致。

设计目标（不变量）：

- **I1 领域无关**：新增声明键与引擎逻辑不出现 symbol / stock / 板块等领域词；股票语义只在示例 JSON。
- **I2 幂等可重跑**：单轮翻页中任一 pass 中断，已落批保留、水位停在最后成功页，重跑自然续页；任意次运行结果一致。
- **I3 失败留痕不拖垮**：单请求失败记 `failures`，该标的本轮不再重试，其他标的继续；整轮状态沿用 `success/partial/failed`。
- **I4 存量兼容**：未声明 `page_to_start` / `url_hosts` 的任务行为与现网完全一致（默认关闭）。
- **I5 终止条件单一入口**：翻页终止只在 runner 的 pass 循环判定一次，provider 与 pipeline 不各自猜测。
- **I6 零迁移**：无表 / 列 / 索引变更；示例数据文件变化不需要 alembic，存量库由人工清理（D10）。

## Decision

### 1. 数据模型

无新表、无新列、无 alembic 迁移。新增的只是 JSON 声明键与一个 dataclass 字段：

| 声明位置 | 新键 | 语义 |
|---|---|---|
| `cursor` | `page_to_start: bool`（默认 false） | 一轮内按标的水位反复翻页，直到终止条件（D2/D3）；仅对 `backfill_date` 生效 |
| `cursor` | `page_size: int`（默认 0 = 不判定短页） | 单页预期根数（示例 800）；抓取行数 < 该值视为「该标的已到头」 |
| `request_spec` | `url_hosts: [str]`（默认空） | 候选主机基础 URL 列表；空 = 单 URL 旧行为 |
| `url_template` 变量 | `{host}` | 逐个候选主机渲染后的完整 URL（D4） |
| `FetchConfig` | `fallback_urls: tuple[str, ...]`（默认空） | 主 URL 之外依次尝试的完整 URL |
| `PipelineOutcome` | `entrant_rows: dict[str, int]` | 每标的**抓取行数**（归一 / 过滤前），供短页判定（D3） |

示例侧数据变化（无 schema 变更）：「股市日线」表删除「来源」「复权方式」两列（`股市日线.csv` 表头与行数据同步改为单序列），`match_keys` 收缩为 `[股票代码, 日期]`。

### 2. 判定算法（唯一入口）

**(a) 单轮翻页**（`services/runner.py` 的 `execute_job`）：

1. 仅当 `cursor.is_backfill and cursor.page_to_start` 进入多 pass 循环；否则保持现在的单 pass 路径（I4）。
2. 每个 pass：`_inject_backfill_ends(db, job, spec, ...)` 现算锚点（水位已更新）→ `run_pipeline(...)` → `_StreamingState` 累积计数与水位（**跨 pass 复用同一实例**，保证计数与运行记录单调）。
3. pass 结束后对「本 pass 活跃标的」逐个判定终止：该标的**无行**、**抓取行数 < `page_size`**、**水位未前移**（含请求失败）三者任一 → 加入本轮 `finished` 集合并从下一 pass 的 `entrant_values` 移除。
4. 循环退出：无活跃标的，或 pass 数达上限 `MAX_BACKFILL_PASSES = 200`（防御无界循环；超出记 `partial` 明细「已达单轮翻页上限」）。
5. 预览（`preview_job`）只跑 1 个 pass、不推进水位，与现状预览口径一致。

**(b) 主机回退**（`core/http.py`）：

1. `HttpJsonProvider._build_config` 对 `url_hosts` 逐个以 `{host}` 渲染 `url_template`，首个为主 `url`，其余进 `fallback_urls`；`url_hosts` 为空时 `{host}` 不被使用，行为不变。
2. `_fetch_json_with_client` 抽出「按单 URL 抓取」的内部函数；外层按 `(url, *fallback_urls)` 依次尝试，**仅当**出现 (i) `httpx.RequestError`（含连接被重置 / 超时）或 (ii) HTTP 状态 ∈ {429, 500, 501, 502, 503, 504} 时切下一主机；JSON 解析失败 / 业务错误码不切（不是主机问题）。
3. 每个候选 URL 都过 `validate_url`（SSRF 口径逐主机生效，I1/安全）；全部失败抛最后一个错误，管线按单请求失败留痕（I3）。

**(c) 进度**：`RequestProgress` 新增 `add_total(n)`（累加）；`run_pipeline` 改用它，使多 pass 的 `progress_total` 为整轮累计（单 pass 时结果与现在相同）。运行记录展示仍为 `done/total`。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| 无 | `request_spec` / `cursor` 本为自由 JSON，新声明键随 payload 透传；创建/更新校验仅加「`page_to_start` 必须搭配 `backfill_date` 且模板含 `{end}`」一条 |

### 4. 边界与例外

1. **短页判定用抓取行数**（`entrant_rows`，归一/`row_filter` 之前）：避免 `row_filter` 剔除导致误判「已到头」。
2. **失败标的本轮不再重试**：请求失败不推进水位、`entrant_rows` 为 0 → 按终止条件剔除；下轮 run 由水位自然重试（不放大限流压力）。
3. **上限保护**：单轮最多 200 pass；触顶记 `partial`，不静默成功。
4. **成交量单位**：合并任务不声明 `scale`，成交量取数据源原值（腾讯主板/创业板/ETF 为「手」、科创板为「股」）。与 lmstock 一致，属已知口径局限；「表列统一为股」的旧口径在本示例撤销（D8）。
5. **同日覆盖**：快照与回补都写「股票代码 + 日期」同一行，后写者覆盖。两者均为不复权原价，收盘一致；成交量单位可能不同（快照=股、腾讯=手），只影响同日一行的量纲标注（D7/D8）。
6. **不复权的历史跳空**：回补改不复权后，除权日前后价格不再连续（前复权的平滑消失）。这是「与快照同口径、单序列」的必然结果（D7）。
7. **`backfill_start` 语义**：仍是下界（示例 2016-01-01），达到即视为该标的完成；不再要求「多轮补满」。
8. **主机回退只覆盖请求层**：不处理「主机可用但数据明显错误」的情况（不做跨源结果比对）。

### 5. 迁移

无 alembic 迁移、无 downgrade。存量实例按 D10 手动处理：删除 3 条板块回补任务与「来源 / 复权方式」两列后重跑 `cndb seed`。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 无 | 无 | 新声明键属配置文件级能力；数据源页只读展示未知键不报错（ADR 0034 §7 既有口径）；运行进度沿用 `progress_done/total` |

### 7. 测试清单

**判定层（单测）**：
- `CursorConfig`：`page_to_start` / `page_size` 解析、默认值、非法组合（非 backfill /
  模板无 `{end}`）报错
- runner 多 pass（假 fetch）：两页数据 → 水位两轮前推、`entrant_rows` 递减、达 `backfill_start` 退出
- 终止条件：空响应、短页（< page_size）、水位未前移（请求失败）、200 pass 上限各一条
- 中断续跑：第 2 个 pass 抛异常 → 已落批保留、水位停在最后成功页、重跑只补缺口
- `progress.add_total`：多 pass 累计；单 pass 与 `set_total` 等价
- `url_hosts` 渲染：`{host}` 逐候选求值、`url_hosts` 为空时行为不变
- 主机回退：主主机网络错误 → 备主机成功；主主机 501 → 备主机；JSON 解析失败**不**切换；全部失败只记 1 条 failure；SSRF 校验对每个候选生效

**接口层**：
- `tests/test_seed_datasource.py` 改锁 5 条任务（2 llm_prompt + 3 http_json）；断言回补任务无 `prefix_in`、无 `fq=qfq`、`page_to_start/page_size` 存在、`url_hosts` 顺序、`match_keys=[股票代码, 日期]`
- 断言「股市日线.csv」表头无「来源 / 复权方式」，且 `(股票代码, 日期)` 唯一
- `execute_job` 假源集成：快照 + 回补同日命中同一行（1 行，后写者覆盖）

**迁移 / 备份**：无迁移；`test_backup_seed_roundtrip.py` 既有链路覆盖字段收缩后的往返

**e2e（前端）**：无新增（不新增页面 / 视图形态）

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 引擎：`cursor.page_to_start/page_size` + `entrant_rows` + runner 多 pass 循环 + 进度累计 + 判定层单测 | 中（触及运行主循环与断点语义，须保 I2/I4） |
| **P1** | 引擎：`url_hosts` / `{host}` / `FetchConfig.fallback_urls` + 主机回退 + 单测 | 中（`core/http.py` 抓取主干重构，须保重定向 / SSRF / 重试语义） |
| **P2** | 示例与文档：合并任务 / CSV 单序列 / 字段与视图收缩 / seed 测试 / 帮助示例 / CONTEXT / CHANGELOG + 真源复验（直连可用性、单轮翻页耗时记录） | 中（第三方接口行为与限流不可控；真源须联网） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 保留 0034 已落地的「快照直写当日 + 缺口驱动（水位）」不变；新增「单轮翻页」与「主机回退」两项通用声明能力；示例收敛为单序列三任务 | 三者叠加才对齐 lmstock 的日常同步形态；引擎能力领域无关，示例语义留在配置 | ① 只改示例不改引擎（单轮翻页与 failover 无法表达）；② 移植 lmstock 整套存储/复权因子（超出同步职责） | 见 P0/P1/P2 |
| D2 | 「一轮补到顶」的表达 | 新游标键 `page_to_start` + runner 多 pass 循环（每 pass 重建 spec、复用 `_StreamingState`） | 水位是 DB 状态，pass 间重建 spec 即天然续页；provider 不掌握行数与水位 | ① provider 内循环翻页（拿不到水位与断点，且 provider 会进状态）；② `time_window.chunk_days` 拼大窗口（请求数按窗口爆炸） | `services/cursor.py`、`services/runner.py` |
| D3 | 单轮翻页终止条件 | 空响应 / 抓取行数 < `page_size` / 水位未前移 / 达 `backfill_start`，任一即剔除该标的；总 pass 上限 200 | 四个条件覆盖「到头 / 新股短页 / 失败 / 达标」；上限防无界循环 | ① 只看空响应（新股每只多 1 次请求，全市场多约 1 分钟）；② 不设上限（配置错误时无限请求） | `services/runner.py`、`services/pipeline.py` |
| D4 | 多主机回退的表达 | `request_spec.url_hosts` + `{host}` 模板 + `FetchConfig.fallback_urls`，仅网络错误 / 连接被掐 / 429·500·501·502·503·504 切换 | 首主机失败即等价资源换主机重试，语义与 lmstock 双主机切换一致；逐候选过 SSRF | ① 每个主机建一条任务（任务翻倍，水位分裂）；② 引擎内写死腾讯域名（领域词进引擎，违反 I1） | `core/http.py`、`providers/http_json.py`、`providers/base.py` |
| D5 | 示例回补任务形态 | 3 条板块回补合并为 1 条「腾讯回补 · 全市场」，`entrant_source` 去 `prefix_in` | 板块拆分原本只为量纲与 `data_path` 兜底；先复权改不复权后兜底不再需要（D7） | ① 保留 3 条（重复配置、慢速多轮叠加）；② 按板块再拆 1+N（与 C5 冲突） | `examples/datasets/工作区-数据源示例/datasource.json` |
| D6 | 单序列口径 | 幂等键 `[股票代码, 日期]`；删除「来源」「复权方式」两列与两条来源筛选视图；快照与回补命中同一行 | lmstock 为单一序列（当日=快照、历史=腾讯）；交叉比对演示随需求方拍板放弃 | ① 保留来源列（同日两行，与 lmstock 不一致）；② 两源分表（回退 0033 已否决的旧结构） | `datasource.json`、`股市日线.csv`、`views.json` |
| D7 | 回补复权口径 | 回补改**不复权**（URL 去 `,qfq`，`data_path=data.{entrant}.day`） | 与快照同口径才能单行单序列；lmstock 亦存不复权 + 本地复权因子（cndb 无因子能力，见负向） | ① 保留前复权（须保留来源列区分，违背 C10）；② 同步层复权换算（需除权因子，超职责） | `datasource.json` |
| D8 | 合并后成交量单位 | 不声明 `scale`，成交量存数据源原值（主板/创业板/ETF=手，科创板=股），记录为已知局限 | 单任务无法按板块取不同 `scale`；lmstock 同款原值存储 | ① 保留 `scale=100`（科创板 100 倍失真）；② 拆任务保量纲（与 C5 冲突）；③ 引擎加「按前缀缩放」（领域语义进引擎，违反 I1） | `datasource.json` |
| D9 | `backfill_start` 深度 | 保留 `2016-01-01` 作为下界；单轮翻页补到该下界或上市首日即停 | 保留「十年历史」演示目标，同时由 D2 保证一轮补满，消除慢速多轮 | ① 改为「一页 800 根即完成」（首灌后历史不深，日线分析价值缩水）；② 去掉下界（无终止目标） | `datasource.json` |
| D10 | 存量库处置 | 手动清理：删 3 条板块任务、删两列后重跑 seed；seed 保持只增不删 | 沿用 ADR 0033 C4 / 0034 D8 口径，seed 不引入删除逻辑 | ① seed 增加删除/覆盖逻辑（误删风险，跨工作区难约束） | `src/cndb/cli/seed/datasource.py`（不改） |
| D11 | 主机顺序与 WAF 记录 | 示例首选直连 `web.ifzq.gtimg.cn`（浏览器 UA + Referer `gu.qq.com`），proxy 作 failover；修正 0033「必须走 proxy」记录 | lmstock 实测直连可用（`~/lmstock/src/lmstock/core/net.py:11-15,67-70`）；单请求延迟为 proxy 的约 1/5 | ① 维持 proxy 首选（放弃直连延迟收益）；② 不设 failover（主主机故障即整轮失败） | `datasource.json`、ADR 0033 修订 |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：历史回补从「3 轮 × 全市场请求」压到「1 轮翻页到顶」，日常与首灌耗时下降；抓取获得主机回退能力，单主机抖动不再整轮失败；示例任务从 5 条股市任务降为 3 条，字段与视图去冗余，与 lmstock 形态一致；流量对第三方更友好（板块重复请求消失）。
- **负向**：① 引擎主循环由「单 pass」变「多 pass」，断点、进度、计数口径需要跨 pass 保持一致（复杂度上升）；② 示例改为不复权后，历史价格有除权跳空，且成交量单位混存（主板为手、科创板为股），作为已知局限记录；③ `core/http.py` 抓取主干抽出单 URL 函数，需回归重定向 / SSRF / 重试语义。
- **风险与缓解**：① 单轮翻页放大请求量（全市场约 2 万请求）→ 沿用全局限速（`workers=10`、`rate_limit_ms=50`）与「失败即停该标的」；② 直连主机若被 WAF 挑战 → failover 保证可用，P2 真源复验后只调 `url_hosts` 顺序；③ 存量库不自动清理 → 交接节写明手动步骤。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

| 维度 | lmstock | stock-strategy（ADR 0034 参照） | 本设计 |
|---|---|---|---|
| 当日增量 | 分页快照直写当日 K 线 | 同（快照翻页） | 同（0034 已落地，本次不改） |
| 历史回补 | 单轮 end 锚点向前翻页到上市首日 | end 锚点 + 800 根/页，多轮收敛 | 单轮翻页（D2/D3），下界 `backfill_start`（D9） |
| 主机 | 直连 `web.ifzq` + proxy 双主机切换 | proxy 单主机 | 主机列表 + 回退（D4/D11） |
| 序列口径 | 单序列、不复权存储 | 双源并存（来源入键） | 单序列、不复权（D6/D7） |

来源：`~/lmstock/src/lmstock/core/sync.py`、`~/lmstock/docs/DEPLOY.md`；本仓库 ADR 0034。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 快照直写当日 / 缺口驱动 / 水位 | `row_defaults={today}`、`backfill_date`、`entrant_source` | 不变 | ADR 0034 D2/D3/D4 |
| `http_json` 声明能力 | `rows_array` / `data_path` / `row_defaults` / `scale` | 能力保留；示例不再使用 `scale` 与「来源」常量列 | ADR 0033 D3/D4（本 ADR D8 修订示例口径） |
| 示例双源口径 | `match_keys` 含来源、来源/复权方式列、来源分组视图 | **撤销**，改单序列 | ADR 0033 D5/D9、0034 D9（本 ADR D6/D7） |
| 回补收敛方式 | 多轮 run 水位前推 | 保留水位机制，收敛方式改单轮翻页 | ADR 0034 §2.4（本 ADR D2） |
| 板块拆任务 | 3 条回补任务（量纲/解析拆分） | **撤销**，合并 1 条 | ADR 0034 §5、0039 D2（本 ADR D5/D8） |
| 示例并发/限速取值 | `workers=10`、`rate_limit_ms=50` | 沿用 | ADR 0035 D3 |
| 幂等落表（应用层先查后写、非唯一索引） | `match_keys` + `ensure_match_keys_index` | 不变（不引入 `ON CONFLICT`） | ADR 0006、0034 D6、0035 D5 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/datasource/services/cursor.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/runner.py` | `tests/test_datasource_runner_pages.py` | `fdc08346` |
| P1 | 已落地 | `src/cndb/core/http.py`、`src/cndb/plugins/datasource/providers/base.py`、`src/cndb/plugins/datasource/providers/http_json.py`、`src/cndb/plugins/datasource/services/runner.py` | `tests/test_datasource_host_fallback.py` | `fdc08346` |
| P2 | 已落地 | `examples/datasets/工作区-数据源示例/datasource.json`、`examples/datasets/工作区-数据源示例/股市日线.csv`、`examples/datasets/工作区-数据源示例/views.json`、`src/cndb/plugins/help/services/examples.py` | `tests/test_seed_datasource.py`、`tests/test_datasource_runner.py` | `9a9a6fdf` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地，等待全量门禁与人工评审（Status 仍 `Proposed`）
- 已完成：需求卡片 0053（C1..C12，6 个未决问题已由需求方逐项拍板）；P0 单轮翻页（游标新键 + 多 pass 循环 + 进度累计 + 判定层测试）；P1 主机回退（`url_hosts` / `{host}` / `fallback_urls` + 24 例单测）；P2 示例收敛为单序列三任务（CSV / 视图 / help 示例 / CHANGELOG / seed 与 runner 集成测试）
- 下一步：`make flow` → `make cov` → 前端 / e2e 门禁；P2 真源复验（联网：直连可用性、单轮翻页耗时）后回填本表；人工评审通过再把 Status 改 `Accepted`
- 已知坑：① 示例合并后成交量单位混存（手 / 股），不要误加 `scale`；② 存量库 seed 不删旧任务与旧列，须手动清理后重跑；③ `page_to_start` 只在 `backfill_date` 且模板含 `{end}` 时合法，配置错会全市场空转；④ `core/http.py` 抓取主干重构须回归 SSRF / 重定向 / 重试用例；⑤ 预览只跑 1 个 pass，`passes/truncated` 明细只在执行记录里；⑥ 路径缺失（北交所 `bj92xxxx` 只回 `data: ""`）按「无数据」返回 `[]`（ADR 0039 D2 修订），该标的零入库但不失败，水位停在原处
- 最近一次全绿：`make check-docs` @ 未提交（2026-10-27）；代码门禁待跑
