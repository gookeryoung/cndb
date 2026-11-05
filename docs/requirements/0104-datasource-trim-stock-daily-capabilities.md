# 需求卡片：数据同步裁剪股市日线专用能力（简化通用管线）

- 编号：0104（与 ADR `docs/adr/0104-*.md` 同号，卡片存 `docs/requirements/0104-<topic>.md`）
- 来源 / 提出人：用户（「请清理和简化用于同步股票日线的复杂数据同步代码」，方向已拍板：删掉不再用的能力）
- 日期：2026-11-05
- 关联 ADR：0104（立项后回填）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请清理和简化用于同步股票日线的复杂数据同步代码。

用户已在方案沟通中拍板方向：**删掉不再用的能力**（并清理对应 ADR 与测试），不做纯内部重构、不回退到最小玩具管线。

## 背景与盘点结论（提出人确认的事实基础）

股市日线示例工作区（双源任务：新浪快照 + 腾讯日线回补）已随 `f732a77f` 整体移除；当前仓库内唯一的同步任务配置是 `examples/datasource/weather-open-meteo.json`（`record_mode=columns` + `cursor=date`），另有 `llm_prompt` provider 依赖管线内核（模板 / 标的 / 流式）。为承载腾讯日线响应形态而引入的一批声明能力自此**无任何配置声明**，仅剩各自的单测在维护它们。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 清理…不再用的能力 | 删除无任何配置声明的股市日线专用声明能力：`record_mode="rows_array"` 位置索引解析、`row_defaults` 行级常量列、`row_filter` 行过滤、`field_mapping.scale` 缩放、`url_hosts` 主机回退 | `providers/base.py`、`providers/http_json.py`、`services/normalize.py`、`services/pipeline.py`、`services/runner.py` | 全仓 grep 无残留声明键；`make test` 通过 |
| C2 | 清理…不再用的能力 | 删除 `cursor="backfill_date"` 游标策略、单轮翻页（multi-pass）与按标的水位断点续跑（`entrant_state` 回补水位） | `services/cursor.py`、`services/entrant_state.py`、`services/runner.py`、`providers/base.py` | 同上 |
| C3 | 清理…不再用的能力 | 删除 `request.workers` 并发分组执行（管线回归串行；`llm_prompt` 强制 1 的分支随之消失）；`rate_limit_ms` 串行限速保留（用户可见 API 字段，实现随之简化） | `services/pipeline.py` | 同上 |
| C4 | 简化…数据同步代码 | 保留仍在用的能力与口径不变：`record_mode` 的 `rows` / `columns`、`data_path` 模板、`fill_entrant`、流式落表（`on_batch`）、请求级进度、push 方向（ADR 0099）、`date` / `none` / `key_set` 游标、幂等 upsert | 全部同步模块 | 既有保留能力测试全绿；weather 示例任务可正常运行 |
| C5 | 清理…（需求移除流程） | 按 design.md「需求移除 / 变更」先清 ADR：删除 / 改写 0033 / 0034 / 0035 / 0039 / 0043 / 0053 中失效的口径行、决策行、测试与分期；被本需求整体取代的决策直接删文件与索引行，编号不复用 | `docs/adr/`、`docs/adr/README.md`、代码注释里的旧编号引用 | `make adr-check` 通过 |
| C6 | 清理…不再用的能力 | 同步删除仅服务于被裁能力的测试（`test_datasource_http_json.py` 中 rows_array/row_defaults/scale/url_hosts 用例、`test_datasource_host_fallback.py`、`test_datasource_cursor_backfill.py`、`test_datasource_pipeline_concurrency.py`、`test_datasource_runner_pages.py` 的多 pass 用例等），保留能力测试相应改写 | `tests/` | `make flow` 全绿，覆盖率门槛不放松 |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | `rows_array` 解析分支 | `providers/http_json.py:100-130`、`providers/base.py:100-105` | 腾讯日线专用，无配置声明 |
| 2 | `row_defaults` | `providers/base.py:111`、`services/pipeline.py:450-482`、`services/runner.py:638` | 新浪快照 `{today}` 专用 |
| 3 | `row_filter` | `providers/base.py:114-163`、`services/pipeline.py:485-518` | 零值快照专用；注意与 tables 行级权限 `row_filter` 同名不同物，后者不动 |
| 4 | `scale` | `providers/base.py:170-182`、`services/normalize.py:100` | 示例从未声明（ADR 0053 D8） |
| 5 | `url_hosts` failover | `providers/base.py:90-150`、`providers/http_json.py:167-193` | 腾讯 proxy 回退专用 |
| 6 | `backfill_date` 游标 / 多 pass / 水位 | `services/cursor.py`、`services/entrant_state.py`、`services/runner.py`、`models.py:178` | 腾讯历史回补专用；`models.py` 列删除涉及迁移口径，由 ADR 定 |
| 7 | `workers` 并发 | `providers/base.py:116-130`、`services/pipeline.py:253-290` | 唯一示例 `weather` 未声明；llm 强制 1 |
| 8 | `rate_limit_ms` 串行限速 | `services/pipeline.py:182-206` | weather 声明 0（关闭）；字段在 API schema 暴露，保留 |

## 未决问题

- [x] 简化方向 → 用户拍板：删掉不再用的能力（不选纯重构、不选最小玩具管线）。
- [x] `datasource_sync_job` 表是否存有线上存量 `backfill_date` 任务 → **代码层不再支持、旧任务执行期显式失败**；水位表 `datasource_entrant_cursor` 整体删除（迁移 `2a4c6e8f0b1d`），存量任务由需求方重配或删除。
- [x] `rate_limit_ms` 保留但并发删除后字段仍暴露于创建/编辑 API → **保留字段与 API 面，前端表单不隐藏**；实现改为串行相邻请求间隔。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认
