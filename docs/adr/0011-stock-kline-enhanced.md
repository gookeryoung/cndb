# ADR 0011: 股市 K 线增强（多周期复权、全历史字段与行内 K 线视图）

Status: Accepted（2026-10-20 评审通过）
Date: 2026-10-20
Related: `src/cndb/plugins/datasource/providers/eastmoney_kline.py`、`src/cndb/plugins/datasource/providers/eastmoney_symbols.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/normalize.py`、`src/cndb/plugins/tables/services/importing/importer.py`、`src/cndb/plugins/tables/services/importing/row_validator.py`、`src/cndb/plugins/tables/routers/views.py`、`src/cndb/cli/seed/stock_quotes.py`、`src/cndb/cli/sync.py`、`frontend/src/pages/grid/views/klineBoard.ts`、`frontend/src/pages/grid/views/KlineView.tsx`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`；上游 ADR `docs/adr/0009-stock-daily-datasource-example.md`
需求卡片: `docs/requirements/0011-stock-kline-enhanced.md`（需求原文与约束编号的唯一副本）

> 示例「自选股」表的标的集合已由 [ADR 0013](0013-stock-daily-multi-source-sample.md) 收敛为 10 只 A 股（与三源日线一致），本文的 kline 视图、多周期复权列与分列 upsert 口径不变。
>
> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」段落；ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用，不在仓库保留 `Superseded` / `Deprecated` 文档。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 更全面的股市K线的获取 | `eastmoney_kline` provider：`secid` 由代码前缀换算（`sh→1.` / `sz→0.` / `hk→116.` / `us→105.`），URL 的 `klt`（101/102/103）控制日 / 周 / 月、`fqt`（0/1/2）控制前 / 后 / 不复权，`beg=0&end=20500101&lmt=100000` 一次覆盖全历史；一只股票输出一行 |
| C2 | 更全的行情字段 | `fields2=f51..f61` 解析为 11 字段（date/open/close/high/low/volume/amount/amplitude/pct_change/change/turnover）；末条 K 线派生 `latest_date` / `latest_close` / `latest_pct_change` / `latest_volume` / `latest_amount` 快照；`normalize` 新增 `json` 分支承接 K 线数组 |
| C3 | 一只股一行数据 | 新增示例表 **自选股**（16 字段）：一标的一行，K 线序列落 5 个 `json` 列（日线前 / 后 / 不复权、周线 / 月线前复权）；手工 `DataTable + DataField + ddl.create_table` 建表，避免自动推断把 list 值提升成 multiselect |
| C4 | K线图能够按照选中的行切换显示 | 新增 `view_type=kline`：左侧标的列表（搜索 / 单选 / 最新价与涨跌幅），右侧 ECharts 双 grid（价格 + 成交量，dataZoom 联动）；`GridPage` 把 `rows/fields/view/initialSelectedRowId/onSelectRow` 传入，视图内选中回写表格 `selectedRowKeys` |
| C5 | 典型示例 | seed 新增 `cli/seed/stock_quotes.py`：读 `自选股.json` + `股市日线.csv`，聚合日线前复权并在 Python 派生周 / 月前复权，计算最新行情快照；`views.json` 增 kline 视图（`filters: 是否自选=true`）；`datasource.json` 增 5 个 `eastmoney_kline` 分列 job（日线三口径 + 周 / 月前复权），`match_keys=["股票代码"]`、`cursor=none` |
| C6 | 更多标的与全市场 | `eastmoney_symbols` provider 分页抓取行情列表（A / HK / US / 全部），输出 `symbol/code/name/market`，新行 `是否自选=false`（字段默认值）；`cndb sync batch-kline` 按市场 / 是否自选从自选股表读代码，每批 ≤100 只创建或更新 `eastmoney_kline` job，支持错峰调度、`--prune`、`--dry-run`、`--json` |
| C7 | 多 job 分列写同一行 | `RowValidator` / `Importer` 增加 `partial: bool = False`；`partial=True` 时不走 gap_filling、未提供的字段不参与必填校验与更新；`datasource/services/write.py` 的 `upsert_rows` 固定 `partial=True`，普通导入语义不变 |
| C8 | 健壮性与测试 | provider 全部用固定 fixture 单测（不联网）；前端 `parseKlineSeriesDetailed` 对非法 JSON / 无效行返回可读错误且不崩溃；`resolveSeries` 缺列返回空态文案不静默回退；后端 / 前端 / e2e 三层覆盖 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准）。沿用卡片「现状影响面」编号；ADR 新发现条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 数据源落表 `upsert_rows` 走 `Importer`，`gap_filling="empty"` 把未提供的目标字段填 `None`，更新路径把 `None` 当显式清空 | `src/cndb/plugins/datasource/services/write.py:61`、`tables/services/importing/importer.py` | 多 job 分别写不同 K 线列会互相清空，C5 的 5 个 job 无法共存 | 确认 |
| 2 | `coerce_value` 只支持 text/int/float/date/datetime/bool，未知类型回退 text | `src/cndb/plugins/datasource/services/normalize.py:130` | K 线数组归一后是 Python repr，无法被前端 `JSON.parse` | 确认 |
| 3 | 内置 provider 只有 `http_json` / `tencent_kline` / `rss_atom` | `src/cndb/plugins/datasource/providers/registry.py` | 无多市场 / 全历史 / 全字段的 K 线源，也无标的发现源 | 确认 |
| 4 | 视图字段校验白名单（含 `charts[]`）在后端与 seed 各一份 | `src/cndb/plugins/tables/routers/views.py:60`、`src/cndb/cli/seed/views.py` | kline 字段键会被 400 / seed 跳过 | 确认 |
| 5 | 视图模式枚举、按钮、类型映射、配置 schema、表单选项、两处后端校验为分散维护 | `frontend/src/pages/grid/views/viewModes.ts`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`CreateEditViewForm.tsx` | 新增模式需同步 ≥6 处，漏一处即入口不可达或配置空白 | 确认 |
| 6 | 示例无「一只股一行」形态的表 | `examples/datasets/工作区-数据源示例/` | 无行内 K 线载体，选中行切换无从演示 | 确认 |
| 7 | 全市场标的数千，单 job `entrant_keys` 会展开同等数量请求 | `src/cndb/plugins/datasource/services/pipeline.py` | 单 job 数千请求不可调度、失败面过大 | 确认 |
| 8 | `records._normalize_values` 只在创建路径应用 `DataField.default_value`，更新路径不应用 | `src/cndb/plugins/tables/services/core/records.py` | 「新行 false、旧行保持用户勾选 true」可只靠字段默认值实现，无需映射该列 | **新增（关键机制）** |
| 9 | `useGridData` 非 grid 模式 `limit=2000` | `frontend/src/pages/grid/useGridData.ts` | 全市场行内 JSON 不能一次性拉取；视图必须用 `filters` 收窄 | **新增（规模边界）** |

**核心缺陷（需求要补的）**：既有示例只有「一行一个交易日的日线明细 + candlestick 图表」，无法表达「一只股一行、行内嵌多周期多复权全历史」的数据形态，也没有多市场全历史数据源与按行切换的 K 线视图；且多 job 分列落表会被全列覆盖语义互相清空。

设计目标（不变量）：

- **I1 一只股一行**：K 线以 JSON 内嵌在自选股表行内，不新增 K 线明细子表；行体积随历史增长可接受，视图只按 `是否自选` 收窄。
- **I2 分列不互相清空**：数据源落表固定部分列语义，未提供的列不更新；普通导入（CSV / Excel / JSON 数组）仍为全列语义。
- **I3 存量零迁移**：无 alembic 迁移；新表由 seed 建立；`view_type` 保持自由字符串，`view_options` 是 JSON。
- **I4 校验单一**：K 线字段白名单与语义校验在 `routers/views.py` 与 `cli/seed/views.py` 两处同口径。
- **I5 空态不静默回退**：请求的周期 / 复权没有对应列时显示空态与原因，不回退到其它口径冒充。
- **I6 全市场不进视图全量**：视图只取自选标的；全市场标的经分批 job 同步，单批 ≤100 只。

## Decision

### 1. 数据模型

无 alembic 迁移。

**自选股表**（seed 手动建表，物理列名由 `ensure_db_name` 生成）：

| 字段 | 类型 | 说明 |
|---|---|---|
| 股票代码 | text, unique | `sh600519` / `sz000001` / `hk00700` / `usAAPL` |
| 股票名称 | text, required | |
| 市场 | select | A股 / 港股 / 美股 |
| 行业 | text | |
| 是否自选 | boolean, default `false` | 新行默认 false，已有行不被重新发现覆盖 |
| 最新价 / 涨跌幅 / 最新交易日 / 成交量 / 成交额 | float / float / date / float / float | 最新行情快照 |
| 日线前复权 / 日线后复权 / 日线不复权 | json | 日线三口径 |
| 周线前复权 / 月线前复权 | json | seed 由日线派生，同步任务可覆盖 |
| 更新时间 | datetime | |

K 线 JSON 元素约定：`{date, open, close, high, low, volume, amount, amplitude, pct_change, change, turnover}`，按日期升序、同日去重。

**视图**：`DataView.view_type = "kline"`（自由字符串），`view_options` 新增 12 个字段键 + `default_period` / `default_adjust` / `show_ma` / `show_volume` / `ma_periods`。

### 2. 判定算法（唯一入口）

- **视图校验（两处同口径）**：后端 `_validate_view_fields`（`src/cndb/plugins/tables/routers/views.py`）与 seed `_validate_view_fields`（`src/cndb/cli/seed/views.py`）：
  - 白名单放行 `symbol_field` / `name_field` / `price_field` / `change_pct_field` / `volume_field` / `amount_field` / `date_field` / `day_qfq_field` / `day_hfq_field` / `day_none_field` / `week_qfq_field` / `month_qfq_field`；
  - `view_type == "kline"` 时：`symbol_field` 必填；至少一个序列字段；`default_adjust` 对应的日线字段必须配置；`default_period` 为 week/month 时需有对应列或 `day_qfq_field` 可派生。
- **部分列 upsert**：`write.upsert_rows` → `Importer(engine, db, table, user=user, partial=True)`；`RowValidator(partial=True)` 不做 gap_filling，`Importer._drop_missing_required` 跳过未提供的必填字段。唯一入口是 `write.upsert_rows`，导入接口不传 `partial`。
- **前端序列解析**：`parseKlineSeriesDetailed` 兼容字符串 / 数组、`date|trade_date|交易日`、数值字符串，排序去重并剔除无效行；`resolveSeries` 按「周期 + 复权」映射到具体列，缺列返回 `{points: [], source: 'empty', message}`。
- **批量任务判定**：`cmd_batch_kline` 为唯一入口——校验目标列 → 读标的（`是否自选=true` 或 `--include-unselected`）→ 按市场前缀过滤 → 按 `batch_size`（收敛到 1..100）切片 → 每批 × 每个序列 upsert `DatasourceSyncJob`（按名称前缀幂等），`--prune` 删除超出本次分批的同前缀旧任务。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET/POST /api/v1/workspaces/{wid}/tables/{tid}/views` | 无结构变更；`view_type=kline` 与 17 个 `view_options` 键通过字段 / 语义校验 |
| `GET /api/v1/workspaces/{wid}/datasource/providers` | 新增 `eastmoney_kline` / `eastmoney_symbols` 两个 provider 描述 |
| CLI `cndb sync batch-kline` | 新增子命令（`--workspace` / `--table` / `--market` / `--batch-size` / `--series` / `--include-unselected` / `--prefix` / `--schedule` / `--at` / `--stagger-minutes` / `--rate-limit-ms` / `--prune` / `--dry-run` / `--json`） |

### 4. 边界与例外

1. **行体积与派生口径**：只落日线三口径 + 周 / 月前复权；周 / 月后复权与不复权由前端 `resampleKline` 从日线派生（open 首日、close 末日、high max、low min、volume/amount sum），不落库，避免行膨胀。
2. **缺列 / 坏数据空态**：请求的周期 / 复权无对应列时显示「该周期暂无数据」；JSON 解析失败展示可读错误，不崩溃、不静默回退。
3. **`是否自选` 语义**：`eastmoney_symbols` 的 `field_mapping` 不含该列；新行靠 `DataField.default_value=false` 落值，已有行在部分列 upsert 下保持用户勾选的 true。
4. **全市场规模**：K 线视图 `filters` 固定 `是否自选=true`；全市场同步走 `batch-kline` 分批任务；`batch-kline` 创建前预检目标 JSON 列存在，缺列直接退出。
5. **第三方接口无 SLA**：provider 单测全部用固定 fixture；运行期错误（错误码 / 非 JSON / 空 data）抛 `ProviderError` 或返回空列表，单 job 失败不阻塞其他 job。
6. **部分列语义边界**：`partial=True` 只用于数据源落表；CSV / Excel / JSON 导入仍为全列语义（未提供列按 gap_filling 处理），避免改变既有导入行为。
7. **幂等键格式**：示例 CSV 与 `entrant_keys` 统一为带前缀代码（`sh` / `sz` / `hk` / `us`），`match_keys=["股票代码"]` 才能命中既有行。
8. **派生实现双份**：seed（Python `_resample`）与前端（`resampleKline`）各一份，口径必须一致；差异由两侧单测钉住。

### 5. 迁移

无 alembic 迁移（无 schema 变更）。自选股表由 `cndb seed` 建立并写入示例行；重复 seed 检测同名表已存在则跳过。视图与同步任务经既有 seed 注入。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 视图模式 | `frontend/src/pages/grid/views/viewModes.ts`、`frontend/src/pages/grid/GridPage.tsx` | `ViewMode` / `VALID_MODES` / `MODE_VIEW_TYPES` / `MODE_BUTTONS` 增 `kline`；lazy import `KlineView` 并预加载；渲染分支传 `rows/fields/view/total/initialSelectedRowId/onSelectRow` |
| K 线纯逻辑 | `frontend/src/pages/grid/views/klineBoard.ts` | `parseKlineSeriesDetailed` / `resampleKline` / `computeMA` / `parseMaPeriods` / `resolveSeries` / `latestQuote` / `buildKlineOption`（双 grid、dataZoom 联动、红涨绿跌、MA 线组） |
| K 线组件 | `frontend/src/pages/grid/views/KlineView.tsx` | 左侧 280px 标的列表（搜索 / 键盘 Enter / Space / 选中高亮 / 窄屏 Select）；右侧周期与复权 Segmented、MA 与成交量开关；单独注册 `CandlestickChart` / `LineChart` / `BarChart` / `GridComponent` / `TooltipComponent` / `LegendComponent` / `DataZoomComponent` / `AxisPointerComponent` / `SVGRenderer` |
| 视图配置 | `frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`CreateEditViewForm.tsx` | 新增 `KLINE_OPTIONS`（17 项）与 `getOptionSchema` 的 `case 'kline'`；`viewTypeOptions` 增「K线 (Kline)」 |

### 7. 测试清单

**判定层（单测）**：`klineBoard` 的解析（字符串 / 数组 / 别名 / 无效行 / 坏 JSON）、重采样、MA、周期复权列解析、option 装配；`viewModes` 的 kline 合法性；后端 partial upsert（三列互不覆盖）；normalize `json` 分支。

**接口 / CLI 层**：views API 对 kline 字段键与语义校验（缺 `symbol_field`、无序列字段、默认复权缺列 400）；`eastmoney_kline` / `eastmoney_symbols` fixture 解析；`cndb sync batch-kline` 分批 / 只取自选 / 市场过滤 / 上限收敛 / 错峰 / 幂等更新 / `--prune` / `--dry-run` / 缺表缺列退出。

**seed**：自选股表字段类型（json / float decimals）、周月派生、幂等跳过、`是否自选` 默认值与既有行不变；`datasource.json` 7 个 job 结构与幂等注入。

**迁移 / 备份**：无迁移；`cndb seed` 全量重建后示例工作区含自选股表、kline 视图与 5 个分列同步任务。

**e2e（前端）**：进入自选股表 → 切 K 线视图 → 默认选中首个标的 → 点击第二只股票断言标题 / 最新价变化 → 切周线 / 后复权（无数据落空态）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 部分列 upsert + `eastmoney_kline` provider + normalize json + 自选股 seed + 两处视图校验 + 前端 klineBoard / KlineView / 视图注册 / 配置 schema + 测试 | 中 |
| **P1** | `eastmoney_symbols` 标的发现 + `cndb sync batch-kline` 分批任务 + 全市场边界 + 测试 | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 视图数据形态 | **单表内嵌 K 线 JSON**（一只股一行） | 用户确认；选中行切换只需一次列表请求，无 N+1 取数 | 独立 K 线明细子表 / 按标的建表（切换需额外请求，且与既有视图框架不兼容） | 「自选股」表 5 个 json 列 |
| D2 | K 线视图实现方式 | **新增 `view_type=kline` 专用模式** | 用户确认；列表 + 图表双栏与 candlestick 单图形态差异大，独立模式无需塞进 chart schema | 扩展 chart candlestick（需新增标的列表与行内 JSON 解析，chart 配置语义被撑爆） | `viewModes.ts`、`KlineView.tsx`、`klineBoard.ts` |
| D3 | 数据源选型 | **东方财富 `eastmoney_kline`** | 一次覆盖 A/HK/US、日/周/月、三种复权与全历史，字段最全且无需按时间分片 | 腾讯 `tencent_kline`（仅 A 股、单周期、无全字段）；多源拼装（复杂度高、口径不一） | `eastmoney_kline.py` |
| D4 | 多 job 分列写入 | **`RowValidator` / `Importer` 增加 `partial`，数据源落表固定 `partial=True`** | 5 个周期 / 复权 job 写同一行，必须只更新本次提供的列 | 每 job 全列写（需先读后并，竞态且复杂）；合并成单 job（URL 参数不同，框架不支持一 job 多模板） | `write.py`、`importer.py`、`row_validator.py` |
| D5 | 全市场标的 `是否自选` 落值 | **不映射该列；新行靠 `DataField.default_value=false`，已有行保持不变** | 部分列 upsert 不提供即不更新，避免重新发现把用户勾选的 true 覆盖成 false | 映射该列并写 false（会覆盖用户选择）；写 true（全市场都进自选视图） | `stock_quotes.py` 字段默认值 |
| D6 | 全市场同步方式 | **P1 标的发现 provider + `cndb sync batch-kline` 分批（≤100 只，错峰调度）** | 单 job 数千请求不可调度、失败面过大；CLI 可幂等重建与裁剪 | 单 job 全市场（请求量爆炸）；视图直连全市场（`useGridData` limit=2000，响应体过大） | `eastmoney_symbols.py`、`cli/sync.py` |
| D7 | 周期 / 复权落库范围 | **日线三口径 + 周 / 月前复权落库；周 / 月后复权与不复权前端从日线派生** | 9 组合全落库会让行体积再翻倍，且派生结果确定可单测 | 9 组合全落库（行膨胀）；全部前端派生（日线之外的周期精度受限于派生算法） | `stock_quotes.py`、`klineBoard.ts` |
| D8 | 视图字段校验 | **后端与 seed 两处白名单 + 语义校验同口径扩展** | 保持校验单一入口（I4），seed 播种视图不能被自身校验拦下 | 只改后端（seed 失败）；不校验（脏配置运行时空白） | `routers/views.py`、`cli/seed/views.py` |
| D9 | 批量任务 CLI 入口 | **复用 `cndb sync` 命令组，新增 `batch-kline` 子命令** | 与既有同步运维命令（list/run/tick/preview）同域，帮助与 `--json` 风格一致 | 新建顶层命令（与数据源同步脱节）；独立脚本（不经 CLI 入口与测试） | `cli/sync.py` |
| D10 | 与 ADR 0009 的关系 | **保留 `股市日线` 与 candlestick 视图，本 ADR 只做增量** | 用户确认；0009 的决策仍然有效，示例并存可对照两种形态 | 替换 0009（推翻既有决策，e2e 与文档大面积返工） | 不动 0009 相关代码 |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：示例具备「一只股一行 + 行内全历史 K 线」的最佳实践形态；数据源一次覆盖三市场 / 三周期 / 三复权与 11 个行情字段；部分列 upsert 为多 job 分列写入提供通用能力；`batch-kline` 让全市场标的可分批接入而不压垮单 job；前端 K 线为独立模式，不污染既有 chart 配置。
- **负向**：行内嵌全历史 JSON 使单行体积显著增大；周 / 月派生逻辑在 seed 与前端各一份，需双份单测守口径；新增视图模式需同步 `ViewMode` / `VALID_MODES` / `MODE_VIEW_TYPES` / `MODE_BUTTONS` / 表单选项 / 两处后端校验，存在一致性维护成本；东方财富接口无官方 SLA。
- **风险与缓解**：接口字段或市场前缀变化 → fixture 单测 + 运行期可读错误，不阻塞其他 job；全市场把行体积与请求量放大 → 视图 `filters` 只取自选 + `batch-kline` 分批 ≤100；派生口径漂移 → seed 与前端单测分别钉住 open/close/high/low/volume 口径。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 同步任务框架 / 幂等 / 调度 | `datasource_sync_job` | 复用既有框架，不新增管线 | ADR 0006 |
| 日线明细表与 candlestick 视图 | `股市日线`、`chart_type=candlestick` | 保留，不改 | ADR 0009 |
| 行内 K 线数据形态与视图模式 | 自选股表、`view_type=kline` | 本 ADR 新增 | ADR 0011 |
| 部分列 upsert | `Importer(partial=True)` | 数据源落表专用语义 | ADR 0011（框架能力增量） |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/normalize.py`、`src/cndb/plugins/datasource/providers/eastmoney_kline.py`、`src/cndb/plugins/datasource/providers/registry.py`、`src/cndb/plugins/tables/services/importing/importer.py`、`src/cndb/plugins/tables/services/importing/row_validator.py`、`src/cndb/plugins/tables/routers/views.py`、`src/cndb/cli/seed/stock_quotes.py`、`src/cndb/cli/seed/views.py`、`src/cndb/cli/seed/runner.py`、`frontend/src/pages/grid/views/viewModes.ts`、`frontend/src/pages/grid/views/klineBoard.ts`、`frontend/src/pages/grid/views/KlineView.tsx`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`frontend/src/pages/grid/view-config/CreateEditViewForm.tsx` | `tests/test_datasource_eastmoney_provider.py`、`tests/test_datasource_partial_upsert.py`、`tests/test_kline_view_validation.py`、`tests/test_seed_stock_quotes.py`、`frontend/src/pages/grid/views/klineBoard.test.ts`、`frontend/src/pages/grid/views/KlineView.test.tsx`、`frontend/src/pages/grid/views/viewModes.test.ts`、`frontend/tests/e2e/critical/kline-view.spec.ts` | cad3c568 |
| P1 | 已落地 | `src/cndb/plugins/datasource/providers/eastmoney_symbols.py`、`src/cndb/plugins/datasource/providers/registry.py`、`src/cndb/cli/sync.py`、`src/cndb/cli/seed/stock_quotes.py`、`examples/datasets/工作区-数据源示例/datasource.json` | `tests/test_datasource_eastmoney_symbols_provider.py`、`tests/test_datasource_batch_kline_cli.py`、`tests/test_datasource_cli.py`、`tests/test_seed_datasource.py` | cad3c568 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件。

## 交接（会话结束更新）

- 当前阶段：P0 / P1 全部落地（含需求卡片、ADR、CONTEXT 术语与 CHANGELOG 回填）
- 已完成：部分列 upsert；`eastmoney_kline` / `eastmoney_symbols` provider；normalize `json` 分支；自选股 seed（含 `是否自选` 默认值）；示例视图与 5 个分列 job；两处视图校验；前端 kline 模式（纯逻辑 / 组件 / 配置 schema / 表单）；`cndb sync batch-kline`；后端 / 前端 / e2e 测试；**限流加固**（`api_fetch` 对连接被掐断改用 2s / 8s 长退避并报「目标站可能正在限流本机出口 IP」，5 个 K 线任务 `rate_limit_ms` 500 → 2000 且错峰到 17:30 / 17:45 / 18:00 / 18:15 / 18:30）
- 下一步：在带可用 bash 的环境复跑 `make flow` 覆盖 `tests/test_deploy_scripts.py`，并补跑 `frontend/tests/e2e/critical/kline-view.spec.ts`（本机无可用 bash / 浏览器环境）
- 已知坑：新增视图模式必须同步 `ViewMode`、`VALID_MODES`、`MODE_VIEW_TYPES`、`MODE_BUTTONS`、`CreateEditViewForm.viewTypeOptions`、`getOptionSchema`、后端两处校验与测试；`_seed_stock_quotes` 必须手动建表（自动推断会把 K 线 list 变成 multiselect）；`是否自选` 依赖「创建路径应用字段默认值、更新路径不应用」的既有语义；东方财富接口无 SLA，单测只用 fixture；东财会按**出口 IP** 限流（TLS 后零响应，`RemoteProtocolError`），此时 7 个标的全失败、任务整体 `failed`，属外部因素 —— 调整 `rate_limit_ms` / 错峰只能降低概率，恢复靠冷却或换出口 IP；界面只显示前 3 条失败是 `runner._finalize` 的截断；本机 PATH 上的 Gow bash 无法解析任何脚本（`bash -c true` 也返回 1），`tests/test_deploy_scripts.py` 在 Windows 下 7 例失败，与本次改动无关（deploy 脚本未改动，Linux CI 可跑）
- 最近一次全绿：`make check-fast` 通过（ruff / pyrefly 0 error、前端 typecheck + lint）；`make test` 5095 passed / 1 skipped，仅上述 7 例环境失败（本机 `bash --version` 直接退出 1）；前端定向单测 49 例、`pnpm -C frontend build` 与 `bundle:budget`（主入口 +0.06 KiB、GridPage +1.8%，均在容差内）通过（2026-10-20）
