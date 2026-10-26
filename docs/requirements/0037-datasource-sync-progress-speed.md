# 需求卡片：数据源同步拉取提速与运行进度

- 编号：0036（与 ADR `docs/adr/0036-*.md` 同号）
- 来源 / 提出人：用户
- 日期：2026-10-26
- 关联 ADR：`docs/adr/0037-datasource-sync-progress-speed.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 数据源同步功能，拉取股市日线的速度显著慢于~/stock-strategy项目的数据校核-智能同步模块，且不能像其一样能够在拉取过程中显示进度。请修复此问题。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「拉取股市日线的速度显著慢于…数据校核-智能同步模块」 | 全市场日线回补（7289 标的 / 每轮约 21,867 请求、5000 行一批）的落库吞吐提升至少 1.8 倍；瓶颈定位到落库路径的匹配查询与逐行 UPDATE 后改为批量执行，抓取并发与限速语义不变 | `plugins/tables/services/core/records.py`、`plugins/tables/services/importing/importer.py` | 同数据 5000 行批次的 `analyze+execute` 基准对比；`tests/test_import_pipeline.py`、`tests/test_datasource_runner_streaming.py` |
| C2 | 「不能像其一样能够在拉取过程中显示进度」 | 运行中可查询进度：`datasource_sync_run` 暴露 `progress_total` / `progress_done` / `progress_entrant`，并实时回写 `fetched`；前端在运行期间每 2 秒轮询运行历史展示「已完成/总请求 + 当前标的 + 已写入行数 + 百分比」 | `plugins/datasource/{models,schemas,routers,services}`、`frontend/src/pages/datasource/` | `tests/test_datasource_api.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` |
| C3 | 「请修复此问题」（可用性） | 「立即运行」不再因前端 30 秒请求超时被误判为失败：端点立即返回运行中记录（202 语义），实际执行转后台线程并沿用租约互斥与批间续期；前端据运行历史轮询收尾并提示最终结果 | `plugins/datasource/routers/sync_jobs.py`、`plugins/datasource/services/runner.py` | `tests/test_datasource_api.py`、`tests/test_datasource_runner.py` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 幂等匹配查询 | `src/cndb/plugins/tables/services/core/records.py:883` | 每 500 键拼一个巨型 `OR (k1 AND k2 …)`，5000 行约 0.54s |
| 2 | 批量更新 | `src/cndb/plugins/tables/services/core/records.py:968` | 逐行 `UPDATE` 且每行归一两次，5000 行约 1.1s |
| 3 | 运行入口 | `src/cndb/plugins/datasource/routers/sync_jobs.py:312` | 同步执行，前端 axios 超时 30s，长任务被判失败 |
| 4 | 运行记录 | `src/cndb/plugins/datasource/models.py:136` | 只有终态计数，无运行中进度 |
| 5 | 前端运行交互 | `frontend/src/pages/datasource/DatasourcePage.tsx:133` | 仅按钮 loading，无进度与轮询 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- 无（用户要求直接修复；方案取「安全批量化 + 同步转后台 + 轮询进度」）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认
