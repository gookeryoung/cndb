# 需求卡片：大模型提示词配置简化（个人级连接 + 提示词极简 + 空表自动化 + 提示词可靠性）

- 编号：0019（与 ADR `docs/adr/0019-*.md` 同号）
- 来源 / 提出人：工作区需求（用户提出）
- 日期：2026-10-22
- 关联 ADR：[ADR 0019](../adr/0019-llm-prompt-config-simplify.md)

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 大模型提示词抓取功能配置项过于复杂，需要进行简化，尽可能只配置提示词项即可确保抓取到合适的数据，并且支持空数据表自动新增和更新数据的能力。系统提示词请默认配置好，提供5组典型可用的推荐用户提示词参考示例，并给出说明。

### 追加需求（2026-10-23，逐字）

> 典型示例数据，数据源同步应当提供数据源同步的配置，包括美食推荐做法和国际形势发展动态。大模型动态拉取的字段能否支持中文，请解决。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 大模型提示词抓取功能配置项过于复杂，需要进行简化 | 新建 / 编辑 `llm_prompt` 任务的主表单只保留「任务名称 + 用户提示词 + 可选目标表」；API 地址 / 模型 / 系统提示词 / 幂等键 / 调度等下沉为高级设置或个人级连接，默认不要求逐任务填写 | `frontend/src/pages/datasource/DatasourcePage.tsx`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`providers/llm_prompt.py` | 前端单测：`llm_prompt` 表单只渲染提示词相关必填项、其余收进高级设置；接口测试：只带 `prompt.user_template` 的任务可保存（201）；用户提示词含 JSON 裸花括号（如 `{"rows": [...]}`）可直接保存 / 运行 |
| C2 | 尽可能只配置提示词项即可确保抓取到合适的数据 | 个人级「大模型配置」配置一次（`base_url` / `model` / `api_key` 加密 / 可选 `system_prompt` 覆盖，按用户隔离）；任务 `request_spec` 允许缺省 `url_template` 与 `llm.model`，保存与运行时由个人配置 / 默认值补齐；未配置 `system` 时自动使用内置默认系统提示词 | `src/cndb/plugins/datasource/services/connection.py`、`src/cndb/plugins/accounts/routers/llm_config.py`、`providers/llm_prompt.py`、`services/runner.py` | 单测：连接解析补 `url_template` / `llm.model`、缺省 url/model 的 `request_spec` 可通过校验；提示词模板宽松求值（未知 `{xxx}` / JSON 裸花括号原样保留、`{today}` 仍替换）；接口测试：只填用户提示词创建任务成功，运行期使用个人配置 |
| C3 | 支持空数据表自动新增和更新数据的能力 | 目标表留空 → 按任务名称自动建表并回填 `table_id`；目标表存在但为空 → 自动新增缺失字段；幂等键留空 → 从结果行自动识别（单列 / 最多 3 列组合）；重复运行更新既有行、不重复插入 | `src/cndb/plugins/datasource/services/auto_table.py`、`services/write.py`、`services/runner.py` | 集成测试：首轮自动建表 + inserted，次轮 updated 且行数不增；已有空表自动补字段；无唯一列时退化为追加并留痕 |
| C4 | 系统提示词请默认配置好 | 内置高质量中文 `DEFAULT_SYSTEM_PROMPT`（角色 / 只输出 JSON / `rows` 结构 / 字段命名与类型约定 / 真实性约束 / 日期口径）；未显式配置时自动使用，前端可查看默认全文并可覆盖 | `src/cndb/plugins/datasource/providers/llm_prompt.py`、`src/cndb/plugins/accounts/routers/llm_config.py` | 单测：未配置 system 时请求体 system 为内置默认；接口测试：`GET /api/v1/accounts/llm-config` 返回 `default_system_prompt` |
| C5 | 提供5组典型可用的推荐用户提示词参考示例 | 内置 8 组预设（首批 5 组：每日新闻摘要 / 城市天气 / 股票行情快照 / 电商竞品价格 / 行业政策公告；2026-10-22 追加 3 组：商业航天新闻动态 / 美食推荐做法 / 国际形势发展动态），每组含名称、说明、建议目标表字段、建议幂等键与 prompt 示例；前端一键套用 | `frontend/src/pages/datasource/llmPromptPresets.ts`、`DatasourcePage.tsx` | 前端单测：预设数量为 8 组、字段齐全、占位符合法、一键填入表单 |
| C6 | 并给出说明 | 每组预设给出「适用场景 / 建议目标表字段 / 建议幂等键 / prompt 示例」说明，页面在套用时展示，文档附录保留同一份说明 | `frontend/src/pages/datasource/llmPromptPresets.ts`、`docs/adr/0019-llm-prompt-config-simplify.md` | 前端单测：套用后展示该组说明；文档：ADR 附录 8 组说明齐全可对照 |
| C7 | 大模型相关配置移到个人配置里（2026-10-22 追加） | 连接配置由工作区级改为**个人级**：新表 `datasource_user_llm_config`（`user_id` 唯一，地址 / 模型 / 加密 Key / 系统提示词覆盖）；迁移把旧工作区配置按 `created_by` 迁给用户并删除旧表；个人接口 `GET|PUT /api/v1/accounts/llm-config`（只操作当前用户，Key 只写不回显）与 `POST /api/v1/accounts/llm-config/test`（可用未保存 Key 测试、不落库）；工作区级 `llm-config` / `test-connection` 端点删除；任务保存校验与运行按当前用户 / `job.created_by` 的个人配置解析；前端入口改为「个人设置 → 大模型」，数据源页不再配置连接；工作区备份升 v7 且**不再导出个人配置**，导入兼容 1-7 | `src/cndb/plugins/datasource/models.py`、`src/cndb/alembic/versions/6a7b8c9d0e1f_add_user_llm_config.py`、`src/cndb/plugins/accounts/routers/llm_config.py`、`src/cndb/plugins/datasource/services/connection.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`frontend/src/pages/settings/SettingsModal.tsx`、`frontend/src/pages/settings/LlmConfigPanel.tsx`、`frontend/src/pages/datasource/DatasourcePage.tsx`、`frontend/src/api/llmConfig.ts` | 接口测试：个人 GET/PUT 只影响当前用户、他人配置互不可见、Key 不回显、test 用未保存 Key 不落库；任务运行按用户解析（job 创建者）；迁移：旧工作区配置迁给 `created_by` 并删旧表、无 `created_by` 时丢弃；备份：v7 不含个人配置、v1-v7 均可导入；前端：个人设置「大模型」页签可编辑并测试，数据源页无连接入口 |
| C8 | 推荐提示词开箱可用：长输出不截断、新闻 / 美食返回结构化数据（2026-10-22 追加） | 默认 `max_tokens` 1024 → 4096；JSON 解析失败且疑似截断时给出「提高 max_tokens / 精简输出」的可执行提示（保留普通非法 JSON 文案）；默认系统提示词对综述 / 摘要 / 推荐类任务要求尽力输出，不因无法联网返回空数组，无法核实的事实标注「综合整理」、`url` 可空；「每日新闻摘要」「美食推荐做法」预设据此调整（新闻基于已掌握近期公开信息、允许标注综合整理；美食控制输出规模） | `src/cndb/plugins/datasource/providers/llm_prompt.py`、`frontend/src/pages/datasource/llmPromptPresets.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx` | 单测：默认 `max_tokens=4096`；截断 JSON 报错含「max_tokens」引导、普通非法 JSON 文案不变；默认系统提示词含「综合整理」与尽力输出约束；预设单测校验新闻 / 美食 prompt 文案；真机验收：新闻摘要与美食推荐两组预设能返回可解析 JSON 并落表 |
| C9 | 典型示例数据要带数据源同步配置（含美食推荐做法 / 国际形势发展动态）；大模型动态拉取的字段要支持中文（2026-10-23 追加） | ① 内置系统提示词字段命名改中文优先（中文短名 / 英文 snake_case 均可，不含空格标点；提示词已指定字段名必须逐字沿用）；② 8 组推荐提示词的 `target_fields` / `match_keys` / 字段说明改中文；③ 自动幂等键「像键」加权补中文片段；④ 示例工作区两张 LLM 内容表的 CSV 表头、`views.json`、`fields.json` 改中文字段；⑤ `datasource.json` 补两条 `llm_prompt` 任务（中文 `field_mapping` / `match_keys`、只配提示词与模型参数、`schedule.mode=manual`）；⑥ 示例数据种子与前端预设测试同步 | `src/cndb/plugins/llm/services/prompts.py`、`src/cndb/plugins/datasource/services/auto_table.py`、`frontend/src/pages/datasource/llmPromptPresets.ts`、`examples/datasets/工作区-数据源示例/` | 单测：默认系统提示词含中文字段口径且不再出现「不要使用中文」；中文字段映射归一保留原名；中文列参与幂等键推断；种子测试校验 4 条任务、中文 `match_keys` 存在且与 CSV 表头一致、LLM 任务为 `manual`；前端预设单测校验中文字段命名与「字段名用中文」说明 |

| C10 | 大模型设置要提供典型服务商及其模型对应列表供选择，选后自动填好 API 地址和模型，同时保留开放入口用于自定义（2026-10-23 追加；2026-10-24 移除国外服务商） | ① 个人设置「大模型」新增「服务商」下拉（DeepSeek / 阿里云百炼 / 智谱 GLM / 月之暗面 / 火山方舟 / 硅基流动 共 6 家国内服务商，各带 OpenAI 兼容 `base_url` 与常用模型列表）；② 选中服务商即覆盖 `base_url` + 默认模型（`models[0]`）；③ 模型字段为「可选可填」AutoComplete，列表外模型名可直接输入；④ 「自定义（自行填写地址与模型）」清空地址回到纯手填，手改地址后服务商自动回落「自定义」；⑤ 服务商预设只在前端（不参与后端校验、不落库），已保存配置按 `base_url` 反查回显服务商 | `frontend/src/pages/settings/llmProviders.ts`、`frontend/src/pages/settings/LlmConfigPanel.tsx` | 单测：`llmProviders.test.ts` 校验预设唯一 / https / 不带 `/chat/completions` / 反查归一（末尾斜杠、大小写、空白）/ 未命中返回 null；`LlmConfigPanel.test.tsx` 校验默认地址回显 DeepSeek、选百炼自动填 `compatible-mode/v1` + `qwen-plus`、选自定义清空地址且手填地址回落自定义、模型可输入列表外名称 |
约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | `llm_prompt` 任务表单逐任务填写 API 地址 / 模型 / 系统提示词 | `frontend/src/pages/datasource/DatasourcePage.tsx:465`、`:556`、`:624-710` | 表单字段多且多为必填，是「配置项过于复杂」的直接来源 |
| 2 | Provider 配置校验强制 `url_template` / `llm.model` / `prompt.user_template` | `src/cndb/plugins/datasource/providers/llm_prompt.py:75-109`（`LlmConfig.from_payload`） | 无连接默认值时无法只填提示词 |
| 3 | `llm_prompt` 任务创建 / 更新校验要求 cron 配 `match_keys` | `routers/sync_jobs.py:94-100`、`providers/llm_prompt.py`（`validate_llm_request_spec`） | 与 C3「自动识别幂等键」冲突，需去掉硬校验 |
| 4 | 任务保存 / 更新只校验目标表字段存在，无「留空目标表」语义 | `routers/sync_jobs.py:66-118` | 目标表留空应合法并触发自动建表 |
| 5 | 运行落表要求 `table_id` 非空；`match_keys` 为空退化为纯追加 | `services/runner.py:297-317`、`services/write.py:39-67` | 需在 runner 内补「建表 + 空表补字段 + 自动幂等键」 |
| 6 | API Key 只走 `datasource_session.secrets.api_key` | `services/runner.py:205-213`、`core/crypto.py:79-84` | 新增个人连接后需兼容旧会话路径（会话 Key 仍优先） |
| 7 | 备份版本 v6，导出工作区级 LLM 连接配置 | `src/cndb/plugins/workspaces/services/backup_io.py:80` | 个人配置不应随工作区备份，需升 v7 并不再导出；导入兼容 1-7 |
| 8 | 前端 `datasourceApi` 封装了工作区级连接类型与端点 | `frontend/src/api/datasource.ts` | 需迁到个人 API（`frontend/src/api/llmConfig.ts`）并从 datasourceApi 删除旧封装 |
| 9 | 内置系统提示词仅一句 `JSON_INSTRUCTION` | `providers/llm_prompt.py:45` | 需替换为完整默认系统提示词 |
| 10 | 提示词模板求值严格模式把未注册占位符与裸 `}` 当错误 | `src/cndb/plugins/datasource/providers/template.py` | 用户直接写 JSON 示例（`{"rows": [...]}`）会被保存校验拦下，需新增 llm_prompt 专用宽松求值 |
| 11 | 现有测试基线 | `tests/test_datasource_llm_provider.py`、`tests/test_datasource_api.py`、`tests/test_datasource_backup.py`、`tests/test_datasource_migration.py`、`tests/test_datasource_llm_config.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx`、`frontend/src/pages/settings/LlmConfigPanel.test.tsx` | 新行为需同轮补测试 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] **大模型连接放哪一层** → **个人级**配置一次（`base_url` / `model` / `api_key` / 可选 `system_prompt`，按用户隔离），任务不再逐条填（2026-10-22 用户确认；同日追加需求由「工作区级」改为「个人级」）
- [x] **API Key 存储与导出** → 个人连接内 Fernet 加密、只写不回显；不随工作区备份导出（2026-10-22 确认）
- [x] **系统提示词默认值** → 内置完整默认系统提示词，未配置时自动使用；连接配置可覆盖（2026-10-22 确认）
- [x] **空表自动化范围** → 目标表留空自动建表 / 已有空表自动补字段 / 自动识别幂等键；仅对 `llm_prompt` 生效，其它 provider 不变（2026-10-22 确认）
- [x] **推荐提示词清单** → 首批 5 组：每日新闻摘要、城市天气、股票行情快照、电商竞品价格、行业政策公告（2026-10-22 确认）；追加 3 组：商业航天新闻动态、美食推荐做法、国际形势发展动态（2026-10-22 用户追加，共 8 组）
- [x] **兼容与备份** → 既有 `llm_prompt` 任务（会话 + url/model）与其它 provider 行为不变；备份升 v7 且导入端兼容 1-7（2026-10-22 确认；同日追加个人级配置后 v7 不再导出个人大模型配置）
- [x] **个人配置的隔离与备份边界（2026-10-22 追加）** → 连接配置属于个人数据：一人一条（`user_id` 唯一）、只对本人可见 / 可改，任务按创建者解析；旧工作区配置按 `created_by` 迁移给用户后删除旧表；个人配置不随工作区备份导出（v7 起），避免把 A 的 Key 带给 B
- [x] **推荐提示词失败原因与修复口径（2026-10-22 追加）** → 美食失败为输出被 `max_tokens=1024` 截断（`Unterminated string`），新闻失败为模型面对实时性要求直接返回空；口径改为默认 `max_tokens=4096`、截断错误提示引导调大或精简、系统提示词要求综述 / 推荐类尽力输出且无法核实处标注「综合整理」、预设 prompt 同步调整（新闻基于已掌握近期公开信息、美食控制单次输出规模）
- [x] **中文字段范围（2026-10-23 追加）** → **全面中文**：默认系统提示词 + 8 组预设 + 示例工作区两张 LLM 内容表（CSV 表头 / `views.json` / `fields.json` / 同步任务映射与幂等键）统一中文字段；英文 snake_case 仍兼容（用户改回英文也可落表）；示例 LLM 任务默认 `manual`，避免无个人 Key 时 cron 空跑失败（2026-10-23 用户确认）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-22）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
