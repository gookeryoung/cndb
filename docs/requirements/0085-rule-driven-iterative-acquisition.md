# 需求卡片：规则驱动的数据表 / 文档迭代获取

- 编号：0085（与 ADR `docs/adr/0085-rule-driven-iterative-acquisition.md` 同号）
- 来源 / 提出人：需求方（会话提出）
- 日期：2026-11-02
- 关联 ADR：`docs/adr/0085-rule-driven-iterative-acquisition.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请对数据表与文档的自动获取功能进行增强设计，参考 F:\Dev\endo 项目情报收集和分析功能的设计增强方案，实现基于用户特定规则的信息迭代获取机制。明确目标数据的范围与来源、用户规则的表达方式与迭代触发和更新策略，并说明项目自身大模型配置API在该流程中的参与方式与调用约束。输出应包含增强后的功能设计方案，涵盖核心流程、关键模块职责、规则迭代逻辑及与现有功能的衔接。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「明确目标数据的范围与来源」 | 采集范围与来源须以可落库的声明表达：渠道清单（HTTP / RSS / 学术开放 API / 大模型生成 / 既有同步任务）、检索式、时间窗、每渠道上限；落点限「工作区数据表行」与「工作区文档（含原件族）」，不接受任意写目标 | `plugins/acquisition`、`plugins/datasource`、`plugins/documents` | `tests/test_acquisition_channels.py`、策略创建校验用例 |
| C2 | 「用户规则的表达方式」 | 规则分四层且均为 JSON 声明：采集规则（`scope`）/ 筛选规则（`filter`）/ 落点规则（`targets`）/ 迭代规则（`iteration`）；筛选支持「必须含 + 可选含 + 必须排除」三段式与布尔表达式（AND/OR/NOT/括号/占位符）；规则带 `rule_version` 并可快照 | `plugins/acquisition/services/rules/` | `tests/test_acquisition_rules.py`（含布尔解析表驱动用例） |
| C3 | 「迭代触发和更新策略」 | 触发三类：定时（复用既有 schedule + 租约）、手动、缺口驱动；每轮结束按「新增量 / 预算 / 覆盖缺口」判定是否继续；写回策略须区分「表 upsert」「文档新建 / 新版本」「人工修改不覆盖」 | `plugins/acquisition/services/{runner,expand,stop,dedupe}.py` | `tests/test_acquisition_runner.py`、`tests/test_acquisition_targets.py` |
| C4 | 「项目自身大模型配置API在该流程中的参与方式」 | 模型能力只经平台 `llm` 插件的个人连接与网关参与，参与点固定为：规则草案、扩展词重排、条目摘要与分类、轮次报告摘要、失败归因；不得另建连接配置 | `plugins/llm`、`plugins/acquisition/services/ai.py` | `tests/test_acquisition_ai.py`、`llm_run` 落库断言 |
| C5 | 「调用约束」 | 调用须满足：唯一出口（`gateway.invoke`）、连接与 Key 来源受限（Key 不进规则 JSON / 备份）、权限同源、策略级预算、结构化输出校验、模型失败降级为确定性路径、调用留痕可复现 | `plugins/llm`、`plugins/acquisition` | `tests/test_acquisition_ai_constraints.py` |
| C6 | 「核心流程」 | 流程须为可枚举状态的策略运行：策略（草稿/启用/暂停）→ 运行（逐轮：抓取→归一→去重→筛选打分→写回→扩展判定）→ 报告；单轮失败不丢已采数据 | `plugins/acquisition` | `tests/test_acquisition_runner.py`（状态机与失败口径） |
| C7 | 「关键模块职责」 | 新增模块只做「规则求值 + 轮次编排 + 落点分发」；抓取、落表、文档写、模型调用一律复用既有唯一入口，不复制实现 | `plugins/acquisition`、`plugins/datasource`、`plugins/documents`、`plugins/llm` | 代码评审 + 依赖方向用例（`tests/test_plugin_dependencies.py`） |
| C8 | 「规则迭代逻辑」 | 扩展须确定性可复现：累计结果提词（词频 + 文档频次）→ 排除已用词 / 基础词 / 短词 → 构造 `base AND (kw1 OR kw2 …)` → 记入轮次历史；连续空轮提前终止 | `plugins/acquisition/services/{keywords,expand}.py` | `tests/test_acquisition_expand.py` |
| C9 | 「与现有功能的衔接」 | 不破坏既有能力：既有同步任务模型与 provider 协议不变、既有 LLM provider 行为不变、文档写路径不新增、工作区模块开关与备份协议同轮扩展 | `plugins/datasource`、`plugins/workspaces`、`plugins/documents` | `make flow` 全绿 + `tests/test_workspace_backup_v13.py` |
| C10 | 「参考 endo 项目」 | 借鉴其「多渠道并行 + 三段式筛选 + 迭代任务留痕 + 词频扩展」设计，但**不引入**其进程内后台线程 + SQLite 单库形态；执行仍走 `strategy → run → round` 落库 + 既有调度租约 | `plugins/acquisition` | 架构评审 |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 数据同步任务定义（单 job = 单 provider → 单表） | `src/cndb/plugins/datasource/models.py:74` | 无法表达「多来源合并 / 多轮扩展」 |
| 2 | 抓取管线（fetch → parse → normalize） | `src/cndb/plugins/datasource/services/pipeline.py` | 可原样复用；缺筛选打分层 |
| 3 | 运行编排与留痕 | `src/cndb/plugins/datasource/services/runner.py` | 以 job 为单位，无轮次概念 |
| 4 | 调度与租约 | `src/cndb/plugins/datasource/services/scheduler.py` | 可复用 tick + lease |
| 5 | 既有同步任务表 / 游标表 | `src/cndb/plugins/datasource/models.py:136,173` | 需与策略共存，不回填 |
| 6 | 文档导入（手动） | `src/cndb/plugins/documents/routers/file_import.py` | 无周期 / URL 来源 |
| 7 | 文档内容写路径 | `src/cndb/plugins/documents/services/content.py:233,349` | 采集落点须复用，不新增写路径 |
| 8 | 大模型网关与留痕 | `src/cndb/plugins/llm/services/gateway.py:104` | 唯一出口，新增动作即可 |
| 9 | 大模型生成数据的既有 provider | `src/cndb/plugins/datasource/providers/llm_prompt.py:151` | 仅单次提示词，无多轮 |
| 10 | 工作区模块开关 | `src/cndb/plugins/workspaces/modules.py:21` | 无「采集」功能位 |
| 11 | 工作区备份协议 | `src/cndb/plugins/workspaces/services/backup_io.py` | 新表须登记并升协议版本 |

## 未决问题

- [x] 「自动获取」是否含文档 —— 含：数据表行与文档两类落点（C1）。
- [x] 迭代是否由模型驱动 —— 否：扩展词由确定性词频产出，模型只做重排 / 归一（C8、C4）。
- [x] 是否需要独立配额中心 —— 否：预算挂在策略上（ADR D9）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认
