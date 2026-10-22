# ADR 0014: 数据源同步接入大模型（llm_prompt Provider + 提示词 + cron + 连通测试）

Status: Implemented（需求方 2026-10-21 确认提案并落地）
Date: 2026-10-21
Related: `src/cndb/plugins/datasource/providers/base.py`、`src/cndb/plugins/datasource/providers/http_json.py`、`src/cndb/plugins/datasource/providers/registry.py`、`src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/core/crypto.py`、`frontend/src/pages/datasource/DatasourcePage.tsx`；上游框架见 ADR 0006
需求卡片: `docs/requirements/0014-llm-prompt-datasource-sync.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，本 ADR 不复制第二份）；约束编号沿用卡片的 C1..C7。

| C # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 数据源同步功能增强 | 新增 `llm_prompt` provider 并登记进 `PROVIDERS`；既有 provider 与其配置结构不变 |
| C2 | 需支持大模型 api 调用 | `LlmPromptProvider` 按 OpenAI 兼容协议请求 `{base_url}/chat/completions`；复用 `api_fetch` 的超时 / 体积上限 / SSRF / 错误留痕 |
| C3 | 配置 api 和 key | `request_spec.url_template` 存 API 地址、`prompt` / `llm` 存提示词与模型参数；Key 只存 `datasource_session.secrets.api_key`（Fernet 加密），运行期渲染 `Authorization: Bearer {api_key}` |
| C4 | 能够设置特定特示词（提示词） | `request_spec.prompt.system + user_template`，经 `render_text` 求值；内置变量 `entrant / start / end / today`，未知占位符保存即 400；`system` 可省略，未配置时使用内置默认系统提示词（简化口径见 ADR 0019） |
| C5 | 和 cron 定时任务 | 复用 `ScheduleMode.CRON` 与 `is_due`；`llm_prompt` + cron 的幂等键改由自动识别（简化口径见 ADR 0019），不再强制手填 `match_keys` |
| C6 | 将得到的结果更新到数据表当中 | 模型回复必须是 JSON（对象 / 对象数组 / `{"rows": [...]}`）；解析后经 `field_mapping` 归一，按 `match_keys` 走 `upsert_rows`；解析失败 → `run=failed` 且不落库 |
| C7 | api 增加连通测试 | `POST /{wid}/datasource/test-connection`：接收未保存的 `request_spec` + `session_id`，发一次最小模型请求，返回 `ok / latency_ms / model / message`；不落库、不写运行记录 |

## Context

现状逐条核对（沿用需求卡片「现状影响面」编号）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | Provider 注册表集中登记内置适配器，`GET /providers` 自动暴露 | `src/cndb/plugins/datasource/providers/registry.py:61-77` | 新 provider 只需登记，前端无需硬编码发现 | 确认 |
| 2 | Provider 协议含 `build_requests / parse / normalize`，且 `FetchConfig.response_handler` 支持 callable | `providers/base.py:177-200`、`providers/http_json.py:86-108`、`tables/services/importing/api_fetch.py:493-506` | 可在 parse 阶段把 `choices[0].message.content` 转成行，无需改抓取内核 | 确认 |
| 3 | `RequestSpec` 只认 `url_template / headers / params / body / data_path / paging / time_window`；`request_spec_from_payload` 也是白名单还原 | `providers/base.py:80-104`、`services/runner.py:227-254` | 提示词与模型参数当前无处可放，需扩展 `RequestSpec` 与还原白名单 | 确认 |
| 4 | 管线是「Provider 展开请求 → fetch → parse → normalize」，单请求失败记 failure | `services/pipeline.py:60-110` | 可原样复用；LLM 响应解析放在 provider 内 | 确认 |
| 5 | 会话 headers 铺底、secrets 解密为模板变量；密钥 Fernet 加密、读接口只回显键名 | `services/runner.py:205-213`、`core/crypto.py:79-84`、`models.py:50-69` | Key 复用会话即可满足「配置 api 和 key」且不新增存储 | 确认 |
| 6 | cron 已有 5 段解析、到期判定与失败退避 | `services/schedule.py:123-143`、`models.py:24-31` | 无需新调度器，只需任务级校验 | 确认 |
| 7 | `upsert_rows` 已按 `match_keys` 先查后写，`partial=True` 保留未提供列 | `services/write.py:39-84`、`services/runner.py:293-315` | 模型结果可直接走同一落表路径 | 确认 |
| 8 | 创建 / 更新校验只做 provider 存在性、RequestSpec、游标、调度、幂等键字段存在性 | `routers/sync_jobs.py:66-100` | 需补 LLM 专属校验（提示词、模型、cron × match_keys） | 确认 |
| 9 | 前端任务表单把 `request_spec` 硬编码为 URL / data_path / 分页 / 时间窗口 | `frontend/src/pages/datasource/DatasourcePage.tsx:451-487`、`:624-710` | 需按 provider 条件渲染提示词与模型配置 | 确认 |
| 10 | 前端 `SyncRequestSpec` 无 prompt / llm 字段 | `frontend/src/api/datasource.ts:44-73` | 需补类型与接口封装 | 确认 |
| 11 | 现有测试覆盖 provider / pipeline / API / 前端页面 | `tests/test_datasource_providers.py`、`tests/test_datasource_pipeline.py`、`tests/test_datasource_api.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | 新 provider 需同轮补测试 | 确认 |
| 12 | 抓取预览必须先保存任务（`/sync-jobs/{id}/preview`） | `routers/sync_jobs.py:279` | 未保存配置无法验证连通性，需独立端点 | 确认 |

**核心缺陷（需求要补的）**：现有框架只能「请求外部 HTTP → 解析 JSON」，没有「把提示词发给模型、再把模型 JSON 结果落表」的 Provider；提示词、模型参数与 API Key 也没有可校验的配置入口。

设计目标（不变量）：

- **I1 领域无关**：调度 / 游标 / 分页 / 幂等 / 重试代码不新增任何 LLM 领域词，模型差异只在 `llm_prompt` provider 内。
- **I2 零迁移**：不新增表 / 列 / 迁移；配置全部进既有 `request_spec` JSON，备份格式不变。
- **I3 密钥不落地明文**：API Key 只存会话密文，读接口与导出不含明文。
- **I4 结构化才落库**：模型输出不能解析成对象行时不写任何数据，运行记 `failed`。
- **I5 单飞与幂等不变**：仍由 DB 租约保证单飞；重复运行只更新不重复插入，cron 任务的幂等键由自动识别承接（简化口径见 ADR 0019）。
- **I6 连通测试无副作用**：测试不写运行记录、不落表、不推进游标。

## Decision

### 1. 数据模型

无新表、无新列、无迁移。`datasource_sync_job.request_spec` 扩展两个 JSON 键：

```json
{
  "url_template": "https://api.deepseek.com/chat/completions",
  "method": "POST",
  "headers_template": {"Authorization": "Bearer {api_key}"},
  "prompt": {
    "system": "你是数据抽取助手，只输出 JSON。",
    "user_template": "请生成 {today} 的天气摘要，地区：{entrant}"
  },
  "llm": {
    "model": "deepseek-chat",
    "temperature": 0.2,
    "max_tokens": 1024,
    "json_mode": true
  }
}
```

- `url_template` 若以 `/chat/completions` 结尾则原样使用，否则追加 `/chat/completions`。
- `llm_cursor.default = none`；提示词需要时间时用 `{today}`，需要区间时由 `time_window=range` 注入 `{start}` / `{end}`。
- `datasource_session.secrets.api_key` 为唯一 Key 入口；会话 headers 仍按既有规则铺底。
- `run.detail.response_metadata` 新增数组，记录每次模型调用的 `model / usage`（不做费用估算）。

### 2. 判定算法（唯一入口）

新增 `providers/llm_prompt.py`：

```python
class LlmPromptProvider:
    name = "llm_prompt"
    default_cursor = "none"
    supports_paging = False
    uses_custom_parse = True

    def build_requests(self, job: SyncJobSpec) -> list[RequestPlan]: ...
    def parse(self, text: str, job: SyncJobSpec) -> list[dict[str, Any]]: ...
    def normalize(self, rows, job) -> NormalizeResult: ...
```

判定顺序：

1. **Key 校验**：`build_requests` 要求 `job.extra_variables["api_key"]` 非空；缺失抛 `ProviderError("llm_prompt 需要绑定包含 api_key 的凭证会话")`，运行落 `failed`，不发出请求（简化口径见 ADR 0019：Key 可由工作区「大模型连接」提供，会话 Key 优先）。
2. **提示词求值**：内置变量 `entrant / start / end / today` 与 `extra_variables` 合并后交给 `render_text`；未知占位符直接报错（保存阶段用同一函数预校验）。
3. **请求构造**：`messages = [system?, user]`；`response_format={"type":"json_object"}` 在 `json_mode=true` 时加入；`temperature / max_tokens` 取 `llm` 配置并夹取合法范围。
4. **结果解析**：取 `choices[0].message.content`（兼容 content 为文本片段数组），去掉 Markdown 代码围栏后 `json.loads`；对象 → 1 行，对象数组 → N 行，`{"rows":[...]}` → 取 `rows`；其它形态抛 `ProviderError`。
5. **落表**：`normalize` 复用 `apply_field_mapping`，随后由既有 `upsert_rows` 按 `match_keys` 写入。

连通测试复用同一构造逻辑，但使用固定提示词「只返回 `{"ok": true}`」，单次请求、不走管线落库。

### 3. API 变更清单（`/api/v1/workspaces/{wid}/datasource`）

| 端点 | 变更 |
|---|---|
| `GET /providers` | 自动新增 `llm_prompt` 元信息（`params_schema` 含 prompt / llm 字段） |
| `POST /sync-jobs`、`PUT /sync-jobs/{id}` | 新增 LLM 专属校验：URL、model、提示词非空；`llm_prompt` + `schedule.mode=cron` 时 `match_keys` 必填；未知占位符 400 |
| `POST /test-connection` | 新增：`{request_spec, session_id}` → `{ok, latency_ms, model, message}`；EDITOR 权限；异常也返回 200 + `ok=false` 便于前端展示 |
| `POST /sync-jobs/{id}/preview` | 行为不变：真实调用模型一次，不落库、不写运行记录 |

### 4. 边界与例外

1. 首期只支持 OpenAI 兼容协议与公网端点；`api_fetch` 的 SSRF 防护原样生效，内网 / 本机端点不支持。
2. 模型必须返回可解析 JSON；解析失败、HTTP 非 2xx、超时均记 `failed`，不写任何行。
3. `json_mode=true` 时发送 `response_format`；部分兼容服务不支持该字段会返回 400，此时任务失败并在错误信息中保留上游响应片段。
4. cron 任务不再强制手填 `match_keys`，幂等键由自动识别承接（简化口径见 ADR 0019）；无法识别唯一键时退化为追加并在 `run.detail` 留痕；其它调度模式仍允许无键追加（显式快照场景）。
5. 未绑定会话或会话缺少 `api_key`：保存允许，运行与连通测试给出明确错误，避免把 401 当网络故障排查。
6. 预览与连通测试都会产生真实模型费用；前端在按钮旁提示。
7. 单次运行按 `entrant × 1` 发请求（无分页、无时间切片）；模型调用间隔沿用 job 的 `rate_limit_ms`。

### 5. 迁移

无。`request_spec` 为 JSON 列，旧任务无 `prompt / llm` 键时由既有白名单还原逻辑忽略；备份导出 / 导入无需升版本。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 接口类型 / 封装 | `frontend/src/api/datasource.ts` | `SyncRequestSpec` 增 `prompt / llm`；新增 `testConnection` |
| 任务抽屉 | `frontend/src/pages/datasource/DatasourcePage.tsx` | `provider=llm_prompt` 时渲染 API 地址 / 模型 / 系统提示词 / 用户提示词 / temperature / max_tokens；隐藏分页与响应数组路径；增加「连通测试」按钮与结果提示；cron 时提示必须填幂等键 |
| 页面测试 | `frontend/src/pages/datasource/DatasourcePage.test.tsx` | 表单条件渲染、payload 组装、连通测试成功 / 失败文案 |

### 7. 测试清单

**判定层（单测）**：URL 归一（带 / 不带 `/chat/completions`）；Key 缺失报错；提示词占位符求值与未知占位符；请求体（model / temperature / max_tokens / response_format）；响应解析（对象 / 数组 / `rows` / 代码围栏 / 非法 JSON / content 片段数组）；字段映射归一；`response_metadata` 采集。

**接口层**：`POST /test-connection` 成功、401、超时三种结果；未绑定 / 错误会话；空提示词返回 400；cron 不配 `match_keys` 可保存（简化口径见 ADR 0019）；现有 `http_json` 任务不受影响。

**迁移 / 备份**：无迁移；备份往返保持 `request_spec.prompt / llm` 原样。

**e2e（前端）**：既有数据源用例保持通过；若新增 LLM 用例，只保存任务不触发真实模型调用。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `llm_prompt` provider（请求构造 / JSON 解析 / 归元）、注册、`RequestSpec` 扩展、校验、连通测试端点 | 中 |
| **P1** | 前端条件表单、连通测试按钮、类型与接口封装 | 中 |
| **P2** | 测试补齐（单测 / 接口 / 前端）、文档与 CHANGELOG 回填 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | LLM 在同步链路中的角色 | 独立数据源 provider `llm_prompt` | 与既有 Provider × SyncJob × Cursor × Normalizer 同构，调度 / 落表 / 留痕零改动 | 抓取后处理器（需改管线中间阶段）；两者都做（范围翻倍） | `providers/llm_prompt.py`、`providers/registry.py` |
| D2 | API 协议与端点范围 | OpenAI 兼容 `/chat/completions`，首期仅公网 | 覆盖主流厂商；复用现有 SSRF 防护 | 内网 / 本机端点（需 SSRF 白名单）；任意 HTTP JSON（配置复杂、可校验性差） | `providers/llm_prompt.py`、`tables/services/importing/api_fetch.py` |
| D3 | 模型输出形态 | 强制 JSON，解析失败即 failed | 可字段映射、可幂等、不写脏数据 | 单列文本（不可分析 / 不可幂等）；任务级可选（两套口径） | `providers/llm_prompt.py`、`services/pipeline.py` |
| D4 | API Key 存储 | 复用 `datasource_session.secrets.api_key`（Fernet 加密）；后续新增工作区级「大模型连接」作为默认 Key 来源，会话 Key 优先（简化口径见 ADR 0019） | 已有加密、只写不回显、不随导出；避免第二套凭证入口 | 任务内联字段；全局环境变量 | `services/runner.py`、`core/crypto.py`、`routers/sessions.py` |
| D5 | 提示词上下文 | 仅内置变量 `entrant / start / end / today` | 首期最小闭环，不引入读表权限与行数上限问题 | 拼目标表 / 其它表已有行（需新取数路径） | `providers/llm_prompt.py`、`providers/template.py` |
| D6 | cron 与幂等 | 复用 `ScheduleMode.CRON`；`llm_prompt` + cron 的 `match_keys` 由自动识别承接（简化口径见 ADR 0019），不再强制手填 | 防止每轮追加重复行；调度器零改动 | 无键追加；新建 LLM 专用调度器 | `services/schedule.py`、`routers/sync_jobs.py` |
| D7 | 连通测试入口 | 独立 `POST /test-connection`，用未保存配置，无副作用 | 现有预览必须先保存任务，无法在表单阶段验证 Key / 模型 | 复用预览端点（有落库 / 运行记录副作用） | `routers/sync_jobs.py`、`providers/llm_prompt.py` |
| D8 | 用量留痕 | `run.detail.response_metadata` 记录 model 与 usage | 便于排查模型 / 计费问题，不做费用估算 | 不记录；单独建表 | `services/pipeline.py`、`services/runner.py` |
| D9 | 是否新增表 / 迁移 | 本 ADR 范围内不新增，配置进 `request_spec` JSON（后续 ADR 0019 新增工作区级连接表 `datasource_llm_config`） | 与既有半结构化配置口径一致，备份零改动 | 新建 `llm_config` 表（无必要抽象） | `services/runner.py`、`services/schemas` |

门禁：本表无「待定」；需求方已于 2026-10-21 确认提案并要求实现，Status 定稿 `Accepted`。

## Consequences

- **正向**：数据源同步从「抓 HTTP」扩展到「提示词生成」，复用调度、游标、幂等、落表、留痕与凭证加密；新增数据源只需一个 Provider。
- **负向**：模型输出质量不可控，提示词与结构化约束成为主要维护面；连通测试与预览会产生真实调用费用。
- **风险与缓解**：模型返回非 JSON → 解析失败即 failed，不落脏数据；Key 泄露 → 只存密文、只回显键名、不随备份导出；cron 重复行 → 强制 `match_keys`；上游不支持 `response_format` → 错误信息透传，必要时关闭 `json_mode`。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 数据同步框架 | Provider × SyncJob × Cursor × Normalizer | `llm_prompt` 作为新 Provider 接入，不改框架 | ADR 0006 |
| 凭证管理 | `datasource_session` | 复用加密会话；ADR 0019 另增工作区级连接 Key，会话 Key 优先 | ADR 0006 D6、ADR 0019 D4 |
| 调度 | `ScheduleMode.CRON` | 复用 cron 判定与租约单飞 | ADR 0006 D3 |
| 配置复杂度简化 | 工作区级「大模型连接」+ 空表自动落表 | llm_prompt 的连接 / 幂等键 / 目标表配置下沉或自动化，provider 协议不变 | ADR 0019 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/datasource/providers/llm_prompt.py`、`src/cndb/plugins/datasource/providers/base.py`、`src/cndb/plugins/datasource/providers/registry.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/plugins/datasource/schemas.py` | `tests/test_datasource_llm_provider.py`、`tests/test_datasource_api.py`（TestLlmPrompt） | f8b79dba |
| P1 | 已落地 | `frontend/src/api/datasource.ts`、`frontend/src/api/index.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx` | `frontend/src/pages/datasource/DatasourcePage.test.tsx` | f8b79dba |
| P2 | 已落地 | `CHANGELOG.md`、`docs/adr/0014-llm-prompt-datasource-sync.md` | `tests/test_datasource_llm_provider.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | f8b79dba |

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地并提交（`f8b79dba`），`Status=Implemented`；配置复杂度的简化已由 **ADR 0019** 承接（工作区级「大模型连接」、内置默认系统提示词、空表自动建表 / 补字段 / 自动幂等键、5 组推荐提示词），本 ADR 保留为 `llm_prompt` provider 的原始设计与口径来源，不标 Superseded
- 已完成：`llm_prompt` provider、创建 / 更新校验、`POST /test-connection`；前端按 `provider=llm_prompt` 条件渲染提示词 / 模型表单与连通测试按钮；单测、接口测试与页面测试同轮补齐
- 下一步：本 ADR 范围内无待办；`llm_prompt` 后续演进（连接 / 空表自动化 / 提示词预设）一律在 ADR 0019 上继续，流式响应 / 多轮对话等增强按使用反馈另立 ADR
- 已知坑：`api_fetch` 对非 2xx 直接抛 `ValueError`（错误信息含上游响应片段）；`render_text` 对未知占位符直接报错；cron 幂等键现由自动识别承接（见 ADR 0019），不再强制手填；抽屉里调度项位于折叠面板，未展开时 `Form.useWatch` 取不到值（已回退到任务配置）
- 最近一次全绿：`make check-docs`（2026-10-22，ADR 0019 文档对齐）；代码门禁以提交 `f8b79dba` 为准
