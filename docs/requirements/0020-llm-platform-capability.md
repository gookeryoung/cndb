# 需求卡片：大模型能力平台化（位置重规划 + 应用地图 + 典型示例）

- 编号：0020（与 ADR `docs/adr/0020-*.md` 同号，卡片存 `docs/requirements/0020-llm-platform-capability.md`）
- 来源 / 提出人：工作区需求（用户提出）
- 日期：2026-10-22
- 关联 ADR：[ADR 0020](../adr/0020-llm-platform-capability.md)

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请针对大模型功能在项目的位置，以及可以应用的地方进行重新规划设计，必要的情况下可重构。请制定方案和典型示例。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 大模型功能在项目的位置…重新规划设计 | 大模型能力从「datasource 插件内嵌 + accounts 插件代挂配置路由」改为**平台级能力归属**：新建 `src/cndb/plugins/llm/`（个人连接 / OpenAI 兼容客户端 / 调用网关 / 动作注册表 / 调用留痕）；datasource 只保留「提示词 → 落表」的领域语义；依赖方向固定为「领域插件 → llm」，`llm` 不得 import 任何领域插件 | `src/cndb/plugins/llm/`、`src/cndb/plugins/datasource/`、`src/cndb/plugins/accounts/` | ADR 0020 P0 代码落点；`grep -r "plugins.datasource" src/cndb/plugins/llm` 为空；插件注册测试通过 |
| C2 | 以及可以应用的地方 | 给出**应用地图**：按「场景 / 归属插件 / 触发入口 / 读写风险 / 优先级」列出文档、数据表、导入、分析、搜索、问题与修改申请六类可应用点，并明确首批落地范围（文档 → 导入建议 → 表格填充 → 分析/搜索） | `docs/adr/0020-llm-platform-capability.md` | ADR「应用地图」表 + 分期表；每条应用点有承载端点或服务的 `file:line` |
| C3 | 必要的情况下可重构 | 重构边界写成硬约束：只新增迁移、不改/删历史迁移（head 级旧表断言改为「旧表不存在、新表存在」，head 常量同轮更新）；不改其它 provider 行为；不旁路权限与既有写路径；前端同轮切换端点；旧任务 / 旧配置 / v1-v7 备份继续可用 | `src/cndb/alembic/versions/`、`tests/test_datasource_migration.py`、`tests/test_migration_missing_model_columns.py`、`src/cndb/plugins/workspaces/services/backup_io.py` | 迁移与备份往返测试通过；旧 `llm_prompt` 任务回归通过 |
| C4 | 请制定方案 | 产出 ADR：数据模型 / 判定入口 / API 变更 / 边界与例外 / 迁移 / 前端 / 测试清单 / 分期，Status `Proposed` 待评审；不进入实现（仓库规定 AI 不得自行越过方案评审） | `docs/adr/0020-llm-platform-capability.md` | `make check-docs`（含 `adr-check`）通过；ADR 决策记录无「待定」 |
| C5 | 请制定方案和典型示例 | 至少 5 个**可直接落地**的典型示例，每个含：触发入口 / API 契约（请求与响应）/ 系统与用户提示词 / 输出 schema / 服务端校验与失败口径 / 写回路径 / 前端交互 / 测试点；覆盖「只读建议」「编辑器内改写」「结构化落库」「自然语言生成配置」四类形态 | `docs/adr/0020-llm-platform-capability.md` 附录 | 附录示例逐项齐全，示例中的端点与既有路由前缀一致 |
| C6 | （沿用 ADR 0019 口径，位置重规划） | 连接仍为**个人级**：一人一条、`api_key` Fernet 密文、只写不回显、不随工作区备份导出；仅归属与端点变化（表 `llm_user_config`、端点 `/api/v1/llm/config`），语义不变 | `src/cndb/plugins/llm/models.py`、`routers/config.py`、`frontend/src/pages/settings/LlmConfigPanel.tsx` | 接口测试：用户隔离、Key 不回显、未保存 Key 可测试且不落库；备份不含个人配置 |
| C7 | （能力复用的前提） | 每次模型调用留一条可查记录：用户 / 工作区 / 动作 / 模型 / prompt·completion·total token / 耗时 / 状态 / 错误摘要 / `request_id`；**不存提示词与输出全文**；个人设置可查最近调用 | `src/cndb/plugins/llm/models.py`（`llm_run`）、`routers/runs.py`、`frontend/src/pages/settings/` | 单测：成功/失败/未配置 Key 各留痕一条；接口测试：只返回本人记录；断言不含正文 |
| C8 | （失败可诊断） | 未配置 Key / 上游 429·5xx·超时 / 响应非 JSON / 输出不合 schema 四类失败分别映射固定状态码与中文可执行文案；输出不合 schema 时**不落库、不改写业务数据**；上游 429/5xx/超时在客户端层有限重试（≤2 次，指数退避，尊重 `Retry-After`） | `src/cndb/plugins/llm/services/client.py`、`gateway.py`、`errors.py` | 单测覆盖四类失败与重试次数；接口测试断言状态码与文案；业务数据写入路径测试断言失败零副作用 |
| C9 | （必要情况下可重构的边界） | AI 不新增写路径：读走既有权限（文档三档可见性 / 行级权限 / 字段隐藏），写一律复用既有保存与修改申请（`resolve_write_mode`、`_dispatch_or_403`）；AI 不得直接产生文档版本、不得直接 DDL、不得直接落行 | `src/cndb/plugins/documents/`、`src/cndb/plugins/tables/`、`src/cndb/plugins/change_requests/services.py` | 接口测试：viewer 应用 AI 结果走 202 修改申请；隐藏字段不出现在模型输入、不可被 AI 写入；非成员 404/403 语义不变 |
| C10 | （位置重规划的隐私修正） | 个人连接默认值（`base_url` / `model`）**不再在保存任务时烘进 `request_spec`**（ADR 0019 遗留：个人地址/模型随工作区备份外泄，且改个人配置对存量任务无效）；运行期解析，显式任务配置仍优先 | `src/cndb/plugins/datasource/routers/sync_jobs.py`、`services/runner.py` | 接口测试：保存只填提示词的任务后 `request_spec` 不含 `url_template`/`llm.model`；备份导出不含个人地址/模型；运行仍使用个人配置 |
| C11 | （前端可复用） | 前端 AI 交互统一为共享层 `api/llm.ts` + `hooks/useLlmAction.ts` + `components/Ai/*`；结果一律「建议 → 预览 → 确认」，第一版同步 JSON（不引入 SSE），AI 组件懒加载并受 bundle budget 约束 | `frontend/src/components/Ai/`、`hooks/`、`api/llm.ts`、`frontend/src/pages/documents/` 等 | 前端单测：共享 hook 的 loading/错误/确认态；`make frontend-static` 与 bundle budget 通过；e2e 只验 UI 与保存，不真调模型 |
| C12 | （不回归） | `llm_prompt` 既有行为全部保留：只填用户提示词的极简表单、自动建表 / 空表补字段 / 自动幂等键、宽松模板求值、默认 `max_tokens=4096`、截断错误提示、`/api/v1/llm/config/test` 可用未保存 Key；其它 provider 行为不变 | `src/cndb/plugins/datasource/providers/llm_prompt.py`、`services/auto_table.py`、`services/write.py`、`services/runner.py` | 既有 `tests/test_datasource_llm_*.py`、`test_datasource_auto_table.py`、`test_datasource_runner.py` 全绿（按新位置改 import，断言语义不变） |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | `llm_prompt` provider 直接实现 OpenAI 兼容调用与 JSON 解析 | `src/cndb/plugins/datasource/providers/llm_prompt.py:159-246` | 调用能力与领域落表耦合在同一文件，其它功能无法复用 |
| 2 | 个人连接读取 / 解密 / 默认值补全 | `src/cndb/plugins/datasource/services/connection.py:42-84`、`src/cndb/plugins/datasource/models.py:74-97` | 连接归属在 datasource 插件，配置路由却挂在 accounts（反向依赖） |
| 3 | 个人配置路由 | `src/cndb/plugins/accounts/routers/llm_config.py:127-217`、`src/cndb/plugins/accounts/plugin.py:17,42` | accounts 插件 import datasource 的 models / provider / runner（`llm_config.py:25-33`） |
| 4 | 任务保存时把个人地址/模型写进 `request_spec` | `src/cndb/plugins/datasource/routers/sync_jobs.py:284-285`、`services/runner.py:300-322` | 随工作区备份导出（`workspaces/routers/workspaces.py:587`），且改个人配置对存量任务无效 |
| 5 | 统一 HTTP 出口与 SSRF 限制 | `src/cndb/plugins/tables/services/importing/api_fetch.py:184-192,546` | 模型调用复用 `fetch_json`；禁内网 / 本地模型；POST 不重试（无 429 处理） |
| 6 | 无调用级留痕 / 用量 | `src/cndb/plugins/datasource/providers/llm_prompt.py:477-486`、`services/runner.py:480` | 只有 `run.detail.response_metadata`，无跨任务汇总 |
| 7 | 文档编辑器 AI 所需能力 | `src/cndb/plugins/documents/routers/documents.py:413-467,387-410`；前端 `frontend/src/components/Document/MarkdownLiveEditor.tsx:41-50`、`pages/documents/DocumentEditorPage.tsx:501-532` | 编辑器已有选区 API；写回需复用双轨制 |
| 8 | 表格 AI 写回边界 | `src/cndb/plugins/tables/routers/records.py:145`、`plugins/change_requests/services.py:65-118`、`plugins/tables/services/core/row_access.py:173`、`access.py:294` | 行级写范围 / 字段隐藏 / 修改申请是硬约束 |
| 9 | 导入列映射建议的承载点 | `src/cndb/plugins/tables/services/importing/importer.py:172,258`、`routers/import_csv.py:36-63` | 已有确定性清洗建议与表头打分（ADR 0018），AI 只能补「建议值」 |
| 10 | 分析模板校验唯一入口 | `src/cndb/plugins/analytics/services/templates.py:33-125` | NL 生成配置必须过该校验；analytics 模板不在工作区备份内 |
| 11 | 前端现有大模型触点 | `frontend/src/api/llmConfig.ts:54-64`、`pages/settings/LlmConfigPanel.tsx`、`pages/datasource/DatasourcePage.tsx:659-717,1499-1547`、`pages/datasource/llmPromptPresets.ts` | 只有「配置 + 填提示词」，无调用态 UI 与共享组件 |
| 12 | 既有测试基线 | `tests/test_datasource_llm_provider.py`、`test_datasource_llm_config.py`、`test_datasource_auto_table.py`、`test_datasource_runner.py`、`test_datasource_api.py`、`test_datasource_backup.py`、`test_datasource_migration.py`、`test_migration_missing_model_columns.py`；前端 `LlmConfigPanel.test.tsx`、`SettingsModal.test.tsx`、`DatasourcePage.test.tsx`、`llmPromptPresets.test.ts` | 位置搬迁需同轮改 import / mock 路径，断言语义不变 |
| 13 | 迁移 head 与旧迁移断言 | `src/cndb/alembic/versions/6a7b8c9d0e1f_add_user_llm_config.py:25`、`tests/test_datasource_migration.py:19-23,182-344`、`tests/test_migration_missing_model_columns.py:35` | 不能改旧迁移；只能新增迁移搬表并更新 head 常量 |
| 14 | 备份版本与排除口径 | `src/cndb/plugins/workspaces/services/backup_io.py:395-396`、`workspaces/routers/workspaces.py:604` | v7 已不导出 `llm_config` 键；新表不得进备份 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [ ] **重构深度**：本轮只出方案（ADR `Proposed`）+ 典型示例，还是同时进入 P0 实现？（仓库规定需求确认 / ADR 评审由人拍板；建议先评审再实现）
- [ ] **端点迁移方式**：个人连接端点从 `/api/v1/accounts/llm-config` 迁到 `/api/v1/llm/config`（前端与测试同轮改，无兼容别名），是否接受这一次性 breaking change？
- [ ] **首批应用范围**：是否同意首批只做「文档 AI（选区改写 + 摘要/标签建议）」，表格 / 导入 / 分析按 P2-P3 排期？
- [ ] **内网 / 本地模型**：默认继续禁内网（沿用 SSRF 防护），仅提供显式白名单环境变量；是否需要本期就支持本地 Ollama 一类内网端点？
- [ ] **调用留痕保留期**：`llm_run` 是否需要自动清理（默认保留 90 天，提供 `cndb llm prune`）？

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认（待人工确认）
