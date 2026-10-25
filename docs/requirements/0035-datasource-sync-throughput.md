# 需求卡片：数据源同步（全市场日线）吞吐优化

- 编号：0035（与 ADR `docs/adr/0035-datasource-sync-throughput.md` 同号）
- 来源 / 提出人：产品负责人（对话提出）
- 日期：2026-10-25
- 关联 ADR：`docs/adr/0035-datasource-sync-throughput.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 日线数据同步数据时间太长，请参考~/stock-strategy的实现方式进行优化。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 日线数据同步数据时间太长 | 首次全市场回补（约 7,289 标的、约 5.8M 行）总耗时从当前小时级降到分钟级；当前基线为「限速地板 ≥54 分钟 + 落表 30~60 分钟」 | `src/cndb/plugins/datasource/services/`、`examples/datasets/工作区-数据源示例/` | 真实任务计时 + `tests/test_datasource_runner_streaming.py` |
| C2 | 时间太长（日常增量同属同步） | 日常快照任务（约 7,286 行/次）落表从实测 16.5s / 34.9s 降到秒级（≤3s） | `src/cndb/plugins/tables/field_types/select.py`、`services/importing/` | 落表基准脚本 + 单测（选项缓存生效） |
| C3 | 请参考 ~/stock-strategy 的实现方式 | 参考实现中与吞吐相关的手法按适用性落地：并发抓取、批量写入、跳过与同步无关的分析、结果缓存；不适用的手法（换存储引擎、复合唯一键）明确否决并记录理由 | ADR「决策记录」 | ADR D 行 + 代码评审 |
| C4 | 参考实现方式 | 不改既有正确性口径：幂等键选择、双源并存、量纲、行级写权限、字段校验语义、断点续跑水位全部保持不变 | `services/write.py`、`services/runner.py`、`services/importing/importer.py` | 既有测试全绿 + 新增等价性用例 |
| C5 | 优化 | 不新增运行期依赖、不更换存储引擎、不改 API 端点与前端交互；引擎侧优化对旧配置零迁移 | `pyproject.toml`、`plugins/datasource/routers/`、`frontend/src/pages/datasource/` | `make check` + 迁移检查 |
| C6 | 优化 | 需要改配置才生效的优化（并发数 / 限速）必须给出存量实例的生效路径，不允许「只改种子不生效」 | `cli/seed/datasource.py`、ADR「交接」 | 存量库复跑计时 + 文档说明 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | select 字段逐行校验 | `src/cndb/plugins/tables/field_types/select.py:161` | 每行每字段重建 7,289 项集合 |
| 2 | 同步落表复用完整导入分析链 | `src/cndb/plugins/tables/services/importing/importer.py:172` | 列画像 / 参考列推荐 / 全表选项同步对同步任务无意义 |
| 3 | 请求并发与全局限速 | `src/cndb/plugins/datasource/services/pipeline.py:115` | 回补任务 6 workers + 150ms → 全局 6.67 req/s 天花板 |
| 4 | 逐行 UPDATE | `src/cndb/plugins/tables/services/core/records.py:968` | 更新路径 7,286 行耗时 34.9s |
| 5 | 回补请求根数固定 800 | `examples/datasets/工作区-数据源示例/datasource.json` | 腾讯单次上限实测即 800，不宜再调 |

## 未决问题

- [x] 参照实现中的「10 线程无限流」是否要原样照搬？结论：不全照搬，保留全局限速语义、仅调整示例任务配置（见 ADR D3）。
- [x] 是否引入复合唯一键 + `ON CONFLICT`？结论：不引入（ADR 0006 口径优先，见 ADR D5）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认（待评审）
