# ADR 0013: 示例日线两源扩样（tencent / sina，一源一表）

Status: Accepted（2026-10-21 评审通过）
Date: 2026-10-21
Related: `src/cndb/plugins/datasource/providers/base.py`、`src/cndb/plugins/datasource/providers/http_json.py`、`src/cndb/plugins/datasource/providers/sina_kline.py`、`src/cndb/plugins/datasource/providers/tencent_kline.py`、`src/cndb/plugins/datasource/providers/registry.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`scripts/build_example_kline.py`、`examples/datasets/工作区-数据源示例/datasource.json`；上游 ADR [0006](0006-periodic-datasource-sync.md)（框架）、[0009](0009-stock-daily-datasource-example.md)（示例与 candlestick）、[0011](0011-stock-kline-enhanced.md)（eastmoney 与 kline 视图）
需求卡片: `docs/requirements/0013-stock-daily-multi-source-sample.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 示例数据源只保留 tencent / sina 两家 | 新增 `sina_kline`（HTTP）内置 provider（`tencent_kline` 已有）；`datasource.json` 只保留这两家的任务，eastmoney 的 6 个示例任务移除（provider 代码与 `cndb sync batch-kline` 保留）；baostock 不接入（见 C5） |
| C2 | 抓取样本参考 StockMaster 数量和时间范围 | 10 只 A 股 × 2021-10-18 ~ 2026-10-20（单标的约 1,210 根，对齐线上 1,212 根/标的）；示例 CSV 由 `scripts/build_example_kline.py` 联网生成，seed 仍只注入配置 |
| C3 | 一源一表 | 表 `股市日线`（腾讯前复权）/ `股市日线-新浪`（新浪不复权），各表独立 `match_keys=[股票代码,交易日]` |
| C4 | 现有 eastmoney 示例处理 | 「自选股」表与 kline 视图保留为静态示例（无同步任务）；kline 视图能力仍有 e2e 回归覆盖 |
| C5 | baostock 移除 | 不引入 baostock：删掉 provider 代码、可选 extra `market` 与 lock 条目（baostock 会拖入 pandas + numpy，只为一条日线源不值得），主表 `股市日线` 由 tencent 承担 |

## Context

现状逐条核对（以代码为准）。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 内置 provider 只有 `http_json` / `tencent_kline` / `eastmoney_kline` / `eastmoney_symbols` / `rss_atom` | `providers/registry.py` | 无新浪源 | 确认 |
| 2 | 专用 provider 全部覆写了 `parse`，但管线只调用 `fetch_json(plan.config)` 取解析后的数组 | `services/pipeline.py:96`、`providers/http_json.py:57` | **核心缺陷**：`parse` 实际从未执行；腾讯 `{data:{symbol:{qfqday:[…]}}}` 被通用数组探测压成「1 行/请求」，长历史抓取必然失真 | **新增** |
| 3 | 新浪日线响应不带 `symbol`（平铺数组只有 day/open/…） | 实测 | 落表缺幂等键维度，upsert 无法按标的区分 | **新增** |
| 4 | `web.ifzq.gtimg.cn` / `ifzq.gtimg.cn` 对脚本流量返回 WAF 501 挑战页；`proxy.finance.qq.com/ifzqgtimg/...` 不拦 | 实测（2026-10-21） | 腾讯示例任务用旧域名会 100% 失败 | **新增** |
| 5 | 腾讯 `volume` 单位是「手」，新浪是「股」 | 实测（腾讯 32156 手 ≈ 3,215,600 股） | 同口径指标（量比、成交额/量）跨源不可比 | **新增** |
| 6 | 示例样本 3 标的 × 60 交易日（2026-07-01 ~ 09-22）= 180 行 | `examples/…/股市日线.csv` | 时间跨度 3 个月，指标（MA60、年度涨跌）无从演示 | 确认 |
| 7 | `datasource.json` 含 6 个 eastmoney 任务（202 行） | `examples/…/datasource.json` | 与「示例数据源只留两源」冲突 | 确认 |
| 8 | baostock 是纯 Python 库 + 全局 TCP 会话，只提供日线一项能力，却把 pandas / numpy 一并拖进依赖图 | `pyproject.toml`（旧 extra `market`） | 镜像与开发环境为一条示例源付出百 MB 级体积；「缺依赖则提示安装」意味着默认安装永远跑不通这条示例任务 | **新增**（C5） |

设计目标（不变量）：

- **I1 零 schema 变更**：只改 provider 协议与示例配置，不动表 / 列 / 枚举，无 alembic 迁移。
- **I2 单一口径**：日线字段名（`symbol/trade_date/open/high/low/close/volume`）+ 成交量单位（股）在两源一致。
- **I3 幂等**：示例 CSV 预置行与同步行按 `match_keys=[股票代码,交易日]` 合并；`entrant_keys` 与表内代码格式（带前缀）一致。
- **I4 seed 不联网**：示例 CSV 由脚本生成并入库，`cndb seed` 只注入任务配置。
- **I5 兼容旧 provider**：未声明 `uses_custom_parse` 的 provider 行为不变（仍走 `fetch_json` 默认解析）。
- **I6 零可选依赖**：示例数据源只用 HTTP + 标准库，`uv sync` 默认安装即可跑通全部示例任务。

## Decision

### 1. Provider 协议扩展（一处，向后兼容）

| 扩展 | 位置 | 语义 |
|---|---|---|
| `uses_custom_parse` 类属性 | `providers/http_json.py` | 为 True 时 `build_requests` 把 `response_handler` 设成绑定自身 `parse` 的 callable，`fetch_json` 拿到原始文本后交回 provider 解析（修复 Context #2） |

### 2. `sina_kline`（HTTP）

URL 模板 `.../CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=1023`；响应为平铺数组，`parse` 把 `day→trade_date` 并剔除空值行；`default_cursor=none`（接口只给最近 N 根，无区间参数）。

### 3. 管线补标的

`pipeline.fill_entrant(rows, entrant_param, entrant)`：按 `setdefault` 语义补 `symbol`。响应自带标的（腾讯/东财）不受影响，新浪平铺数组得以带幂等键。

### 4. 一源一表与示例规模

| 表 | provider | 复权 | 行数 |
|---|---|---|---|
| `股市日线` | `tencent_kline` | 前复权 | 12,129 |
| `股市日线-新浪` | `sina_kline` | 不复权 | 10,230 |

10 只标的（白酒 ×2 / 银行 ×2 / 保险 / 电池 / 汽车 / 有色 / 电力 / 家电），`entrant_keys` 为带 `sh/sz` 前缀的统一格式。

### 5. 示例数据生成

`scripts/build_example_kline.py`：按 provider 真实抓取 → 中文列映射 → 区间裁剪 + 幂等去重 → UTF-8 BOM CSV。抓取为空时保留原文件（防 WAF / 断网把样本清空）。腾讯按 440 自然日分片（接口语义是「截至 end 的最近 320 根」，窗口须 ≥ 320 天）。

### 6. 腾讯口径修正

- `volume` 在 `parse` 阶段由「手」×100 换算为「股」（I2）。
- 默认 URL 模板改 `proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get`（Context #4）。

### 7. 示例配置调整

`datasource.json` 2 个任务（17:30 / 17:45 错峰）；`views.json` 两表各配「全部」+ 单标的 K 线，主表另有放量日 / 最近一年 / 成交量图 / 量价散点图；`fields.json` 两表必填 `股票代码`+`交易日`；`analytics.json` 三个模板 `limit` 1000 → 3000 以覆盖更长样本，量价模板的「区间累计成交额」改为「区间累计成交量」（两源都不提供成交额列，I2 只保 6 个价量字段）。

## 边界与例外

1. **复权口径差异**：主表是腾讯前复权、对照表是新浪不复权，跨表只能看形态不看绝对值；表名即源名，避免误用。
2. **新浪时间范围更短**：只给最近 1,023 根（2022-07 起），无法与主表的 5 年完全对齐，属接口能力边界。
3. **腾讯 WAF**：脚本流量触及阈值会返回 501 挑战页；示例任务 `rate_limit_ms=2000`，回填失败留部分行并保留原 CSV。
4. **自选股表无同步任务**：`kline` 视图与 `batch-kline` CLI 仍可用（后者按需自建 eastmoney job）。标的集合收敛为与两源一致的 10 只 A 股（原 A/H/US 7 只里的港股、美股随东财任务一并移除，`是否自选` 留一只 false 供筛选演示）。

## 迁移

无 alembic 迁移（无 schema 变更）。`cndb seed` 全量重建后两张表与两个任务就位；旧示例的 6 个 eastmoney 任务与 baostock 任务随 seed 重建消失。

## 前端

无改动。两表复用既有 grid / candlestick / bar / scatter 视图能力。

## 测试清单

**判定层（单测）**：`sina_kline` 平铺数组解析 / 空日剔除 / 非法响应报错 / 默认类型归一；`uses_custom_parse` 注入 handler（`http_json` 不注入）；`fill_entrant` 三种情形。

**接口 / seed**：真实 `datasource.json` 两任务结构自洽（provider ↔ 表 ↔ CSV 表头 ↔ 幂等键 ↔ 错峰）。

**回归**：`tests/test_datasource_providers.py`（腾讯 volume 手→股）、`test_backup_seed_roundtrip.py`、`test_kline_view_validation.py`、`test_datasource_batch_kline_cli.py` 全绿。

## 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | provider 协议扩展（uses_custom_parse）+ `sina_kline` + 注册 | 中（触及既有 5 个 provider 的解析路径） |
| **P1** | 示例数据生成脚本 + 两表 CSV + datasource/views/fields/analytics 重写 | 中（外网抓取受 WAF 限流） |
| **P2** | 单测 / seed 断言 / 文档与交接回填 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 两源落表 | 一源一表 | 前复权 / 不复权混写会互相覆盖；表名即源名，误用成本低 | 同表多复权列（列数膨胀，仍需映射隔离）；同表混写（后跑覆盖先跑） | `datasource.json`、两张示例 CSV |
| D2 | 专用 provider 的 `parse` 未被调用 | 新增 `uses_custom_parse` → 注入 `response_handler` | 复用 `fetch_json` 的重试 / SSRF / 编码能力，只替换解析段 | 管线改为自己发请求并调 `parse`（重复实现重试与 SSRF 防护） | `http_json.py`、5 个 provider |
| D3 | 新浪无标的列 | 管线 `fill_entrant` 按 entrant 补齐 | 通用能力，未来同类源同样受益；`setdefault` 不覆盖响应自带值 | 在 sina provider 内拼 symbol（parse 拿不到 entrant，需改协议签名） | `pipeline.py` |
| D4 | 腾讯成交量单位 | parse 阶段手 → 股（×100） | 两源同口径（I2），落表后指标可直接比较 | 表内保留手并改列名（跨表口径不一致） | `tencent_kline.py` |
| D5 | 腾讯域名 | 默认模板改 `proxy.finance.qq.com` | 实测 `web.ifzq` / `ifzq` 返回 WAF 501，proxy 域名同一数据不拦 | 保持旧域名 + 重试（WAF 挑战页无法通过重试绕过） | `tencent_kline.py` |
| D6 | eastmoney 示例任务 | 移除 6 个任务，保留 provider 与 batch-kline CLI、自选股表与 kline 视图 | 需求只要求示例数据源为两源；kline 视图能力需要静态载体做 e2e 回归 | 删除自选股表与 kline 视图（丢失 0011 能力的示例与回归覆盖） | `datasource.json`、`views.json` |
| D7 | 示例数据来源 | 脚本联网生成后入库，seed 不联网 | 保持 I4；样本可复现、可重跑 | seed 时联网抓取（CI / 离线部署不可用） | `scripts/build_example_kline.py` |
| D8 | baostock 去留 | 整源移除（provider + extra `market` + lock 条目） | 只为一条日线源付出 pandas / numpy 依赖，且默认安装跑不通；腾讯已覆盖前复权长历史 | 保留为可选 extra（I6 被破坏，生产镜像仍需额外开关）；包一层本地代理（多进程，体积照旧） | `registry.py`、`pyproject.toml`、`uv.lock` |

## Consequences

- **正向**：示例样本从 180 行 / 3 个月扩到约 2.2 万行 / 5 年，MA60、年度涨跌、量价关系等模板有真实形态；两源对照可验证「多源写不同表」的完整链路；修复了专用 provider 的 `parse` 从未执行的存量缺陷（腾讯 / 东财 / RSS 均受益）；依赖图回到纯 HTTP + 标准库（I6），`uv sync` 即可跑通全部示例。
- **负向**：示例表不再有 `成交额` 列（两源都不提供），量价模板改用成交量；仓库仍保留约 1.5MB 示例 CSV。
- **风险与缓解**：外网抓取受 WAF / 频率限制 → 脚本按失败保留原文件、任务侧 `rate_limit_ms` 与错峰调度；两源复权算法差异 → 一源一表 + 命名隔离 + 文档明示。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 同步框架 / 游标 / 调度 | `datasource_sync_job` | 任务声明与幂等落表 | ADR 0006 |
| 示例与 candlestick 视图 | `views.json`、`view_options.chart_type` | K 线/成交量/量价视图口径 | ADR 0009（本 ADR 只换数据源与样本量） |
| 行内 K 线视图与多周期复权 | `自选股` 表、`view_type=kline` | 保留为静态示例 | ADR 0011 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/datasource/providers/base.py`、`src/cndb/plugins/datasource/providers/http_json.py`、`src/cndb/plugins/datasource/providers/sina_kline.py`、`src/cndb/plugins/datasource/providers/tencent_kline.py`、`src/cndb/plugins/datasource/providers/registry.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`pyproject.toml` | `tests/test_datasource_sina.py`、`tests/test_datasource_providers.py` | 984097c3 |
| P1 | 已落地 | `scripts/build_example_kline.py`、`examples/datasets/工作区-数据源示例/datasource.json`、`examples/datasets/工作区-数据源示例/views.json`、`examples/datasets/工作区-数据源示例/fields.json`、`examples/datasets/工作区-数据源示例/analytics.json`、`examples/datasets/工作区-数据源示例/股市日线.csv`、`examples/datasets/工作区-数据源示例/股市日线-新浪.csv` | `tests/test_seed_datasource.py` | 5fcc5a6c |
| P2 | 已落地 | `docs/adr/0013-stock-daily-multi-source-sample.md`、`docs/requirements/0013-stock-daily-multi-source-sample.md`、`CHANGELOG.md`、`CONTEXT.md`、`docs/adr/README.md` | `tests/test_seed_datasource.py` | 5fcc5a6c |

## 交接（会话结束更新）

- 当前阶段：P0-P2 全部落地
- 已完成：provider 协议扩展（uses_custom_parse）、`sina_kline`、两源示例数据（12,129 / 10,230 行）、示例配置重写、单测与回归；baostock 已整源移除（依赖图不再含 pandas / numpy）
- 下一步：如需「多源写同一张表做逐日对账」，按 D1 另立 ADR（跨源价格差异需要口径归一策略）
- 已知坑：腾讯 WAF 会拦脚本流量（当前用 `proxy.finance.qq.com`）；新浪只给最近 1,023 根；主表无成交额列；两源复权口径不同，跨表不比绝对值
- 最近一次全绿：`python -m pytest -m "not slow"`（2026-10-21）
