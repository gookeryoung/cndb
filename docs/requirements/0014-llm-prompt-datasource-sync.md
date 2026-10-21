# 需求卡片：数据源同步支持大模型 API（提示词 + cron + 结构化落表）

- 编号：0014（与 ADR `docs/adr/0014-*.md` 同号）
- 来源 / 提出人：工作区需求（用户提出）
- 日期：2026-10-21
- 关联 ADR：[ADR 0014](../adr/0014-llm-prompt-datasource-sync.md)

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 数据源同步功能增强，需支持大模型 api 调用，配置 api 和 key，能够设置特定特示词和 cron 定时任务，将得到的结果更新到数据表当中。

> api 增加连通测试。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 数据源同步功能增强 | 增强限定在 `datasource` 插件内：新增 `llm_prompt` provider 并登记；既有 6 个 provider 的配置结构与运行行为不变 | `src/cndb/plugins/datasource/providers/registry.py`、`providers/llm_prompt.py` | 回归：现有 `tests/test_datasource_*` 全绿；单测：注册表同时包含新旧 provider，旧名称不变 |
| C2 | 需支持大模型 api 调用 | 任务可选 `provider=llm_prompt`，按 OpenAI 兼容 `POST {base_url}/chat/completions` 调用；`base_url` / `model` / `timeout` 由 `request_spec` 配置；复用 `api_fetch` 的超时、重试、响应体积上限与失败留痕 | `providers/llm_prompt.py`、`services/pipeline.py` | 单测：假模型端点返回 `choices[0].message.content` → 解析成行；非 2xx / 超时记为 failure |
| C3 | 配置 api 和 key | `base_url` / `model` 存 `request_spec`；API key **只存** `datasource_session.secrets`（Fernet 加密），运行时以 `{api_key}` 渲染进 `Authorization` 头；读接口只回显键名、不随工作区导出 | `services/runner.py`、`core/crypto.py`、`routers/sessions.py` | 单测：密文入库、接口无明文回显、备份不含密钥；接口测试：未绑定密钥时返回明确错误 |
| C4 | 能够设置特定特示词（提示词） | `request_spec.prompt` 含 `system` + `user_template`；支持内置占位符 `{entrant}` / `{start}` / `{end}` / `{today}`，只做字面替换、不求值表达式；保存时校验提示词非空与占位符白名单 | `providers/llm_prompt.py`、`providers/template.py`、`routers/sync_jobs.py` | 单测：模板渲染（缺参 / 转义 / 未知占位符）；接口测试：空提示词 400 |
| C5 | 和 cron 定时任务 | 复用现有 `ScheduleMode.CRON`（5 段表达式 + 时区偏移 + 失败退避），不新增调度器；前端调度下拉的 cron 选项沿用，保存时校验 `expr` | `services/schedule.py`、`models.py`、`frontend/src/pages/datasource/DatasourcePage.tsx` | 单测：cron 到期判定沿用现有用例；e2e：新建 cron 任务并回显表达式 |
| C6 | 将得到的结果更新到数据表当中 | 模型回复必须是 JSON（对象 → 1 行，对象数组 → N 行）；经 `field_mapping` 归一后按 `match_keys` upsert 到 `table_id`；解析失败 → `run=failed` 且不写脏数据；预览不落库 | `providers/llm_prompt.py`、`services/write.py`、`services/runner.py` | 集成：假模型两次相同 `match_keys` → 首次 inserted=1、二次 updated=1；单测：非法 JSON 不落库 |
| C7 | api 增加连通测试 | 新增 `POST /{wid}/datasource/test-connection`：用未保存的 `request_spec` + `session_id` 发一次最小模型请求，返回 `ok / latency_ms / model / message`；不落库、不写运行记录；仅工作区 EDITOR 可用 | `routers/sync_jobs.py`、`providers/llm_prompt.py`、`frontend/.../DatasourcePage.tsx` | 接口测试：假模型成功 / 401 / 超时三种结果；前端单测：按钮展示成功与失败文案 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | Provider 注册与发现 | `src/cndb/plugins/datasource/providers/registry.py:61` | 新 provider 需在 `register_builtins` 登记，`GET /providers` 自动暴露 |
| 2 | Provider 协议与响应处理器 | `src/cndb/plugins/datasource/providers/base.py:177`、`providers/http_json.py:86` | 已有 `response_handler_for` 自定义解析入口，可从 `choices[].message.content` 取 JSON |
| 3 | 请求声明白名单 | `providers/base.py:80`、`services/runner.py:227` | `RequestSpec` / `request_spec_from_payload` 只认 `url_template` 等键，需新增 prompt / llm 配置键 |
| 4 | 抓取管线 | `services/pipeline.py:60` | `fetch_json` 默认返回对象数组；LLM 需在 parse 阶段把 content 转成行 |
| 5 | 凭证会话与加密 | `services/runner.py:205`、`core/crypto.py:79` | 会话 headers 铺底 + secrets 模板变量已有，需确认 `Authorization` 模板可用 |
| 6 | 调度与 cron | `services/schedule.py:123`、`models.py:24` | `cron` 模式已实现（解析 / 到期 / 退避），本需求无需新调度器 |
| 7 | 幂等落表 | `services/write.py:39` | `upsert_rows` 已按 `match_keys` 先查后写，可直接复用 |
| 8 | 任务创建校验 | `routers/sync_jobs.py:66` | 需按 provider 增加提示词 / 结构化输出 / 模型参数的校验分支 |
| 9 | 前端任务表单 | `frontend/src/pages/datasource/DatasourcePage.tsx:451`、`:560` | `request_spec` 目前硬编码 url / data_path / 分页，需按 provider 条件渲染提示词与模型配置 |
| 10 | 前端接口类型 | `frontend/src/api/datasource.ts:44` | `SyncRequestSpec` 需补 llm / prompt 字段 |
| 11 | 测试基线 | `tests/test_datasource_providers.py`、`tests/test_datasource_pipeline.py`、`tests/test_datasource_api.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx`、`frontend/tests/e2e/critical/datasource.spec.ts` | 新 provider 需补单测、接口测试与 e2e |
| 12 | 既有抓取预览入口 | `routers/sync_jobs.py`（`/sync-jobs/{id}/preview`） | 预览必须先保存任务；连通测试要用未保存配置，需独立端点 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] **LLM 角色** → 独立数据源 provider `llm_prompt`（2026-10-21 需求方确认）
- [x] **API 协议与端点** → OpenAI 兼容 `/chat/completions`，首期仅公网端点；内网自建端点不在本期范围（2026-10-21 确认）
- [x] **落表格式** → 强制结构化 JSON；解析失败即 `run=failed`（2026-10-21 确认）
- [x] **提示词上下文** → 首期仅内置变量（`entrant` / `start` / `end` / `today`），不读表（2026-10-21 确认）
- [x] **幂等口径** → cron 任务必须配置 `match_keys`（2026-10-21 确认）
- [x] **预览行为** → 真实调用模型 1 次，前端提示可能产生费用（2026-10-21 确认）
- [x] **用量留痕** → token 用量与模型名写入 `run.detail`，不做费用估算（2026-10-21 确认）
- [x] **Key 管理** → 复用 `datasource_session`，密钥加密入库、只写不回显（2026-10-21 确认）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-21）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
