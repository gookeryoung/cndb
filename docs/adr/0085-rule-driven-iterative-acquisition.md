# ADR 0085: 规则驱动的数据表 / 文档迭代获取（采集策略 + 规则引擎 + 大模型参与边界）

Status: Proposed（待评审）
Date: 2026-11-02
Related: `src/cndb/plugins/datasource/models.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/services/scheduler.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/auto_table.py`、`src/cndb/plugins/datasource/services/cursor.py`、`src/cndb/plugins/datasource/providers/base.py`、`src/cndb/plugins/datasource/providers/registry.py`、`src/cndb/plugins/datasource/providers/llm_prompt.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/plugins/llm/services/gateway.py`、`src/cndb/plugins/llm/services/actions.py`、`src/cndb/plugins/llm/services/connection.py`、`src/cndb/plugins/documents/services/content.py`、`src/cndb/plugins/workspaces/modules.py`、`src/cndb/plugins/workspaces/services/backup_io.py`；上游 ADR 0006 / 0014 / 0019 / 0020 / 0034 / 0080
需求卡片: `docs/requirements/0085-rule-driven-iterative-acquisition.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」段落；ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用，不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。
>
> 与 ADR 0006 / 0034 的关系：单 job「声明式抓取 → 幂等落表 → 游标推进 → 租约调度」的内核**不变**，本 ADR 只在其上加「多来源 × 多轮 × 双落点」的策略层；与 ADR 0014 / 0019 / 0020 的关系：`llm_prompt` provider、个人连接与调用网关**行为不变**，本 ADR 只规定策略层**如何使用**该能力以及硬性边界。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C10），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「明确目标数据的范围与来源」 | 新增 `acquisition_strategy`：`scope` JSON 声明渠道集合 + 检索式 + 时间窗 + 每渠道上限；渠道目录由 `providers/registry.py`（既有 provider）+ 学术开放 API 渠道适配器 + `job:<id>` 引用（复用既有同步任务的请求 / 凭证 / 游标）合成；落点只允许 `targets[].kind ∈ {table, document}`，创建期校验表 / 目录归属与工作区模块开关（D1 / D11） |
| C2 | 「用户规则的表达方式」 | 四层 JSON：`scope` / `filter` / `targets` / `iteration`；`filter` 采用 endo 同构的「必须含 + 可选含 + 必须排除」三段式 + 布尔表达式（AND/OR/NOT/括号 + `{topic}` 类占位符）；规则整体带 `rule_version`，每次运行把快照写进 `acquisition_run.rule_snapshot`（D3） |
| C3 | 「迭代触发和更新策略」 | 触发：`schedule`（复用 `is_due` + 租约）/ 手动 / 缺口驱动；停止判定三重：连续空轮、`min_new_items`、预算触顶；写回：表走 `upsert_rows`（`match_keys` 幂等）、文档走 `create_document` / `update_content`（新版本、`change_type=auto_import`），人工改过的文档不覆盖转 issue（D5 / D6 / D7） |
| C4 | 「大模型配置API的参与方式」 | 参与点固定 5 个 `ActionSpec`：`acquisition.rule_draft`、`acquisition.keyword_refine`、`acquisition.item_summary`、`acquisition.run_report`、`acquisition.failure_diagnose`；连接一律取 `llm_user_config`（个人连接），任务级凭证会话仅在 `llm_prompt` 渠道内生效；新增 `acquisition/services/ai.py` 作为薄适配层（构造输入 → `gateway.invoke` → 校验输出） |
| C5 | 「调用约束」 | 见 §6 约束 L1–L9：唯一出口、Key 不落规则 / 备份、权限同源、策略级预算、结构化校验、模型失败降级、留痕可复现、模型不得成为事实来源、单次输入裁剪 |
| C6 | 「核心流程」 | 策略状态机 + 轮次状态机见 §3；每轮固定七步（抓取 → 归一 → 去重 → 筛选打分 → 写回 → 记账 → 扩展判定），单轮失败只降级该轮，已写数据不回滚 |
| C7 | 「关键模块职责」 | §4 职责表：新模块只做「规则求值 + 轮次编排 + 落点分发」；抓取 / 落表 / 文档写 / 模型调用一律复用既有唯一入口（I2） |
| C8 | 「规则迭代逻辑」 | 三段：① 迭代产出候选词 —— `keywords.extract`（词频 + 文档频次 + 停用词 + 最小词长）；② 大模型第二次判断 —— `expand.review_by_llm` 对候选做 keep / drop / rename / 加权（**不得新增候选集之外的词**），判定结果与模型名落 `acquisition_round`；③ 用户可再调整（也可不调）—— `iteration.expand.review="manual"` 时轮末停 `awaiting_review`，用户改关键词 / 检索式后 `resume`，不改则直接续跑；最终检索式由 `expand.build` 拼 `(base) AND (kw1 OR kw2 …)`，与上轮相同则回退 base（D5 / D14） |
| C9 | 「与现有功能的衔接」 | 既有 `datasource_sync_job` / provider 协议 / `llm_prompt` / 文档写路径 / 调度租约**一行不改行为**；新增工作区模块位 `acquisition`（依赖 tables 或 documents 至少其一）；备份协议 v12→v13；既有 job 可被策略以 `job:<id>` 引用而不迁移（D2 / D11 / D12） |
| C10 | 「参考 endo 项目」 | 借鉴其 `FilterRule` / 布尔解析器 / `IterationTask.iteration_history` / 词频扩展策略；**不借鉴**进程内后台线程 + 单库直写的执行形态，改用「strategy → run → round」落库 + 既有 tick/lease（D7） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准）。编号沿用卡片「现状影响面」，ADR 逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 同步任务 = 单 provider → 单表：`DatasourceSyncJob` 只有 `provider` / `request_spec` / `table_id` / `entrant_*` / `cursor` / `schedule` 字段 | `src/cndb/plugins/datasource/models.py:74` | 「同一主题从多来源合并进一张表」「同一批结果同时进表和文档」都无处表达 | 确认（C1） |
| 2 | 管线是「Provider 展开请求 → fetch → parse → normalize → 落表」，全程无质量层 | `src/cndb/plugins/datasource/services/pipeline.py`、`providers/base.py:185` | 抓什么落什么；只有单个数值条件的 `row_filter`，无法做「必须含 / 排除 / 机构 / 类型 / 引用数」这类语义筛选 | 确认（C2） |
| 3 | 去重只在单次运行内按 `match_keys` 先查后写；跨运行、跨来源靠表内主键 | `src/cndb/plugins/datasource/services/write.py`、`models.py:173` | 来源追溯缺失：无法回答「这条行 / 这篇文档是哪一轮、哪个渠道、按哪条规则进来的」 | 确认（C3） |
| 4 | 检索式是静态模板，运行时只做字面替换，不根据已采结果调整 | `src/cndb/plugins/datasource/providers/base.py:82`、`providers/template.py` | 首轮召回不足时没有「自我扩展」路径，只能人工改配置重跑 | 确认（C8） |
| 5 | 文档侧只有手动导入（文件批次 / Obsidian 库），无周期或 URL 来源 | `src/cndb/plugins/documents/routers/file_import.py`、`routers/vault.py` | 「自动获取」在文档域完全缺位 | 确认（C1 / C6） |
| 6 | 调度器按 job 扫描到期 + DB 租约互斥，与具体业务解耦 | `src/cndb/plugins/datasource/services/scheduler.py:1-30` | 策略可复用同一套 tick / lease，无需新调度器 | 排除（新建调度器） |
| 7 | 大模型调用已收敛：`gateway.invoke` 唯一出口，落 `llm_run` 元数据 + `core_event`，不存提示词全文 | `src/cndb/plugins/llm/services/gateway.py:104`、`src/cndb/plugins/llm/models.py:47` | 语义辅助能力现成；缺的是「哪些环节允许用、失败怎么办、预算怎么算」 | 确认（C4 / C5） |
| 8 | `llm_prompt` provider 一次提示词生成一组行，可 json_mode + 自动幂等键 | `src/cndb/plugins/datasource/providers/llm_prompt.py:151` | 可作为一个「生成式渠道」直接复用；但它没有多轮扩展语义 | 确认（C4） |
| 9 | 工作区模块开关为 tables / documents / design 三项，派生功能矩阵在后端单点 | `src/cndb/plugins/workspaces/modules.py:21` | 「采集」若作为可见功能需登记功能位，且文档落点依赖 documents 模块开启 | 确认（C9） |
| 10 | 备份按表清单导出并带协议版本号，新表须登记 | `src/cndb/plugins/workspaces/services/backup_io.py` | 四张新表须进 v13 导出 / 恢复 / 清空，旧备份无键不影响 | 确认（C9） |
| 11 | 文档写路径是「创建 + 新版本」双函数，`change_type` 已预留 `auto_import` | `src/cndb/plugins/documents/services/content.py:233,349`、`models.py:44-48` | 采集落点可直接复用，无需新写路径；但「人工改过的文档被自动覆盖」需要显式保护 | 确认（C3） |
| 12 | HTTP 传输有 SSRF 白名单 / 体积上限 / 超时 / 错误留痕，LLM 调用同源 | `src/cndb/core/http.py`、`src/cndb/plugins/llm/services/client.py` | 渠道适配器不得绕过；爬取类渠道需额外声明域名与页数上限 | 确认（C1） |

**核心缺陷（需求要补的）**：今天的「自动获取」是**一次声明、一次抓取、一个落点**——`job` 既是配置单位也是执行单位，因此无法表达「**一条用户规则 → 多来源合并 → 按结果自我扩展 → 多轮迭代 → 双落点（表 / 文档）→ 全程可追溯到轮次与来源**」这件事；同时大模型能力虽然已平台化，但缺一份「在采集流程里可以做什么、不可以做什么」的边界，导致任何接入都会各自发明口径。

设计目标（不变量）：

- **I1 规则与执行分离**：策略（`acquisition_strategy`）只声明规则与预算，执行一律经 `runner.execute_strategy`；抓取仍由 provider + 管线承担，策略层不得直接发 HTTP。
- **I2 复用唯一入口**：抓取 → `pipeline.run_pipeline`；落表 → `write.upsert_rows`；建表补列 → `auto_table.ensure_job_table`；文档写 → `documents.services.content.{create_document,update_content}`；模型 → `llm.services.gateway.invoke`。新增模块不复制上述任一实现。
- **I3 依赖单向**：`plugins/acquisition` 可依赖 `datasource` / `documents` / `llm`；反向禁止（`llm` 仍不 import 任何领域插件，ADR 0020 I2 不变）。
- **I4 迭代可控可复现**：扩展词的**候选集**由确定性算法产出（词频 + 文档频次 + 排除规则），模型只能在候选集内做保留 / 剔除 / 改名 / 加权，**不得新增候选集之外的词**；每次判定（模型名 + 判定明细）与人工调整（`source=user`）都落 `acquisition_round`，同一规则版本 + 同一候选集可复现同一条扩展链路。
- **I5 已采数据不因后续失败丢失**：单轮抓取 / 筛选 / 模型失败只降级该轮或该渠道，已写表行与文档不回滚；运行状态按 `success / partial / failed` 分级。
- **I6 人工内容不被静默覆盖**：自动写文档仅在「该文档由本策略写入且其后无人工版本」时执行；否则转 issue 建议。
- **I7 密钥与个人配置不落业务数据**：API Key 只存 `llm_user_config` / `datasource_session` 密文；规则 JSON、运行快照、备份均不含 Key 与个人地址。
- **I8 预算硬上限**：请求数 / 行数 / 模型调用次数 / token 在策略级封顶，触顶即停轮（`partial`），不出现「跑飞」。
- **I9 全链可追溯**：每条入库行 / 文档 ↔ `acquisition_item`（策略、运行、轮次、渠道、来源 URL、匹配分、落点 id）。
- **I10 存量零回归**：既有 job、游标、provider、`llm_prompt`、文档写路径、备份 v1–v12 一律不变。

## Decision

### 1. 数据模型

新建插件 `src/cndb/plugins/acquisition/`（表前缀 `acquisition_`），四张表。半结构化配置一律 JSON 列（沿用 ADR 0006 的口径：不把规则拆成强类型列，避免每加一种渠道就改表）。

**`acquisition_strategy`** — 策略定义（规则载体 + 调度 + 预算）

| 列 | 类型 | 说明 |
|---|---|---|
| `workspace_id` / `created_by` | FK | 归属与创建者 |
| `name` | str(128) | 策略名 |
| `enabled` | bool | 启停 |
| `scope` | JSON | 采集范围与来源（见下） |
| `filter_rule` | JSON | 筛选规则（三段式 + 布尔式） |
| `targets` | JSON | 落点数组（table / document 可并存） |
| `iteration` | JSON | 轮次、扩展、停止、预算 |
| `llm` | JSON | 语义辅助开关与动作白名单 |
| `schedule` | JSON | 复用 `{"mode","at","seconds","expr","timezone"}` + `cooldown_minutes` |
| `rule_version` | int | 规则每次实质变更 +1；运行快照带此值 |
| `last_run_at` / `last_status` | - | 与既有 job 同口径 |
| `lease_owner` / `lease_until` | - | 与 `datasource_sync_job` 同语义（多副本互斥） |

**`acquisition_run`** — 一次策略运行

`strategy_id`、`trigger`（`manual|scheduler|cli`）、`status`（`running|awaiting_review|success|partial|failed|cancelled`）、`rule_snapshot`（运行时规则 + `rule_version`）、`round_count`、`progress` / `progress_message`、`fetched` / `inserted` / `updated` / `skipped` / `docs_created` / `docs_updated` / `docs_skipped`、`budget_used`（`{"requests","rows","llm_calls","llm_tokens"}`）、`error_message`、`detail`（失败明细 / 渠道错误 / 降级记录）、`started_at` / `finished_at` / `duration_ms`。

**`acquisition_round`** — 轮次明细（对齐 endo `iteration_history`，但落表可查询）

`run_id`、`round_no`、`query`、`channels`、`stats`（`total_collected / after_dedup / after_filter / by_channel / channel_errors`）、`new_items`、`accumulated_items`、`top_keywords`（`[{term,count,df,weight,source:"tf"|"llm"|"user",reason?,dropped?,rename_to?}]`）、`next_query`、`gap`（缺口快照）、`review_state`（`auto|llm|pending|confirmed`）、`stop_reason`（`empty_round|min_new|budget|max_rounds|null`）、`status`、`error_message`、`duration_ms`。

**`acquisition_item`** — 条目台账（来源追溯 + 跨运行去重 + 落点绑定）

`strategy_id`、`run_id`、`round_no`、`channel`、`dedupe_key`（唯一索引 `(strategy_id, dedupe_key)`）、`title`、`source_url`、`published_at`、`match_score`、`target_kind`、`target_id`（表落点记 `table_id`；文档记 `document_id`）、`payload_digest`（内容指纹，判断是否需要新版本）、`created_at`。

> **表落点的去重键是 ``row:<match_keys 指纹>``**（`rules.dedupe` 的 `identity` 参数）：业务身份由 `targets[].match_keys` 决定，不能退化成内容指纹——否则同一行换了数值就变成新条目，台账与"跨运行去重"都会失真。台账的**拦截**只对「只追加」落点（文档）生效，表落点重复由 `upsert_rows` 承担更新（D4）。

规则 JSON 形态（前端表单与 API 同构，示例）：

```json
{
  "scope": {
    "channels": ["rss", "arxiv", "job:12"],
    "query": "(固态电池 OR solid-state battery) AND NOT 回收",
    "time_window": {"mode": "range", "start_param": "from", "end_param": "to", "chunk_days": 7},
    "max_results_per_channel": 50,
    "languages": ["zh", "en"]
  },
  "filter_rule": {
    "must_have_keywords": ["固态电解质"],
    "optional_keywords": ["界面", "离子电导率"],
    "exclude_keywords": ["广告", "招聘"],
    "institutions": ["宁德时代"],
    "document_types": ["article", "preprint"],
    "date_from": "2024-01-01",
    "min_citations": 5,
    "require_fulltext": false,
    "query_boolean": "({topic}) AND (sulfide OR oxide)"
  },
  "targets": [
    {"kind": "table", "table_id": 42, "match_keys": ["doi"],
     "field_mapping": {"标题": {"name": "title"}, "DOI": {"name": "doi"}}},
    {"kind": "document", "parent_id": 88, "title_template": "{published_at:%Y-%m-%d} {title}",
     "body_template": "# {title}\n\n{summary}\n\n> 来源：{source_url}",
     "tags": ["自动采集"]}
  ],
  "iteration": {
    "max_rounds": 3, "top_keywords_per_round": 5,
    "expand": {"strategy": "cooccurrence", "max_terms": 5, "min_df": 2, "exclude_base_terms": true,
               "review": "llm"},
    "stop": {"empty_rounds": 1, "min_new_items": 1, "max_total_items": 400},
    "budget": {"max_requests": 240, "max_rows": 5000, "max_llm_calls": 12, "max_llm_tokens": 120000}
  },
  "llm": {"enabled": true, "actions": ["keyword_refine", "item_summary"]}
}
```

**与既有表的关系**：策略不复制 job 的请求 / 凭证 / 游标。渠道 `job:<id>` 在运行期读该 job 的 `request_spec` / `session_id` / `cursor` / `entrant_*` 构造内存 `SyncJobSpec`（`providers/base.py:185` 的设计意图即「纯内存声明」），因此**既有任务零迁移即可被策略引用**；策略自身不写 `datasource_sync_job`。

### 2. 判定算法（唯一入口）

新增 `plugins/acquisition/services/` 下六个纯函数模块 + 一个编排入口：

| 入口 | 签名 | 职责 |
|---|---|---|
| `runner.execute_strategy` | `(db, strategy, trigger, *, fetcher=None, now=None) -> AcquisitionRun` | 唯一执行入口：领租约 → 逐轮循环 → 写 run/round/item → 收尾 |
| `rules.expr.parse` | `(expr: str) -> AST \| None` | 布尔表达式解析（AND/OR/NOT/括号/隐式 AND），失败抛 `RuleError` |
| `rules.expr.substitute` | `(expr, ctx) -> str` | `{topic}` / `{today}` / `{entrant}` 占位符替换（含引号成对处理） |
| `rules.filter.apply` | `(items, rule) -> list[ScoredItem]` | 三段式 + 硬条件 + 0–100 匹配分，返回按分降序 |
| `rules.dedupe.key` | `(item, channel) -> str` | `doi` > 归一 URL > `sha1(正文去空白)` > `归一标题+日期` |
| `rules.keywords.extract` | `(items, top_n, stop_words) -> list[Keyword]` | 词频 + 文档频次（df），最小词长 3，去停用词 |
| `rules.expand.build` | `(base, keywords, used, previous) -> str` | 构造 `(base) AND (kw1 OR kw2 …)`；≤5 词；与 `previous` 相同则回退 base |
| `rules.expand.apply_llm_decisions` | `(candidates, decisions) -> (list[Keyword], rejected)` | 应用模型第二次判断：keep / drop / rename / weight，候选集外新增词进 `rejected` |
| `rules.expand.apply_user_edit` | `(keywords, user_terms) -> list[Keyword]` | 应用用户调整：新词 `source="user"`、被删词记 `dropped`；不改则原样返回 |
| `rules.stop.decide` | `(round_ctx, iteration, budget) -> StopReason \| None` | 空轮 / `min_new_items` / 预算 / 轮数上限 |
| `targets.dispatch` | `(db, strategy, items, run, round) -> TargetReport` | 表走 `upsert_rows`，文档走 `create_document` / `update_content`，逐条写 `acquisition_item` |

**判定顺序（一轮内固定）**：

1. **渠道展开**：`scope.channels` → 每个渠道一个 `SyncJobSpec`（`job:<id>` 复用其声明；学术渠道由适配器生成 `RequestSpec`；`llm_prompt` 渠道按提示词生成）。请求数超 `budget.max_requests` 余量 → 截断并记 `budget_truncated`。
2. **抓取**：逐渠道 `pipeline.run_pipeline`（并发 / 限速 / 分页 / 失败隔离沿用既有实现）；渠道异常只记 `channel_errors`，全渠道失败该轮 `failed`。
3. **归一**：`provider.normalize` + `field_mapping`（表落点）或文档正文构建（文档落点）；同一批次统一成 `Candidate`（`title / summary / url / doi / published_at / authors / affiliations / categories / document_type / citation_count / fulltext_url / raw`）。
4. **跨轮 + 跨运行去重**：`rules.dedupe.key` 命中本运行内存 `seen` 或 `acquisition_item` 已有 `(strategy_id, dedupe_key)` → `skipped`。
5. **筛选打分**：`rules.filter.apply`（布尔式优先于 `must_have` 强制，与 endo 口径一致）；`after_filter` 记入轮次统计。
6. **写回**：`targets.dispatch`。表：`upsert_rows(match_keys)` + `auto_table` 补列；文档：见 §3「文档写回」。
7. **记账与扩展**：写 `acquisition_round`（统计 / 关键词 / `next_query` / `stop_reason`），推进 `budget_used`，`rules.stop.decide` 决定下一轮。

**必须复用该入口的路径**：手动运行、调度 tick、CLI（`cndb acquisition run`）、API 预览（`preview` 走同一函数但 `dry_run=True`，不写 item / 不写表 / 不写文档）；任何绕过 `rules.filter.apply` 的「临时过滤」一律不接受。

### 3. 核心流程

**策略状态机**：`draft`（未启用，可预览）→ `active`（`enabled=true`，参与 tick）→ `paused`（手动暂停）→ `draft`（改规则后需重新启用）。规则实质变更（`scope` / `filter_rule` / `targets` / `iteration`）→ `rule_version += 1`，`draft` 状态回写，避免「静默改规则影响在跑任务」。

**运行状态机**：`running` →（`awaiting_review` → `running` …）→（`success` | `partial` | `failed` | `cancelled`）。`awaiting_review` 仅在 `expand.review="manual"` 时出现，占住轮边界、不占租约（租约按轮续期，等待期释放并由 `resume` 重新领取）。`partial` 的三类来源：单渠道失败、部分落点失败、预算触顶。

**轮次循环（伪代码，即 endo `IterativeCollector` 的改造版）**：

```text
run = create_run(strategy, rule_snapshot)
current_query = render(scope.query, ctx)          # {topic} 等占位符
for round_no in 1..iteration.max_rounds:
    candidates = fetch_all(channels, current_query, window(round_no))
    fresh = dedupe(candidates)                     # 内存 seen + acquisition_item
    scored = rules.filter.apply(fresh, filter_rule)
    report = targets.dispatch(scored)               # 表 upsert / 文档新建或新版本
    kws = rules.keywords.extract(accumulated, top_keywords_per_round, stop_words)   # ① 迭代产出
    kws = maybe_refine_by_llm(kws)                  # ② 模型第二次判断（白名单内 keep/drop/rename/weight）
    if expand.review == "manual":
        record_round(review_state="pending", next_query=build(base, kws, ...))
        run.status = "awaiting_review"; park(run)   # ③ 用户可调，也可不调
        kws, current_query = await_resume(run)      # 不调 → 原样继续
    next_query = rules.expand.build(base_query, kws, used_kws, current_query)
    record_round(...)                               # 含 gap / stop_reason / review_state
    if rules.stop.decide(...): break
    current_query = next_query
finish_run(status)                                  # 可选 run_report 摘要
```

**关键时序约束**：

1. **轮间串行、轮内并行**：扩展式依赖「累计结果」，因此轮与轮之间严格串行；单轮内渠道并发沿用 `request.workers` 与 `rate_limit_ms`。
2. **流式落库**：表落点沿用 `pipeline` 的 `on_batch` 回调（批 10,000 行，ADR 0039 D4），中途失败保留已落批次。
3. **进度上报**：`progress = 轮次区间占比（80%）+ 收尾（20%）`，与既有 `datasource_sync_run` 的进度口径一致，前端复用既有进度条组件。
4. **取消**：`cancelled` 只在轮边界生效（不中断在途 HTTP），避免半批数据。
5. **人工复核闸口**：`awaiting_review` 是轮边界的显式停点，等待期内不持有租约、不占线程；超过 `iteration.expand.review_timeout_hours`（默认 72h）未处理按「不调」自动续跑，避免策略被遗忘卡住。

**文档写回（幂等 + 人工保护）**：

```text
key = dedupe_key
item = acquisition_item.get(strategy_id, key)
if item is None or item.target_kind != "document":
    doc = create_document(parent_id, title_template.render(c), body, tags, change_type="auto_import")
    bind item.target_id = doc.id, item.payload_digest = sha1(body)
else:
    doc = get_document(item.target_id)
    if latest_version(doc).change_type != "auto_import":      # 人工改过
        open_issue("自动采集建议更新", 摘要 + 来源链接)          # 不覆盖
        skipped += 1
    elif sha1(body) != item.payload_digest:                    # 内容确有变化
        update_content(doc, body, change_type="auto_import")   # 产生新版本
        item.payload_digest = sha1(body)
    else:
        skipped += 1                                            # 无变化不产版本
```

> 文档标题 / 目录由 `title_template` 与 `parent_id` 决定；同一策略同一 `dedupe_key` 恒定指向同一 `document_id`，因此「重跑只更新、不新增」。

**报告**：运行结束写一条「运行摘要」（计数 + 每轮检索式 + 关键词 + 缺口 + 失败原因）。启用 `run_report` 时由模型生成 3–5 句自然语言摘要，**追加**在结构化摘要之后（不替代、不作为唯一事实来源）。

### 4. 关键模块职责

| 模块 | 位置 | 职责 | 明确不做 |
|---|---|---|---|
| 策略 API / 校验 | `plugins/acquisition/routers/strategies.py` | CRUD、启停、规则校验（占位符 / 布尔式 / 表与目录归属 / 模块开关）、`rule_version` 递增 | 不执行抓取 |
| 运行 API | `plugins/acquisition/routers/runs.py` | 手动运行 / 取消 / 预览 / 运行与轮次查询 | 不改规则 |
| 编排 | `plugins/acquisition/services/runner.py` | 租约、轮次循环、预算、状态机、留痕 | 不发 HTTP、不写表、不写文档 |
| 规则引擎 | `plugins/acquisition/services/rules/` | 表达式 / 筛选 / 打分 / 去重 / 关键词 / 扩展 / 停止判定（纯函数） | 不碰 DB、不碰网络 |
| 渠道适配 | `plugins/acquisition/services/channels.py` | `rss_atom` / `sitemap`（受限）/ `arxiv` / `openalex` / `crossref` / `job:<id>` / `llm_prompt` → `SyncJobSpec` | 不实现 HTTP 细节（复用 `core/http.py`） |
| 落点分发 | `plugins/acquisition/services/targets.py` | 表 `upsert_rows` + `auto_table`；文档 `create_document` / `update_content`；写 `acquisition_item` | 不新增写路径、不做 DDL 之外的 schema 变更 |
| 语义辅助 | `plugins/acquisition/services/ai.py` | 5 个 `ActionSpec` 的输入构造、裁剪、调用、输出校验与降级 | 不自建 HTTP、不直连模型、不写业务表 |
| 调度接入 | `plugins/acquisition/services/scheduler_hook.py` | 向既有 tick 注册策略到期扫描（复用 `is_due` + 租约列） | 不新建调度线程 |
| 文档侧 | `plugins/documents/services/content.py`（复用） | 建文档 / 新版本 / 版本类型标记 | 不感知「采集」概念 |
| 模型侧 | `plugins/llm/`（复用 + 注册动作） | 连接解析、调用、留痕、错误分类 | 不 import 领域插件 |
| 工作区 | `plugins/workspaces/modules.py` | 新增功能位 `acquisition`（依赖 tables / documents 至少其一） | 不改既有绑定语义 |

### 5. 大模型参与方式

参与点**固定为 5 个**，全部注册为 `ActionSpec`（`plugins/llm/services/actions.py` 的注册表），全部经 `gateway.invoke`：

| # | 动作名 | 何时调用 | 输入（已裁剪） | 输出 schema | 失败时 |
|---|---|---|---|---|---|
| A | `acquisition.rule_draft` | 用户写自然语言需求后点「生成规则草案」 | ≤4000 字需求描述 + 可用渠道 / 表字段清单 | `RuleDraft{scope, filter_rule, targets, iteration}` | 返回空草案并提示手填；**不自动启用** |
| B | `acquisition.keyword_refine` | 每轮 `keywords.extract` 产出候选后（`expand.review` 为 `llm` / `manual` 时） | 候选词 ≤40 个 + `{term,count,df}` + 已用词 + 上轮检索式 | `KeywordDecision{decisions:[{term,action:"keep"\|"drop",rename?,weight?,reason}], note}` | 直接用确定性排序（`review=auto` 等价行为） |
| C | `acquisition.item_summary` | 文档落点写正文前（可选） | 单条候选的标题 + 摘要（≤3000 字） | `ItemSummary{summary, tags[], category}` | 用原文摘要 / 空标签 |
| D | `acquisition.run_report` | 运行收尾（可选） | 结构化统计 + 每轮检索式 + 关键词 | 自由文本 ≤800 字 | 只保留结构化摘要 |
| E | `acquisition.failure_diagnose` | 用户点「为什么这轮没结果」（只读） | 失败明细 + 渠道错误 + 筛选前后计数 | 自由文本 ≤600 字 | 返回规则化诊断文案 |

**参与边界（这是本 ADR 的核心口径）**：模型在流程中的角色是「**规则翻译器 + 语义辅助**」，**不是采集执行者**——除 `llm_prompt` 渠道（既有能力，生成式数据源）外，模型不发起、不扩展、不决定抓取目标；模型输出的任何内容都只有两种命运：**经人工确认成为规则**（A），或**受候选集白名单约束成为判定 / 排序 / 文案**（B/C/D/E）。

**迭代扩展词的三段判定（D5 / D14）**：

```text
candidates = keywords.extract(accumulated)          # ① 迭代产出：确定性词频 + df
decisions  = maybe_refine_by_llm(candidates)        # ② 大模型第二次判断：只允许 keep/drop/rename/weight
                     ↓（review="manual" 时在此暂停）
review     = round.review_state = "pending"          # ③ 用户可再调整（也可不调）
                     ↓ POST /runs/{rid}/resume（可带 keywords / query）
next_query = expand.build(base, final_keywords, used, previous)
```

- ② 的产物必须逐词可解释（`reason` ≤60 字）；`rename` 只能映射到候选词、基础词或其**同义变体**，每条 rename 都记原词 / 新词，便于审计与回退；模型返回候选集之外的新增词一律丢弃并记 `rejected_terms`。
- ③ 的调整写回本轮 `top_keywords[].source="user"` 与实际 `next_query`；不调整则 `resume` 时不带参数，行为等价于 `review=llm`。`review` 默认 `llm`（不停顿），`auto` 表示完全不走模型（纯确定性），`manual` 表示每轮停下等确认——三者共用同一份 `round` 结构，切换不改变历史数据的可读性。

### 6. 调用约束（L1–L9）

| # | 约束 | 判定口径 | 落地 |
|---|---|---|---|
| L1 | **唯一出口** | 采集域不得出现 `requests` / `fetch_json` 直调模型；只允许 `gateway.invoke`（或 `llm_prompt` provider 内部的 `as_fetcher`） | `plugins/acquisition/services/ai.py` 只 import gateway |
| L2 | **连接与密钥来源** | 连接取 `load_connection(db, strategy.created_by)`（个人连接，一人一条）；`llm_prompt` 渠道仍可用凭证会话 Key 覆盖；**Key 永不写入 `scope` / `filter_rule` / `rule_snapshot` / 备份** | `llm/services/connection.py` 复用；规则校验拒绝含 `api_key` 的字段 |
| L3 | **权限同源** | 创建 / 修改 / 启停 / 手动运行需工作区 `EDITOR`；模型输入按可见性裁剪（文档正文按该用户可见性、表字段跳过隐藏字段） | 复用 `documents/services/visibility.py`、`tables` 行 / 字段权限 |
| L4 | **预算硬上限** | `iteration.budget.max_llm_calls` / `max_llm_tokens`；单次输入超 `ActionSpec.max_input_chars` 直接拒绝（不分片）；超预算停用 LLM 但继续确定性流程 | `runner` 记账，`run.budget_used` 落库 |
| L5 | **结构化校验 + 失败降级** | 结构化动作必须过 Pydantic `output_schema`；校验失败 → 该步降级为确定性结果；**模型失败不得导致已抓数据丢失或运行整体 failed**（记 `detail.llm_degraded`） | gateway 抛 `LlmOutputInvalid`，`ai.py` 捕获降级 |
| L6 | **模型不得成为事实来源** | 不得编造 URL / DOI / 精确统计；扩展词不得越出候选集；`item_summary` 的 `tags` 必须来自既有标签或明显主题词（校验：≤8 个、去重、非空） | 输出 schema + 二次校验（`ai.py` 白名单 / 长度 / 数量） |
| L7 | **可复现留痕** | 每次调用落 `llm_run`（动作 / 模型 / token / 耗时 / 状态，不含提示词全文）；`run.detail.llm = {action, model, calls, tokens, degraded}`；`rule_snapshot` 与提示词模板版本号一同落库 | `gateway.record_run` 既有能力 |
| L8 | **模型不得直写业务数据** | 除 `llm_prompt` 渠道（走既有管线 + 幂等落表）外，模型输出不得直接 INSERT / UPDATE 表或文档；`item_summary` 只作为 `create_document` 的入参 | 写路径集中在 `targets.dispatch` |
| L9 | **上下文最小化** | 单条候选送模≤3000 字（标题 + 摘要），整表 / 整文档不外发；`rule_draft` 只送字段名不送行数据 | `ai.py` 裁剪函数 + 单测断言字符上限 |

**降级链**：未配置 Key → `LlmNotConfigured` → 策略仍可运行（A/C/D/E 跳过，B 用确定性排序）；`429` / 5xx 由客户端 ≤2 次退避重试，仍失败则同上降级；输出非法 → 单步跳过。**任何情况下「采集能否跑通」不依赖模型可用性**。

### 7. API 变更清单（`/api/v1/workspaces/{wid}/acquisition`）

| 端点 | 变更 |
|---|---|
| `GET /channels` | 新增：渠道目录（既有 provider + 学术渠道 + 可引用的 `job:<id>` 列表），含 `params_schema` 与 `requires_key` |
| `GET /strategies`、`POST /strategies` | 新增：列表 / 创建；创建校验占位符、布尔式、`targets` 归属、模块开关、预算上下限 |
| `GET /strategies/{id}`、`PUT /strategies/{id}`、`DELETE /strategies/{id}` | 新增：读写删（软删）；实质变更 → `rule_version+1` 且回 `draft` |
| `POST /strategies/{id}/enable`、`POST /strategies/{id}/disable` | 新增：启停（启用前跑一次规则校验 + `preview` 必须存在） |
| `POST /strategies/{id}/preview` | 新增：`dry_run` 首轮——真实抓取、真实筛选，**不写表 / 不写文档 / 不写 item**，返回 `{collected, after_dedup, after_filter, samples[], channel_errors[]}` |
| `POST /strategies/{id}/run` | 新增：手动触发（`EDITOR`），**同步执行**并返回终态运行记录；租约被占用 409。P0 之所以同步：单轮受 `iteration.budget.max_requests` 封顶（默认 1000），耗时可控；P2 接入调度后改后台线程 + `run_id` 轮询 |
| `POST /runs/{rid}/cancel` | 新增：轮边界取消 |
| `POST /runs/{rid}/resume` | 新增：`awaiting_review` 续跑；可选 `{keywords?: [{term,action}], query?}`，不带参数 = 「不调」，直接进下一轮；`EDITOR` 权限 |
| `GET /strategies/{id}/runs`、`GET /runs/{rid}`、`GET /runs/{rid}/rounds` | 新增：运行历史与轮次时间线 |
| `POST /rule-drafts` | 新增：`{description, table_id?, parent_id?}` → `{draft, model, run_id}`；**只返回草案，不落策略** |
| `POST /rules/validate` | 新增：规则片段校验（前端表单实时校验复用） |

### 8. 边界与例外

1. **不做通用爬虫**：`sitemap` 渠道仅允许声明域名白名单、`max_pages`、深度 1、遵守 `robots.txt`；不抓登录态页面、不解析 JS 渲染内容；内网 / 本机地址仍被 `core/http.py` 的 SSRF 白名单拒绝。
2. **单策略上限**：渠道 ≤8、`max_rounds` ≤5、每渠道每轮 ≤200 条、单次运行请求 ≤1000；超限创建期 400。
3. **零新增不算失败**：「抓到了但全部被筛掉 / 全部去重」属正常收敛，`status=success` 且 `stop_reason=empty_round`。
4. **失败分级**：全渠道失败 → `failed`；部分渠道 / 部分落点失败 → `partial`；预算触顶 → `partial` 且 `detail.budget_exhausted=true`。
5. **规则变更与在跑运行隔离**：运行使用 `rule_snapshot`，中途改规则不影响当前运行。
6. **文档落点前置**：`targets` 含 `document` 时要求工作区开启 `documents` 模块，否则创建期 400；含 `table` 时要求 `tables` 模块。
7. **学术渠道合规**：仅用公开开放 API（arXiv / OpenAlex / Crossref / Unpaywall），带 `mailto`（polite pool），单轮条数受 API 自身 limit 约束。
8. **时区**：时间窗与 `{today}` 一律按工作区时区（复用 `schedule.timezone`），跨时区不额外转换。
9. **复核不阻塞调度**：`awaiting_review` 的运行不占租约、不计入「运行中」，同一策略的下一次定时到点仍会正常新建运行；超时按「不调」续跑并记 `detail.review_timeout=true`。

### 9. 迁移

- 单条 alembic 迁移 `a7c1d2e3f4b5_add_acquisition_plugin.py`：四张表 + 索引（`(strategy_id, dedupe_key)` 唯一、`(run_id, round_no)` 唯一、`strategy(workspace_id, enabled)`、`run(strategy_id, started_at)`）；`downgrade` 逆序 drop（数据不恢复，与既有迁移一致）。
- 存量零迁移：既有 `datasource_sync_job` / 游标 / 运行记录不动，策略以 `job:<id>` 引用。
- 工作区模块：`WORKSPACE_MODULES` 增 `acquisition`，`MODULE_FEATURES` 增绑定 `acquisition → {acquisition}`；`normalize_modules` 校验「acquisition 至少依赖 tables 或 documents 之一」，旧备份模块集合按原样导入（不自动加 acquisition）。
- 备份：协议 `v12 → v13`，新增顶层 `acquisition: {strategies[], runs[], rounds[], items[]}`（`rule_snapshot` 随 run 导出，**不含任何 Key / 个人地址**）；导入按 `(workspace, name)` 幂等跳过；≤v12 旧备份无该键正常导入；清空恢复包含四表。

### 10. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 页面 | `frontend/src/pages/acquisition/StrategiesPage.tsx` | 策略列表（名称 / 渠道数 / 落点 / 下次运行 / 最近状态）+ 启停 + 手动运行 |
| 页面 | `frontend/src/pages/acquisition/StrategyEditor.tsx` | 四段式表单（范围 / 筛选 / 落点 / 迭代）+ 自然语言「生成规则草案」入口（草案需确认才落表单） |
| 页面 | `frontend/src/pages/acquisition/RunDetail.tsx` | 运行摘要 + 轮次时间线（检索式、新增、关键词、停止原因）+ 失败明细 |
| 组件 | `frontend/src/pages/acquisition/RulePreviewPanel.tsx` | 预览结果：筛选前后计数、样例行、渠道错误；未预览不允许启用 |
| API | `frontend/src/api/acquisition.ts` | 类型与封装（`Strategy` / `Run` / `Round` / `Channel` / `RuleDraft`） |
| 导航 | `frontend/src/layouts/MainLayout.tsx` | 数据表段新增二级页签「智能采集」（`acquisition` 功能位开启时渲染） |
| 帮助 | `frontend/src/pages/help/content/tutorials.tsx` | 新增「规则驱动的自动获取」主题（规则写法、迭代与预算、模型参与边界） |

前端约束：整页 `lazy`；草案生成与预览使用同步 JSON（不引入 SSE）；bundle budget 需同步复核。

### 11. 测试清单

**判定层（单测，纯函数优先）**：

- `rules.expr`：AND/OR/NOT/括号/隐式 AND/引号短语/占位符成对引号/非法式抛错（表驱动，对齐 endo 用例覆盖面）。
- `rules.filter`：三段式组合、布尔式优先于 `must_have`、机构 / 类型 / 引用数 / 全文硬条件、评分单调性与上限 100。
- `rules.keywords` / `rules.expand`：停用词与短词过滤、df 阈值、已用词排除、≤5 词、与上轮相同回退 base、确定性（同输入同输出）。
- `rules.stop`：空轮、`min_new_items`、`max_rounds`、预算四类触发与优先级。
- `rules.dedupe`：doi / url 归一 / 正文指纹 / 标题+日期四级回落。

**编排层**：

- `runner`：单渠道成功、多渠道部分失败（`partial`）、全失败（`failed`）、预算触顶停轮、轮次串行与累计结果参与扩展、`dry_run` 零写入、租约互斥、取消只在轮边界。
- `runner` × 复核闸口：`review=auto` 不调用模型；`review=llm` 自动续跑；`review=manual` 停在 `awaiting_review` → 带关键词 `resume` 生效、不带参数 `resume` 行为等价 `llm`、超时自动续跑并记 `review_timeout`。
- `expand` 判定应用：keep / drop / rename / weight 生效，候选集外新增词进 `rejected` 且不进入检索式。
- `targets`：表 upsert 幂等（重跑不新增）、自动补列、文档新建 / 新版本 / 内容未变不产版本 / 人工改过转 issue。

**接口层**：

- 策略 CRUD、`rule_version` 递增与 `draft` 回落、非法占位符 400、`targets` 越权 / 跨工作区 400、模块未开启 400、`preview` 不落库、`run` 异步返回、轮次查询分页。

**模型参与层**：

- 五类动作各一条成功用例 + 输出 schema 非法 / 上游 502 / 429 / 未配置 Key 的降级用例；断言降级后运行仍 `success`；断言 `llm_run` 只含元数据（不含提示词 / 输出）；断言 `keyword_refine` 越界词被丢弃。

**迁移 / 备份**：

- v13 往返（策略 / 运行 / 轮次 / 台账一致）、≤v12 旧备份导入、清空恢复含四表、迁移 head 常量与幂等。

**e2e（前端）**：

- 新建策略 → 生成草案 → 预览 → 启用 → 手动运行 → 轮次时间线可见；无 Key 时草案按钮给出「先配置大模型连接」并可用手填表单完成创建。

### 12. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 四表 + 迁移 + 规则引擎（expr / filter / dedupe）+ `runner` 骨架（单轮、仅表落点）+ CLI 运行 | 低（不接前端） |
| **P1** | 迭代（keywords / expand / stop / budget）+ 轮次留痕 + 文档落点 + 人工保护 + 台账 | 中（幂等与并发） |
| **P2** | 渠道（rss / 学术 / `job:<id>`）+ 调度接入 + 备份 v13 + 模块位 | 中（外部源稳定性） |
| **P3** | 五个 LLM 动作 + 草案生成 + 预览 / 前端页面 + 帮助文档 | 中（提示词与预算） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 策略层放哪（整体方案选型） | 新建插件 `plugins/acquisition/`，依赖 datasource / documents / llm | 跨表 + 文档双落点，塞进 datasource 会使其反向依赖 documents（I3） | ① 扩 `datasource_sync_job`：job 语义被「多轮 + 双落点」撑爆，且文档落点与表无关；② 放 documents：结构化行语义不属于文档域 | `src/cndb/plugins/acquisition/` |
| D2 | 策略与既有 job 的关系 | 策略只引用 `job:<id>`，运行期派生内存 `SyncJobSpec`，不复制 job | `providers/base.py` 已把声明设计为纯内存对象；既有任务零迁移 | 每渠道建一条 job：出现双套调度、双套留痕，规则与 job 一对多难溯源 | `services/channels.py` |
| D3 | 规则载体 | JSON 四段 + `rule_version` + 运行快照 | 沿用 ADR 0006「半结构化配置一律 JSON」；每加渠道不改表 | 强类型列：每加一种筛选维度就迁移一次 | `models.py`、`routers/strategies.py` |
| D4 | 去重层级 | 三层：运行内内存 seen、跨运行 `acquisition_item` 唯一键、表内 `match_keys` upsert | 前两层解决「同一来源反复进文档」，第三层解决「行幂等」 | 仅靠 upsert：文档会重复创建，且无法追溯来源 | `services/rules/dedupe.py`、`models.py` |
| D5 | 扩展词由谁产出 | 三段：迭代（确定性词频 + df）产出候选 → 大模型第二次判断（keep / drop / rename / weight，候选集外拒绝）→ 用户可再调整（也可不调） | 候选集确定性保证可解释与可回退；模型只在候选内判断，兼顾语义质量；用户保留最终否决权（需求方 2026-11-02 拍板） | ① 纯确定性（仅词频）：同义词 / 泛词无法剔除；② 模型直接生成检索词：不可复现、易跑偏、成本高 | `services/rules/{keywords,expand}.py`、`services/ai.py` |
| D14 | 用户调整的载体 | `expand.review ∈ {auto, llm, manual}`；`manual` 在轮边界停 `awaiting_review`，`POST /runs/{rid}/resume` 带 / 不带关键词均可，超时 72h 自动按「不调」续跑 | 「可调可不调」必须是无摩擦的可选项；停顿点放轮边界才能避免半批数据与租约悬挂 | 在运行中途随时改检索式：状态机与幂等都会失控；只提供「改策略重跑」：等于没有微调能力 | `services/runner.py`、`routers/runs.py`、`models.py` |
| D6 | 停止条件 | 空轮 / `min_new_items` / 预算 / 轮数四重取最先触发 | endo 用「空轮提前终止」，实测足够；再加预算防跑飞 | 固定轮数：召回差的场景白跑 3 轮，召回好的场景 1 轮就枯 | `services/rules/stop.py` |
| D7 | 执行形态 | 落库 `strategy → run → round` + 既有 tick / lease | 多副本安全、可查询、可断点；endo 的后台线程 + 单库不可移植 | 进程内线程池（endo 形态）：多副本重复跑、进程重启丢任务 | `services/runner.py`、`scheduler_hook.py` |
| D8 | 文档冲突 | 人工版本不覆盖，转 issue 建议 | I6；文档是知识资产，静默覆盖不可接受 | 后写覆盖：丢失人工编辑；跳过全部更新：自动能力失效 | `services/targets.py` |
| D9 | 模型角色 | 「规则翻译器 + 语义辅助」，非执行者 | 采集正确性不应依赖模型可用性；成本与漂移可控 | 让模型规划每轮检索并决定落点：不可复现、失败即停摆 | `services/ai.py`、`plugins/llm/services/actions.py` |
| D10 | 预算机制 | 策略级 `budget` JSON + 运行期记账 | 首期不需要全局配额中心；预算随策略导出 / 迁移 | 全局配额表 / 计费中心：超需求，且引入跨工作区耦合 | `services/runner.py`、`models.py` |
| D11 | 工作区模块 | 新增功能位 `acquisition`，依赖 tables / documents 至少其一 | 与 ADR 0080 模块口径一致；文档落点必须开 documents | 不登记功能位（恒显）：仅设计工作区会看到不可用入口 | `plugins/workspaces/modules.py` |
| D12 | 备份协议 | v12 → v13，四表入归档，规则快照随 run 导出 | 与既有「按表清单 + 版本号」口径一致 | 不进备份：恢复后策略全丢；或因含 Key 被排除（Key 本就不在规则里） | `plugins/workspaces/services/backup_io.py` |
| D13 | 落点写文档是否新增写路径 | 否，复用 `create_document` / `update_content`（`change_type=auto_import`） | ADR 0020 I3「AI 与自动写不新增写路径」的延伸 | 新写路径：版本 / 权限 / 草稿语义会分叉 | `plugins/documents/services/content.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：把「自动获取」从「一次抓取」升级为「一条规则长期迭代」，数据表与文档共用一套规则与留痕；规则可解释（版本 + 快照 + 轮次历史）；模型参与有硬边界，换模型 / 模型不可用不阻塞采集；既有 job / provider / 文档写路径零改动。
- **负向**：新增 1 个插件、4 张表、1 条迁移与 1 次备份协议升级；规则表达能力上去后，校验与前端表单复杂度显著上升（四段式 + 布尔式 + 预算）；轮间串行意味着单策略吞吐低于并发抓取。
- **风险与缓解**：① 规则写错导致空转 —— `preview` 必须先跑通才能启用；② 文档被大量自动创建 —— 文档落点默认需人工在 `document` 决策登记（禁用 `document` 落点时不自动建页面）；③ 外部源不稳定 —— 渠道级失败隔离 + `partial` 状态 + 失败诊断动作；④ 预算失控 —— 四类上限 + 运行期记账。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 抓取 / 分页 / 游标 / 幂等 | `datasource` 服务层 | 原样复用，不改行为 | ADR 0006 / 0034 |
| 模型调用与连接 | `plugins/llm` | 唯一出口、个人连接、留痕 | ADR 0020 |
| 模型生成数据行 | `llm_prompt` provider | 作为渠道之一复用 | ADR 0014 / 0019 |
| 文档写路径与版本 | `documents.content` | 复用，不新增 | ADR 0025（原件族）/ 0057（草稿） |
| 工作区功能开关 | `workspaces.modules` | 新增 `acquisition` 功能位 | ADR 0080 |
| 质量检查 | `plugins/pipeline` | 采集后可用既有 `sync.finished` 触发检查（本期不接） | ADR 0076 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/acquisition/models.py`、`src/cndb/plugins/acquisition/plugin.py`、`src/cndb/plugins/acquisition/schemas.py`、`src/cndb/plugins/acquisition/services/channels.py`、`src/cndb/plugins/acquisition/services/targets.py`、`src/cndb/plugins/acquisition/services/runner.py`、`src/cndb/plugins/acquisition/services/validation.py`、`src/cndb/plugins/acquisition/services/rules/expr.py`、`src/cndb/plugins/acquisition/services/rules/filter.py`、`src/cndb/plugins/acquisition/services/rules/dedupe.py`、`src/cndb/plugins/acquisition/routers/strategies.py`、`src/cndb/cli/acquisition.py`、`src/cndb/alembic/versions/a7c1d2e3f4b5_add_acquisition_plugin.py` | `tests/test_acquisition_rules.py`、`tests/test_acquisition_runner.py`、`tests/test_acquisition_api.py`、`tests/test_acquisition_migration.py` | `5eae7b60` |
| P1 | 未开始 | — | — | — |
| P2 | 未开始 | — | — | — |
| P3 | 未开始 | — | — | — |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P1（P0 已提交 [5eae7b60]；正在接入多轮迭代、复核闸口与文档落点）
- 已完成：需求卡片 0085 + 本 ADR；P0 代码与测试（`tests/test_acquisition_*.py` 4 个文件，全量 `6557 passed / 17 skipped`）
- 下一步：① 提交 P0（`feat: 采集策略基础框架（ADR 0085 P0）`）；② 落 P1：`rules/{keywords,expand,stop}.py` + 轮次循环（`max_rounds`）+ `review ∈ {auto,llm,manual}` 复核闸口 + `acquisition.awaiting_review` 状态与 `POST /runs/{rid}/resume` + 文档落点与人工保护
- 已知坑：① `acquisition_item.target_id` 对表落点只记 `table_id`（不记行 id），避免行级外键随表重建失效；② 表落点去重键必须用 `match_keys` 身份（`row:` 前缀），用内容指纹会让「同一行换数值」变成新条目；③ 文档幂等依赖「最新版本 `change_type`」，与草稿（ADR 0057）并发时以「存在草稿即视为人工改动」优先；④ 备份 v13 必须与 `workspaces` 协议常量同轮改，否则 `make test` 会红在旧 v12 用例；⑤ 租约更新须 `synchronize_session=False`（SQLite 读出的 naive datetime 与 aware 参数比较会在 ORM 求值器里炸）
- 最近一次全绿：`pytest -m "not slow" -n 4` @ 2026-11-02（6557 passed / 17 skipped）；`ruff check src tests`、`pyrefly check` 0 error
