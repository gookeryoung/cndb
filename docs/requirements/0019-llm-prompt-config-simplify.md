# 需求卡片：大模型提示词配置简化（工作区连接 + 提示词极简 + 空表自动化）

- 编号：0019（与 ADR `docs/adr/0019-*.md` 同号）
- 来源 / 提出人：工作区需求（用户提出）
- 日期：2026-10-22
- 关联 ADR：[ADR 0019](../adr/0019-llm-prompt-config-simplify.md)

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 大模型提示词抓取功能配置项过于复杂，需要进行简化，尽可能只配置提示词项即可确保抓取到合适的数据，并且支持空数据表自动新增和更新数据的能力。系统提示词请默认配置好，提供5组典型可用的推荐用户提示词参考示例，并给出说明。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 大模型提示词抓取功能配置项过于复杂，需要进行简化 | 新建 / 编辑 `llm_prompt` 任务的主表单只保留「任务名称 + 用户提示词 + 可选目标表」；API 地址 / 模型 / 系统提示词 / 幂等键 / 调度等下沉为高级设置或工作区级连接，默认不要求逐任务填写 | `frontend/src/pages/datasource/DatasourcePage.tsx`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`providers/llm_prompt.py` | 前端单测：`llm_prompt` 表单只渲染提示词相关必填项、其余收进高级设置；接口测试：只带 `prompt.user_template` 的任务可保存（201）；用户提示词含 JSON 裸花括号（如 `{"rows": [...]}`）可直接保存 / 运行 |
| C2 | 尽可能只配置提示词项即可确保抓取到合适的数据 | 工作区级「大模型连接」配置一次（`base_url` / `model` / `api_key` 加密 / 可选 `system_prompt` 覆盖）；任务 `request_spec` 允许缺省 `url_template` 与 `llm.model`，保存与运行时由连接配置 / 默认值补齐；未配置 `system` 时自动使用内置默认系统提示词 | `src/cndb/plugins/datasource/services/connection.py`、`routers/llm_config.py`、`providers/llm_prompt.py`、`services/runner.py` | 单测：连接解析补 `url_template` / `llm.model`、缺省 url/model 的 `request_spec` 可通过校验；提示词模板宽松求值（未知 `{xxx}` / JSON 裸花括号原样保留、`{today}` 仍替换）；接口测试：只填用户提示词创建任务成功，运行期使用连接配置 |
| C3 | 支持空数据表自动新增和更新数据的能力 | 目标表留空 → 按任务名称自动建表并回填 `table_id`；目标表存在但为空 → 自动新增缺失字段；幂等键留空 → 从结果行自动识别（单列 / 最多 3 列组合）；重复运行更新既有行、不重复插入 | `src/cndb/plugins/datasource/services/auto_table.py`、`services/write.py`、`services/runner.py` | 集成测试：首轮自动建表 + inserted，次轮 updated 且行数不增；已有空表自动补字段；无唯一列时退化为追加并留痕 |
| C4 | 系统提示词请默认配置好 | 内置高质量中文 `DEFAULT_SYSTEM_PROMPT`（角色 / 只输出 JSON / `rows` 结构 / 字段命名与类型约定 / 不得编造 / 日期口径）；未显式配置时自动使用，前端可查看默认全文并可覆盖 | `src/cndb/plugins/datasource/providers/llm_prompt.py`、`routers/llm_config.py` | 单测：未配置 system 时请求体 system 为内置默认；接口测试：`GET llm-config` 返回 `default_system_prompt` |
| C5 | 提供5组典型可用的推荐用户提示词参考示例 | 内置 5 组预设（每日新闻摘要 / 城市天气 / 股票行情快照 / 电商竞品价格 / 行业政策公告），每组含名称、说明、建议目标表字段、建议幂等键与 prompt 示例；前端一键套用 | `frontend/src/pages/datasource/llmPromptPresets.ts`、`DatasourcePage.tsx` | 前端单测：预设恰好 5 组、字段齐全、占位符合法、一键填入表单 |
| C6 | 并给出说明 | 每组预设给出「适用场景 / 建议目标表字段 / 建议幂等键 / prompt 示例」说明，页面在套用时展示，文档附录保留同一份说明 | `frontend/src/pages/datasource/llmPromptPresets.ts`、`docs/adr/0019-llm-prompt-config-simplify.md` | 前端单测：套用后展示该组说明；文档：ADR 附录 5 组说明齐全可对照 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | `llm_prompt` 任务表单逐任务填写 API 地址 / 模型 / 系统提示词 | `frontend/src/pages/datasource/DatasourcePage.tsx:465`、`:556`、`:624-710` | 表单字段多且多为必填，是「配置项过于复杂」的直接来源 |
| 2 | Provider 配置校验强制 `url_template` / `llm.model` / `prompt.user_template` | `src/cndb/plugins/datasource/providers/llm_prompt.py:75-109`（`LlmConfig.from_payload`） | 无连接默认值时无法只填提示词 |
| 3 | `llm_prompt` 任务创建 / 更新校验要求 cron 配 `match_keys` | `routers/sync_jobs.py:94-100`、`providers/llm_prompt.py`（`validate_llm_request_spec`） | 与 C3「自动识别幂等键」冲突，需去掉硬校验 |
| 4 | 任务保存 / 更新只校验目标表字段存在，无「留空目标表」语义 | `routers/sync_jobs.py:66-118` | 目标表留空应合法并触发自动建表 |
| 5 | 运行落表要求 `table_id` 非空；`match_keys` 为空退化为纯追加 | `services/runner.py:297-317`、`services/write.py:39-67` | 需在 runner 内补「建表 + 空表补字段 + 自动幂等键」 |
| 6 | API Key 只走 `datasource_session.secrets.api_key` | `services/runner.py:205-213`、`core/crypto.py:79-84` | 新增工作区级连接后需兼容旧会话路径 |
| 7 | 备份版本 v5，不含 LLM 连接配置 | `src/cndb/plugins/workspaces/services/backup_io.py:80` | 需升 v6 并导入兼容 1-5；API Key 不导出 |
| 8 | 前端 `datasourceApi` 无工作区级连接类型与端点封装 | `frontend/src/api/datasource.ts` | 需补 `getLlmConfig` / `updateLlmConfig` |
| 9 | 内置系统提示词仅一句 `JSON_INSTRUCTION` | `providers/llm_prompt.py:45` | 需替换为完整默认系统提示词 |
| 10 | 提示词模板求值严格模式把未注册占位符与裸 `}` 当错误 | `src/cndb/plugins/datasource/providers/template.py` | 用户直接写 JSON 示例（`{"rows": [...]}`）会被保存校验拦下，需新增 llm_prompt 专用宽松求值 |
| 11 | 现有测试基线 | `tests/test_datasource_llm_provider.py`、`tests/test_datasource_api.py`、`tests/test_datasource_backup.py`、`tests/test_datasource_migration.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | 新行为需同轮补测试 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] **大模型连接放哪一层** → 工作区级配置一次（`base_url` / `model` / `api_key` / 可选 `system_prompt`），任务不再逐条填（2026-10-22 用户确认）
- [x] **API Key 存储与导出** → 工作区连接内 Fernet 加密、只写不回显；不随备份导出（2026-10-22 确认）
- [x] **系统提示词默认值** → 内置完整默认系统提示词，未配置时自动使用；连接配置可覆盖（2026-10-22 确认）
- [x] **空表自动化范围** → 目标表留空自动建表 / 已有空表自动补字段 / 自动识别幂等键；仅对 `llm_prompt` 生效，其它 provider 不变（2026-10-22 确认）
- [x] **5 组推荐提示词清单** → 每日新闻摘要、城市天气、股票行情快照、电商竞品价格、行业政策公告（2026-10-22 确认）
- [x] **兼容与备份** → 既有 `llm_prompt` 任务（会话 + url/model）与其它 provider 行为不变；备份升 v6，导入端兼容 1-5（2026-10-22 确认）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-22）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
