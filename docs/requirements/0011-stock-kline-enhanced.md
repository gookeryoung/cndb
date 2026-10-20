# 需求卡片：股市 K 线增强（多周期复权、全历史字段与行内 K 线视图）

- 编号：0011（与 ADR `docs/adr/0011-*.md` 同号）
- 来源 / 提出人：用户
- 日期：2026-10-20
- 关联 ADR：`docs/adr/0011-stock-kline-enhanced.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 针对更全面的股市K线的获取和更接近最佳实践的视图实现，制定开发计划并实施。典型示例需要实现一只股一行数据，并且K线图能够按照选中的行切换显示。

## 澄清结论（用户确认）

| # | 澄清项 | 结论 |
|---|---|---|
| Q1 | 视图形态 | **单表内嵌 K 线数据**：一只股一行，多周期 / 多复权 K 线序列以 JSON 字段存在行内，不新建 K 线明细子表 |
| Q2 | 获取范围 | **多周期 + 复权 + 全历史**、**更全的行情字段**、**更多标的与全市场**（三项均选） |
| Q3 | 与既有示例的关系 | 保留 `股市日线` 表与 `chart` candlestick 视图（ADR 0009），新方案只做增量，不改既有决策 |

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 更全面的股市K线的获取 | 新增 `eastmoney_kline` provider：代码前缀换算 `secid`（A 股 / 港股 / 美股），URL 的 `klt` 控制日 / 周 / 月，`fqt` 控制前 / 后 / 不复权，`beg=0&lmt=100000` 覆盖全历史；一只股票输出一行 | `src/cndb/plugins/datasource/providers/eastmoney_kline.py`、`providers/registry.py` | 固定 JSON fixture 单测覆盖 A/HK/US、空数据、字段缺失 |
| C2 | 更全的行情字段 | `fields2=f51..f61` 全部解析为 11 个行情字段（日期、开、收、高、低、成交量、成交额、振幅、涨跌幅、涨跌额、换手率），并给出最新交易日 / 最新价 / 涨跌幅 / 成交量 / 成交额快照 | 同上、`services/normalize.py` | fixture 解析断言 11 字段与最新快照 |
| C3 | 一只股一行数据 | 新增示例表 **自选股**：一标的一行，K 线序列存 `json` 列（日线前 / 后 / 不复权 + 周线 / 月线前复权），手工建表避免自动推断成 multiselect | `src/cndb/cli/seed/stock_quotes.py`、`examples/datasets/工作区-数据源示例/自选股.json` | `cndb seed` 后表字段类型为 `json`，7 只示例标的各一行 |
| C4 | K线图能够按照选中的行切换显示 | 新增 `view_type=kline`：左侧标的分列表（代码 / 名称 / 最新价 / 涨跌幅 / 成交量、搜索、单选），右侧 ECharts 双 grid（价格 + 成交量）；选中行切换序列，支持周期 / 复权 / MA / 成交量开关，红涨绿跌 | `frontend/src/pages/grid/views/klineBoard.ts`、`KlineView.tsx`、`GridPage.tsx`、`viewModes.ts` | 纯逻辑单测 + 组件测试 + e2e 点击第二只股票断言图表标题变化 |
| C5 | 典型示例 | 「数据源示例」工作区落地端到端示例：`自选股.json` 元数据 + `股市日线.csv` 派生 K 线、`views.json` 的 kline 视图（`filters: 是否自选=true`）、`datasource.json` 的 5 个 `eastmoney_kline` 分列任务（日线三口径 + 周 / 月前复权） | `src/cndb/cli/seed/runner.py`、`examples/datasets/工作区-数据源示例/` | seed 测试：建表 / 字段类型 / 周月派生 / datasource job 结构与幂等 |
| C6 | 更多标的与全市场 | 新增 `eastmoney_symbols` provider（行情列表分页，A 股 / 港股 / 美股 / 全部）写入自选股表，新行 `是否自选=false`；新增 `cndb sync batch-kline` 按批（≤100 只）创建 / 更新 `eastmoney_kline` 任务，支持市场过滤、错峰调度、幂等更新、`--prune`、`--dry-run` | `src/cndb/plugins/datasource/providers/eastmoney_symbols.py`、`src/cndb/cli/sync.py` | provider 分页 / 市场换算单测；CLI 分批、只取自选、上限收敛、幂等裁剪单测 |
| C7 | 多 job 分列写同一行 | 数据源落表链路支持**部分列 upsert**：只更新本次 job 实际提供的列，未提供的 JSON 列保持原值；默认导入语义不变 | `tables/services/importing/{row_validator,importer}.py`、`datasource/services/write.py` | 先日线 qfq → 再周线 qfq → 再日线 hfq，断言三列都保留 |
| C8 | 健壮性与测试 | provider 单测全部用固定 fixture、不依赖外网；前端 JSON 解析失败不崩溃、缺列落空态不静默回退；后端 / 前端 / e2e 三层覆盖 | `tests/`、`frontend/src/pages/grid/views/*.test.*`、`frontend/tests/e2e/critical/kline-view.spec.ts` | 定向测试全绿，`make check-fast` / `make test` 通过 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 数据源落表对未提供列填空 / 显式清空 | `src/cndb/plugins/datasource/services/write.py`、`tables/services/importing/importer.py` | 多 job 分列写同一行会互相清空，需 partial 语义 |
| 2 | 归一化不支持 `json` 目标类型 | `src/cndb/plugins/datasource/services/normalize.py` | K 线数组需序列化为字符串落 Text 列 |
| 3 | 内置 provider 只有 http_json / tencent_kline / rss_atom | `src/cndb/plugins/datasource/providers/registry.py` | 需新增 eastmoney_kline / eastmoney_symbols |
| 4 | 视图字段校验白名单 | `src/cndb/plugins/tables/routers/views.py`、`src/cndb/cli/seed/views.py` | 新字段键需两处同口径放行 + 语义校验 |
| 5 | 前端视图模式枚举 / 按钮 / 配置 schema | `frontend/src/pages/grid/views/viewModes.ts`、`GridPage.tsx`、`view-config/` | 新增模式需同步 6 处 + 测试（历史坑） |
| 6 | 示例无「一只股一行」形态的表 | `examples/datasets/工作区-数据源示例/` | 需新增自选股表 seed 与视图 / 数据源配置 |
| 7 | 全市场标的数千，单 job 请求量过大 | `src/cndb/cli/sync.py` | 需标的发现 provider + 分批任务 CLI |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 视图形态：**单表内嵌 K 线 JSON**（用户 2026-10-20 确认），不建 K 线明细子表。
- [x] 获取范围：多周期 + 复权 + 全历史、更全行情字段、更多标的与全市场三项全选（用户确认）。
- [x] 周期 / 复权落库范围：日线三口径 + 周 / 月前复权落库，周 / 月后复权与不复权由前端从日线派生，避免行膨胀。
- [x] 全市场 K 线：不把全市场塞进 K 线视图，视图 `filters` 只取自选；全市场经 `batch-kline` 分批建任务。
- [x] 与 ADR 0009 的关系：保留 `股市日线` 与 candlestick 视图，ADR 0011 只做增量。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-20）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
