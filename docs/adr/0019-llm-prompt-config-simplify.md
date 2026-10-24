# ADR 0019: 大模型提示词配置简化（个人级连接 + 内置系统提示词 + 空表自动落表 + 提示词可靠性）

Status: Implemented
Date: 2026-10-22
Related: `src/cndb/plugins/llm/models.py`、`src/cndb/plugins/llm/plugin.py`、`src/cndb/plugins/llm/services/connection.py`、`src/cndb/plugins/llm/services/client.py`、`src/cndb/plugins/llm/services/parsing.py`、`src/cndb/plugins/llm/services/prompts.py`、`src/cndb/plugins/llm/routers/config.py`、`src/cndb/core/http.py`、`src/cndb/plugins/datasource/schemas.py`、`src/cndb/plugins/datasource/services/auto_table.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/providers/llm_prompt.py`、`src/cndb/plugins/datasource/providers/template.py`、`src/cndb/cli/sync.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/plugins/datasource/routers/__init__.py`、`src/cndb/alembic/versions/7b8c9d0e1f2a_add_llm_plugin.py`、`src/cndb/alembic/versions/6a7b8c9d0e1f_add_user_llm_config.py`、`src/cndb/plugins/workspaces/routers/workspaces.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`frontend/src/api/llm.ts`、`frontend/src/api/datasource.ts`、`frontend/src/pages/settings/LlmConfigPanel.tsx`、`frontend/src/pages/settings/llmProviders.ts`、`frontend/src/pages/settings/SettingsModal.tsx`、`frontend/src/pages/datasource/llmPromptPresets.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx`；上游见 ADR 0006 / ADR 0014 / ADR 0020
需求卡片: `docs/requirements/0019-llm-prompt-config-simplify.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」段落；ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用，不在仓库保留 `Superseded` / `Deprecated` 文档。
>
> 2026-10-22 用户追加需求：① 大模型相关配置移到个人配置；② 推荐提示词（新闻摘要 / 美食推荐）获取失败。本 ADR 就地改写为「个人级连接 + 提示词可靠性」口径，C7/C8 见需求卡片。
>
> 2026-10-23 用户追加需求：大模型设置要提供典型服务商及其模型对应列表，选后自动填好 API 地址与模型，同时保留自定义入口。本 ADR 追加 C10 口径（服务商预设），代码落点见 `frontend/src/pages/settings/llmProviders.ts`、`frontend/src/pages/settings/LlmConfigPanel.tsx`。

> 2026-10-23 用户追加需求：典型示例数据要带「美食推荐做法 / 国际形势发展动态」的数据源同步配置，且大模型动态拉取的字段要支持中文。本 ADR 追加 C9 口径（字段命名中文化 + 示例同步任务），代码落点见 `llm/services/prompts.py`、`auto_table.py`、`frontend/src/pages/datasource/llmPromptPresets.ts`、`examples/datasets/工作区-数据源示例/`。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C8），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 大模型提示词抓取功能配置项过于复杂，需要进行简化 | 任务抽屉 `llm_prompt` 分支主表单只留「任务名称 / 用户提示词 / 目标表（可留空）」；API 地址、模型、系统提示词、幂等键、调度、温度等收进高级设置或个人级连接；后端 `_validate_job_config` 对 `llm_prompt` 只强制用户提示词 |
| C2 | 尽可能只配置提示词项即可确保抓取到合适的数据 | 个人级「大模型连接」（`base_url` / `model` / `api_key` / 可选 `system_prompt`，按 `user_id` 隔离，表 `llm_user_config`）配置一次；`llm/services/connection.py` 的 `resolve_request_spec_defaults` 在运行 / 预览期补齐 `url_template` / `llm.model`（保存时仅在内存中补齐用于校验），均不写回 `request_spec`；未配置 system 时使用内置默认系统提示词；提示词模板用宽松求值（`render_text_lenient`）：JSON 裸花括号与未知 `{xxx}` 原样保留，仅替换已注册变量，`{{`/`}}` 仍转义为字面花括号 |
| C3 | 支持空数据表自动新增和更新数据的能力 | `auto_table.ensure_job_table`（留空目标表 → 按任务名建表）、`is_table_empty` + `upsert_rows(auto_add_fields=True)`（空表补字段）、`infer_match_keys` + `upsert_rows(auto_match_keys=True)`（自动幂等键）；重复运行只更新不重复插入 |
| C4 | 系统提示词请默认配置好 | `src/cndb/plugins/llm/services/prompts.py` 维护完整 `DEFAULT_SYSTEM_PROMPT`（输出格式 / 字段命名 / 真实性约束，`providers/llm_prompt.py` 复用导出）；请求构造在未配置 system 时使用它；个人配置或任务高级设置可层层覆盖 |
| C5 | 提供5组典型可用的推荐用户提示词参考示例 | `frontend/src/pages/datasource/llmPromptPresets.ts` 内置 8 组预设（首批 5 组：每日新闻摘要 / 城市天气 / 股票行情快照 / 电商竞品价格 / 行业政策公告；2026-10-22 追加 3 组：商业航天新闻动态 / 美食推荐做法 / 国际形势发展动态），任务抽屉「推荐提示词」一键套用 |
| C6 | 并给出说明 | 每组预设带 `description / target_fields / match_keys / prompt`，套用时在页面展示「适用场景 + 建议目标表字段 + 建议幂等键」；同一份说明写入本 ADR 附录，页面与文档同源 |
| C7 | 大模型相关配置移到个人配置里（2026-10-22 追加） | 连接归属为**个人级**：新表 `llm_user_config`（`user_id` 唯一，级联删除；模型 `LlmUserConfig`）；接口在 `GET|PUT /api/v1/llm/config` + `POST /api/v1/llm/config/test`（旧 `GET|PUT /api/v1/accounts/llm-config` / `POST /api/v1/accounts/llm-config/test` 删除）；工作区级 `llm-config` / `test-connection` 端点删除；任务保存只校验、运行 / 预览按当前用户 / `job.created_by` 解析个人连接（不把默认值写回任务）；前端入口改为「个人设置 → 大模型」，数据源页不再配置；备份升 v7 且不导出个人配置 |
| C8 | 推荐提示词开箱可用（2026-10-22 追加） | 默认 `max_tokens` 1024 → 4096；JSON 解析失败且疑似截断时给出「提高 max_tokens / 精简输出」提示；默认系统提示词要求综述 / 推荐类任务尽力输出，不因无法联网返回空数组，无法核实的事实标注「综合整理」、`url` 可空；「每日新闻摘要」「美食推荐做法」预设按此调整 |
| C9 | 大模型动态拉取的字段能否支持中文（2026-10-23 追加） | 字段命名默认中文化：内置系统提示词改为「字段名支持中文（中文短名 / 英文 snake_case 均可）、提示词已指定的字段名必须逐字沿用」；8 组推荐提示词的 `target_fields` / `match_keys` / 字段说明全部改中文；自动幂等键的「像键」加权补中文片段（日期 / 编号 / 名称 / 城市 / 标题 / 主题…）；示例工作区两张 LLM 内容表（美食推荐做法 / 国际形势发展动态）的 CSV 表头、视图引用、字段设置、同步任务映射与幂等键同步改中文，并补齐两条 `llm_prompt` 同步配置 |

| C10 | 大模型设置提供典型服务商及其模型对应列表，选后自动填好 API 地址和模型，保留自定义入口（2026-10-23 追加；2026-10-24 移除国外服务商） | `frontend/src/pages/settings/llmProviders.ts` 维护 6 家国内服务商预设（DeepSeek / 阿里云百炼 / 智谱 GLM / 月之暗面 Kimi / 火山方舟 / 硅基流动）：每条只带 OpenAI 兼容 `base_url`（不含 `/chat/completions`，前端保存 / 测试时仍由后端补全）与常用模型列表，`models[0]` 为默认模型；面板「服务商」下拉选中即写入 `base_url` + 默认模型，模型字段是「可选可填」AutoComplete（列表外可直接输入）；「自定义（自行填写地址与模型）」清空地址回到手填，手改地址后按 `base_url` 反查自动回落「自定义」；预设只在前端，不落库、不参与后端校验（后端默认值 `DEFAULT_BASE_URL` / `DEFAULT_MODEL` 不变），新增服务商只改这一个文件 |
决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，本轮变更后口径）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 连接配置按用户存放：一个用户至多一条，不再跟随工作区 | `src/cndb/plugins/llm/models.py`（`LlmUserConfig`，表 `llm_user_config`）、`src/cndb/plugins/llm/routers/config.py` | 同一用户跨工作区共用一份配置；共享工作区里各成员的 Key 相互隔离 | 确认（C7） |
| 2 | 个人接口 `GET|PUT /api/v1/llm/config`（登录即可，无需工作区权限）与 `POST /api/v1/llm/config/test`（可用未保存 Key，不落库） | `src/cndb/plugins/llm/routers/config.py`、`src/cndb/plugins/llm/plugin.py` | 配置入口与工作区解耦，任何页面/任务都能复用 | 确认（C7） |
| 3 | 工作区级端点 `GET|PUT /{wid}/datasource/llm-config` 与 `POST /{wid}/datasource/test-connection` 已删除 | `src/cndb/plugins/datasource/routers/__init__.py`、`routers/sync_jobs.py` | 不会再有「工作区连接」与「个人配置」两份配置并存 | 确认（C7） |
| 4 | 迁移链：`6a7b8c9d0e1f`（历史保留）建个人表 `datasource_user_llm_config` 并把旧工作区配置按 `created_by` 迁给用户；`7b8c9d0e1f2a` 把该表数据全量搬入 `llm_user_config` 后删除旧表；head 常量 = `7b8c9d0e1f2a` | `src/cndb/alembic/versions/7b8c9d0e1f2a_add_llm_plugin.py`、`src/cndb/alembic/versions/6a7b8c9d0e1f_add_user_llm_config.py` | 存量配置不丢（个人表按列一一对应搬迁）；head 处 schema 只剩 `llm_user_config`，旧表不再出现 | 确认（C7） |
| 5 | 任务保存只做连接校验（不把默认值写回 `request_spec`）；运行 / 预览时按**用户**解析连接：当前登录用户或 `job.created_by` | `src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/llm/services/connection.py` | 任务由谁创建就用谁的 Key；管理员代跑不会误用他人配置；地址 / 模型不再随任务与备份外泄 | 确认（C7/C2） |
| 6 | 工作区备份 v7 不再导出大模型配置，导入接受 1-7；旧 v6 备份里的 `llm_config` 键按未知键忽略；任务 `request_spec` 也不再持久化个人 `base_url` / `model` | `src/cndb/plugins/workspaces/routers/workspaces.py`、`src/cndb/plugins/workspaces/services/backup_io.py` | 个人 Key / 地址 / 模型不随工作区交付给其他成员 / 其他环境 | 确认（C7） |
| 7 | 前端入口在「个人设置 → 大模型」页签，API 封装走 `frontend/src/api/llm.ts` 的 `llmApi`（`/v1/llm/config`）；数据源页无连接按钮 / Tag / 弹窗 | `frontend/src/pages/settings/SettingsModal.tsx`、`frontend/src/pages/settings/LlmConfigPanel.tsx`、`frontend/src/pages/datasource/DatasourcePage.tsx` | 配置位置符合「个人配置」直觉，数据源页只保留任务本身 | 确认（C7） |
| 8 | `llm_prompt` 任务主表单只留任务名称 / 用户提示词 / 目标表，其余收高级设置 | `frontend/src/pages/datasource/DatasourcePage.tsx` | 「只写一句提示词」可保存，地址 / 模型 / Key 从个人配置继承 | 确认（C1/C2） |
| 9 | 默认 `max_tokens` 曾为 1024，长新闻 / 美食 JSON 在中途被截断（`Unterminated string`） | `src/cndb/plugins/llm/services/prompts.py`（`DEFAULT_MAX_TOKENS`，`llm_prompt` 复用） | 推荐提示词开箱即失败，且错误文案看不出是 token 不足 | 确认（C8） |
| 10 | 截断后的 JSON 解析错误与普通非法 JSON 使用同一文案，无修复指引 | `src/cndb/plugins/llm/services/parsing.py`（`parse_chat_response` / `looks_truncated` 迁入，`llm_prompt` 薄封装复用） | 用户无法自查是「输出太长」还是「模型没按要求输出」 | 确认（C8） |
| 11 | 默认系统提示词旧版要求「无法产出就返回 `{"rows": []}`」，模型面对实时性要求时倾向返回空 | `src/cndb/plugins/llm/services/prompts.py`（`DEFAULT_SYSTEM_PROMPT` 真实性约束） | 新闻摘要 / 美食推荐这类不依赖实时库的综述任务直接拿到空数据 | 确认（C8） |
| 12 | 「每日新闻摘要」「美食推荐做法」预设旧文案按实时抓取口径写，且美食一次要求四类多道菜，输出过长 | `frontend/src/pages/datasource/llmPromptPresets.ts` | 与新的系统提示词口径不一致，长输出仍可能截断 | 确认（C8） |
| 13 | 空表自动建表 / 补字段 / 自动幂等键保持原实现 | `src/cndb/plugins/datasource/services/auto_table.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/runner.py` | 本轮不改写路径语义，只换连接来源（`llm/services/connection.py`） | 确认（C3） |
| 14 | 测试覆盖个人接口 / 迁移 / 备份 / 运行解析 / 提示词可靠性 / 前端页签与预设；平台层（client / parsing / 连接搬表）用例见 ADR 0020 P0 | `tests/test_datasource_llm_config.py`、`tests/test_datasource_migration.py`、`tests/test_datasource_backup.py`、`tests/test_datasource_llm_provider.py`、`tests/test_datasource_api.py`、`tests/test_migration_missing_model_columns.py`、`frontend/src/pages/settings/LlmConfigPanel.test.tsx`、`frontend/src/pages/settings/SettingsModal.test.tsx`、`frontend/src/pages/datasource/DatasourcePage.test.tsx`、`frontend/src/pages/datasource/llmPromptPresets.test.ts` | 新行为同轮补测试 | 确认（C1-C8） |
| 15 | 字段命名只能英文：内置系统提示词第 4 条要求「统一使用英文 snake_case，不要使用中文」，8 组预设的字段说明也照抄该约束 | `src/cndb/plugins/llm/services/prompts.py`（`DEFAULT_SYSTEM_PROMPT`）、`frontend/src/pages/datasource/llmPromptPresets.ts` | 模型把中文业务语义翻成英文键，落表后表内是 `dish_name` / `region`，与示例工作区其余表（天气每日等全中文字段）不一致；用户要中文字段只能改写系统提示词 | 确认（C9） |
| 16 | 自动幂等键的「像键」加权只认英文片段（`date` / `city` / `title`…） | `src/cndb/plugins/datasource/services/auto_table.py`（`KEY_NAME_HINTS`） | 中文字段（日期 / 城市 / 标题）权重恒为 0，多列唯一时按候选顺序取，推断结果不稳定 | 确认（C9） |
| 17 | 食品 / 国际形势两张 LLM 内容表只有 CSV 与视图，没有同步配置 | `examples/datasets/工作区-数据源示例/datasource.json` | 示例数据无法演示「提示词 → 中文字段 → 落表」的完整链路，用户无从参考配置 | 确认（C9） |

**核心缺陷（需求要补的）**：连接配置挂在**工作区**上，无法表达「这是某个人的模型账号」——同一用户跨工作区要重复配置，共享工作区下配置归属与 Key 可见性也说不清；同时默认 token 上限与系统提示词的「宁可返回空」倾向，让已内置的新闻 / 美食推荐提示词开箱即失败。

设计目标（不变量）：

- **I1 最少必填**：`llm_prompt` 任务只要求「任务名称 + 用户提示词」；其余配置由个人连接、内置默认或自动推断补齐。
- **I2 默认系统提示词恒有效**：任何 `llm_prompt` 请求都必须带系统提示词（任务覆盖 > 个人覆盖 > 内置默认），不允许空 system 直接调模型；内置默认须支持综述 / 推荐类任务尽力输出并标注「综合整理」。
- **I3 自动化仅限 `llm_prompt`**：其它 provider 的校验、落表、调度语义完全不变；不在通用框架层引入隐式建表。
- **I4 自动幂等键可回退**：推断出的键必须来自结果行且行内唯一；无唯一组合时返回空并退化为追加，同时在 `run.detail` 留痕，不伪造幂等键。
- **I5 密钥不落地明文**：个人连接 `api_key` 只存 Fernet 密文，读接口不回显，备份导出不含 Key；工作区备份不含个人配置。
- **I6 失败不写脏数据**：模型输出不可解析或没有行时，不建表、不补字段、不落库，运行记 `failed`。
- **I7 存量兼容**：旧 `llm_prompt` 任务（会话 + 显式 url/model）继续可用；旧工作区连接按 `created_by` 迁移；v1-v7 备份继续可导入。
- **I8 个人配置按 user 隔离**：一条记录对应用户，读写只作用当前登录用户；任务按创建者解析，不复用他人的 Key。
- **I9 长输出不被静默截断**：默认 `max_tokens` 足够覆盖推荐类任务，截断时错误信息必须指向可执行的修复动作（提高 max_tokens / 精简输出）。

## Decision

### 1. 数据模型

个人级连接表 `llm_user_config`（模型 `LlmUserConfig`，由迁移 `7b8c9d0e1f2a` 自 `datasource_user_llm_config` 全量搬入后删除旧表）：

| 列 | 类型 | 约束 / 说明 |
|---|---|---|
| `user_id` | int | 唯一键（`ix_llm_user_config_user_id`），一个用户至多一条连接；随用户级联删除 |
| `base_url` | varchar | OpenAI 兼容端点，保存时校验必须是 http(s) |
| `model` | varchar | 非空，默认 `deepseek-chat` |
| `api_key` | varchar(1024) | Fernet 密文（`enc:v1:` 前缀），空表示未配置；只写不回显 |
| `system_prompt` | text | 可选，留空表示使用内置默认系统提示词 |
| `created_at` / `updated_at` | — | 沿用审计时间戳 mixin |

- 历史表链不可改：工作区表 `datasource_llm_config` 由迁移 `6a7b8c9d0e1f` 搬迁后删除；个人表 `datasource_user_llm_config` 由 `7b8c9d0e1f2a` 全量搬入 `llm_user_config` 后删除——两条历史迁移保留，head 处只剩 `llm_user_config`（不再有 `workspace_id` / `created_by` 列）。
- `datasource_sync_job` 不加列：目标表仍用 `table_id`（可空），显式幂等键仍用 `match_keys`（可空），自动推断结果回填 `match_keys` 持久化。
- `request_spec` 结构不变：任务可只保留 `{"prompt": {"user_template": "..."}}`；显式 `url_template` / `llm.model` 仍允许（高级覆盖）。**保存任务不再把个人连接的 `url_template` / `llm.model` 写回 `request_spec`**，默认值只在运行 / 预览期解析（ADR 0020 D8）。
- 工作区备份升 **v7**：**不导出**个人大模型配置（个人数据不随工作区备份），导入端接受版本 1-7；v6 备份里可能残留的 `llm_config` 键忽略；任务配置里也不再出现个人 `base_url` / `model`。

### 2. 判定入口（唯一实现）

**个人连接解析** `src/cndb/plugins/llm/services/connection.py`：

```python
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

@dataclass(frozen=True, slots=True)
class LlmConnection:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = ""        # 解密后的明文，仅运行期使用
    system_prompt: str = ""
    has_api_key: bool = False

def find_user_llm_config(db: Session, user_id: int) -> LlmUserConfig | None: ...
def load_llm_connection(db: Session, user_id: int) -> LlmConnection: ...
def resolve_request_spec_defaults(spec: dict, conn: LlmConnection) -> dict: ...
```

- `find_user_llm_config` / `load_llm_connection`：按 `user_id` 查询，缺失时返回默认值（`DEFAULT_BASE_URL` / `DEFAULT_MODEL` / 空 Key）；解密失败按「未配置 Key」处理。
- `resolve_request_spec_defaults`：只在运行 / 预览期、`url_template` / `llm.model` 缺省时补默认值，**不写 `api_key`**（Key 由运行期注入），显式值优先；保存任务只在内存里补齐用于校验，不写回 `request_spec`。
- Key 解析优先级：任务绑定会话的 `secrets.api_key` > 个人连接的 `api_key`；两处都没有时保存 / 连通测试给出「请先在「个人设置 → 大模型」配置 API Key」的明确错误。

**任务侧用户解析** `routers/sync_jobs.py` / `services/runner.py`：

- 保存 / 更新任务：`_validate_job_config(..., user=current_user)`，用当前登录用户的连接在内存里补齐默认值并校验 Key，**不写回 `request_spec`**。
- 运行 / 预览：`runner.build_job_spec(..., llm_user_id=...)`，手动运行 / 预览传当前操作人 `user.id`，未传时回退 `job.created_by`；`preview_job` 新增 `user` 参数并透传；默认值在此期解析补齐。
- 自动建表 / 补字段 / 自动幂等键逻辑不变（见 `auto_table.py` / `write.py` / `runner.py`），连接来源统一为平台插件 `llm/services/connection.py`。

**平台层调用**（ADR 0020 P0）：`llm_prompt.build_requests` 通过 `RequestPlan.fetcher` 注入 `llm/services/client.py`，模型 HTTP 调用 / 重试 / SSRF 白名单由平台层统一；JSON 围栏与截断识别在 `llm/services/parsing.py`。消息构造（`render_text_lenient`）与「提示词 → 行 → 幂等落表」仍留在 datasource；内置系统提示词 / JSON 指令在 `llm/services/prompts.py`（`llm_prompt` 复用导出）。

**提示词可靠性** `providers/llm_prompt.py` + `src/cndb/plugins/llm/services/parsing.py` + `src/cndb/plugins/llm/services/prompts.py`：

- `DEFAULT_MAX_TOKENS = 4096`（定义在 `llm/services/prompts.py`，`llm_prompt` 重新导出；上限仍为 32768；连通测试仍用 `min(config.max_tokens, 64)` 的小请求）。
- `_parse_response`（provider 薄封装）/ `parse_chat_response` / `looks_truncated`（实现位于 `llm/services/parsing.py`，`llm_prompt` 复用并把 `LlmOutputInvalid` 映射回既有 `ProviderError` 文案）：JSON 解析失败时区分「疑似截断」（`Unterminated string`，或 `Expecting ...` 且错误位置贴近内容末尾）与普通非法 JSON；截断文案为「模型输出可能被截断：请提高 max_tokens（当前默认 4096）或精简提示词输出（本次返回 N 字符）；原始错误: …」。
- `DEFAULT_SYSTEM_PROMPT`（`llm/services/prompts.py`）真实性约束改为：综述 / 摘要 / 推荐类任务基于已掌握公开知识尽力输出、不因无法联网返回空数组；无法确认的实时事实在 `summary` / `source` 标注「综合整理」、`url` 用空串；禁止编造可核实的精确统计数字；只有确实无法生成时才返回 `{"rows": []}`。
- `DEFAULT_SYSTEM_PROMPT` 字段命名条（C9）改为：字段名支持中文，默认中文短名（城市 / 交易日 / 收盘价），也接受英文 snake_case；不得含空格 / 标点；用户提示词或目标表已指定字段名时必须**逐字沿用**，不翻译、不改写。
- 提示词模板宽松求值（`render_text_lenient`）与 URL / headers 严格模板保持不变。

**CLI** `src/cndb/cli/sync.py`：`sync preview` 与 `sync run --dry-run` 同样按任务的 `created_by` 解析个人连接默认值 / Key，并在 JSON 输出里带 `suggested_match_keys`。

### 3. API 变更清单

**平台级（`/api/v1/llm`）**：

| 端点 | 变更 |
|---|---|
| `GET /config` | 新增（替代 `GET /api/v1/accounts/llm-config`）：读取当前用户连接，返回 `configured / base_url / model / has_api_key / system_prompt / default_system_prompt`；**不回显 api_key**；登录即可读 |
| `PUT /config` | 新增（替代 `PUT /api/v1/accounts/llm-config`）：保存当前用户连接；`base_url` 必须 http(s)、`model` 非空；`api_key` 非空才更新、`clear_api_key=true` 清除；密钥 Fernet 加密；局部更新 |
| `POST /config/test` | 新增（替代 `POST /api/v1/accounts/llm-config/test`）：用当前用户连接 + 请求体可选 `base_url` / `model` / `api_key` / `system_prompt` 发一次最小请求，**不落库**；Key 优先级 请求体 > 已保存个人 Key |
| `GET|PUT /api/v1/accounts/llm-config`、`POST /api/v1/accounts/llm-config/test` | **删除**：配置与连通测试迁到 `/api/v1/llm/config`、`/api/v1/llm/config/test`，前端与测试同轮切换 |

**工作区级（`/api/v1/workspaces/{wid}/datasource`）**：

| 端点 | 变更 |
|---|---|
| `GET|PUT /llm-config` | **删除**（配置迁到平台级 `/api/v1/llm/config`） |
| `POST /test-connection` | **删除**（连通测试迁到 `POST /api/v1/llm/config/test`） |
| `POST /sync-jobs`、`PUT /sync-jobs/{id}` | `llm_prompt` 只强制 `prompt.user_template`；缺省 `url_template` / `llm.model` 在运行 / 预览期由**当前用户**的个人连接补齐（保存只在内存里补齐校验，不写回 `request_spec`）；cron 不再强制 `match_keys`；目标表可留空；无可用 Key 时 400 并提示「个人设置 → 大模型」 |
| `POST /sync-jobs/{id}/preview` | 响应含 `suggested_match_keys`；预览按当前用户解析个人连接 |

### 4. 边界与例外

1. 个人配置严格按用户隔离：`GET /api/v1/llm/config` 只返回本人记录，`PUT /api/v1/llm/config` 只写本人记录；任务运行时按 `job.created_by` 解析，管理员代跑不会使用自己的 Key。
2. 自动建表只在模型返回非空行后触发；同名未删除表直接复用，不重复建表；任务失败不留下空表。
3. 自动补字段只在目标表为空（无字段或无数据行）时启用；已有数据表不自动加字段，未知列按既有策略处理。
4. 自动幂等键基于本轮结果行推断：显式 `match_keys` 优先；无唯一组合时退化为追加，`run.detail.auto_match_keys=[]` 留痕，不静默覆盖。
5. 个人连接未配置或没有可用 API Key（会话与个人连接都没有）时：保存 / 更新任务直接 400「请先在「个人设置 → 大模型」配置 API Key」；前端数据源页提示去个人设置配置，不再弹工作区连接弹窗。
6. 任务的高级设置可显式覆盖 `url_template` / `llm.model` / `system_prompt`（兼容旧任务与特殊模型）；显式值优先于个人连接。
7. 仅 `llm_prompt` 触发自动建表 / 补字段 / 自动幂等键；`http_json`、行情、RSS 等 provider 行为不变。
8. 备份 v7 不导出个人大模型配置；v6 及更早备份可导入，其中 `llm_config` 键按未知键忽略，导入后用户的个人配置保持不变。
9. 模型输出不可解析 / 为空时运行记 `failed`，不建表、不写行；疑似截断时错误文案显式引导提高 `max_tokens` 或精简输出，普通语法错误仍报「模型返回内容不是合法 JSON」。
10. `system_prompt` 三层优先级：任务显式配置 > 个人连接覆盖 > 内置默认；页面可查看内置默认全文。
11. 提示词模板宽松求值仅限 `llm_prompt` 的 system / user 提示词；`{{` / `}}` 仍等价于字面花括号。`llm_prompt` 的 URL / headers 模板仍严格；其它 provider 的 URL / headers / body 模板也保持严格模式。
12. 连通测试支持未保存配置：`POST /api/v1/llm/config/test` 的 `api_key` 只用于本次请求（不落库、不回显）；未填写的字段回退当前用户已保存配置 / 内置默认。
13. 内置默认系统提示词对实时数据（行情 / 今日要闻）要求「无法确认就用 null 或标注综合整理」，不鼓励编造；推荐类任务不能以「无法联网」为由返回空数组。
14. 旧工作区配置迁移：同一用户多条只保留 id 最小的一条；`created_by` 为空的记录无处归属，直接丢弃；downgrade 重建旧表但**不恢复数据**。
15. 连接表搬迁（ADR 0020 P0）：迁移 `7b8c9d0e1f2a` 把 `datasource_user_llm_config` 全量搬入 `llm_user_config` 后删除旧表，`down_revision = 6a7b8c9d0e1f`；downgrade 重建**空**旧表（数据不恢复）；保存任务不再把个人 `base_url` / `model` 写回 `request_spec`。
16. 字段命名（C9）：`llm_prompt` 结果行允许中文字段名——物理列名由 `field_<随机段>` 生成，与字段显示名无关，中文名在 DDL / 写入 / 视图 / 分析公式中均按显示名引用；自动补字段与自动幂等键对中文名同样生效（`KEY_NAME_HINTS` 中英并列）。字段名仍不得包含空格与标点，避免导出 CSV / 公式引用歧义。
17. 示例同步任务（C9）默认 `schedule.mode=manual`：`llm_prompt` 需要个人「大模型连接」的 API Key，示例环境通常没有，自动 cron 会每天产生失败运行记录；用户配好 Key 后可在任务抽屉改成 `daily` / `cron` 或直接点「立即运行」。

### 5. 迁移

历史迁移保留（不改）：`5e6f7a8b9c01_add_datasource_llm_config.py` 建工作区级表，`6a7b8c9d0e1f_add_user_llm_config.py`（`down_revision = 5e6f7a8b9c01`）建个人表 `datasource_user_llm_config` 并按 `created_by` 搬旧工作区配置。

新增单条迁移 `7b8c9d0e1f2a_add_llm_plugin.py`（`down_revision = 6a7b8c9d0e1f`，ADR 0020 P0）：

- upgrade：建 `llm_user_config`（`user_id` 唯一索引 + 级联删除；列与旧个人表一一对应）→ 从 `datasource_user_llm_config` 全量搬行 → 建 `llm_run`（调用留痕）→ 删除 `datasource_user_llm_config`；表 / 索引已存在、旧表已不存在时跳过，可重复执行。
- downgrade：重建**空**的 `datasource_user_llm_config`（数据不恢复）→ 删除 `llm_run` → 删除 `llm_user_config`；可重复执行。
- 迁移 head 同步：`tests/test_migration_missing_model_columns.py` 的 `HEAD_REVISION` = `7b8c9d0e1f2a`；head 级断言为「旧表 `datasource_user_llm_config` 已删除、新表 `llm_user_config` 存在」。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/llm.ts` | 新增 `llmApi.get / update / testConnection / listActions / listRuns`（`/v1/llm/*`）与类型 `LlmConfig` / `LlmConfigPayload` / `LlmConnectionTestPayload` / `LlmConnectionTestResult` / `LlmAction` / `LlmRun` |
| API 封装 | `frontend/src/api/datasource.ts`、`frontend/src/api/index.ts` | 删除工作区级 `getLlmConfig` / `updateLlmConfig` / `testConnection` 与对应类型；导出 `llmApi`；旧 `frontend/src/api/llmConfig.ts` 删除，端点迁入 `llm.ts` |
| 个人设置页签 | `frontend/src/pages/settings/LlmConfigPanel.tsx`、`SettingsModal.tsx`、`frontend/src/store/ui.ts` | 「个人设置」新增「大模型」页签：服务商预设 / 地址 / 模型（可选可填）/ Key（只写不回显，已保存可清除）/ 系统提示词覆盖 / 内置默认全文 / 「测试连接」（可用未保存 Key）；`SettingsTab` 增加 `llm` |
| 服务商预设 | `frontend/src/pages/settings/llmProviders.ts` | 6 家国内 OpenAI 兼容服务商（`base_url` + 常用模型，`models[0]` 默认）+ `findProviderByBaseUrl` 地址反查（忽略末尾斜杠 / 大小写 / 空白）；前端专用，不落库、不改后端默认值 |
| 数据源页 | `frontend/src/pages/datasource/DatasourcePage.tsx` | 删除页头「大模型连接」按钮 / 状态 Tag / 连接弹窗与未配置引导；`llm_prompt` 抽屉改为提示去「个人设置 → 大模型」；高级设置 `max_tokens` 默认 4096 |
| 推荐提示词 | `frontend/src/pages/datasource/llmPromptPresets.ts` | 8 组预设；「每日新闻摘要」改为基于已掌握近期公开信息、允许标注「综合整理」；「美食推荐做法」控制单次输出规模；其余预设补充实时数据口径说明；弹窗列表默认收起（手风琴，一次展开一组），点击场景名才展示适用场景 / 建议字段 / 建议幂等键 |
| 页面测试 | `frontend/src/pages/settings/LlmConfigPanel.test.tsx`、`SettingsModal.test.tsx`、`llmProviders.test.ts`、`frontend/src/pages/datasource/DatasourcePage.test.tsx`、`llmPromptPresets.test.ts` | 个人页签保存 / 测试 / 清除 Key / 用户隔离提示 / 选服务商自动填地址与模型 / 选自定义清空地址 / 模型可手填；数据源页无连接入口、提示文案；预设文案与数量 |

### 7. 测试清单

**判定层（单测）**：
- 个人连接：未配置返回默认值、按 `user_id` 查询、解密失败按未配置；显式 url/model 优先。
- `infer_match_keys` / `ensure_job_table` / `is_table_empty` / `upsert_rows` 自动补字段与自动幂等键（沿用既有用例）。
- 提示词可靠性：默认 `max_tokens=4096`；截断 JSON（`Unterminated string` / 末尾 `Expecting`）报错包含「max_tokens」引导；普通非法 JSON 文案不变；`DEFAULT_SYSTEM_PROMPT` 含「综合整理」与「不要因为无法联网…返回空数组」约束。
- 宽松模板：JSON 裸花括号可原样保存 / 运行；`{"date": "{today}"}` 内层变量仍替换；`{{` / `}}` 转义；严格 `render_text` 回归。

**接口层**：
- 个人 `GET|PUT /api/v1/llm/config` 与 `POST /api/v1/llm/config/test`：默认值、加密不回显、`clear_api_key`、非法 base_url 400、未登录 401、用户间隔离（A 的配置 B 读不到）、test 使用未保存 Key 不落库。
- 旧个人端点 `GET|PUT /api/v1/accounts/llm-config`、`POST /api/v1/accounts/llm-config/test` 已删除（404）。
- 工作区级 `llm-config` / `test-connection` 端点已删除（404）。
- `sync-jobs`：只填用户提示词可保存；保存后 `request_spec` 不含个人 `url_template` / `llm.model`（create 与 update 两条路径）；缺 Key 400 且文案指向「个人设置 → 大模型」；cron 不配 `match_keys` 可保存；任务按创建者 / 当前用户解析个人连接（含预览、运行）。
- CLI `sync preview` / `sync run --dry-run` 使用任务创建者的个人连接并输出 `suggested_match_keys`。
- 既有 `llm_prompt` 任务与其它 provider 回归。

**迁移 / 备份**：
- `6a7b8c9d0e1f` upgrade / downgrade / 重复执行幂等；旧表数据按 `created_by` 迁移、无归属丢弃、同用户多行取一条；downgrade 重建旧表（空）。
- `7b8c9d0e1f2a` upgrade / downgrade / 重复执行幂等；`datasource_user_llm_config` 数据全量搬入 `llm_user_config`；downgrade 重建空旧表（数据不恢复）。
- `HEAD_REVISION` = `7b8c9d0e1f2a`。
- 备份 v7 导出不含任何个人大模型配置，任务配置不再含个人 `base_url` / `model`；v1-v7 均可导入；v6 备份的 `llm_config` 键被忽略。
- 平台层（客户端重试 / JSON 解析 / 连接搬表 / `llm_run` 留痕）用例见 ADR 0020 P0 测试清单。

**前端（单测）**：`LlmConfigPanel.test.tsx`（读取 / 保存 / 测试 / 清除 / 默认系统提示词展示）、`SettingsModal.test.tsx`（「大模型」页签）、`DatasourcePage.test.tsx`（无连接入口、个人配置提示、保存 payload、预览幂等键、非 LLM 任务回归）、`llmPromptPresets.test.ts`（8 组、新闻 / 美食文案）。

**e2e（前端）**：既有 `datasource.spec.ts` 默认 provider 流程保持通过；LLM 流程只校验保存与表单，不触发真实模型调用。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 大模型连接（模型 / 迁移 / GET·PUT 端点 / 连接解析）+ 内置系统提示词 + prompt-only 校验 / 连通测试 + 备份格式 | 中（模型 + 迁移 + 备份格式） |
| **P1** | 自动建表、空表补字段、自动幂等键（`auto_table` + `write` + `runner` + 预览建议键） | 中（写路径改动，需既有落表回归） |
| **P2** | 前端极简表单 + 8 组推荐提示词 + 测试与文档 | 中（跨前后端契约） |
| **P3** | 连接迁移到个人级（个人表 / 个人接口 / 任务按用户解析 / 个人设置页签 / 备份 v7）+ 提示词可靠性（`max_tokens` / 截断提示 / 系统提示词 / 新闻美食预设） | 中（数据迁移不可逆 + 前后端入口切换） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案 | 个人级连接一次配置 + 任务只填用户提示词 + 空表自动落表 | 配置复杂度集中在「每个任务都要重复填连接和模型」；把不变的部分上提、把可推断的部分交给系统（I1） | 继续逐任务全量配置（C1 未解决）；只做提示词模板但字段不减（换皮不减压） | `src/cndb/plugins/llm/services/connection.py`、`src/cndb/plugins/llm/routers/config.py` |
| D2 | 连接归属层级 | **个人级**：`llm_user_config` 以 `user_id` 唯一；任务可在高级设置显式覆盖 url/model | 模型账号属于个人（Key 计费 / 配额 / 保密都归人）；跨工作区复用同一份配置，共享工作区下天然隔离（I8） | 工作区级唯一记录（同一用户跨工作区重复配置、共享工作区下归属与 Key 可见性说不清）；全局环境变量（个人无法配置）；任务级复用连接（仍需逐任务选） | `src/cndb/plugins/llm/models.py`（`LlmUserConfig`）、`src/cndb/plugins/llm/routers/config.py` |
| D3 | 系统提示词默认值 | 内置完整默认 + 个人覆盖 + 任务高级覆盖三层优先级；内置默认要求综述 / 推荐类尽力输出、无法核实标注「综合整理」 | 用户不写 system 也要保证 JSON 结构、命名与「不得编造」（I2）；推荐类任务不能因无法联网返回空（C8） | 要求用户每条任务填写（C1 未解决）；只保留一句 JSON 指令（缺字段与真实性约束）；继续鼓励「无法产出就返回空数组」（新闻 / 美食开箱即空） | `src/cndb/plugins/llm/services/prompts.py`、`src/cndb/plugins/datasource/providers/llm_prompt.py`、`src/cndb/plugins/llm/routers/config.py` |
| D4 | API Key 存储 | 个人连接内 Fernet 加密、只写不回显、不随备份导出；运行期会话 Key 优先 | 复用既有加密能力与保密口径（I5）；保留会话以兼容旧任务 | 明文入库；导出备份带 Key；只保留会话（每任务绑定偏重） | `src/cndb/plugins/llm/routers/config.py`、`src/cndb/plugins/llm/services/connection.py`、`src/cndb/plugins/workspaces/services/backup_io.py` |
| D5 | 目标表自动化 | 留空按任务名建表（同名复用）；已有空表自动补字段 | 「空数据表自动新增和更新」的直接落点；同名复用避免重复建表 | 强制先手建表（C3 未解决）；每次运行重建表（丢历史与幂等基础） | `src/cndb/plugins/datasource/services/auto_table.py`、`src/cndb/plugins/datasource/services/runner.py` |
| D6 | 幂等键来源 | 显式配置优先；缺省时从结果行自动识别（单列唯一优先，最多 3 列组合）；无唯一组合退化为追加并留痕 | 去掉 cron 强制手填（C3），同时不伪造键（I4） | cron 强制手填（原 ADR 0014 D6 口径，复杂且易错）；固定取首列（可能不唯一）；为 match_keys 建复合唯一索引（ADR 0006 D8 已否决） | `src/cndb/plugins/datasource/services/auto_table.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/runner.py` |
| D7 | 自动化触发范围 | 仅 `provider=llm_prompt` | 其它 provider 有确定的目标表与字段语义，隐式建表是意外副作用（I3） | 所有 provider 统一自动建表（改变既有行为，回归面不可控） | `src/cndb/plugins/datasource/services/runner.py` |
| D8 | 备份版本 | 升 v7，**不导出**个人大模型配置；任务 `request_spec` 也不再含个人地址 / 模型；导入接受 1-7（v6 的 `llm_config` 键忽略） | 个人 Key / 模型选择属于用户私有数据，导出给他人即越权；工作区备份只承载工作区数据（I5/I8） | 继续导出（个人配置随工作区泄露给协作者 / 其他环境）；保留 v6 并加个人键（版本号不再可信） | `src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/workspaces/routers/workspaces.py` |
| D9 | 旧任务 / 旧配置兼容 | 显式 url/model/api_key 优先于个人连接；旧工作区连接按 `created_by` 迁移、个人表由 `7b8c9d0e1f2a` 搬入 `llm_user_config`；v1-v6 备份可导入 | 不强制重写存量任务（I7）；迁移后用户无需重配 | 批量重写旧任务 `request_spec`（不可逆、风险高）；保留旧工作区表双写（两份配置并存） | `src/cndb/plugins/llm/services/connection.py`、`src/cndb/plugins/llm/routers/config.py`、`src/cndb/alembic/versions/7b8c9d0e1f2a_add_llm_plugin.py`、`src/cndb/alembic/versions/6a7b8c9d0e1f_add_user_llm_config.py` |
| D10 | 提示词模板求值严格度 | `llm_prompt` 专用宽松入口 `render_text_lenient`：仅替换已注册变量，未知 `{xxx}` / 裸花括号原样保留；其它 provider 仍用严格 `render_text` | 用户会直接在提示词里写 JSON 示例，要求先转义违背「只配提示词即可」（C1/C2）；宽松只作用于提示词，不影响 URL / body 的缺参保护 | 全链路放宽（其它 provider 的 URL / body 模板失去缺参保护）；要求用户手动转义（C1 未解决） | `providers/template.py`、`providers/llm_prompt.py` |
| D11 | 提示词可靠性 | 默认 `max_tokens` 1024 → 4096；截断错误识别并提示调大 / 精简；系统提示词支持综述 / 推荐类尽力输出与「综合整理」；新闻 / 美食预设同步 | 用户的失败是可复现的 token 截断与「无实时数据即返回空」，必须在默认配置层解决而不是让用户自查（C8/I9） | 继续 1024 并要求用户手动调（开箱失败）；把截断当普通 JSON 错误（无可执行指引）；新闻 / 美食预设保持实时抓取口径（模型无法满足） | `src/cndb/plugins/llm/services/prompts.py`、`src/cndb/plugins/llm/services/parsing.py`、`src/cndb/plugins/datasource/providers/llm_prompt.py`、`frontend/src/pages/datasource/llmPromptPresets.ts` |
| D12 | 字段命名语言 | 中文优先：默认系统提示词放开中文、要求逐字沿用指定字段名；预设 / 示例表 / 示例同步任务统一中文字段；英文 snake_case 仍兼容 | 用户与示例数据都是中文语境，中文字段可直接进视图 / 公式 / 导出，省掉「中文语义 → 英文键」的翻译和维护两套命名（C9） | 继续强制英文 snake_case（模型翻译不稳定、与示例工作区其余表不一致）；按任务可选命名语言（多一套口径，提示词模板与测试翻倍） | `src/cndb/plugins/llm/services/prompts.py`、`src/cndb/plugins/datasource/services/auto_table.py`、`frontend/src/pages/datasource/llmPromptPresets.ts`、`examples/datasets/工作区-数据源示例/` |

门禁：本表无「待定」；需求方已于 2026-10-22 确认简化方案与个人级迁移 / 提示词可靠性追加，Status 定稿 `Implemented`。

## Consequences

- **正向**：新建 `llm_prompt` 任务只需「任务名 + 一句提示词」，系统自动建表、补字段、识别幂等键并持续更新；模型账号跟人走，跨工作区复用同一份配置，共享工作区下互不读取他人 Key；系统提示词默认可用且支持综述 / 推荐类任务；推荐提示词开箱可用，长输出不再默认被截断。
- **负向**：个人配置迁移不可逆（downgrade 不恢复旧数据，`datasource_user_llm_config` → `llm_user_config` 的搬运同样只保结构不保回滚数据）；工作区接管 / 移交后，任务的模型调用仍归创建者的个人配置，需要交接 Key；备份不再携带模型配置，换环境后每人各自重配。
- **风险与缓解**：旧工作区配置无 `created_by` 时丢弃 → 迁移日志 / 文档说明，用户可重填；个人配置随账号删除级联清除 → 删除用户前确认任务归属；截断仍可能发生在超大输出 → 错误文案给出 `max_tokens` 调整建议；模型对「综合整理」的理解差异 → 预设 prompt 明确要求标注并与系统提示词一致；旧客户端仍调工作区 / accounts 端点 → 端点已删除（404），前端同轮切换到 `/api/v1/llm/config`。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 数据同步框架（Provider × SyncJob × Cursor × Normalizer） | `plugins/datasource/` | 自动化只在 `llm_prompt` 内实现，框架层不动 | ADR 0006 |
| 凭证管理 | `datasource_session` → `llm_user_config` | 会话 Key 保留并优先，个人连接作为默认来源 | ADR 0006 D6、本 ADR D2/D4 |
| 幂等落库 | `upsert_rows` 应用层先查后写 | 沿用应用层 upsert，不引入复合唯一索引；新增自动键推断 | ADR 0006 D8、本 ADR D6 |
| 备份格式 | 工作区备份 v5 → v7 | v6 曾导出工作区连接；v7 起不再导出大模型配置（个人数据），导入端向下兼容 1-7 | ADR 0006、本 ADR D8 |
| `llm_prompt` provider | `src/cndb/plugins/datasource/providers/llm_prompt.py` | 本 ADR 简化其配置门槛、新增默认系统提示词 / 空表自动化 / 提示词可靠性；provider 协议不变 | ADR 0014 |
| LLM 能力归属 | `src/cndb/plugins/llm/`（ADR 0020 P0 抽层） | 连接 / 调用 / 解析 / 留痕归平台插件；本 ADR 的配置简化与提示词可靠性结论不变，位置改为 `llm_user_config` / `/api/v1/llm/config`，`llm_prompt` 经 `RequestPlan.fetcher` 消费平台客户端 | ADR 0020 |
| cron 与幂等键 | `ScheduleMode.CRON` | **简化口径见 ADR 0019**：`llm_prompt` + cron 不再强制 `match_keys`，改为自动识别 | ADR 0014 D6 → 本 ADR D6 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/llm/models.py`、`src/cndb/plugins/llm/plugin.py`、`src/cndb/plugins/llm/services/connection.py`、`src/cndb/plugins/llm/routers/config.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/plugins/datasource/providers/llm_prompt.py`、`src/cndb/plugins/datasource/providers/template.py`、`src/cndb/plugins/datasource/schemas.py`、`src/cndb/plugins/workspaces/routers/workspaces.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/alembic/versions/6a7b8c9d0e1f_add_user_llm_config.py` | `tests/test_datasource_llm_config.py`、`tests/test_datasource_llm_provider.py`、`tests/test_datasource_api.py`、`tests/test_datasource_backup.py`、`tests/test_datasource_migration.py`、`tests/test_migration_missing_model_columns.py` | d0e2841e |
| P1 | 已落地 | `src/cndb/plugins/datasource/services/auto_table.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/cli/sync.py` | `tests/test_datasource_auto_table.py`、`tests/test_datasource_runner.py`、`tests/test_datasource_cli.py` | d0e2841e |
| P2 | 已落地 | `frontend/src/api/datasource.ts`、`frontend/src/api/llm.ts`、`frontend/src/pages/datasource/llmPromptPresets.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx`、`frontend/src/pages/settings/LlmConfigPanel.tsx`、`frontend/src/pages/settings/SettingsModal.tsx` | `frontend/src/pages/datasource/DatasourcePage.test.tsx`、`frontend/src/pages/datasource/llmPromptPresets.test.ts`、`frontend/src/pages/settings/LlmConfigPanel.test.tsx`、`frontend/src/pages/settings/SettingsModal.test.tsx` | d0e2841e |
| P3 | 已落地 | `src/cndb/plugins/llm/plugin.py`、`src/cndb/plugins/llm/models.py`、`src/cndb/plugins/llm/services/connection.py`、`src/cndb/plugins/llm/routers/config.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/providers/llm_prompt.py`、`src/cndb/alembic/versions/7b8c9d0e1f2a_add_llm_plugin.py`、`src/cndb/alembic/versions/6a7b8c9d0e1f_add_user_llm_config.py`、`src/cndb/plugins/workspaces/routers/workspaces.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`frontend/src/api/llm.ts`、`frontend/src/pages/settings/LlmConfigPanel.tsx`、`frontend/src/pages/settings/SettingsModal.tsx`、`frontend/src/pages/datasource/DatasourcePage.tsx`、`frontend/src/pages/datasource/llmPromptPresets.ts` | `tests/test_datasource_llm_config.py`、`tests/test_datasource_migration.py`、`tests/test_datasource_llm_provider.py`、`tests/test_datasource_api.py`、`tests/test_datasource_backup.py`、`frontend/src/pages/settings/LlmConfigPanel.test.tsx`、`frontend/src/pages/settings/SettingsModal.test.tsx`、`frontend/src/pages/datasource/llmPromptPresets.test.ts` | dba416e5 |
| P4 | 已落地 | `src/cndb/plugins/llm/services/prompts.py`、`src/cndb/plugins/datasource/services/auto_table.py`、`frontend/src/pages/datasource/llmPromptPresets.ts`、`examples/datasets/工作区-数据源示例/datasource.json`、`examples/datasets/工作区-数据源示例/views.json`、`examples/datasets/工作区-数据源示例/fields.json`、`examples/datasets/工作区-数据源示例/美食推荐做法.csv`、`examples/datasets/工作区-数据源示例/国际形势发展动态.csv` | `tests/test_datasource_llm_provider.py`、`tests/test_datasource_auto_table.py`、`tests/test_seed_datasource.py`、`frontend/src/pages/datasource/llmPromptPresets.test.ts` | a544d5a |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系；提交列由 Lead 在提交后回填 sha。
>
> ADR 0020 P0 已把连接 / 端点 / 前端 API 迁到 `plugins/llm/`（表 `llm_user_config`、端点 `/api/v1/llm/config`、`frontend/src/api/llm.ts`），本表落点已就地指向新位置；提交列沿用各期实现提交。

## 交接（会话结束更新）

- 当前阶段：P0-P4 已落地；ADR 0020 P0 已把连接 / 调用 / 解析 / 留痕抽到平台插件 `plugins/llm/`（表 `llm_user_config`、端点 `/api/v1/llm/config`），本 ADR 落点已就地改写
- C10（服务商预设）提交：`89cbc348`（CHANGELOG 条目随 `7a1bd2fa` 一并入库，该提交同时含数据表拖拽排序）
- 追加（2026-10-23，C10）：个人设置「大模型」加服务商预设 —— `llmProviders.ts` 6 家国内服务商（DeepSeek 默认 / 百炼 / 智谱 / Kimi / 火山方舟 / 硅基流动），选服务商自动填 `base_url` + 默认模型，模型字段改 AutoComplete（可选可填），「自定义」清空地址、手改地址按地址反查回落自定义；前端 `check-fast` + `test` + 前端全量 `vitest` 全绿
- 追加（2026-10-24，C10）：服务商预设移除国外选项（OpenRouter / OpenAI），只保留国内服务商 6 家；已保存的国外地址不受影响，仍按 `base_url` 反查未命中回落「自定义」
- 追加（2026-10-23，C9）：字段命名中文化 + 示例同步配置 —— 默认系统提示词放开中文并禁止翻译指定字段名；8 组预设改中文字段；`KEY_NAME_HINTS` 中英并列；示例工作区「美食推荐做法 / 国际形势发展动态」CSV 表头、`views.json`、`fields.json` 改中文字段，`datasource.json` 新增两条 `llm_prompt` 任务（中文 `match_keys` / `field_mapping`，`schedule.mode=manual`）
- 追加（2026-10-22）：推荐提示词由 5 组扩为 8 组（新增商业航天新闻动态 / 美食推荐做法 / 国际形势发展动态），提交 `c39a8f6d`；页面按钮按预设数量动态显示
- 追加（2026-10-22）：连接测试支持未保存 Key（现为 `POST /api/v1/llm/config/test`），提交 `f2bf92bc`
- 追加（2026-10-22）：大模型配置改为个人级（「个人设置 → 大模型」，表 `llm_user_config`；迁移 `7b8c9d0e1f2a` 把 `datasource_user_llm_config` 搬入后删旧表；备份升 v7 不再导出个人配置）+ 提示词可靠性修复（默认 max_tokens 4096、截断错误提示、新闻 / 美食预设重写）；真机验证新闻 rows=12、美食 rows=8 且 JSON 可解析（响应 model 显示 deepseek-flash）
- 追加（2026-10-22，ADR 0020 P0）：大模型连接 / 调用 / 解析 / 留痕抽到平台插件 `plugins/llm/`；HTTP 传输层上移到 `core/http.py`（`api_fetch.py` 保留 re-export shim）；`llm_prompt` 经 `RequestPlan.fetcher` 走平台客户端；保存任务不再把个人 `base_url` / `model` 写回 `request_spec`；端点迁到 `/api/v1/llm/config`，旧 `/api/v1/accounts/llm-config*` 删除
- 追加（2026-10-22）：推荐提示词弹窗改为手风琴折叠列表 —— 8 组默认收起，点击场景名展开适用场景 / 建议字段 / 建议幂等键，详情随展开挂载、收起即卸载；「使用」按钮留在折叠头右侧（阻止冒泡）；内容区限高 `min(60vh, 480px)` 内部滚动，避免对话框被详情撑高
- 已完成：P0 大模型连接 + 内置默认系统提示词 + prompt-only 校验 + 备份格式 + 提示词宽松模板（`render_text_lenient`）；P1 自动建表 / 空表补字段 / 自动幂等键 + 预览建议键 + CLI 输出；P2 前端极简表单 + 8 组推荐提示词；P3 个人级迁移 + 提示词可靠性；P4 中文字段口径 + 示例工作区两条 `llm_prompt` 同步配置
- 下一步：人工确认后保持 `Status: Implemented`；`docs/adr/README.md` 索引由本轮 Lead 同步；如后续要支持「自动幂等键人工纠错入口 / 多连接 / 个人配置随账号导出」另立 ADR
- 已知坑：自动幂等键只在结果行内可判定，无唯一组合时退化为追加（看 `run.detail.auto_match_keys`）；自动补字段只在空表启用；个人配置不随工作区备份导出，导入备份后每人需各自配置；任务运行按 `job.created_by` 解析个人连接，创建者离职 / 换 Key 后任务需改由他人重建或用会话 Key 兜底；旧工作区配置 `created_by` 为空时迁移会丢弃；`6a7b8c9d0e1f` / `7b8c9d0e1f2a` 的 downgrade 都不恢复数据；推荐类任务长输出仍可能超过 `max_tokens`，错误文案会提示调大或精简；无联网模型无法取实时新闻 / 行情，只能基于已掌握信息并标注「综合整理」；宽松模板只作用于 `llm_prompt` 的 system / user 提示词，URL 与 headers 仍严格；CLI 预览按任务创建者解析个人连接；`make adr-check` 会校验已落地期的代码 / 测试路径，接口或迁移改名时必须同步本表；中文字段名不含空格与标点（导出 CSV 与公式引用才无歧义），已有英文表不会被自动改名，需要中文时就新建任务 / 表；示例两条 LLM 任务为 `manual`，缺少个人 Key 时不会自动跑
- 最近一次全绿：`make check-docs`（2026-10-23，P4 中文字段口径与示例同步配置文档同步）

## 附录：8 组推荐用户提示词说明（2026-10-22 追加 3 组；2026-10-23 字段改中文）

页面「推荐提示词」与本节保持同一份口径（预设定义见 `frontend/src/pages/datasource/llmPromptPresets.ts`；prompt 中的 `{{` / `}}` 是后端模板语法里的字面花括号，运行时还原为 `{` / `}`）。「每日新闻摘要」「美食推荐做法」两组已按提示词可靠性口径调整（基于已掌握信息 / 标注综合整理 / 控制输出规模）；C9 起全部字段名改中文，英文 snake_case 仍兼容（用户自行改回英文也能落表）。

| 预设 id | 场景 | 建议目标表字段 | 建议幂等键 |
|---|---|---|---|
| `daily_news` | 每日新闻摘要 | 日期、板块、标题、摘要、来源、链接、重要度 | 日期 + 板块 + 标题 |
| `city_weather` | 城市天气预报 | 日期、城市、天气、最高气温、最低气温、降水概率、风力风向、空气质量 | 日期 + 城市 |
| `market_snapshot` | 股票 / 基金行情快照 | 交易日、证券代码、证券名称、收盘价、涨跌幅、成交量、成交额、换手率 | 交易日 + 证券代码 |
| `ecommerce_price` | 电商竞品价格监控 | 日期、平台、商品编号、商品标题、售价、划线价、优惠信息、销量 | 日期 + 平台 + 商品编号 |
| `policy_tracker` | 行业政策公告跟踪 | 日期、发文机构、标题、摘要、政策类型、生效日期、链接 | 日期 + 发文机构 + 标题 |
| `commercial_aerospace` | 商业航天新闻动态 | 日期、公司、事件类型、标题、摘要、来源、链接、重要度 | 日期 + 公司 + 标题 |
| `food_recipes` | 美食推荐做法 | 菜名、菜系、难度、烹饪时长、主要食材、分步做法、小贴士 | 菜名 + 菜系 |
| `global_affairs` | 国际形势发展动态 | 日期、地区、主题、标题、摘要、来源、链接、趋势判断 | 日期 + 地区 + 标题 |

### 1. 每日新闻摘要（`daily_news`）

- **适用场景**：每天汇总国内要闻 / 财经 / 科技三个板块的重点新闻，按 `日期 + 板块 + 标题` 去重，适合资讯看板；基于模型已掌握的近期公开信息整理，不因无法联网返回空数组，无法核实的来源标注「综合整理」。
- **建议目标表字段**：日期（`YYYY-MM-DD`）、板块、标题、摘要（≤120 字）、来源（来源媒体，无法确认写「综合整理」）、链接（原文链接，无法确认用空串）、重要度（1-5 整数）。
- **建议幂等键**：日期 + 板块 + 标题。
- **prompt 示例**（节选，实际含完整字段说明）：

```text
请基于你已掌握的近期公开信息，汇总 {today} 前后的每日新闻摘要，覆盖国内要闻、财经、科技三个板块。
每个板块挑选最重要的 3-5 条，按重要度从高到低排列；每条给出一句话摘要（不超过 120 字）。
字段要求（字段名用中文）：日期（YYYY-MM-DD）、板块、标题、摘要、来源（来源媒体）、链接（原文链接）、重要度（1-5 的整数）。
来源无法确认具体媒体时写「综合整理」；链接无法确认时用空字符串，不要编造链接；不要因为无法联网就返回空数组。
同一天同一板块下的标题应稳定，日期 + 板块 + 标题 组合用于去重。
只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。不要输出 Markdown 代码围栏或任何解释文字。
```

### 2. 城市天气预报（`city_weather`）

- **适用场景**：按城市 + 日期生成当天及未来两天的天气预报，适合天气日报表；`日期 + 城市` 即天然幂等键。
- **建议目标表字段**：日期、城市、天气、最高气温（℃ 整数）、最低气温、降水概率（0-100 整数）、风力风向、空气质量（等级）。
- **建议幂等键**：日期 + 城市。
- **prompt 示例**（节选）：

```text
请生成城市天气预报，基准日期：{today}。默认覆盖北京、上海、广州、深圳。
每个城市给出当天及未来 2 天（共 3 天）的预报：天气现象、最高/最低气温、降水概率、风向风力、空气质量等级。
字段要求（字段名用中文）：日期、城市、天气、最高气温、最低气温、降水概率、风力风向、空气质量。
同一城市同一日期只能有一条记录，日期 + 城市 为稳定键。
只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。
```

### 3. 股票 / 基金行情快照（`market_snapshot`）

- **适用场景**：抓取指定标的的收盘行情快照（价格 / 涨跌幅 / 成交量），`交易日 + 证券代码` 去重，适合行情日表与趋势分析。
- **建议目标表字段**：交易日、证券代码、证券名称、收盘价、涨跌幅（百分比数值，1.23 表示 +1.23%）、成交量（股）、成交额（元）、换手率（换手率百分比）。
- **建议幂等键**：交易日 + 证券代码。
- **prompt 示例**（节选）：

```text
请整理 {today} 的股票 / 基金行情收盘快照。默认覆盖沪深 300 成分股中市值前 10 的标的。
每个标的给出：证券代码、证券名称、收盘价、涨跌幅、成交量、成交额、换手率。
字段要求（字段名用中文）：交易日、证券代码、证券名称、收盘价、涨跌幅、成交量、成交额、换手率。
同一标的同一交易日只能有一条记录，交易日 + 证券代码 为稳定键。
只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。
```

### 4. 电商竞品价格监控（`ecommerce_price`）

- **适用场景**：按平台 + 商品监控竞品售价与促销信息，`日期 + 平台 + 商品编号` 去重，适合价格波动看板与调价提醒。
- **建议目标表字段**：日期、平台（如 京东 / 淘宝）、商品编号（平台商品 ID）、商品标题、售价（元）、划线价（元）、优惠信息（无则空串）、销量（整数）。
- **建议幂等键**：日期 + 平台 + 商品编号。
- **prompt 示例**（节选）：

```text
请监控 {today} 的电商竞品价格。默认覆盖 3 个主要竞品，可替换为指定商品编号 / 链接列表。
每个竞品给出：平台、平台商品编号、商品标题、当前售价、划线价、优惠信息、销量。
字段要求（字段名用中文）：日期、平台、商品编号、商品标题、售价、划线价、优惠信息、销量。
同一平台同一商品同一日期只能有一条记录，日期 + 平台 + 商品编号 为稳定键。
只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。
```

### 5. 行业政策公告跟踪（`policy_tracker`）

- **适用场景**：跟踪部委 / 地方 / 行业协会发布的政策公告，`日期 + 发文机构 + 标题` 去重，适合政策台账与合规提醒。
- **建议目标表字段**：日期、发文机构、标题、摘要（≤200 字）、政策类型（通知 / 征求意见 / 办法 / 规划等）、生效日期（暂无空串）、链接（原文链接）。
- **建议幂等键**：日期 + 发文机构 + 标题。
- **prompt 示例**（节选）：

```text
请跟踪 {today} 发布的行业政策与监管公告，覆盖国家部委、地方主管部门和行业协会官网。
每条记录给出：发布日期、发文机构、政策标题、政策摘要、政策类型、生效日期、原文链接。
字段要求（字段名用中文）：日期、发文机构、标题、摘要、政策类型、生效日期、链接。
同一机构同一日期同一标题只能有一条记录，日期 + 发文机构 + 标题 为稳定键。
只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。
```

### 6. 商业航天新闻动态（`commercial_aerospace`）

- **适用场景**：跟踪商业航天公司的发射任务、融资并购、政策监管、订单合作与技术进展，适合行业情报看板；`日期 + 公司 + 标题` 去重。
- **建议目标表字段**：日期（`YYYY-MM-DD`）、公司（公司或机构）、事件类型（发射 / 融资 / 政策 / 订单 / 技术）、标题、摘要（≤150 字）、来源、链接、重要度（重要度 1-5 整数）。
- **建议幂等键**：日期 + 公司 + 标题。
- **prompt 示例**（节选）：

```text
请汇总 {today} 商业航天领域的新闻动态，覆盖国内外主要商业航天公司以及监管机构与发射场。
重点收集：发射任务与结果、融资与并购、政策与监管、订单与合作协议、关键技术进展。
字段要求（字段名用中文）：日期、公司、事件类型、标题、摘要、来源、链接、重要度。
同一天同一公司同一标题只能有一条记录，日期 + 公司 + 标题 为稳定键。
只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。
```

### 7. 美食推荐做法（`food_recipes`）

- **适用场景**：按菜名 + 菜系整理家庭可操作的美食做法，适合菜谱库、每日菜单与美食内容推荐；`菜名 + 菜系` 即天然幂等键。不依赖实时数据，模型基于已掌握知识输出；单次输出控制在 8 道菜以内，避免长 JSON 被截断。
- **建议目标表字段**：菜名、菜系、难度（简单 / 中等 / 困难）、烹饪时长（分钟，整数）、主要食材（文本）、分步做法（文本）、小贴士（无则空串）。
- **建议幂等键**：菜名 + 菜系。
- **prompt 示例**（节选）：

```text
请推荐 {today} 适合家庭制作的美食做法，覆盖家常菜、汤羹、主食、甜点四类，每类 2 道，共 8 道，优先当季食材。
每道菜给出：菜名、菜系、难度、烹饪时长、主要食材、分步做法、关键小贴士。
控制输出规模：每道菜的主要食材不超过 6 种；分步做法用编号与分号分隔，每步不超过 60 字；小贴士一句话即可，避免输出过长被截断。
字段要求（字段名用中文）：菜名、菜系（如 川菜/粤菜/西餐）、难度（简单/中等/困难）、烹饪时长（分钟，整数）、主要食材（用顿号分隔的文本）、分步做法（用编号与分号分隔的文本）、小贴士（无则空字符串）。
同一菜名同一菜系只能有一条记录，菜名 + 菜系 为稳定键；不要返回空数组。
只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。不要输出 Markdown 代码围栏或解释文字。
```

### 8. 国际形势发展动态（`global_affairs`）

- **适用场景**：梳理大国关系、地区冲突、全球经济与多边机制等国际动态，适合形势研判与每日晨报；`日期 + 地区 + 标题` 去重。
- **建议目标表字段**：日期（`YYYY-MM-DD`）、地区（地区或国家）、主题（主题分类）、标题、摘要（≤150 字）、来源、链接、趋势判断（缓和 / 升温 / 僵持 / 不确定）。
- **建议幂等键**：日期 + 地区 + 标题。
- **prompt 示例**（节选）：

```text
请梳理 {today} 的国际形势发展动态，覆盖大国关系、地区冲突、全球经济与贸易、多边机制与外交活动等主题。
每条记录给出：日期、地区/国家、主题、标题、摘要、来源、原文链接、趋势判断。
字段要求（字段名用中文）：日期、地区、主题、标题、摘要、来源、链接、趋势判断。
同一天同一地区同一标题只能有一条记录，日期 + 地区 + 标题 为稳定键。
只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。
```
