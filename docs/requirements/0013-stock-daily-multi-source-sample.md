# 需求卡片 0013：示例日线两源扩样（tencent / sina）

Status: Accepted
Date: 2026-10-21
ADR: [0013](../adr/0013-stock-daily-multi-source-sample.md)

## 需求原句

> 示例数据源采用 baostock，tencent，sina，。抓取样本参考 https://stock.gookeryoung.cn 数量和时间范围，当前样本太少，时间太窄。
>
> 后续变更：把 baostock 移除，避免镜像膨胀。

## 约束（评审确认）

| # | 约束 | 确认结果 |
|---|---|---|
| C1 | 示例数据源只保留 tencent / sina 两家 | 移除 eastmoney 的 6 个示例同步任务（provider 代码与 batch-kline CLI 保留）；baostock 整源移除（C5） |
| C2 | 样本数量与时间范围对齐 StockMaster 线上 | 10 只 A 股 × 近 5 年（2021-10-18 ~ 2026-10-20），单标的约 1,214 根 |
| C3 | 两源落表方式 | 一源一表（避免前复权 / 不复权口径互相覆盖） |
| C4 | 现有 eastmoney 示例（自选股表 + kline 视图） | 表与 kline 视图保留为静态示例，不再挂同步任务 |
| C5 | baostock 移除 | provider 代码、可选 extra `market` 与 lock 条目一并删除（baostock 会拖入 pandas + numpy，只为一条日线源不值得），同步任务改由 tencent 承担主表 |

## 参考口径（StockMaster 线上实测，2026-10-21）

| 指标 | 线上值 |
|---|---|
| 标的数 | 7,778（含指数） |
| 日线总行数 | 1,890,227 |
| 单标的根数 | 1,212 ~ 1,214（约 5 年） |
| 最新交易日 | 2026-10-16 |

cndb 示例改造前：3 标的 × 60 交易日（2026-07-01 ~ 2026-09-22）= 180 行。

## 验收

- 两张示例表：`股市日线`（腾讯前复权，12,129 行）/ `股市日线-新浪`（10,230 行）
- 两个同步任务随 `cndb seed` 注入且 `enabled=true`，一源一表
- 单测 / seed 配置校验 / 全量后端测试全绿
- 示例数据可由 `scripts/build_example_kline.py` 复现
