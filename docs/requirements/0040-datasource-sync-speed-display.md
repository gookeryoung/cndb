# 需求卡片：数据源同步实时写入速度与 stock-strategy 对标

- 编号：0040（与 ADR `docs/adr/0040-*.md` 同号，卡片存 `docs/requirements/0040-<topic>.md`）
- 来源 / 提出人：用户
- 日期：2026-10-26
- 关联 ADR：`docs/adr/0040-datasource-sync-speed-display.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请在同步过程中实时提示写入速度信息。并且本项目需要和~/stock-strategy对比，同步速度方面是否还存在差距。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「同步过程中实时提示写入速度信息」 | 运行中前端持续（沿用 2s 轮询）显示「已写入行数 · 行/秒 · 已用时」；行/秒与已用时由服务端按运行记录计算并随运行历史接口返回，前端不自行推算时钟差；运行结束后展示最终值，未开始落库时显示「准备中」 | `plugins/datasource/{schemas,routers}`、`frontend/src/{api,pages}/datasource/` | 接口用例（运行中 / 已结束 / 失败三种状态）+ 前端组件用例 + 既有数据源页面用例 |
| C2 | 「和~/stock-strategy对比，同步速度方面是否还存在差距」 | 在同一台机器、同一数据源口径（腾讯日线）下量化对比抓取吞吐（请求/秒）、落库吞吐（行/秒）与端到端耗时；**同步速度以端到端同口径耗时为验收口径**（不以参考项目无逐格校验的裸 SQL 写入作为对标口径）；对比结论与基准数据写入 ADR「行业对照」 | `docs/adr/0040-*.md` | 基准数据归档在 ADR；需求方已确认「完全补齐」方向 |
| C3 | 「请完全补齐差距」（需求方已明确要求补齐，且授权按需增加库依赖） | 端到端同口径耗时补齐到参考项目水平（约 192s / 3.83M 行），落地：① 抓取层单次运行共享 HTTP 客户端（SSRF / 超时 / 重试 / 重定向语义不变）；② 腾讯回补任务限速 50 → 10ms（上限 100 请求/秒）；③ 落库层「一次校验、一次归一」：跳过同步链路无消费方的预览 / 字段级 diff，并复用校验产出的归一值，不再第二次逐格归一（逐格校验不放宽）；验收：抓取 ≥85 请求/秒、落库 ≥25k 行/秒、端到端 ≤192s；新增依赖仅在现有栈无法达标时启用（用户已授权，本方案评估为不需要） | `core/http.py`、`plugins/datasource/services/pipeline.py`、`plugins/tables/services/importing/importer.py`、`plugins/tables/services/core/records.py`、`examples/datasets/工作区-数据源示例/datasource.json` | 前后基准对比 + 归一/预览等价性用例 + 全量既有测试全绿 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 运行记录对外字段 | `src/cndb/plugins/datasource/schemas.py:126` | 只有 `duration_ms` 与累计计数，无运行中耗时 / 速度 |
| 2 | 前端运行中进度 | `frontend/src/pages/datasource/DatasourcePage.tsx:376` | 只显示请求数、当前标的、已写入行数 |
| 3 | HTTP 传输层 | `src/cndb/core/http.py:581` | 每次 `fetch_json` 新建并关闭 Client，TLS 连接不复用 |
| 4 | 示例任务限速 | `examples/datasets/工作区-数据源示例/datasource.json:28` | `rate_limit_ms=50`，即 20 请求/秒硬上限 |
| 5 | 落库固定开销 | `src/cndb/plugins/tables/services/importing/importer.py:226` | 每批构建预览与字段级 diff，同步链路不消费 |
| 6 | 参考项目实时速度文案 | `~/stock-strategy/src/stock_strategy/core/sync.py:690` | 模块级状态里直接带「只/秒」 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- 已确认：需求方要求「完全补齐差距」，允许按需增加库依赖；C2 的对比结论与 C3 的补齐口径见 ADR 0040「行业对照」。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-26：完全补齐、可加依赖）
