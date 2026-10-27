# ADR 0033: 股市日线同步到本地示例（http_json 通用解析扩展）

Status: Implemented
Date: 2026-10-25
Related: `src/cndb/plugins/datasource/providers/http_json.py`、`src/cndb/plugins/datasource/providers/base.py`、`src/cndb/plugins/datasource/services/normalize.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/cli/seed/datasource.py`、`examples/datasets/工作区-数据源示例/`；上游 ADR 0006（适配器收敛）、0029/0032（示例内容口径）；示例口径由 ADR 0053 修订（单序列）
需求卡片: `docs/requirements/0033-stock-daily-sync-to-local.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 参照 stockmaster 的日线同步链路（公开行情接口 → 增量拉取 → 本地表幂等 upsert） | 复用 cndb 既有同步框架（`execute_job` → `run_pipeline` → `upsert_rows`），幂等键 `股票代码+日期`（单序列口径，见 ADR 0053 D6），重复运行只更新不重复；不引入任何新同步框架 |
| C2 | 实现股市日线「同步到本地」 | 两个 `http_json` 任务：新浪快照（当日直写，不复权）+ 腾讯日线（历史回补，不复权，嵌套数组靠 P0 的通用解析扩展承载）；支持增量游标与手动触发 |
| C3 | 相关配置完善到「数据源示例」 | `examples/datasets/工作区-数据源示例/` 新增 `股市日线.csv`（示例表）+ `datasource.json` 两条 http_json 任务 + `views.json` 视图 + `fields.json` 必填项；`cndb seed` 只注入配置不联网 |
| C4 | 移除现有的【股市日线-新浪】等已有内容 | 仓库侧旧内容已随 `299f4e6a` 移除；本设计**不回退**旧的按源分表静态结构——两源写**同一张**「股市日线」表的同一行（同日单行单口径，见 ADR 0053 D6/D7），存量库残留由需求方自行清理，seed 不加删除逻辑 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 通用 http_json provider：`record_mode` 仅 `rows`（对象行）/ `columns`（列名→数组）两种 | `src/cndb/plugins/datasource/providers/base.py:92`、`providers/http_json.py:96-104` | 腾讯日线的「数组的数组」（`qfqday: [["2026-01-02","26.4",...]]`）无法声明式解析 | 确认（C2 需要 P0 扩展） |
| 2 | `data_path` 为静态路径，不支持按标的渲染 | `providers/http_json.py:147-157`（`_build_config` 原样传入）、`src/cndb/core/http.py:300`（`_resolve_path`） | 腾讯响应按标的嵌套（`data.sh600519.qfqday`），路径随 entrant 变化 | 确认（C2 需要 P0 扩展） |
| 3 | `fill_entrant` 行内补标的列（新浪日线响应不回显 symbol，正是该注释预留的场景） | `src/cndb/plugins/datasource/services/pipeline.py:123-139` | 新浪 job 配 `entrant_param=symbol` 即可拿到标的列 | 确认（C2 直接复用） |
| 4 | 归一层只做改名 + 类型归一，无数值缩放 | `src/cndb/plugins/datasource/services/normalize.py:74-134`、`providers/base.py:111-117`（`FieldTransform`） | 成交量单位随市场不同（主板/创业板/ETF 为「手」，科创板原值即股），示例已不声明 `scale`（ADR 0053 D8） | 确认（能力已有，示例不使用） |
| 5 | 行级常量列无机制：响应不回显「日期」等维度时无法补齐 | `services/pipeline.py`（`fill_entrant` 与 `row_defaults` 两个补齐点） | 快照任务靠 `row_defaults: {日期: {today}}` 补当日 | 确认（`row_defaults` 已在 P0 落地） |
| 6 | 新浪日线接口为纯 JSON 平铺数组，`_extract_array` 原生支持顶层数组 | `src/cndb/core/http.py:336-354`；历史实现参考被删 provider（`git show 35b88306^:.../sina_kline.py`，接口 `CN_MarketData.getKLineData?symbol=sh600519&scale=240&ma=no&datalen=1023`，上限 1023 根、仅不复权、成交量单位股） | 新浪 job 零代码改动 | 确认（C2） |
| 7 | 腾讯日线接口与响应格式（历史实现参考 `git show 35b88306^:.../tencent_kline.py`） | URL `…/appstock/app/newfqkline/get?param={symbol},day,{start},{end},320`；直连 `web.ifzq.gtimg.cn` 带浏览器 UA / Referer 可正常返回，`proxy.finance.qq.com` 作 failover（ADR 0053 D11 修正本节旧「必须走 proxy」记录）；行序 `[日期,开,收,高,低,成交量]`；序列键 `day`（不复权） | P0 解析扩展的领域参照 | 确认（C2；0029 旧记录已修正） |
| 8 | seed 注入：按 `(workspace_id, name)` 幂等，只增不删 | `src/cndb/cli/seed/datasource.py:40-117` | 新任务开箱注入；存量库旧任务不受影响（卡片未决问题 3 已拍板不加删除） | 确认（C3/C4） |
| 9 | 旧股市示例（「股市日线」「股市日线-新浪」「自选股」表 + CSV + KlineView + candlestick 图表）已整体移除 | `299f4e6a`（`examples/datasets/工作区-数据源示例/` 现仅存两条 llm_prompt 任务 + 天气/政策/国际形势 CSV） | C4 的「移除」在仓库侧已成立，本设计只须不回退 | 确认（C4） |
| 10 | 同步执行链路完备：`execute_job`（游标 → 抓取 → 归一 → upsert → 留痕）+ 假源注入测试钩子 | `src/cndb/plugins/datasource/services/runner.py:84-195`（`fetch` 参数） | 集成测试可用假 fetch 断言落表与幂等，不联网 | 确认（C1/C2 测试路径） |
| 11 | 真实示例配置的结构校验测试锁「2 条 llm_prompt 任务」 | `tests/test_seed_datasource.py:170-199` | 新增 2 条 http_json 任务后须同步改断言 | 新增（C3 测试面） |
| 12 | 视图校验白名单两处同口径（`charts[i].<key>` 分支） | `src/cndb/plugins/tables/routers/views.py`、`src/cndb/cli/seed/views.py` | 新视图只用既有 grid/kanban/chart 形态与既有字段键，**不动白名单** | 排除（无需改动） |

**核心缺陷（需求要补的）**：通用 `http_json` 适配器表达不了「腾讯日线」这类**数组的数组 + 按标的嵌套 + 缺日期维度**的响应形态，导致历史日线无法在不新增领域专用 provider 的前提下同步到同一张表。

设计目标（不变量）：

- **I1 通用适配器收敛不回退**：不新增任何领域专用 provider（守住 ADR 0006 D2）；P0 的解析扩展全部是**领域无关**的声明式能力——`providers/` 与 `services/pipeline.py` 不出现 symbol / 股票等领域词，股票语义只存在于 `examples/datasets` 的 JSON 配置里。
- **I2 幂等可重跑**：同一任务任意次运行，「股票代码 + 日期」二元组唯一（ADR 0053 D6），重跑只更新既有行；当日快照与历史回补命中同一行时按幂等键覆盖。
- **I3 seed 只注入不联网**：`cndb seed` 不发起任何行情请求；示例任务调度一律 `manual`，由演示者点「立即运行」。
- **I4 归一失败不丢行**：`rows_array` 行缺列、缩放遇到非数值 → 该字段降级 `None` 并记失败明细，整行保留（沿用 normalize 既有口径）。
- **I5 存量零迁移**：无数据库 schema 变更、无 API 破坏性变更；旧库升级行为不变。

## Decision

### 1. 数据模型

无新表、无新列、无迁移。`datasource_sync_job` 复用现状（ADR 0006 M2），新增的只是 `request_spec` / `field_mapping` JSON 内的**声明键**：

| 声明位置 | 新键 | 语义 |
|---|---|---|
| `request_spec` | `record_mode: "rows_array"` | 响应数组每项是**行数组**（而非对象），配合 `record_layout` 按位置取值 |
| `request_spec` | `record_layout: {目标列: 位置索引(int)}` | `rows_array` 模式下列名 → 元素下标；`columns` 模式语义不变（列名 → 源键） |
| `request_spec` | `row_defaults: {列: 常量}` | 行级常量列，`setdefault` 语义并入每行（响应自带值优先）；示例用于快照任务补 `日期: {today}` |
| `field_mapping` 每项 | `scale: number`（可选） | 数值归一前乘的缩放系数；仅 int/float 生效，其它类型忽略。能力保留，示例不再声明（合并任务跨市场，单位不可统一，见 ADR 0053 D8） |

`data_path` 从静态路径升级为**模板**：`_build_config` 里经 `render_text(spec.data_path, variables)` 渲染（支持 `{entrant}` 等，与 URL 模板同一求值器），腾讯声明 `data.{entrant}.day`。

### 2. 判定算法（唯一入口）

- **解析入口**：`HttpJsonProvider.parse`（`providers/http_json.py:96`）按 `record_mode` 三分支派发——`rows`（现状 `_extract_array`）/ `columns`（现状 `columns_to_rows`）/ 新增 `rows_array`（新函数 `rows_array_to_rows`：`json.loads` → `_resolve_path(data_path)` → 要求 list → 逐项按 `record_layout` 索引拼行）。`rows_array` 的取数走 `response_handler_for` 返回的自定义 handler（`uses_custom_parse` 判定扩为 `uses_custom_parse or record_mode == "rows_array"`，与既有腾讯快照 handler 同机制），避免 `fetch_json` 通用提取把行数组过滤成空。
- **归一入口**：`apply_field_mapping`（`services/normalize.py:74`）唯一；`FieldTransform` 增加 `scale: float | None`，`coerce_value` 前对 int/float 乘系数，失败沿用降级留痕口径。
- **常量列入口**：`run_pipeline`（`services/pipeline.py:111`）在 `fill_entrant` 之后按 `setdefault` 并入 `row_defaults`，`SyncJobSpec` 增加对应字段、`build_job_spec` 从 `request_spec` payload 解析。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| 无 | 任务创建 / 编辑接口本就接受自由 `request_spec` JSON，新声明键零接口改动 |

### 4. 边界与例外

1. 新浪分页快照接口只返回「当日截面」（无区间参数）：快照任务 `cursor=none`，靠 `row_defaults` 补当日，幂等靠 upsert；长历史由腾讯回补任务承担。
2. 腾讯接口语义为「截至 end 的最近 800 根」：单轮翻页（每页 800 根向前翻到 `backfill_start` 或不足一页）由 ADR 0053 D2/D3 的游标能力承载，本 ADR 只负责解析与落表。
3. 腾讯返回错误码（`code != 0`）时 `data_path` 解析不到 → 抛 `ProviderError` → 记入该请求 `failures`，不拖垮同批其它标的请求（ADR 0006 I3 失败口径）。
4. `rows_array` 行长度不足声明的最大索引 → 缺位补 `None`（I4），不丢行。
5. 两源同为**不复权**口径（ADR 0053 D7），同日同一行、同键覆盖；除权日前后价格跳空属未复权真实值，不做价格换算（换算需除权因子，超出同步职责）。
6. `scale` 只对数值类型生效；布尔 / 日期 / 文本遇到 `scale` 原样归一（不报错，记 debug 日志）。示例不声明 `scale`，成交量取数据源原值（主板/创业板/ETF=手，科创板=股，已知局限见 ADR 0053 D8）。

### 5. 迁移

无。`request_spec` / `field_mapping` 均为 JSON 列，新声明键对旧数据向后兼容（缺省即旧行为）；无 alembic 迁移、无 downgrade。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 无 | 无 | 任务由 seed 注入，数据源页既有渲染直接可用；`HTTP_JSON_PARAMS_SCHEMA`（向导表单描述）不渲染新键，`record_mode` / `row_defaults` / `scale` 属配置文件级能力（与 `record_mode=columns` 现状一致——`examples/datasource/weather-open-meteo.json` 同为配置文件形态） |

### 7. 测试清单

**判定层（单测）**：
- `rows_array_to_rows`：腾讯日线样例响应（含 `code` 外层、`day` 数组的数组）→ 行拼装；`data_path` 渲染 `{entrant}`；路径缺失 / 顶层非 dict / 序列为空 → `ProviderError` 或空数组口径
- `record_layout` 位置索引：行长度不足补 `None`；`columns` 模式回归不受影响
- `row_defaults`：常量列 `setdefault` 并入；响应自带同名值不被覆盖
- `FieldTransform.scale`：×100 换算、非数值原样、`None` 值跳过；旧映射（无 scale）回归不变（能力保留，示例不再声明）
- `data_path` 模板：`_build_config` 对 `data.{entrant}.day` 的逐请求渲染

**接口层 / 集成**：
- `execute_job` 假 fetch 桩：快照样例响应（平铺对象行、不带日期）→ `fill_entrant` 补「股票代码」、`row_defaults` 补「日期」、upsert 幂等（跑两次行数不变）
- 腾讯样例响应（嵌套数组）→ 同一「股市日线」表落行；与快照同标的同日命中同一行（1 行，后写者覆盖，幂等键 `股票代码+日期`）
- `test_seed_datasource.py::test_real_datasource_json_is_valid` 改锁 5 条任务（2 llm_prompt + 3 http_json），校验 http_json 任务的表/CSV/映射/幂等键自洽与 `record_mode` / `row_defaults` 声明

**迁移 / 备份**：无迁移；seed 往返（`test_backup_seed_roundtrip.py` 既有链路自动覆盖新表）

**e2e（前端）**：无新增（不新增页面 / 视图形态；`gallery-view.spec.ts` 既有示例工作区断言不受影响）

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | http_json 通用解析扩展（`rows_array` + `data_path` 模板 + `row_defaults` + `scale`）+ 判定层单测 | 低 |
| **P1** | 数据源示例工作区落地（`股市日线.csv` / 快照与回补两条 `datasource.json` 任务 / `views.json` / `fields.json`）+ 集成测试（假源落表幂等）+ seed 结构测试更新 | 中（示例配置与 seed 校验口径需逐项对齐） |
| **P2** | 文档同步（CHANGELOG、workspace `_comment`、帮助文档涉及数据源示例的描述核查）+ `make flow` 全绿收尾 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案：日线同步如何承载 | 不恢复专用 provider，扩 `http_json` 四项**领域无关**声明能力（`rows_array` / `data_path` 模板 / `row_defaults` / `scale`），股票语义全在示例 JSON 配置层 | ADR 0006 D2 收敛成果要守住；解析形态（数组行 / 按键嵌套 / 缺常量维度 / 单位换算）在各类 API 中普遍存在 | ① 新增 `tencent_kline` provider（回退 0006 收敛，维护面随领域膨胀）；② 不扩能力直接写死解析（领域代码进 provider） | `providers/http_json.py`、`providers/base.py`、`services/normalize.py`、`services/pipeline.py` |
| D2 | 腾讯嵌套数组的解析表达 | `record_mode` 新增 `rows_array` + `record_layout` 位置索引；`data_path` 支持模板渲染；取数走自定义 response handler 绕开通用 dict 过滤 | 声明式、领域无关；与既有 `columns` 模式对称 | ① `_extract_array` 递归猜数组（不可声明、易误判）；② 专用 parse 函数写在 provider 里（又变领域代码） | `providers/http_json.py` |
| D3 | 行级常量列 | `request_spec.row_defaults` 行级常量列（`setdefault`），示例用于快照任务补「日期」 | 通用（大量 API 不回显某维度常量），语义与 `fill_entrant` 同族 | ① 按源分表（需求方已否——旧结构）；② `field_mapping` 里造常量语法（混淆「改名」语义） | `services/pipeline.py`、`providers/base.py`（`SyncJobSpec`） |
| D4 | 成交量单位口径 | 能力 `field_mapping.scale` 保留；示例**不声明**，成交量存数据源原值（主板/创业板/ETF=手、科创板=股） | 合并为单任务后无法按板块取不同系数；lmstock 同为原值存储（ADR 0053 D8） | ① 统一乘 100（科创板 100 倍失真）；② 按板块拆任务保量纲（与 ADR 0053 C5 冲突） | `services/normalize.py`、`providers/base.py`（`FieldTransform`） |
| D5 | 幂等键 | `match_keys = [股票代码, 日期]`：单序列口径，快照与回补命中同一行（ADR 0053 D6） | 单行单口径是「与快照同源、单序列」的前提；交叉比对演示随需求方拍板放弃 | 来源入键（同日两行并存，与 ADR 0053 D6 冲突） | `examples/datasets/工作区-数据源示例/datasource.json` |
| D6 | 游标与调度 | 快照任务 `cursor=none`（接口只给当日截面，幂等靠 upsert）；回补任务 `cursor=backfill_date` + `backfill_start` + 单轮翻页（ADR 0053 D2/D3）；两任务 `schedule=manual` | 接口能力所限；示例不自动跑，避免演示环境无网 / 被限流时空跑失败（与 0032 后 llm 任务 manual 同理） | daily 定时（演示环境联网不确定，失败运行记录污染示例） | 同上 |
| D7 | K 线可视化与校核引擎 | 均不做：candlestick / KlineView 不恢复（`299f4e6a` 刚移除），stockmaster 的质量检查引擎不移植 | 需求方拍板（卡片未决问题 1、4）；示例价值聚焦「同步到本地」链路本身 | 恢复 KlineView（约千行前端改动，与刚完成的移除决策冲突）；移植 quality.py（大新功能面，超出本卡范围） | 无 |
| D8 | 示例标的 | `sh600519` / `sz000001`，带市场前缀（两接口均要求前缀格式） | 与 `299f4e6a` 前老示例及 stockmaster 标的格式一致；带前缀避免 upsert 键不命中 | 无前缀裸代码（`match_keys` 永不命中 → 重复行，老坑） | 同 D5 |
| D9 | 复权口径 | 两源统一**不复权**（快照天然不复权，腾讯 URL 不带 `qfq`），同日同键覆盖 | 单序列口径要求同源同构；换算需除权因子数据，超出同步职责（ADR 0053 D7） | 前复权与不复权混存（须保留来源/复权方式列区分，与 ADR 0053 C10 冲突） | 同 D5 |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：`http_json` 获得覆盖「数组行 / 按键嵌套 / 缺常量维度 / 单位换算」四类常见形态的声明式能力，任何同类 API（不限股票）都可用配置接入；「数据源示例」工作区具备一条**开箱可运行**的行情同步链路（快照兜当日 + 回补补历史，单序列）。
- **负向**：`FieldTransform` / `RequestSpec` 各多一个可选声明键，归一层与解析层分支 +1；示例工作区多一张表与三条 manual 任务（无 Key、无网环境下不点不跑，无副作用）；示例不再使用 `scale`，成交量单位随市场不同（ADR 0053 D8）。
- **风险与缓解**：① 行情接口属第三方，限流 / 改版不可控 → 失败口径沿用 ADR 0006 I3（单请求失败留痕不拖垮任务），示例任务 manual 不自动跑；② 主机策略变化 → 直连 + proxy failover（ADR 0053 D11），失效表现为运行记录 `failures`，可观察可换 URL 模板（纯配置改动）。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

无（本 ADR 为示例内容与既有框架的通用能力扩展，不引入新领域模型）。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 适配器边界 | `providers/registry.py` 只注册 `http_json` / `llm_prompt` | 本 ADR 不触碰注册表，扩展全部落在 `http_json` 内部声明能力 | ADR 0006 D2 |
| 示例工作区内容口径 | `examples/datasets/工作区-数据源示例/` | 股市示例以「可运行的同步任务」回归（不再是静态 CSV），内容严肃化口径不变 | ADR 0032 |
| 示例口径（单序列 / 不复权 / 任务合并） | 同一示例工作区 | 由 ADR 0053 D5-D11 修订：`match_keys` 去来源、删来源/复权方式列、回补改不复权、3 条板块回补合并为 1 条并单轮翻页 | ADR 0053 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/datasource/providers/http_json.py`、`src/cndb/plugins/datasource/providers/base.py`、`src/cndb/plugins/datasource/services/normalize.py`、`src/cndb/plugins/datasource/services/pipeline.py` | `tests/test_datasource_http_json.py` | `bfbefb33` |
| P1 | 已落地 | `examples/datasets/工作区-数据源示例/`、`src/cndb/plugins/datasource/services/runner.py` | `tests/test_seed_datasource.py`、`tests/test_datasource_runner.py` | `bfbefb33` |
| P2 | 已落地 | `CHANGELOG.md`、`CONTEXT.md`、`src/cndb/plugins/help/services/examples.py` | `tests/test_help_examples_api.py` | `bfbefb33` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：Implemented（P0-P2 全部落地，代码与文档已提交）
- 已完成：需求卡片 0033（四个未决问题已由需求方逐项拍板）、ADR 评审通过（2026-10-25）、P0 `http_json` 四项通用声明能力 + 判定层单测、P1 示例 CSV / 双源任务 / 字段 / 视图 / seed 结构测试 / 端到端落表集成测试、P2 CHANGELOG / CONTEXT / 帮助示例清单；真实 `cndb seed` 到临时库核查通过（21 张表、4 条同步任务、9 字段类型推断正确）
- 下一步：无（后续如需恢复 K 线可视化或移植质量检查引擎，按 D7 另开 ADR）
- 已知坑：① 腾讯请求首选直连 `web.ifzq.gtimg.cn`（须带浏览器 UA / Referer），`proxy.finance.qq.com` 作 failover（ADR 0053 D11）；② 标的代码必须带市场前缀（sh600519），无前缀会 upsert 不命中产生重复行；③ 快照接口只给当日截面；④ `field_mapping.scale` 按**目标类型**判定，测试表 float 字段须配 `config={"decimals": 2}`，否则 `NumberFieldConfig.decimals` 默认 0 会把价格四舍五入，且示例已不声明 `scale`（ADR 0053 D8）；⑤ `make check -j4` 偶发前端 coverage 目录锁，单跑 `make frontend-coverage` 重跑即可
- 最近一次全绿：`make check` @ bfbefb33（2026-10-25，后端 5345 passed / 3 skipped，覆盖率 97.03%）
