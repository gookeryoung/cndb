# ADR 0020: 大模型能力平台化（LLM Gateway + 能力目录 + 应用地图）

Status: Implemented（P0-P3 全部落地，2026-10-22）
Date: 2026-10-22
Related: `src/cndb/plugins/llm/models.py`、`src/cndb/plugins/llm/services/connection.py`、`src/cndb/plugins/llm/services/client.py`、`src/cndb/plugins/llm/services/gateway.py`、`src/cndb/plugins/llm/services/actions.py`、`src/cndb/plugins/llm/routers/config.py`、`src/cndb/plugins/llm/plugin.py`、`src/cndb/core/http.py`、`src/cndb/alembic/versions/7b8c9d0e1f2a_add_llm_plugin.py`、`tests/test_llm_platform.py`、`frontend/src/api/llm.ts`、`src/cndb/plugins/datasource/providers/llm_prompt.py`、`src/cndb/plugins/datasource/services/connection.py`、`src/cndb/plugins/datasource/models.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/services/auto_table.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/llm/routers/config.py`、`src/cndb/plugins/accounts/plugin.py`、`src/cndb/plugins/tables/services/importing/api_fetch.py`、`src/cndb/plugins/tables/services/core/access.py`、`src/cndb/plugins/tables/services/core/row_access.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/services/visibility.py`、`src/cndb/plugins/change_requests/services.py`、`src/cndb/plugins/analytics/services/templates.py`、`src/cndb/plugins/workspaces/services/search.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/core/crypto.py`、`src/cndb/core/config.py`、`src/cndb/core/events.py`、`src/cndb/core/plugin_registry.py`、`src/cndb/alembic/versions/6a7b8c9d0e1f_add_user_llm_config.py`、`frontend/src/api/llm.ts`、`frontend/src/pages/settings/LlmConfigPanel.tsx`、`frontend/src/pages/datasource/DatasourcePage.tsx`、`frontend/src/pages/datasource/llmPromptPresets.ts`、`frontend/src/components/Document/MarkdownLiveEditor.tsx`、`frontend/src/components/DiffView/index.ts`；上游见 ADR 0014 / ADR 0019
需求卡片: `docs/requirements/0020-llm-platform-capability.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」段落；ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用，不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。
>
> 与 ADR 0014 / 0019 的关系：0014 的 provider 协议、0019 的「个人级连接 + 提示词极简 + 自动落表 + 提示词可靠性」结论**继续有效**；本 ADR 只改它们的**位置**（代码归属、表名、端点、文档引用）。P0 落地时同步就地改写 ADR 0019 的「数据模型 / 判定入口 / API 变更清单 / 前端 / 与既有 ADR 的关系 / 落地状态」中被本 ADR 替代的段落（改指向 `plugins/llm/` 与 `llm_user_config`），并更新 ADR 0014 的 provider 代码落点；不保留失效表名与端点。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C12），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 大模型功能在项目的位置…重新规划设计 | 新建平台插件 `src/cndb/plugins/llm/`：`models.py`（`llm_user_config` / `llm_run`）、`services/connection.py`（个人连接）、`services/client.py`（OpenAI 兼容调用 + 重试）、`services/gateway.py`（唯一调用网关）、`services/actions.py`（动作注册表）、`services/parsing.py`（JSON 围栏 / 截断识别，自 `llm_prompt.py` 迁入）、`routers/{config,actions,runs}.py`、`plugin.py`；datasource 的 `llm_prompt` 改为「构造消息 → gateway → 解析行 → 领域落表」的薄适配层；`accounts` 不再持有 LLM 配置路由 |
| C2 | 以及可以应用的地方 | 「应用地图」节给出六类场景（文档 / 数据表 / 导入 / 分析 / 搜索 / 问题与修改申请）与优先级；P1 文档、P2 导入建议与表格填充、P3 分析与搜索；每条场景标注承载端点与现有服务 |
| C3 | 必要的情况下可重构 | Decision §5/§4：只新增一条 alembic 迁移搬表（不改 `5e6f7a8b9c01` / `6a7b8c9d0e1f`；head 级旧表断言改写为「旧表不存在、新表存在」，head 常量同轮更新）；其它 provider 行为不变；AI 写路径一律复用；前端与测试同轮切端点；旧任务 / 旧配置 / v1-v7 备份兼容 |
| C4 | 请制定方案 | 本 ADR 按模板给齐数据模型 / 判定入口 / API / 边界 / 迁移 / 前端 / 测试 / 分期；Status `Proposed`，评审通过前不写实现 |
| C5 | 请制定方案和典型示例 | 附录 A-F 共 6 个典型示例（数据源接入、文档选区改写、文档摘要与标签、导入映射建议、表格字段填充、自然语言生成分析模板），每个含触发入口 / API 契约 / 提示词 / 输出 schema / 校验与失败 / 写回 / 前端 / 测试 |
| C6 | （沿用 ADR 0019 口径，位置重规划） | 连接仍为个人级一人一条；`api_key` 仍 Fernet 密文、只写不回显、不进备份；仅表名改 `llm_user_config`、端点改 `/api/v1/llm/config`（新迁移搬数据后删旧表）；凭据优先级仍是「任务会话 Key > 个人 Key」 |
| C7 | （能力复用的前提） | 新表 `llm_run`：每次调用一行，记录 `user_id / workspace_id / action / model / prompt_tokens / completion_tokens / total_tokens / latency_ms / status / error / request_id / detail`；**不存提示词与输出全文**；同时写 `core_event(action="llm.invoke")` 串联 request_id；`GET /api/v1/llm/runs` 只返回本人记录 |
| C8 | （失败可诊断） | `llm/services/errors.py` 固定四类错误：`LlmNotConfigured`(400)、`LlmUpstreamError`(502)、`LlmOutputInvalid`(422)、`LlmRateLimited`(429)；客户端对 429/5xx/超时做 ≤2 次指数退避重试（尊重 `Retry-After`），4xx 不重试；JSON / schema 校验失败在 gateway 内完成，异常上抛前不触碰业务表 |
| C9 | （必要情况下可重构的边界） | 领域 AI 端点先走本域权限（`visibility.get_visible_document_or_404`、`check_action`、`row_access`），再调 gateway；模型输入由领域构造并已按权限裁剪；写回只复用 `PUT /{doc_id}/content` / `submit`（双轨制）与 `records._dispatch_or_403`（修改申请 202）；AI 不产生版本、不做 DDL、不直接 INSERT/UPDATE |
| C10 | （位置重规划的隐私修正） | `sync_jobs` 保存任务时不再把解析后的 `url_template` / `llm.model` 写回 `request_spec`（删除 create `sync_jobs.py:180-199` 与 update `:284-285` 两处持久化）；运行 / 预览期解析；显式任务配置仍优先；备份导出因此不再包含个人地址 / 模型 |
| C11 | （前端可复用） | 新增 `frontend/src/api/llm.ts`、`frontend/src/hooks/useLlmAction.ts`、`frontend/src/components/Ai/`（`AiActionButton` / `AiResultDrawer` / `AiSuggestionList`，全部 lazy）；结果统一「建议 → 预览 → 确认」；第一版同步 JSON，不引入 SSE |
| C12 | （不回归） | `llm_prompt` 的 provider 协议、极简表单、自动建表 / 补字段 / 自动幂等键、`render_text_lenient`、`DEFAULT_MAX_TOKENS=4096`、截断提示、连通测试行为全部保留；只改连接来源与模块位置；其它 provider 一行不改 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，本轮变更前口径；编号沿用需求卡片「现状影响面」）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `llm_prompt` provider 自建请求体、直接调用模型、自行解析 JSON 与截断识别 | `src/cndb/plugins/datasource/providers/llm_prompt.py:159-246`（构造）、`:383-432`（解析）、`:477-486`（用量） | 调用能力与「提示词→落表」领域语义耦合在同一文件，文档 / 表格 / 分析无法复用；换模型协议要改 provider | 确认（C1） |
| 2 | 个人连接读取 / 解密 / 默认值补全在 datasource 服务层；表模型也在 datasource | `src/cndb/plugins/datasource/services/connection.py:42-84`、`src/cndb/plugins/datasource/models.py:74-97` | 「平台配置」挂在领域插件里，其它插件要用连接必须依赖 datasource | 确认（C1/C6） |
| 3 | 个人配置路由在 accounts，却 import datasource 的 models / provider / connection / runner | `src/cndb/plugins/accounts/routers/llm_config.py:25-33`、`src/cndb/plugins/accounts/plugin.py:17,42` | 已存在 accounts → datasource 反向依赖；当前因插件字典序发现（`src/cndb/core/plugin_registry.py:67`）与 runner 函数内延迟 import 才未成环，新增模块级依赖即可能成环 | 确认（C1/C3） |
| 4 | 任务保存时把个人连接的地址 / 模型解析后写回 `request_spec` 并持久化，create 与 update 两条路径都写 | `src/cndb/plugins/datasource/routers/sync_jobs.py:180-199`（create 持久化）、`:284-285`（update 持久化）、`src/cndb/plugins/datasource/services/runner.py:300-322`（解析） | 任务随工作区备份导出（`src/cndb/plugins/workspaces/routers/workspaces.py:587`）→ 个人地址 / 模型外泄；且解析结果成为显式覆盖，用户改个人配置后存量任务仍跑旧模型；`tests/test_datasource_api.py:351-364` 还断言了该持久化行为，删除时必红 | 新增（C10） |
| 5 | 模型调用走 `fetch_json`：禁内网 / localhost / 保留网段；POST 不重试 | `src/cndb/plugins/tables/services/importing/api_fetch.py:184-192,546` | 本地 Ollama / 内网模型网关不可用；429 / 5xx 直接失败，无退避重试 | 确认（C8） |
| 6 | 没有调用级留痕与用量汇总，只有任务运行明细里的响应元数据 | `providers/llm_prompt.py:477-486` → `services/pipeline.py:106-107` → `services/runner.py:480` | 无法回答「谁在何时调了多少 token / 失败几次」；无法做配额与成本观察 | 确认（C7） |
| 7 | 文档写路径是双轨制；读权限有草稿 / 归档可见性收敛；编辑器已有选区 API | `src/cndb/plugins/documents/routers/documents.py:413-467,387-410`、`src/cndb/plugins/documents/services/visibility.py:24,125`、`frontend/src/components/Document/MarkdownLiveEditor.tsx:41-50` | AI 改写只需改编辑器内存态；写回必须复用 `resolve_write_mode`，不能另开写路径 | 确认（C2/C9） |
| 8 | 表格写路径按角色 / 表级 / 行级 / 字段隐藏分层判定，无直编资格转修改申请 | `src/cndb/plugins/tables/routers/records.py:50`（`_dispatch_or_403`）、`:269`（PATCH 更新）、`src/cndb/plugins/change_requests/services.py:65-118`、`src/cndb/plugins/tables/services/core/row_access.py:173`、`access.py:294` | 表格 AI 填充的输入必须按字段隐藏裁剪，写回必须逐行走既有分派 | 确认（C9） |
| 9 | 导入分析已有确定性清洗建议与表头打分（ADR 0018），无 AI 参与 | `src/cndb/plugins/tables/services/importing/importer.py:172,258`、`routers/import_csv.py:36-63` | AI 只能补「列映射建议」，不能替代确定性表头识别，也不能跳过 pending_confirm | 确认（C2） |
| 10 | 分析模板有唯一校验入口（公式语法 / 字段引用 / 聚合） | `src/cndb/plugins/analytics/services/templates.py:33-125` | NL 生成配置必须过 `normalize_config`；analytics 模板不在工作区备份内（`workspaces/routers/workspaces.py:603-611`） | 确认（C2） |
| 11 | 前端只有「配置 + 填提示词」两处大模型触点，无调用态 UI 与共享组件 | `frontend/src/api/llmConfig.ts:54-64`、`frontend/src/pages/settings/LlmConfigPanel.tsx`、`frontend/src/pages/datasource/DatasourcePage.tsx:659-717,1499-1547` | 每个功能都要复制一套 loading / 错误 / 预览，且容易各自实现权限与写回 | 确认（C11） |
| 12 | 现有测试基线以 datasource / accounts 位置组织 | `tests/test_datasource_llm_provider.py`、`test_datasource_llm_config.py`、`test_datasource_auto_table.py`、`test_datasource_runner.py`、`test_datasource_api.py`、`test_datasource_backup.py`、`test_datasource_migration.py`、`test_migration_missing_model_columns.py`；前端 `LlmConfigPanel.test.tsx`、`SettingsModal.test.tsx`、`DatasourcePage.test.tsx`、`llmPromptPresets.test.ts` | 位置搬迁必须同轮改 import / mock 路径，断言语义保持不变 | 确认（C3/C12） |
| 13 | 迁移链式历史 + 测试直接断言旧表；head 常量写死 | `src/cndb/alembic/versions/6a7b8c9d0e1f_add_user_llm_config.py:25`、`tests/test_datasource_migration.py:19-23,182-344`、`tests/test_migration_missing_model_columns.py:35` | 不能改 / 删旧迁移；搬表只能新增迁移 + 更新 head 常量；head 级「旧表存在」断言需改为「旧表已删、新表存在」；downgrade 语义与既有迁移一致（数据不恢复） | 确认（C3） |
| 14 | 备份 v7 不导出 `llm_config` 键，但任务 `request_spec` 里的个人地址 / 模型仍随任务导出 | `src/cndb/plugins/workspaces/services/backup_io.py:395-396`（v7 排除注释）、`workspaces/routers/workspaces.py:604`（版本字面量）、`:587`（任务导出） | 「个人配置不进备份」只对连接表成立，对烘进任务的默认值不成立 | 确认（C10） |
| 15 | 前端无 SSE / 流式通道（axios JSON、30s 超时）；bundle budget 余量很小 | `frontend/src/api/client.ts:93-97`、`frontend/scripts/bundle-budget.json:3,16` | 第一版必须同步 JSON；AI 组件必须 lazy，否则表页 chunk 超限 | 确认（C11） |

**位置对照（重构前 → 重构后）**：

| 能力 | 现在位置 | 目标位置 |
|---|---|---|
| 个人连接（表 + 配置） | `datasource/models.py:74-97`（`datasource_user_llm_config`）、`accounts/routers/llm_config.py` | `plugins/llm/models.py`（`llm_user_config`）、`llm/routers/config.py` |
| 连接解析 / 解密 / 默认值 | `datasource/services/connection.py:42-84` | `llm/services/connection.py` |
| 模型 HTTP 调用 | `datasource/providers/llm_prompt.py` 内联构造 `FetchConfig` | `llm/services/client.py`（重试 + SSRF 白名单 + JSON 模式） |
| JSON / 截断解析 | `llm_prompt.py:383-432` | `llm/services/parsing.py`（`llm_prompt` 复用，行为不变） |
| 调用留痕 / 用量 | 无（仅 `run.detail` 附带响应元数据） | `llm/models.py`（`llm_run`）+ `core_event("llm.invoke")` |
| 提示词预设（8 组） | `frontend/src/pages/datasource/llmPromptPresets.ts` | 不变（领域预设留在 datasource 页；平台只放动作级提示词） |
| 提示词 → 行 → 幂等落表 | `datasource/providers/llm_prompt.py`、`services/auto_table.py`、`services/write.py` | 不变（领域语义保留在 datasource） |
| 文档 AI（改写 / 摘要 / 标签） | 不存在 | `documents/services/ai.py` + `documents/routers/documents.py` 的 `/ai/actions/...` |
| 表格 / 导入 AI | 不存在 | `tables/services/ai.py` + tables / import 路由的 `/ai/...` |
| 分析 AI | 不存在 | `analytics/services/ai.py` + `analytics/routers/` |
| 前端 AI 入口 | 无共享层（只有配置页与数据源内嵌 Modal） | `frontend/src/api/llm.ts` + `hooks/useLlmAction.ts` + `components/Ai/*` |

**核心缺陷（需求要补的）**：大模型能力今天是「某一种数据源 provider 的内部实现 + 挂在 accounts 上的个人配置路由」——**位置错了**。它既是跨插件的基础设施（连接、调用、解析、留痕），又是数据同步的领域细节（提示词→JSON→幂等落表），两者混在 `plugins/datasource/` 里，导致：别的功能要用模型只能复制代码或反向依赖；调用可靠性、用量、失败口径没有统一落点；配置归属与代码归属分离（accounts 反向 import datasource）。因此本 ADR 不是「再加几个 AI 功能」，而是先把能力归位，再用「动作 + 网关」把它变成可被各插件安全复用的基础设施。

设计目标（不变量）：

- **I1 调用只有一个出口**：模型 HTTP 调用只允许经 `llm/services/client.py`；连接只允许从个人配置解析（任务会话 Key 仅作为 `llm_prompt` 的凭据来源保留）。领域插件不得自建 `fetch_json` 调用。
- **I2 依赖单向**：`plugins/llm/` 只依赖 `core/`（含新 `core/http.py`）与 `accounts.models.User`（FK / 类型）；**不得 import 任何领域插件**（datasource / documents / tables / analytics / workspaces / issues / change_requests）。HTTP 传输层随 P0 上移到 `core/http.py`（`tables/services/importing/api_fetch.py` 保留 re-export 兼容），避免 llm→tables 与 P2 起 tables→llm 形成双向模块边。领域插件 → llm 允许。
- **I3 权限同源**：AI 读复用既有可见性 / 行级权限 / 字段隐藏；AI 写不新增写路径，只复用保存与修改申请；AI 永不产生版本、DDL、直接落行。
- **I4 输出可校验**：结构化动作必须声明 Pydantic 输出 schema；校验失败不返回半成品、不写业务数据；自由文本动作（改写）返回纯文本并限制长度。
- **I5 敏感内容不落库**：`llm_run` 只存元数据与摘要（长度、目标 id、错误摘要），不存提示词与输出全文；Key 不落 `request_spec`、不进备份。
- **I6 配置不烘进任务**：连接默认值只在运行 / 预览期解析，不持久化进任务配置（修复现状 #4）。
- **I7 失败可诊断可重试**：四类失败固定状态码与文案；只有 429 / 5xx / 超时可重试（≤2 次），4xx 不重试；非法输出零副作用。
- **I8 存量零回归**：旧 `llm_prompt` 任务、旧个人配置数据、v1-v7 备份、其它 provider 行为全部不变；旧端点删除但前端与测试同轮切换。
- **I9 每次调用可追溯**：一条 `llm_run` + 一条 `core_event`，带 `request_id`，可与访问日志 / 慢查询日志关联。
- **I10 前端可复用且不膨胀**：共享 hook / 组件 + 懒加载 + 同步 JSON；新增 AI 面不突破 bundle budget。

## Decision

### 1. 数据模型

**新表 `llm_user_config`**（模型 `LlmUserConfig`，从 `datasource_user_llm_config` 原样搬迁，不加列）：

| 列 | 类型 | 约束 / 说明 |
|---|---|---|
| `user_id` | int | 唯一键（`ix_llm_user_config_user_id`），一人一条；随用户级联删除 |
| `base_url` | varchar(512) | OpenAI 兼容端点，保存时校验 http(s) |
| `model` | varchar(128) | 非空，默认 `deepseek-chat` |
| `api_key` | varchar(1024) | Fernet 密文（`enc:v1:` 前缀），空 = 未配置；只写不回显 |
| `system_prompt` | text | 可选覆盖，空串 = 用内置默认 |
| `created_at` / `updated_at` | — | 沿用 `TimestampMixin` |

**新表 `llm_run`**（模型 `LlmRun`，调用留痕）：

| 列 | 类型 | 约束 / 说明 |
|---|---|---|
| `id` | int | 主键 |
| `user_id` | int | FK `accounts_user.id`，`ondelete=CASCADE`，索引 |
| `workspace_id` | int | 可空（无工作区语义的动作留空），索引 |
| `action` | varchar(64) | 动作名，如 `document.polish` / `datasource.llm_prompt` |
| `model` | varchar(128) | 实际使用的模型 |
| `status` | varchar(16) | `success` / `failed` |
| `latency_ms` | int | 端到端耗时 |
| `prompt_tokens` / `completion_tokens` / `total_tokens` | int | 上游未返回时记 0 |
| `error` | text | 失败摘要（≤500 字，不含提示词 / 输出全文） |
| `detail` | JSON | `{target_type, target_id, input_chars, output_chars, attempts, request_id}` 等定位信息 |
| `created_at` | — | 索引（按时间倒序查「我的调用」） |

- **删除**旧表 `datasource_user_llm_config`（由新增迁移在搬迁后删除）；`datasource_llm_config` 早已由 `6a7b8c9d0e1f` 删除，不再出现。
- `datasource_sync_job` 不加列；`request_spec` 结构不变，但**不再持久化**连接默认值（I6）。
- `llm_run` 与 `llm_user_config` 都**不进工作区备份**（不是工作区数据）；`llm_run` 默认保留 90 天，提供 `cndb llm prune --days N`。

### 2. 判定入口（唯一实现）

**归属判定规则**（决定「某段代码该放哪」的四条规则，后续新增 AI 能力按此归位）：

1. **有表 / 迁移 / 端点 / 插件生命周期** → 独立插件 `plugins/llm/`（平台插件）；
2. **无状态横切能力**（加密、配置、事件、限流） → `core/`（本 ADR 只新增 settings 字段，不新增 core 模块）；
3. **领域输入构造 / 权限校验 / 输出落库或写回** → 该领域插件（documents / tables / analytics / …），平台不得代做；
4. **可复用 UI 交互**（触发 / 预览 / 确认） → 前端共享层 `frontend/src/components/Ai/` + `hooks/`，各页面只放入口。

**目录与职责**（新建 `src/cndb/plugins/llm/`）：

```
plugins/llm/
  plugin.py                 # 注册 models / routes；无侧边导航、无 APP 入口
  models.py                 # LlmUserConfig / LlmRun
  services/
    connection.py           # find_user_config / load_connection / resolve_defaults（自 datasource 迁入）
    client.py               # complete(messages, ...) -> LlmResponse：OpenAI 兼容 + 重试 + 超时
    parsing.py              # strip_json_fences / _looks_truncated / rows 解析（自 llm_prompt 迁入）
    errors.py               # LlmNotConfigured / LlmUpstreamError / LlmRateLimited / LlmOutputInvalid
    gateway.py              # invoke(action, messages, schema) -> LlmResult：唯一调用入口 + 留痕
    actions.py              # ActionSpec 注册表（领域插件注册，llm 不反向依赖）
    presets.py              # 平台级提示词预设（数据源 8 组仍留在前端 datasource 页）
  routers/
    config.py               # GET|PUT /config、POST /config/test
    actions.py              # GET /actions（能力目录，只读）
    runs.py                 # GET /runs（本人调用记录）
```

**唯一调用链**（所有领域动作共用）：

```python
# cndb/plugins/llm/services/gateway.py
@dataclass(frozen=True, slots=True)
class ActionSpec:
    name: str                      # "document.polish"
    label: str                     # 前端展示名
    scope: str                     # "document" / "table" / "import" / "analytics" / "personal"
    output_schema: type[BaseModel] | None   # 结构化动作必填；None 表示自由文本
    system_prompt: str             # 动作级系统提示词（与用户个人 system 覆盖合并，见下）
    max_tokens: int = 4096
    temperature: float = 0.2
    json_mode: bool = False
    max_input_chars: int = 12000

def invoke(
    db: Session,
    user: User,
    action: ActionSpec,
    variables: Mapping[str, Any],
    *,
    context: LlmContext,           # workspace_id / target_type / target_id
    connection: LlmConnection | None = None,
) -> LlmResult:
    """校验连接 → 渲染提示词 → 调上游 → schema 校验 → 写 llm_run + core_event → 返回。"""
```

- 连接解析：`connection.load_connection(db, user_id)`（自 datasource 迁入，语义不变）；无 Key → `LlmNotConfigured`（400，文案指向「个人设置 → 大模型」）。
- 系统提示词三层优先级沿用 ADR 0019：**任务 / 动作显式 system > 个人连接覆盖 > 内置默认**；动作级 system 与个人覆盖按「动作 system + 个人覆盖」拼接，最后追加 JSON 指令（结构化动作）。
- 输出校验：`output_schema is not None` 时 `Output.model_validate(parsed)`；失败 → `LlmOutputInvalid`（422），不写业务数据。
- 留痕：无论成败都在 `finally` 写 `llm_run` 与 `core_event(action="llm.invoke", target_type="llm")`；`core/events.py` 增加 `ACTION_LLM_INVOKE` / `TARGET_LLM` 常量。
- **不提供通用执行端点**：`POST /llm/actions/{name}` 故意不存在。领域数据的输入构造与权限校验必须留在领域路由，`llm` 只接收「已授权、已裁剪」的 messages（D5）。
- 动作注册：领域插件在自己的 `services/ai.py` 模块 import 时调用 `actions.register(ActionSpec(...))`；`llm` 不 import 领域。`GET /llm/actions` 返回已注册动作的 `{name,label,scope,enabled}`，供前端决定入口显隐。

**客户端**（`services/client.py`）：

```python
def complete(connection: LlmConnection, *, messages, model, temperature,
             max_tokens, json_mode, timeout=None) -> LlmResponse
```

- 复用 `core/http.py` 的 `fetch_json`（自 `api_fetch.py:512` 迁入）发 POST，复用其 SSRF / 超时 / 响应体上限；**不重试**交给本模块的显式重试循环（`_RETRYABLE_STATUS = {429, 500, 502, 503, 504}` + 超时；最多 2 次，指数退避 0.5s/1.5s，优先 `Retry-After`）。
- 解析 `choices[0].message.content`、`usage`、`model`；空 content → `LlmUpstreamError`。
- SSRF：默认沿用 `validate_url`（禁内网 / localhost）；新增 `settings.LLM_PRIVATE_HOST_ALLOWLIST: list[str] = []`（env `LLM_PRIVATE_HOST_ALLOWLIST`），命中白名单才放行内网主机；**只对 LLM 客户端生效**，不改变 `fetch_json` 对其它 provider 的语义（D10）。

**HTTP 传输层上移（P0 前置）**：`tables/services/importing/api_fetch.py` 的实现（`FetchConfig` / `fetch_json` / `validate_url` / 响应处理器 / 重试退避常量）整体迁入 `core/http.py`；原模块保留 `from cndb.core.http import ...` 的 re-export（现有 `~10` 处 import 与测试无需改动）。`llm/services/client.py` 只 import `cndb.core.http`，从根上消除 llm→tables 的模块边（I2）。

**datasource 适配层**（`llm_prompt` 行为不变）：

- `provider.build_requests` 保留消息构造（`render_text_lenient`、`DEFAULT_SYSTEM_PROMPT`、时间 / 标的变量）与 `FetchConfig` 组装职责；`_parse_response` / `_looks_truncated` / `strip_json_fences` 迁到 `llm/services/parsing.py` 供双方复用（行为逐字不变）。
- **执行契约**：`providers/base.py` 的 `RequestPlan` 增加可选字段 `fetcher: FetchFn | None = None`（`FetchFn = Callable[[FetchConfig], list[dict]]`，默认 `None` = 现有 `fetch_json`）；`services/pipeline.py` 执行时取 `plan.fetcher or fetch_json`。`llm_prompt.build_requests` 注入 `client.as_fetcher(connection)`（内部仍接收 `FetchConfig`、保留 `response_handler` 形状，执行时套用重试与 SSRF 白名单），因此 LLM 请求**一路经 `client.py`**，而其它 provider 与 pipeline 默认行为零变化。
- **错误类型映射**：`parsing.py` 抛 `LlmOutputInvalid`；datasource 适配层捕获后转回既有 `ProviderError`，错误文案逐字保留（截断提示 / 非法 JSON 文案不变）。
- `services/runner.py` 的 `_load_llm_connection` / `_apply_llm_connection` 改为 `from cndb.plugins.llm.services.connection import ...`；自动建表 / 补字段 / 自动幂等键 / 宽松模板仍留在 datasource（D7）。
- `routers/sync_jobs.py` 删除两处持久化（create `:180-199` 与 update `:284-285`）：连接默认值只在内存中补齐用于校验 / 预览，不写回 `request_spec`（C10）；同时改写 `tests/test_datasource_api.py:351-364` 的断言。

### 3. API 变更清单

**平台级（`/api/v1/llm`，新插件）**：

| 端点 | 变更 |
|---|---|
| `GET /config` | 新增（替代 `GET /api/v1/accounts/llm-config`）：返回 `configured / base_url / model / has_api_key / system_prompt / default_system_prompt`；不回显 Key |
| `PUT /config` | 新增（替代 `PUT /api/v1/accounts/llm-config`）：局部更新；`api_key` 非空才覆盖、`clear_api_key` 清除；Fernet 加密 |
| `POST /config/test` | 新增（替代 `POST /api/v1/accounts/llm-config/test`）：可用未保存地址 / 模型 / Key，不落库 |
| `GET /actions` | 新增：能力目录（已注册动作，只读，供前端显隐入口） |
| `GET /runs` | 新增：本人调用记录（分页，可按 action / status 过滤） |
| `GET|PUT /api/v1/accounts/llm-config`、`POST /api/v1/accounts/llm-config/test` | **删除**（前端 `frontend/src/api/llmConfig.ts:54-64` 与 `tests/test_datasource_llm_config.py:36` 同轮切换） |

**领域级（各插件自有前缀，示例）**：

| 端点 | 期 | 变更 |
|---|---|---|
| `POST /api/v1/workspaces/{wid}/documents/{doc_id}/ai/actions/{action}` | P1 | 新增：文档选区改写 / 摘要 / 标签建议；动作名 `polish` / `summarize` / `suggest_tags` |
| `POST /api/v1/workspaces/{wid}/import-file/ai/mapping-suggestion` | P2 | 新增：列映射建议（只返回建议，不改导入任务） |
| `POST /api/v1/workspaces/{wid}/tables/{table_id}/ai/actions/{action}` | P2 | 新增：`fill_field`（预览 / 应用两步）；应用走既有记录写路径 |
| `POST /api/v1/workspaces/{wid}/analytics/ai/suggest-template` | P3 | 新增：自然语言 → `TemplateConfig` 建议（过 `normalize_config`，不落库） |
| `POST /api/v1/workspaces/{wid}/analytics/ai/explain` | P3 | 新增：对统计 / 汇总结果生成文字解读（只读） |
| `POST /api/v1/workspaces/{wid}/search/ai/rewrite` | P3（可选） | 新增：搜索意图改写；失败回退原查询 |

**CLI**：新增 `cndb llm test`（用个人 / 指定用户连接测一次）、`cndb llm runs [--user]`、`cndb llm prune --days N`；`cndb sync preview` 行为不变。

### 4. 边界与例外

1. **不提供通用动作执行端点**：`POST /llm/actions/{name}` 不存在；能力目录只读。领域数据只能从领域路由进入模型，平台不承担领域权限判定（I2/I3）。
2. **第一版不做流式**：前端 HTTP 客户端无 SSE 通道（`frontend/src/api/client.ts:93-97`），所有动作同步 JSON；单次输入超过 `max_input_chars` 时拒绝并提示分段，不做自动长文分片。
3. **不做多连接 / 模型档位**：一人一条连接、一个默认模型；per-action 只允许覆盖 `temperature` / `max_tokens`，不允许覆盖 `base_url` / `api_key`（数据源任务高级设置的显式 url/model 仍保留，属领域配置）。
4. **默认不支持内网 / 本地模型**：沿用 SSRF 防护；仅当主机命中 `LLM_PRIVATE_HOST_ALLOWLIST` 才放行（运维显式配置，默认空）。被否决项见 D10。
5. **AI 不写版本 / 不落库**：文档改写只改编辑器内存态，保存仍走 `PUT /{doc_id}/content` 或 `POST /{doc_id}/submit`（双轨制）；摘要 / 标签建议只有 editor+ 可经既有 `PATCH /{doc_id}` 应用，viewer 仅预览（不在本期引入「文档元数据修改申请」）。
6. **表格 AI 的输入必须裁剪**：字段隐藏（`field.hidden`）字段不进模型输入；行级权限外（`row_access` 拒绝）的行不进输入；单批最多 20 行、单字段，超出分片由前端顺序发起。
7. **表格 AI 的写回只能是既有两条路**：直编用户的更新走 `records` 写路径；无直编资格走修改申请（202）；AI 不得直接 DDL / upsert 新行（自动建表豁免仍只属于 `llm_prompt`）。
8. **导入建议不改变导入流程**：映射建议只回填前端编辑态，用户仍需走「分析 → 预览 → 确认」；已有确定性表头识别（ADR 0018）优先，AI 不替代。
9. **分析生成的配置必须过 `normalize_config`**：公式语法 / 字段引用 / 聚合校验失败即 400，不返回半成品；生成结果只填编辑态，保存仍由用户点击；analytics 模板不在备份内（既有事实）。
10. **调用留痕不存正文**：`llm_run` 只存元数据；`error` 截断 500 字且不含提示词；需要排查时按 `request_id` 关联访问日志（`core/observability.py`）。
11. **配额与限流**：进程内按用户滑窗（`settings.LLM_CALLS_PER_MINUTE`，默认 20），超限 429；多副本部署时按副本独立限流（与登录限流同口径）。
12. **Key 归属与计费**：一律用当前操作人的个人 Key；`llm_prompt` 的 CLI 路径沿用任务创建者（现状不变）；viewer 的只读动作（如文档摘要）同样消耗 viewer 自己的 Key，不代付。
13. **备份边界**：`llm_user_config` / `llm_run` 不进工作区备份；任务 `request_spec` 不再含个人地址 / 模型；`llm_prompt` 任务的显式 url/model（旧数据）保持原样（无法与个人默认值区分，不自动清理）。
14. **ADR 落地门禁**：本 ADR 经需求方 2026-10-22 确认「按建议直接开工」后进入实现（`Status: Accepted`）。P0 落地时已同步就地改写 ADR 0019 的失效段落与 ADR 0014 代码落点、`CONTEXT.md` 术语（大模型能力平台 / AI 动作 / AI 调用记录）与 `docs/adr/README.md` 索引行；P1-P3 落地时继续按同一口径回填。
15. **本期不做**（明确排除，避免范围蔓延）：跨功能 AI 助手 / 工具调用、文档问答（RAG）、问题与修改申请的 AI 分类 / 相似合并、搜索 AI 重排、图片 / OCR、自动写回且免确认的批处理。

### 5. 迁移

新增单条 alembic 迁移（建议 revision `7b8c9d0e1f2a`，`down_revision = 6a7b8c9d0e1f`）：

- **upgrade**：建 `llm_user_config`（`user_id` 唯一索引 + 级联删除）→ 从 `datasource_user_llm_config` 全量搬行（列一一对应）→ 建 `llm_run`（`user_id` / `workspace_id` / `created_at` 索引）→ 删除 `datasource_user_llm_config`；表 / 索引已存在、旧表已不存在时跳过，可重复执行（沿用 `6a7b8c9d0e1f:36-44,160-177` 的 `_table_exists` / `_indexes` 幂等守卫风格）。
- **downgrade**：重建**空**的 `datasource_user_llm_config`（列 / 索引与 `6a7b8c9d0e1f` 的 `_create_new_table` 一致：`user_id` 唯一索引 + 级联删除，**数据不恢复**，与既有迁移的 downgrade 口径一致）→ 删除 `llm_run` → 删除 `llm_user_config`；可重复执行。
- **不改任何历史迁移文件**；`tests/test_migration_missing_model_columns.py:35` 的 `HEAD_REVISION` 同轮更新为新 revision；head 级旧表断言改为「`datasource_user_llm_config` 已不存在、`llm_user_config` 存在」，并同步 `tests/test_datasource_migration.py:277`、`tests/test_datasource_llm_config.py:12` 的 `UserLlmConfig` import。
- **迁移演练**：升级前做一次全库备份；在副本上执行 `upgrade → downgrade → upgrade` 验证幂等；迁移窗口建议停写（表搬迁为秒级，SQLite 单文件库需先停进程避免 file lock）；生产回滚 = 执行 `downgrade` + 恢复升级前备份（downgrade 不恢复数据，回滚到「旧表空 + 新表数据仍在备份里」）。
- **备份**：`backup_io` 无新增导出项（两表都不属于工作区数据）；`backup_io.py:395-396` 的 v7 注释补充「个人地址 / 模型也不再写入任务配置」；`workspaces/routers/workspaces.py:604` 的版本字面量保持 `"7"`；导入端继续接受 v1-v7。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/llm.ts`（新） | `llmApi.getConfig / updateConfig / testConfig / listActions / listRuns`；类型 `LlmConfig` / `LlmRun` / `LlmAction`；`frontend/src/api/index.ts` 导出 |
| API 封装 | `frontend/src/api/llm.ts`（删） | 端点迁入 `llm.ts`；`datasource.ts` 不保留 LLM 连接类型 |
| 共享 hook | `frontend/src/hooks/useLlmAction.ts`（新） | 统一 `idle / loading / success / error` 与「确认应用」回调；30s 超时提示；错误文案直出后端 `detail` |
| 共享组件 | `frontend/src/components/Ai/`（新，lazy） | `AiActionButton`（入口按钮）、`AiResultDrawer`（结果 / Diff 预览 / 应用）、`AiSuggestionList`（建议列表）；样式只用 antd + `theme/tokens.ts`，弹层用本地 Modal / Drawer |
| 个人设置 | `frontend/src/pages/settings/LlmConfigPanel.tsx`、`SettingsModal.tsx`、`store/ui.ts` | 连接配置保留；新增「调用记录」区（最近 20 条，含模型 / token / 耗时 / 状态）；`SettingsTab` 不变 |
| 文档 | `frontend/src/components/Document/MarkdownToolbar.tsx`、`pages/documents/DocumentEditorPage.tsx` | 选区工具栏加「AI 润色 / 精简 / 扩写」；顶栏加「摘要 / 标签建议」入口；结果 Drawer 用 `components/DiffView` 展示；应用 = 写回编辑器内存态，不自动保存 |
| 表格 | `frontend/src/pages/grid/cells/buildColumns.tsx`、`frontend/src/pages/grid/gridToolbar.tsx` | 列头菜单加「AI 填充本列（预览）」；结果预览表 → 确认后逐行走既有更新 / 修改申请 202；组件 lazy import（ESLint 已禁 GridPage 静态引 Dialog/Modal/Drawer） |
| 导入 | `frontend/src/pages/import-export/ImportExportDialog/ImportPanel.tsx` | 预览页加「AI 建议列映射」按钮；建议回填映射编辑态，不自动确认 |
| 分析 | `frontend/src/pages/analytics/` | 模板编辑区加「用一句话生成分析」；生成结果填入编辑态；复用 `RecommendationPanel.tsx` 的「建议 → 一键应用」范式 |
| 测试 | 同目录 `*.test.tsx`、`frontend/tests/e2e/critical/` | 共享 hook / 组件单测；各页面入口显隐与确认流；e2e 只验 UI 与保存，不真调模型 |

### 7. 测试清单

**判定层（单测）**：
- 平台层 `tests/test_llm_platform.py`：`core.http` 的 `retry_on_status`（429 重试 / `Retry-After` 优先 / 4xx 不重试）与 `allow_hosts`；`parsing` 截断文案；`client.as_fetcher` 注入重试策略、429→`LlmRateLimited`、500→`LlmUpstreamError`；`gateway.invoke` 成功 / schema 失败留痕（不存正文）；动作注册表幂等；迁移 `7b8c9d0e1f2a` 往返；`plugins/llm` 无领域插件 import 的静态断言。
- `llm/services/client.py`：429 / 500 / 502 / 503 / 504 重试 ≤2 次并成功；400 / 401 不重试；`Retry-After` 优先；超时归类；JSON 模式关闭时不发 `response_format`。
- `providers/base.py` + `services/pipeline.py`：`RequestPlan.fetcher` 缺省 `None` 时仍走 `fetch_json`（其它 provider 零变化）；`llm_prompt` 注入的 fetcher 走 `client`（重试 / 白名单生效）。
- `llm/services/parsing.py`：`strip_json_fences`、截断识别文案与 `llm_prompt` 现状逐字一致（同一组用例从 `test_datasource_llm_provider.py` 复用）。
- `llm/services/gateway.py`：未配置 Key → `LlmNotConfigured`；schema 校验失败 → `LlmOutputInvalid` 且不写 `llm_run.status=success`；成功写 `llm_run` + `core_event`；`detail` 不含正文；`request_id` 透传。
- `llm/services/actions.py`：重复注册幂等；`GET /actions` 目录只含已注册项；`plugins/llm` 无任何 `cndb.plugins.*` import（静态断言，唯一例外是 `accounts.models.User` 类型）。
- 连接迁移：`load_connection` 未配置返回默认值、解密失败按未配置、显式任务配置优先。

**接口层**：
- `GET|PUT /api/v1/llm/config`、`POST /api/v1/llm/config/test`：默认值、加密不回显、`clear_api_key`、非法 base_url 400、未登录 401、用户间隔离、未保存 Key 测试不落库。
- 旧端点 `/api/v1/accounts/llm-config*` 返回 404。
- `GET /api/v1/llm/runs`：只返回本人记录；字段不含正文；分页与过滤。
- `sync-jobs`：只填用户提示词可保存；保存后 `request_spec` **不含** `url_template` / `llm.model`（create 与 update 两条路径都断言）；缺 Key 400 文案指向「个人设置 → 大模型」；运行 / 预览仍按操作人或创建者解析个人连接；`match_keys` 自动推断不变；改写 `tests/test_datasource_api.py:351-364`（原断言两键存在）为「两键均不存在 + 运行期仍继承个人连接」。
- 领域端点（P1-P3）：文档 404 / 403 语义、viewer 应用走 202、字段隐藏字段不进模型输入、导入建议不落库、分析生成配置过 `normalize_config` 失败 400。

**迁移 / 备份**：
- 新迁移 upgrade / downgrade 幂等；旧表数据全量搬入 `llm_user_config`；head 常量更新；downgrade 重建**空**旧表（数据不恢复）；`tests/test_datasource_migration.py:277` 与 `tests/test_datasource_llm_config.py:12` 的 `UserLlmConfig` import 改到 `plugins.llm.models`。
- 备份 v1-v7 均可导入；导出的任务配置里不出现个人 `base_url` / `model`；导入后个人配置与调用记录不受影响。

**前端（单测 / e2e）**：
- `useLlmAction` 的 loading / 错误 / 确认；`AiResultDrawer` 的 Diff 与应用回调；各入口按钮显隐（无 Key / 未注册动作）。
- `LlmConfigPanel.test.tsx` 迁到新 API mock；`DatasourcePage.test.tsx` 去掉连接入口断言、保留极简表单与预设。
- e2e：文档 AI 面板打开与「应用 → 保存」链路（mock 后端动作返回固定文本）、表格 AI 预览；只验 UI，不触发真实模型调用。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 平台归位：`plugins/llm/`（模型 / 迁移 / 连接 / client / parsing / gateway / config 与 runs 端点）+ `core/http.py` 传输层上移（`api_fetch.py` 保留 shim）+ `RequestPlan.fetcher` 执行契约 + datasource 改消费方（含「不把默认值写回任务」）+ 前端 `api/llm.ts` 与设置页迁移 + 删除 accounts 路由 + 文档同步（ADR 0014/0019 就地改写、CONTEXT 新增「大模型能力平台 / AI 动作 / AI 调用记录」三术语、README 索引） | 中（表搬迁 + 跨插件依赖 + 端点 breaking change） |
| **P1** | 文档 AI：动作注册表 + `document.polish / summarize / suggest_tags` + 共享前端三件套 + 编辑器选区入口 + Diff 预览 | 中（编辑器交互 + 双轨制写回） |
| **P2** | 导入与表格 AI：`import.mapping-suggestion`（只建议）+ `table.fill_field`（预览 → 逐行走既有写路径 / 202）+ 权限裁剪 | 高（行级权限 / 字段隐藏 / 批量写回） |
| **P3** | 分析与搜索：`analytics.suggest-template` / `analytics.explain` / `search.rewrite` + 用量页完善 + `cndb llm` CLI + 保留策略 | 中（生成配置的正确性与可校验性） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案 | 能力归位为平台插件 + 领域插件按需注册动作；先重构再扩应用 | 现状把基础设施与领域实现混在 datasource，复用只能复制；先归位后扩展才能避免每个新功能各自造轮子（I1/I2） | 继续在 datasource 里加分支（复用面为零）；直接上「AI 助手」不归位（把耦合带进更高层） | `plugins/llm/` |
| D2 | 归属位置 | 独立插件 `plugins/llm/`，不放进 `core/` | 它有自己的表、端点、迁移与配置，符合插件三件套（模型由插件 `register_models` 注册）；`core/` 只承载横切基础设施（事件流 `CoreEvent` 是唯一例外），让 core 承担插件级生命周期会破坏分层 | 放 `core/llm/`（迁移 / 端点 / 插件注册语义进 core，破坏 core 定位）；继续放 datasource（反向依赖无法消除） | `plugins/llm/plugin.py` |
| D3 | 连接表迁移方式 | 新增迁移「建 `llm_user_config` → 搬迁 → 删旧表」，与 `6a7b8c9d0e1f` 同口径；不改历史迁移 | 历史迁移被测试直接断言（`test_datasource_migration.py:182-344`），改则回归面不可控；copy+drop 已是本仓库既有先例 | `ALTER TABLE ... RENAME`（索引名残留、历史 downgrade 断言冲突）；保留旧表双写（两份配置并存） | 新迁移文件、`plugins/llm/models.py` |
| D4 | 配置端点前缀 | 新端点 `/api/v1/llm/config`；旧 `/api/v1/accounts/llm-config` 直接删除，前端与测试同轮切换 | 配置属于大模型能力，不应再由 accounts 代挂；`/llm` 前缀可与 actions / runs 共用；仓库无 API 兼容层先例（ADR 0019 也是直接删端点） | 保留 accounts 前缀（语义错位，且 actions/runs 无处安放）；加过渡别名（双端点长期并存，无移除机制） | `routers/config.py`、`frontend/src/api/llm.ts` |
| D5 | 是否提供通用执行端点 | 不提供 `POST /llm/actions/{name}`；只提供能力目录（只读） | 领域数据的权限判定只能由领域负责；通用执行端点会诱导把权限校验漏到平台层（I2/I3） | 平台统一执行（必须把领域权限塞进平台，依赖反转）；完全不暴露动作（前端无法按能力显隐） | `routers/actions.py`、`services/actions.py` |
| D6 | 动作注册方向 | 领域插件 import 时注册 `ActionSpec`；`llm` 不 import 领域，目录接口只读注册表 | 保证依赖单向（I2）；目录与代码同源，不会出现「文档写了动作但没实现」 | 平台维护动作清单（需 import 领域插件，成环）；前端硬编码能力清单（与后端漂移） | `services/actions.py`、各领域 `services/ai.py` |
| D7 | 领域语义归属 | 「提示词 → 行 → 幂等落表 / 自动建表」仍留在 datasource；平台只做调用与留痕 | 落表语义是数据同步的领域规则，上移会让平台依赖 tables / auto_table（I2） | 平台统一落表（跨域耦合）；把 autotable 做成通用能力（范围不可控） | `datasource/providers/llm_prompt.py`、`services/auto_table.py` |
| D8 | 连接默认值持久化 | 不写回 `request_spec`，运行 / 预览期解析 | 现状 #4：写回导致个人地址 / 模型随备份外泄，且用户改配置对存量任务无效（I6/C10） | 继续写回（缺陷保留）；保存时清空所有任务显式值（无法区分用户意图） | `datasource/routers/sync_jobs.py`、`services/runner.py` |
| D9 | 调用留痕形态 | 新表 `llm_run` + `core_event`；不存正文 | 需要可查用量与失败、又不能让工作区内容因 AI 调用落库（I5/I9）；事件流已提供 request_id 串联 | 只写日志（不可查、多副本分散）；把提示词 / 输出全文入库（隐私与体积风险） | `plugins/llm/models.py`、`services/gateway.py`、`core/events.py` |
| D10 | SSRF 与本地模型 | 默认沿用禁内网；新增 `LLM_PRIVATE_HOST_ALLOWLIST` 显式白名单（默认空），只作用于 LLM 客户端 | 安全默认必须保守；但自托管 Ollama 是合理需求，需要可运维的开闸方式（I7） | 全局放开 `validate_url`（削弱所有 provider 的 SSRF 防护）；永不支持内网（自托管用户被排除） | `services/client.py`、`core/config.py`、`api_fetch.py`（仅新增可选白名单参数） |
| D11 | 重试策略 | 客户端层对 429/5xx/超时重试 ≤2 次并尊重 `Retry-After`；4xx 不重试；不放宽 `fetch_json` 的 GET-only 语义 | LLM 端点最常见失败是限流与瞬时 5xx；改 `fetch_json` 会影响所有 provider（I7/C8） | 改 `fetch_json` 支持 POST 重试（回归面大）；完全不重试（限流即失败） | `services/client.py` |
| D12 | 流式与异步 | 第一版全部同步 JSON；批量动作由前端分片顺序调用；不引入队列 | 前端无 SSE 通道（`client.ts:93-97`），引入流式要重做 HTTP 客户端与 401 刷新；批量 AI 单批 ≤20 行已足够（I10） | 第一版上 SSE（前端基建缺失、工期长）；引入 Celery/RQ（部署与依赖成本高，仓库现无队列） | 无（边界） |
| D13 | 文档 AI 写回 | 改写只改编辑器内存态；摘要 / 标签只有 editor+ 经既有 PATCH 应用；viewer 只预览 | 复用双轨制与可见性语义，不新增写路径（I3/C9） | AI 直接保存版本（绕过审核）；为文档元数据新增修改申请（本期范围外） | `documents/routers/documents.py`、前端编辑器 |
| D14 | 表格 AI 写回 | 预览后逐行走 `records` 写路径（直编 / 202 修改申请）；输入按字段隐藏与行级权限裁剪；不 DDL | 行级权限与字段隐藏是安全不变量，AI 不得有旁路（I3/C9） | AI 直接批量 upsert（越权与不可审计）；只读不写（价值不足） | `tables/routers/records.py`、`change_requests/services.py` |
| D15 | 分析生成配置 | 只生成 `TemplateConfig` 建议，过 `normalize_config` 后填入编辑态，不自动保存 | 公式引擎有明确白名单与字段引用约束，LLM 输出必须被机器校验（I4） | AI 直接保存模板（脏配置入库）；AI 直接执行分析（绕过公式校验） | `analytics/services/templates.py`、`analytics/routers/` |
| D16 | 前端架构 | `api/llm.ts` + `hooks/useLlmAction.ts` + `components/Ai/*`（lazy）；统一「建议 → 预览 → 确认」 | 三处现状各自实现会重复 loading / 错误 / 权限提示；bundle budget 不允许静态引入（I10） | 每个页面自造弹窗（复制粘贴、行为漂移）；把 AI 组件静态放进 GridPage（chunk 超限，ESLint 已禁） | `frontend/src/components/Ai/` |
| D17 | 应用优先级 | 文档 → 导入建议 → 表格填充 → 分析 / 搜索；问题与修改申请 AI 本期不做 | 文档无落库风险、复用现有选区与双轨制，最快验证平台层；表格写回风险最高放后面；问题分类价值低且非阻断（C2） | 先做表格批量填充（权限与写回风险最高，平台层未验证）；先做助手（范围失控） | 分期表 |
| D18 | HTTP 传输层归属 | `fetch_json` / `validate_url` / `FetchConfig` / 响应处理器实现迁到 `core/http.py`，`tables/services/importing/api_fetch.py` 保留 re-export shim（其它 provider 与测试 import 不变）；`llm/client.py` 只 import `core.http` | I2 要求 llm 不 import 领域插件；P2 起 tables→llm 与 llm→tables 会形成双向模块边，仅靠加载顺序规避不可持续；迁移是纯机械搬迁、行为不变 | 让 llm 直接 import `tables.api_fetch`（双向依赖，随 P2 成环）；在 llm 内复制 httpx 封装（SSRF / 重试策略两份漂移） | `core/http.py`、`tables/services/importing/api_fetch.py`（shim）、`llm/services/client.py` |

门禁：本表无「待定」；需求方确认后由人工评审把 Status 从 `Proposed` 改为 `Accepted`，再进入实现。

## 应用地图（C2 落点）

| 场景 | 归属插件 | 触发入口 | 读写风险 | 优先级 | 典型示例 |
|---|---|---|---|---|---|
| 数据源提示词生成数据 | datasource | 数据源任务抽屉（既有） | 写（落表，已有自动化） | P0 保持 | 附录 A |
| 文档选区改写 | documents | 编辑器选区工具栏 | 读 + 编辑器内存态 | P1 | 附录 B |
| 文档摘要 / 标签建议 | documents | 文档顶栏 / 详情 Drawer | 读 + editor+ 应用元数据 | P1 | 附录 C |
| 导入列映射建议 | tables | 导入预览页 | 只读建议 | P2 | 附录 D |
| 表格字段批量填充 | tables | 列头菜单 / 工具栏 | 写（逐行走既有写路径） | P2 | 附录 E |
| 自然语言生成分析模板 | analytics | 分析模板编辑区 | 只读建议（用户保存） | P3 | 附录 F |
| 分析结论解读 | analytics | 统计 / 汇总结果区 | 只读 | P3 | 附录 F |
| 搜索意图改写 | workspaces | 顶栏搜索 | 只读（失败回退原文） | P3 可选 | 同 P3 |
| 问题 / 修改申请分类建议 | issues / change_requests | 详情页 | 只读建议 | 本期不做（边界 15） | — |
| 跨功能 AI 助手 | 新层 | — | 高 | 本期不做（边界 15） | — |

## Consequences

- **正向**：模型调用、连接、解析、失败口径、用量留痕收敛到一处，后续任何功能接 AI 只需「领域路由 + 注册动作 + 共享前端组件」；依赖方向固定为「领域 → llm」，accounts 反向依赖消除；个人地址 / 模型不再随任务与备份外泄；AI 复用既有权限与写路径，安全边界可审计。
- **负向**：P0 一次表搬迁 + 端点迁移是不可逆改动（downgrade 可还原结构，但需停机窗口管理）；`accounts` 与前端、测试同轮改，回归面覆盖 LLM 相关全部用例；`llm` 插件成为新的「被依赖层」，后续任何领域插件加模块级 import 都要检查依赖方向（新增静态断言测试）。
- **风险与缓解**：表搬迁失败 → 迁移幂等 + 测试覆盖 upgrade/downgrade/重复执行；端点迁移漏改 → 全局搜索 `accounts/llm-config` 并加 404 断言；AI 写回越权 → 领域端点先权限后调用 + 隐藏字段 / 行级输入裁剪测试；bundle 超限 → AI 面全部 lazy + `make frontend-static` 卡口；上游模型限流 → 客户端退避重试 + 429 文案；内网模型需求 → 显式白名单 env，默认关闭。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 数据同步框架（Provider × SyncJob × Cursor × Normalizer） | `plugins/datasource/` | 框架与 provider 协议不变；`llm_prompt` 改为消费平台网关，落表自动化仍归 datasource | ADR 0006 |
| `llm_prompt` provider 行为（极简表单 / 自动建表 / 自动幂等键 / 宽松模板 / 截断提示） | `providers/llm_prompt.py`、`services/auto_table.py`、`services/write.py` | 行为逐条保留；代码位置与连接来源改变 | ADR 0014 / ADR 0019 |
| 个人级连接与密钥口径 | `llm_user_config` → 替代 `datasource_user_llm_config` | 个人级、一人一条、Fernet 密文、只写不回显、不进备份；端点改 `/api/v1/llm/config` | ADR 0019（本 ADR 仅改位置） |
| 备份格式 | 工作区备份 v7 | 不导出个人配置；任务配置不再烘入个人地址 / 模型；导入兼容 v1-v7 | ADR 0006 / ADR 0019 / 本 ADR D8 |
| 文档双轨制写入与可见性 | `documents/services/{change_requests,visibility}.py` | AI 写回复用；不新增写路径 | ADR 0003 / 文档编辑文档 |
| 行级权限 / 字段隐藏 / 修改申请 | `tables/services/core/{access,row_access}.py`、`change_requests/services.py` | 表格 AI 输入裁剪与写回分派复用；AI 无旁路 | ADR 0004 / ADR 0005 |
| 表头识别 | `tables/services/transfer/header_detect.py` | 确定性识别优先；AI 只补列映射建议 | ADR 0018 |
| 分析模板校验 | `analytics/services/templates.py` | NL 生成配置必须过同一校验入口 | 本 ADR D15（分析模块既有约束） |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/llm/plugin.py`、`src/cndb/plugins/llm/models.py`、`src/cndb/plugins/llm/services/connection.py`、`src/cndb/plugins/llm/services/client.py`、`src/cndb/plugins/llm/services/parsing.py`、`src/cndb/plugins/llm/services/gateway.py`、`src/cndb/plugins/llm/services/actions.py`、`src/cndb/plugins/llm/services/errors.py`、`src/cndb/plugins/llm/services/prompts.py`、`src/cndb/plugins/llm/routers/config.py`、`src/cndb/plugins/llm/routers/actions.py`、`src/cndb/plugins/llm/routers/runs.py`、`src/cndb/core/http.py`、`src/cndb/plugins/datasource/providers/llm_prompt.py`、`src/cndb/plugins/datasource/providers/base.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/alembic/versions/7b8c9d0e1f2a_add_llm_plugin.py`、`frontend/src/api/llm.ts` | `tests/test_llm_platform.py`、`tests/test_datasource_llm_config.py`、`tests/test_datasource_llm_provider.py`、`tests/test_datasource_api.py`、`tests/test_datasource_migration.py`、`tests/test_migration_missing_model_columns.py`、`frontend/src/pages/settings/LlmConfigPanel.test.tsx` | a8070bb3 |
| P1 | 已落地 | `src/cndb/plugins/documents/services/ai.py`、`src/cndb/plugins/documents/services/__init__.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/schemas/__init__.py`、`src/cndb/plugins/llm/services/actions.py`、`frontend/src/api/documents.ts`、`frontend/src/hooks/useLlmAction.ts`、`frontend/src/components/Ai/AiActionButton.tsx`、`frontend/src/components/Ai/AiResultDrawer.tsx`、`frontend/src/components/Ai/AiSuggestionList.tsx`、`frontend/src/components/Ai/AiDocEntry.tsx`、`frontend/src/components/Document/MarkdownToolbar.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx` | `tests/test_documents_ai.py`、`frontend/src/hooks/useLlmAction.test.ts`、`frontend/src/components/Ai/AiActionButton.test.tsx`、`frontend/src/components/Ai/AiResultDrawer.test.tsx`、`frontend/src/components/Ai/AiSuggestionList.test.tsx`、`frontend/src/components/Ai/AiDocEntry.test.tsx`、`frontend/src/components/Document/MarkdownToolbar.test.tsx`、`frontend/src/pages/documents/DocumentEditorPage.test.tsx` | e77c7ff8 |
| P2 | 已落地 | `src/cndb/plugins/tables/services/ai.py`、`src/cndb/plugins/tables/routers/ai.py`、`src/cndb/plugins/tables/routers/import_ai.py`、`src/cndb/plugins/tables/routers/__init__.py`、`frontend/src/api/tables.ts`、`frontend/src/api/importExport.ts`、`frontend/src/pages/grid/cells/buildColumns.tsx`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/aiFillField/AiFillFieldDrawer.tsx`、`frontend/src/pages/import-export/ImportExportDialog/ImportPanel.tsx`、`src/cndb/plugins/tables/models.py`、`src/cndb/plugins/tables/services/importing/import_tasks.py`、`src/cndb/plugins/tables/routers/bulk_import.py`、`src/cndb/alembic/versions/9d0e1f2a3b4c_add_import_column_mapping.py` | `tests/test_tables_ai.py`、`tests/test_import_ai_mapping.py`、`tests/test_import_column_mapping.py`、`frontend/src/pages/grid/aiFillField/AiFillFieldDrawer.test.tsx`、`frontend/src/pages/grid/GridPage.aiFill.test.tsx`、`frontend/src/pages/grid/cells/buildColumns.aiFill.test.tsx`、`frontend/src/pages/import-export/ImportExportDialog/ImportPanel.aiMapping.test.tsx` | 1c944408 |
| P3 | 已落地 | `src/cndb/plugins/analytics/services/ai.py`、`src/cndb/plugins/analytics/routers/ai.py`、`src/cndb/plugins/analytics/plugin.py`、`src/cndb/plugins/analytics/services/__init__.py`、`src/cndb/plugins/workspaces/services/ai.py`、`src/cndb/plugins/workspaces/routers/search.py`、`src/cndb/cli/llm.py`、`src/cndb/cli/main.py`、`frontend/src/api/analytics.ts`、`frontend/src/pages/analytics/analyticsAi.ts`、`frontend/src/pages/analytics/AnalyticsAiPanel.tsx`、`frontend/src/pages/analytics/AnalyticsAiExplainDrawer.tsx`、`frontend/src/pages/analytics/AnalyticsPage.tsx`、`frontend/src/pages/analytics/AnalyticsResultView.tsx`、`frontend/src/pages/settings/LlmConfigPanel.tsx` | `tests/test_analytics_ai.py`、`tests/test_llm_cli.py`、`frontend/src/pages/analytics/analyticsAi.test.ts`、`frontend/src/pages/analytics/AnalyticsPage.test.tsx`、`frontend/src/pages/settings/LlmConfigPanel.test.tsx` | 523b244a |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系；提交列由 Lead 在提交后回填 sha。

## 交接（会话结束更新）

- 当前阶段：P3 已落地（分析 AI 生成模板 / 结论解读、搜索意图改写端点、`cndb llm` CLI、个人设置调用记录）；ADR 0020 P0-P3 全部落地
- 已完成：现状盘点；应用地图与 6 个典型示例；P0 平台归位；P1 文档 AI；P2 表格与导入 AI；P3 分析与搜索 AI（`analytics.suggest_template` 过 `normalize_config` 后只填编辑态、`analytics.explain` 只读解读、`search.rewrite_query` 失败回退原查询；`cndb llm test/runs/prune`；个人设置调用记录）
- 下一步：人工验收与真机联调（配置真实个人 Key 走一遍 P1-P3 入口）→ `make push` 推远端 → 视需要更新 bundle budget 基线（当前主入口 / GridPage 为 P1-P2 累计 warn，未超上限）
- 追加（2026-10-22，ADR 0020 补全）：AI 列映射建议真正落库（ImportTask.column_mapping + 迁移 9d0e1f2a3b4c，analyze/confirm/reanalyze/execute 全链路）；新增 AI 入口 e2e（rontend/tests/e2e/critical/ai-entrypoints.spec.ts，3 例，不调真实模型）；undle-budget.json 按实测收口（主入口 179886 / GridPage 33806 / ChartView 14472）
- 已知坑：历史迁移不可改、表名被测试断言（只能新增迁移搬表 + 更新 head 常量）；`fetch_json` 禁内网且 POST 不重试（LLM 客户端自带重试与白名单，不改其全局语义）；`test_plugin_registry` 断言内置插件无 APP 入口（新插件不得注册 apps）；前端无 SSE、bundle budget 余量小（AI 面必须 lazy、第一版同步 JSON）；analytics 模板不在工作区备份内；旧任务 `request_spec` 里已烘入的个人地址 / 模型无法与新数据区分，不自动清理；个人配置与调用记录不进备份，换环境需各自重配；**导入 AI 映射建议已接入导入链路（确认导入时按 `column_mapping` 写入目标字段，迁移 `9d0e1f2a3b4c`）**；表格 AI 应用为逐行串行 PATCH，20 行最坏需数十秒
- 最近一次全绿：`make flow`（2026-10-22：check-fast 全绿；后端 5350 passed / 8 skipped）+ `make cov` 97.39% + `make frontend-coverage`（核心行 97.55% / branches 100%；全局 82.10%）+ `make e2e` 入口用例 3 passed + `make check-docs` 0 error / 0 warning；本轮改动未提交

## 附录：典型应用示例（C5 落点）

> 示例中的端点与既有路由前缀一致：documents / tables / analytics / search 均挂在 `/api/v1/workspaces/{wid}/...`（插件 `route_prefix="workspaces"`）；平台端点挂在 `/api/v1/llm/...`。提示词里的 `{{` / `}}` 是模板语法的字面花括号，运行时还原为 `{` / `}`。

### 附录 A：`llm_prompt` 接入平台层（P0，行为不变的基准示例）

**目的**：验证「归位」不改变行为，是 P0 的回归基准。

| 项 | 内容 |
|---|---|
| 触发入口 | 数据源同步 → 新建 / 编辑任务 → provider 选「大模型提示词」（既有页面） |
| 改动前 | `ds/providers/llm_prompt.py` 直接构造 `FetchConfig` 调 `fetch_json`；连接来自 `ds/services/connection.py`；配置路由在 `accounts` |
| 改动后 | 消息构造仍在 provider；HTTP 调用走 `llm/services/client.py`；JSON 解析走 `llm/services/parsing.py`；连接来自 `llm/services/connection.py`；配置路由在 `llm/routers/config.py` |
| 不改 | `request_spec.prompt.user_template` 极简表单、`DEFAULT_SYSTEM_PROMPT`、`render_text_lenient`、自动建表 / 补字段 / 自动幂等键、`max_tokens=4096`、截断提示、`datasource_session` Key 优先 |
| 新增约束 | 保存（create 与 update）后 `request_spec` 不再含 `url_template` / `llm.model`（D8）；运行 / 预览期解析个人连接；LLM 请求经 `RequestPlan.fetcher` 注入的 `client`（重试 / 白名单生效），其它 provider 仍走 `fetch_json` |
| 测试 | 既有 `tests/test_datasource_llm_provider.py` / `test_datasource_auto_table.py` / `test_datasource_runner.py` 只改 import 与 mock 路径，断言语义不变；`tests/test_datasource_api.py:351-364` 改写为「保存后两键均不存在 + 运行期仍继承个人连接」；新增断言：create 与 update 两条路径都不写回 |

### 附录 B：文档选区改写（P1，自由文本动作）

**触发入口**：文档编辑器选区后点「AI 润色 / 精简 / 扩写」；结果以 Diff 预览，确认后写回编辑器内存态（不自动保存）。

**API**：

```http
POST /api/v1/workspaces/12/documents/345/ai/actions/polish
{
  "selection": "该方案需要对现有流程进行重新梳理，从而提升整体效率。",
  "instruction": "polish",          // polish / shorten / expand / formal / translate
  "language": "zh",                 // translate 时必填
  "context": "一级标题：第三章 流程优化"   // 可选，帮助保持术语一致
}
→ 200
{
  "action": "document.polish",
  "run_id": 8891,
  "result": {"text": "该方案需重新梳理现有流程，以提升整体效率。"},
  "usage": {"model": "deepseek-chat", "total_tokens": 214, "latency_ms": 1280}
}
```

**动作定义**（`documents/services/ai.py` 注册）：

```python
POLISH = ActionSpec(
    name="document.polish", label="AI 润色", scope="document",
    output_schema=PolishOutput,             # {"text": str}
    system_prompt=(
        "你是中文文档编辑助手。只改写用户给出的片段，保持原意、术语与事实，"
        "不要添加原文没有的信息，不要输出解释、标题或 Markdown 代码围栏。"
        "输出 JSON：{{\"text\": \"改写后的片段\"}}。"
    ),
    temperature=0.3, max_tokens=1500, json_mode=True, max_input_chars=4000,
)
```

**服务端流程**（`documents/routers/documents.py` 新增）：

1. `services.visibility.get_visible_document_or_404(db, wid, doc_id, user)` → 404 语义不变；
2. `selection` 长度 ≤ 4000，`instruction` 白名单校验；
3. 组装 `messages`（系统提示词 + 用户内容：`{instruction}\n标题：{doc.title}\n片段：{selection}`）；
4. `gateway.invoke(db, user, POLISH, variables, context=LlmContext(workspace_id=wid, target_type="document", target_id=doc_id))`；
5. schema 校验 `PolishOutput`，返回结果 + `run_id`。

**失败口径**：未配置 Key → 400（提示去个人设置）；429 → 429 并带「稍后重试」；输出非 JSON / schema 不符 → 422（用户可重试，无副作用）；文档不存在 / 无权限 → 404（不泄露存在性）。

**前端**：`MarkdownToolbar` 选区态显示入口（lazy）；`AiResultDrawer` 展示原片段与新片段的 Diff；「应用」调用编辑器 `setSelection` 替换文本；「重新生成 / 取消」保留原选区。

**测试**：接口测试用 mock gateway 返回固定 `{"text": ...}`；断言选区为空 400、超长 400、非成员 404；前端单测断言确认后文本被替换且不触发保存请求。

### 附录 C：文档摘要 + 标签建议（P1，结构化动作 + 用户确认）

**触发入口**：文档详情页「AI 摘要 / 标签建议」；结果抽屉展示，editor+ 可「应用到文档」（走既有 `PATCH /{doc_id}`），viewer 只读。

**API**：

```http
POST /api/v1/workspaces/12/documents/345/ai/actions/summarize
{}  → 200
{
  "action": "document.summarize",
  "run_id": 8892,
  "result": {
    "summary": "本文给出流程优化的三步方案：梳理现状、收敛审批环节、建立指标看板。",
    "key_points": ["现状流程有 5 个审批节点", "建议收敛到 3 个", "以周均时长作为指标"],
    "suggested_tags": ["流程优化", "审批效率", "指标看板"]
  },
  "usage": {"model": "deepseek-chat", "total_tokens": 1024, "latency_ms": 2210}
}
```

**输出 schema**：

```python
class SummarizeOutput(BaseModel):
    summary: str = Field(min_length=10, max_length=200)
    key_points: list[str] = Field(default_factory=list, max_length=5)
    suggested_tags: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("suggested_tags")
    @classmethod
    def _tag_shape(cls, v: list[str]) -> list[str]:
        return [t.strip() for t in v if t.strip()][:5]
```

**提示词**（动作级 system + 用户内容）：

```text
你是文档摘要助手。阅读用户给出的文档正文，输出 JSON：
{{"summary": "不超过 120 字的中文摘要", "key_points": ["3-5 条要点"], "suggested_tags": ["3-5 个 2-6 字中文标签"]}}
只依据正文内容，不要编造正文没有的事实；无法总结时 summary 用空串、其余为空数组。
```

**服务端约束**：正文取「最新版本」内容（`services.content.latest_version` + `load_content`），超过 `max_input_chars=12000` 时截取前 12000 字并在 `detail.truncated=true` 留痕；`suggested_tags` 只作为建议返回，**不自动创建标签**；应用由前端调既有 `PATCH`（editor+ 才允许，viewer 收到 403 时只展示只读结果）。

**测试**：schema 越界（summary 超 200 字 / tags 超 5 个）→ 422；截断标志；viewer 调 PATCH 403；应用标签走既有 `_apply_tags` 行为不变。

### 附录 D：导入列映射建议（P2，只读建议）

**触发入口**：导入预览页「AI 建议列映射」；建议回填到现有映射编辑态，仍由用户确认后导入。

**API**：

```http
POST /api/v1/workspaces/12/import-file/ai/mapping-suggestion
{
  "target_table_id": 77,
  "headers": ["日期", "代码", "收盘价(元)", "涨跌%"],
  "sample_rows": [["2026-10-20", "600519", "1277.96", "+1.23"], ["..."]],
  "existing_mapping": {"日期": "trade_date"}
}
→ 200
{
  "action": "import.mapping-suggestion",
  "run_id": 8893,
  "result": {
    "mappings": [
      {"source": "代码", "target": "symbol", "confidence": 0.93, "reason": "列名与目标字段语义一致"},
      {"source": "收盘价(元)", "target": "close", "confidence": 0.88, "reason": "括号内单位提示数值列"},
      {"source": "涨跌%", "target": "change_pct", "confidence": 0.81, "reason": "百分比列"}
    ],
    "unmapped": []
  }
}
```

**输入构造**（`tables/services/importing/ai_mapping.py`）：

- 目标字段来自 `DataTable.active_fields()`，丢弃 `hidden` 字段（字段隐藏不进入模型输入）；
- `headers` ≤ 50、`sample_rows` ≤ 20 行 × 200 字符 / 单元格；
- 已有确定性分析结果（`importer.analyze` 的 `cleaning_suggestions` / 表头识别）作为白名单与提示上下文，AI 不得改写表头判定。

**校验**：`target` 必须在目标字段集合内；`confidence` ∈ [0,1]；重复 `source` / 重复 `target` 去重并保留最高置信度；**只返回建议，不修改 `ImportTask` 任何字段**。

**测试**：目标字段含隐藏字段时不出现在候选；非法 target 被过滤；断言业务表零变更（`ImportTask` / 数据表不变），仅 `llm_run` 新增一条留痕；映射建议在前端可一键填充且仍需「确认导入」。

### 附录 E：表格字段批量填充（P2，写入动作，最高风险）

**触发入口**：表格列头菜单「AI 填充本列（预览）」；先预览 20 行，确认后逐行走既有写路径。

**API（两步）**：

```http
POST /api/v1/workspaces/12/tables/77/ai/actions/fill_field
{
  "field_name": "summary",
  "row_ids": [1001, 1002, 1003],
  "instruction": "根据「标题」和「正文」生成不超过 40 字的中文摘要",
  "preview_only": true
}
→ 200
{
  "action": "table.fill_field",
  "run_id": 8894,
  "preview": [
    {"row_id": 1001, "value": "……"},
    {"row_id": 1002, "value": "……"}
  ],
  "usage": {"model": "deepseek-chat", "total_tokens": 1860, "latency_ms": 3120}
}
```

**确认应用**：前端对每行调用既有更新接口（与手工编辑完全同一路径）：

- 有直编资格：`PATCH /api/v1/workspaces/{wid}/tables/{tid}/records/{row_id}`（既有）→ 200；
- 无直编资格：同一端点返回 **202 + `change_request`**（既有双轨制），前端提示「已提交修改申请 #N」。

**硬约束**：

1. 输入行按 `row_access` 过滤（`row_access.py:173`）：调用者看不到的行不进入预览，也不接受其 `row_ids`；
2. 只允许写「当前用户可见且非隐藏」的字段（`access.py:294` + 字段 hidden 判定）；`fill_field` 目标字段若隐藏直接 400；
3. 单批 ≤ 20 行、单字段；超出由前端分片，服务端拒绝超限（400）；
4. 模型输出必须是 `{row_id: value}` 且 `row_id` 属于请求集合；多余 / 缺失行丢弃并在 `detail` 留痕；
5. AI 不新增行、不删行、不做 DDL；`preview_only=true` 时**业务表零写入**（仅 `llm_run` 一条留痕）。

**测试**：越权 row_id 被过滤；隐藏字段 400；202 修改申请路径；预览时业务表零写入（仅留痕一条）；输出含未知 row_id 被丢弃；20 行上限 400。前端单测断言「应用」逐行调用既有更新接口，不调用任何批量 upsert。

### 附录 F：自然语言生成分析模板 + 结论解读（P3）

**触发入口**：分析页模板编辑区「用一句话生成分析」；生成结果填入编辑态，用户确认后保存（既有保存接口不变）。

**API**：

```http
POST /api/v1/workspaces/12/analytics/ai/suggest-template
{
  "table_id": 77,
  "question": "按月份看各城市的平均气温，并标出温差最大的三个城市"
}
→ 200
{
  "action": "analytics.suggest_template",
  "run_id": 8895,
  "result": {
    "name": "各城市月均气温与温差 Top3",
    "config": {
      "formulas": [{"key": "temp_range", "label": "昼夜温差", "expr": "temp_high - temp_low"}],
      "chart": {"type": "line", "x": "month", "y": "avg_temp", "series": "city", "aggregation": "avg"},
      "summary": {"group_by": "city", "metrics": [{"agg": "avg", "field": "temp_range"}], "sort_by": "avg_temp_range", "sort_order": "desc", "limit": 3},
      "fields": ["month", "city", "avg_temp", "temp_range"],
      "limit": 5000
    },
    "warnings": ["表中无 month 字段，已按 date 截取月份，请确认"]
  }
}
```

**输入构造**：复用既有 `GET /{wid}/analytics/recommendations`（`analytics/services/recommend.py`）的字段画像（角色 / 基数 / 非空率 / 类型）作为上下文，避免把整表数据发给模型；只发字段名、类型与画像摘要。

**校验**：`result.config` 必须能构造 `TemplateConfig` 并通过 `normalize_config(config, table_field_names(...))`（公式语法 / 字段引用 / 聚合白名单）；失败 → 422 并原样返回校验错误，不填编辑态；`warnings` 展示给用户。

**结论解读**（同 P3）：

```http
POST /api/v1/workspaces/12/analytics/ai/explain
{"template_id": 5, "summary_rows": [{"city": "北京", "avg_temp_range": 12.3}], "chart_type": "bar"}
→ 200 {"result": {"insight": "北京昼夜温差最大（12.3℃），其次为……", "caveats": ["样本仅覆盖 3 个城市"]}}
```

- 只读：不写模板、不改数据；`summary_rows` ≤ 50 行。
- 测试：生成配置含未知字段 → 422；公式非法 → 422；合法配置可通过既有保存接口落库；解读接口不改模板 / 数据（仅 `llm_run` 留痕）。

### 附录 G：为什么本期不做「AI 助手 / 文档问答」（边界 15 的说明）

跨功能助手需要「工具调用 → 领域服务 → 多轮上下文」三件基础设施，且每一步都要重新证明权限不旁路（行级 / 字段级 / 可见性）。在 P0-P3 未把「单动作 + 权限裁剪 + 留痕」跑稳之前做助手，只会把风险放大到不可审计。前置条件是：`llm` 网关稳定、领域动作目录覆盖读写两类、`llm_run` 可按会话聚合、以及一个独立的「工具调用权限模型」ADR。
