# 需求卡片：数据源同步对齐 lmstock 机制与典型示例精简

- 编号：0053（与 ADR `docs/adr/0053-*.md` 同号）
- 来源 / 提出人：用户（2026-10-27 会话，前序分析：cndb 同步实测 / lmstock 机制对照）
- 日期：2026-10-27
- 关联 ADR：`docs/adr/0053-datasource-sync-lmstock-alignment.md`（Proposed，待评审）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请参考该机制完善设计，并且在典型示例的数据表和数据源同步示例中，仅保留与之相同的做法，其余内容移除。

（前一轮被中断消息的变体，语义更具体，一并留痕：）

> 请参考该机制完善设计，并且在典型示例的数据表和数据源同步示例中，仅保留与之相同的做法，其余慢速或者重复的内容移除。

「该机制」指 lmstock 同步机制，经本轮分析确认的四个要点（证据见前序分析结论）：

1. **快照直写当日**：全市场当日增量走分页快照接口（~80 请求）+ 一次批量落库，不逐标的抓 K 线；
2. **缺口驱动**：库内已到最新水位的标的不重复请求，逐标的抓取只兜真正缺的；
3. **单轮翻页回补**：历史回补以水位为锚在一轮内向前翻页，直至目标起点 / 空页即停，不靠多轮水位推进；
4. **直连主机 + failover**：优先直连 `web.ifzq.gtimg.cn`（浏览器 UA / Referer），失败自动切换备用主机；回补任务不按板块拆分（全市场一条）。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「参考该机制完善设计」 | `backfill_date` 游标新增「单轮翻页到顶」声明能力（request_spec 新声明键）：一轮运行内以标的水位为起点、end 锚点逐页向前翻，覆盖 `backfill_start` 或遇不足一页即停；落库沿用流式幂等 upsert，不新增领域语义 | `plugins/datasource`（`providers/http_json.py` build_requests、`services/runner.py` 水位注入） | 判定层单测（假 fetch）：一轮生成多页请求、水位一轮推到 `backfill_start`；不声明新键时行为不变 |
| C2 | 「参考该机制完善设计」 | `http_json` 抓取支持**多主机 failover**：request_spec 声明 `url_hosts` 列表，单请求按序尝试主机，网络错误 / 限流切换下一主机，全失败才算该请求失败；自定义请求头沿用既有 `FetchConfig.headers`（已支持，`core/http.py:581-582`），每主机过 `validate_url` | `core/http.py` fetch_json、`plugins/datasource/providers/http_json.py` | 判定层单测：首主机失败切换次主机成功；全失败仅记 1 条 failure；SSRF 校验逐主机生效 |
| C3 | 「仅保留与之相同的做法」 | 示例保留「股票清单（全市场快照）」分页任务（lmstock 同款新浪分页快照），作为标的池与当日数据来源 | `examples/datasets/工作区-数据源示例/datasource.json` | seed 结构测试 |
| C4 | 「仅保留与之相同的做法」 | 示例保留「股市日线（新浪快照 · 当日）」任务：快照直写当日 K 线（= lmstock `update_snapshot` 做法），当日增量不逐标的抓 K 线 | 同上 | seed 结构测试 |
| C5 | 「其余慢速或者重复的内容移除」 | 三条按板块拆分的腾讯回补任务（主板创业板 / 科创板 / 基金ETF）**合并为一条全市场回补任务**（`entrant_source=股票清单`，不做板块前缀过滤），移除板块拆分 | 同上 | seed 结构测试锁 1 条回补任务 |
| C6 | 「其余慢速…的内容移除」 | 回补任务改配 C1「单轮翻页到顶」，消除「每轮每标的只推进 800 根、补到 2016 需 ~3 轮」的慢速多轮水位推进 | 同上 | seed 结构测试断言新声明键存在 |
| C7 | 「参考该机制完善设计」 | 回补任务主机改**直连 `web.ifzq.gtimg.cn`**（`url_hosts=[直连, proxy.finance.qq.com]` + 浏览器 UA / Referer `gu.qq.com`），proxy 域名降级为 failover（对 ADR 0033 Context#7「web.ifzq WAF 挑战」记录的修正——lmstock 已验证带浏览器头可用） | 同上 | seed 结构测试断言 url_hosts；真源直连连通性人工复验（演示环境） |
| C8 | 「典型示例的数据表…仅保留」 | 示例工作区数据表保留「股票清单」「股市日线」两张（= lmstock stocks/bars 两表口径）；非股市链路（天气每日 / 行业政策与合规台账 / 国际形势发展动态 3 表 + 2 条 llm_prompt 任务）**保留**（未决问题 1 结论） | `examples/datasets/工作区-数据源示例/`（csv / datasource.json / fields.json / views.json / analytics.json） | seed 结构测试 |
| C9 | 「仅保留与之相同的做法」（未决问题 2） | 回补任务 `url_template` 改为**不复权**（去掉 `fq=qfq`），与快照任务同口径 | `examples/datasets/工作区-数据源示例/datasource.json` | seed 结构测试断言无 `fq=qfq` |
| C10 | 「仅保留与之相同的做法」（未决问题 2） | 「股市日线」表**单行单口径**：幂等键去掉「来源」；删除「来源」「复权方式」两列；移除按来源分组的视图；快照与回补命中同一行时按幂等键覆盖（快照兜当日、腾讯补历史） | `examples/.../fields.json`、`views.json`、`datasource.json`、表幂等键配置 | seed 结构测试：字段清单无两列、幂等键不含来源；判定层单测：两源同日同键覆盖为 1 行 |
| C11 | 「参考该机制」（未决问题 3） | `backfill_start` 不再作为必须补满的硬目标；一轮以标的水位为锚向前翻页，**补到上市首日或不足一页即停** | 同 C1 | 判定层单测：翻到空页即终止、水位推到上市首日 |
| C12 | 「参考该机制」（未决问题 4） | 示例回补任务 `url_hosts` 首选直连 `web.ifzq.gtimg.cn` + 浏览器 UA / Referer `gu.qq.com`，proxy 域名作 failover；P2 真源复验后若直连仍被挑战，仅调换示例中 hosts 顺序 | `examples/.../datasource.json` | seed 结构测试断言 url_hosts 顺序；P2 人工真源复验 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | `backfill_date` 每轮每标的只推进一页（水位 −1 天锚点注入；达标标的零请求） | `src/cndb/plugins/datasource/services/runner.py:638-648`、`:496` | C1 需在 build_requests / 水位注入处扩展「一轮多页向前翻」 |
| 2 | 抓取单 URL、无多主机 failover；`FetchConfig.headers` 已支持自定义头 | `src/cndb/core/http.py:214`、`:575-582`（`validate_url` + allow_hosts） | C2 只需加主机列表与切换逻辑 |
| 3 | 示例 7 条任务：2 llm_prompt + 5 http_json（含 3 条板块回补） | `examples/datasets/工作区-数据源示例/datasource.json` | C3-C7 的主战场 |
| 4 | seed 按 `(工作区, 名称)` 幂等只增不删 | `src/cndb/cli/seed/datasource.py:40-117` | 合并/移除任务对存量库不生效，需人工清理（ADR 0033 C4 同口径） |
| 5 | seed 结构测试锁「7 条任务」条数与板块任务断言 | `tests/test_seed_datasource.py:170-199` | 任务增删后须同步改断言 |
| 6 | 双源同表口径：幂等键含「来源」（ADR 0033 D5）、「复权方式」列（D9）、来源分组视图 | `examples/datasets/工作区-数据源示例/datasource.json`、`views.json` | lmstock 是单序列单源口径（当日=快照、历史=腾讯，同日不并存）；见未决问题 2 |
| 7 | 腾讯接口走 proxy 域名的 WAF 记录 | ADR 0033 Context#7（`web.ifzq` 对脚本流量有 WAF 挑战） | C7 与既有记录冲突，lmstock 实测证明带浏览器 UA/Referer 可用，需真源复验后修正口径 |
| 8 | 帮助文档示例清单与 CHANGELOG 口径 | `src/cndb/plugins/help/services/examples.py`、`CHANGELOG.md` | 示例内容增删后须同步 |
| 9 | 复权口径：回补任务现取前复权（`fq=qfq`），快照任务为不复权 | `examples/datasets/工作区-数据源示例/datasource.json`（url_template） | lmstock 存不复权 + 复权因子本地换算；cndb 无该能力，见未决问题 2 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题（需求方已于 2026-10-27 逐项拍板）

- [x] **1. 「其余内容移除」的边界** → **保留**：非股市链路内容（天气每日、行业政策与合规台账、国际形势发展动态 3 张表 + 2 条 llm_prompt 任务）不移除——它们是 llm_prompt 示例，不属于「股市同步链路」的慢速 / 重复项。仅重构股市链路（C3-C7）。
- [x] **2. 双源同表语义** → **按 lmstock 单序列**：当日 = 快照、历史 = 腾讯，同日**一行**、**同口径不复权**。落地为：回补任务改取不复权（`fq=` 空）；幂等键**去掉「来源」**；删除「来源」「复权方式」两列；移除按来源分组的视图与交叉比对演示语义。
- [x] **3. `backfill_start` 深度** → **参考 lmstock**：不再以 `2016-01-01` 为必须补满的目标；单轮以水位为锚向前翻页，**补到上市首日或空页即停**；首灌「一页 800 根」已满足日常可用，更深历史随单轮翻页自然到位（C1 保证一轮内翻到底）。
- [x] **4. 直连主机默认值** → **参考 lmstock**：`url_hosts` 首选直连 `web.ifzq.gtimg.cn`（浏览器 UA + Referer `gu.qq.com`），`proxy.finance.qq.com` 作为 failover；P2 真源复验后若直连仍被挑战，则仅在示例数据中调换 hosts 顺序，不改引擎能力。
- [x] **5. 存量库清理口径** → **手动清理**：存量实例中的旧任务（3 条板块回补）与旧列由需求方手动处理，seed 保持「只增不删」（沿用 ADR 0033 C4 口径）。
- [x] **6. 「股票清单」任务** → **按建议**：分页快照已与 lmstock 一致，按现状保留，不新增能力。

> 以上 6 项为需求确认结论，ADR「决策记录」引用本清单，不重复原文。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
