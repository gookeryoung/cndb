# ADR 0019: 大模型提示词配置简化（工作区连接 + 内置系统提示词 + 空表自动落表）

Status: Implemented
Date: 2026-10-22
Related: `src/cndb/plugins/datasource/models.py`、`src/cndb/plugins/datasource/schemas.py`、`src/cndb/plugins/datasource/services/connection.py`、`src/cndb/plugins/datasource/services/auto_table.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/providers/llm_prompt.py`、`src/cndb/plugins/datasource/providers/template.py`、`src/cndb/cli/sync.py`、`src/cndb/plugins/datasource/routers/llm_config.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/plugins/datasource/routers/__init__.py`、`src/cndb/alembic/versions/5e6f7a8b9c01_add_datasource_llm_config.py`、`src/cndb/plugins/workspaces/routers/workspaces.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/workspaces/schemas/models.py`、`frontend/src/api/datasource.ts`、`frontend/src/pages/datasource/llmPromptPresets.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx`；上游见 ADR 0006 / ADR 0014
需求卡片: `docs/requirements/0019-llm-prompt-config-simplify.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」段落；ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用，不在仓库保留 `Superseded` / `Deprecated` 文档。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C6），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 大模型提示词抓取功能配置项过于复杂，需要进行简化 | 任务抽屉 `llm_prompt` 分支主表单只留「任务名称 / 用户提示词 / 目标表（可留空）」；API 地址、模型、系统提示词、幂等键、调度、温度等收进高级设置或工作区级连接；后端 `_validate_job_config` 对 `llm_prompt` 只强制用户提示词 |
| C2 | 尽可能只配置提示词项即可确保抓取到合适的数据 | 新增工作区级「大模型连接」（`base_url` / `model` / `api_key` / 可选 `system_prompt`），`connection.resolve_request_spec_defaults` 在保存与运行时补齐 `url_template` / `llm.model`；未配置 system 时使用内置默认系统提示词；提示词模板用宽松求值（`render_text_lenient`）：JSON 裸花括号与未知 `{xxx}` 原样保留，仅替换已注册变量，`{{`/`}}` 仍转义为字面花括号 |
| C3 | 支持空数据表自动新增和更新数据的能力 | `auto_table.ensure_job_table`（留空目标表 → 按任务名建表）、`is_table_empty` + `upsert_rows(auto_add_fields=True)`（空表补字段）、`infer_match_keys` + `upsert_rows(auto_match_keys=True)`（自动幂等键）；重复运行只更新不重复插入 |
| C4 | 系统提示词请默认配置好 | `providers/llm_prompt.py` 新增完整 `DEFAULT_SYSTEM_PROMPT`；请求构造在未配置 system 时使用它；`GET llm-config` 返回 `default_system_prompt` 供前端查看 / 覆盖 |
| C5 | 提供5组典型可用的推荐用户提示词参考示例 | `frontend/src/pages/datasource/llmPromptPresets.ts` 内置 5 组预设（每日新闻摘要 / 城市天气 / 股票行情快照 / 电商竞品价格 / 行业政策公告），任务抽屉「推荐提示词」一键套用 |
| C6 | 并给出说明 | 每组预设带 `description / target_fields / match_keys / prompt`，套用时在页面展示「适用场景 + 建议目标表字段 + 建议幂等键」；同一份说明写入本 ADR 附录，页面与文档同源 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（沿用需求卡片「现状影响面」编号，以代码为准）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `llm_prompt` 任务表单逐任务填写 API 地址 / 模型 / 系统提示词 / 用户提示词 / 幂等键 | `frontend/src/pages/datasource/DatasourcePage.tsx:465-520`、`:556` | 想「只写一句提示词」必须理解并填完连接与模型参数，是配置复杂的直接来源 | 确认（C1/C2） |
| 2 | Provider 校验强制 `url_template` / `llm.model` / `prompt.user_template` 非空 | `src/cndb/plugins/datasource/providers/llm_prompt.py:75-109`（`LlmConfig.from_payload`） | 没有连接默认值时无法只填提示词 | 确认（C2） |
| 3 | `llm_prompt` + cron 强制 `match_keys` | `src/cndb/plugins/datasource/providers/llm_prompt.py`（`validate_llm_request_spec`）、`routers/sync_jobs.py:94-100` | 与「自动识别幂等键」冲突，用户必须先懂目标表字段 | 确认（C3） |
| 4 | 任务保存 / 更新只校验目标表字段存在，无「目标表留空」语义 | `src/cndb/plugins/datasource/routers/sync_jobs.py:66-118` | 目标表必须预先存在，空表 / 新场景不可用 | 确认（C1/C3） |
| 5 | 运行落表要求 `table_id` 非空；`match_keys` 为空退化为纯追加 | `src/cndb/plugins/datasource/services/runner.py:297-317`、`services/write.py:39-67` | 空表不能自动建表 / 补字段，重复运行会追加重复行 | 确认（C3） |
| 6 | API Key 只走 `datasource_session.secrets.api_key` | `services/runner.py:205-213`、`core/crypto.py:79-84` | 每任务绑定会话对「一次性提示词任务」仍然偏重；但加密与不回显口径要保留 | 确认（C2/C4） |
| 7 | 备份版本 v5，不含 LLM 连接配置 | `src/cndb/plugins/workspaces/services/backup_io.py:80` | 连接配置不随备份迁移；导入端需接受 v6 且不导出 Key | 新增（C2） |
| 8 | 前端 `datasourceApi` 无工作区级连接类型与端点封装 | `frontend/src/api/datasource.ts` | 连接配置无处可读写 | 新增（C1/C2） |
| 9 | 内置系统提示词仅一句 `JSON_INSTRUCTION` | `providers/llm_prompt.py:45` | 用户不写 system 时缺少结构化输出、字段命名、禁止编造等约束 | 确认（C4） |
| 10 | 测试覆盖 provider / API / 备份 / 迁移 / 页面 | `tests/test_datasource_llm_provider.py`、`tests/test_datasource_api.py`、`tests/test_datasource_backup.py`、`tests/test_datasource_migration.py`、`frontend/src/pages/datasource/DatasourcePage.test.tsx` | 新连接、自动落表、极简表单需同轮补测试 | 确认（C1-C6） |
| 11 | 模板求值严格模式把未注册占位符与裸 `}` 当错误 | `src/cndb/plugins/datasource/providers/template.py`（`render_text`） | 用户在提示词里直接写 JSON 示例（`{"rows": [...]}`）会被判「模板变量缺失 / 未转义 }」而保存失败 | 新增（C1/C2） |

**核心缺陷（需求要补的）**：现有模型把「连接参数 + 模型参数 + 幂等键 + 目标表结构」全部压到每个任务上，任务必须先有目标表并显式配置 `match_keys`，导致「只想写一句提示词、交给系统自己建表并幂等更新」这条路走不通。

设计目标（不变量）：

- **I1 最少必填**：`llm_prompt` 任务只要求「任务名称 + 用户提示词」；其余配置由工作区连接、内置默认或自动推断补齐。
- **I2 默认系统提示词恒有效**：任何 `llm_prompt` 请求都必须带系统提示词（任务覆盖 > 连接覆盖 > 内置默认），不允许空 system 直接调模型。
- **I3 自动化仅限 `llm_prompt`**：其它 provider 的校验、落表、调度语义完全不变；不在通用框架层引入隐式建表。
- **I4 自动幂等键可回退**：推断出的键必须来自结果行且行内唯一；无唯一组合时返回空并退化为追加，同时在 `run.detail` 留痕，不伪造幂等键。
- **I5 密钥不落地明文**：连接 `api_key` 只存 Fernet 密文，读接口不回显，备份导出不含 Key。
- **I6 失败不写脏数据**：模型输出不可解析或没有行时，不建表、不补字段、不落库，运行记 `failed`。
- **I7 既有任务向后兼容**：旧 `llm_prompt` 任务（会话 + 显式 url/model）与 v1-v5 备份继续可用；显式配置优先于连接默认值。

## Decision

### 1. 数据模型

新增工作区级连接表 `datasource_llm_config`（模型 `DatasourceLlmConfig`）：

| 列 | 类型 | 约束 / 说明 |
|---|---|---|
| `workspace_id` | int | 唯一键，一个工作区至多一条连接；随工作区级联删除 |
| `base_url` | varchar | OpenAI 兼容端点，保存时校验必须是 http(s) |
| `model` | varchar | 非空，默认 `deepseek-chat` |
| `api_key` | text | Fernet 密文（`enc:v1:` 前缀），空表示未配置；只写不回显 |
| `system_prompt` | text | 可选，留空表示使用内置默认系统提示词 |
| `created_by` / 时间戳 | — | 沿用审计时间戳 mixin |

- `datasource_sync_job` 不加列：目标表仍用 `table_id`（可空），显式幂等键仍用 `match_keys`（可空），自动推断结果回填 `match_keys` 持久化，便于复用与排查。
- `request_spec` 结构不变：连接信息不再要求写进任务，任务可只保留 `{"prompt": {"user_template": "..."}}`；显式 `url_template` / `llm.model` 仍允许（高级覆盖）。
- 工作区备份升 **v6**：导出 `llm_config`（`base_url` / `model` / `system_prompt`，**不含 `api_key`**），导入端接受版本 1-6 并按缺省还原。

### 2. 判定入口（唯一实现）

**连接解析** `services/connection.py`：

```python
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

@dataclass(frozen=True)
class LlmConnection:
    base_url: str
    model: str
    api_key: str = ""        # 解密后的明文，仅运行期使用
    system_prompt: str = ""
    has_api_key: bool = False

def load_llm_connection(db: Session, workspace_id: int) -> LlmConnection: ...
def resolve_request_spec_defaults(spec: dict, conn: LlmConnection) -> dict: ...
```

- `load_llm_connection`：查询工作区连接，缺失时返回默认值（`DEFAULT_BASE_URL` / `DEFAULT_MODEL` / 空 Key）；解密失败按「未配置 Key」处理。
- `resolve_request_spec_defaults`：只在 `url_template` / `llm.model` 缺省时补默认值，**不写 `api_key`**（Key 由运行期注入），显式值优先。
- Key 解析优先级：任务绑定会话的 `secrets.api_key` > 工作区连接的 `api_key`；两处都没有时运行与连通测试给出「请先配置大模型连接」的明确错误。

**空表自动化** `services/auto_table.py`：

```python
def ensure_job_table(db: Session, job: DatasourceSyncJob) -> DataTable: ...
def is_table_empty(db: Session, table: DataTable) -> bool: ...
def candidate_names(rows: Sequence[Mapping[str, Any]], field_names: Sequence[str]) -> list[str]: ...
def infer_match_keys(rows: Sequence[Mapping[str, Any]], candidate_names: Sequence[str]) -> list[str]: ...
```

- `ensure_job_table`：`job.table_id` 为空时按 `job.name` 建表（同名未删除表复用；否则建 `DataTable` + `ensure_db_name` + `ddl_create` + `ensure_default_view`），回填 `job.table_id` 并提交，失效表列表缓存；建表失败回滚并清理半初始化元数据。
- `is_table_empty`：无未删除字段，或表内没有任何未删除数据行（回收站行不计）→ 视为空表；物理表缺失也按空表处理。
- `candidate_names`：候选列 = 结果行键 ∩ 目标表字段名（目标表无字段时直接用行键），保持行内首次出现顺序。
- `infer_match_keys`：只考虑有非空值的候选列；优先单列唯一（多列唯一时按名称含 `date/day/id/code/symbol/city/name/title` 等片段加权）；无单列唯一时枚举 2 列、再 3 列组合（候选封顶 15 列避免组合爆炸），组合需在全部行上唯一且非空；最多返回 3 列，无唯一组合返回 `[]`。
- `DEFAULT_SYSTEM_PROMPT`（`providers/llm_prompt.py`）：角色、只输出 JSON / `{"rows": [...]}`、字段英文 snake_case、日期与数值格式、缺失用 null、每行带稳定键、禁止编造；未配置时自动使用并追加既有 `JSON_INSTRUCTION`。
- **提示词模板求值**：`llm_prompt` 的 system / user 模板统一走 `providers/template.py` 新增的 `render_text_lenient` —— `{name}` 仅在命中内置 / 任务变量（`today` / `entrant` / `start` / `end` 等）时替换；未知 `{xxx}`、JSON 裸花括号、孤立 `}`、未闭合 `{` 一律原样保留；`{{` / `}}` 仍转义为字面花括号。保存校验（`validate_llm_request_spec`）同样走宽松求值，提示词含 JSON 裸花括号可直接保存。**`llm_prompt` 的 URL / headers 模板仍用严格 `render_text`**（缺参继续报错）；其它 provider 的全部模板求值保持严格，不受影响。

**写路径** `services/write.py` / `services/runner.py`：

- `upsert_rows` 新增 `auto_add_fields: bool = False`、`auto_match_keys: bool = False`；空表时以 `unknown_cols_strategy="add_text_field"` 执行自动补字段；`match_keys` 为空且 `auto_match_keys=True` 时先 analyze 取数、用 `infer_match_keys` 推断键后重新 analyze + execute。
- `WriteOutcome` 增加 `auto_fields: list[str]`、`match_keys: list[str]`（实际使用 / 推断的键），写入 `run.detail` 留痕。
- `runner.execute_job` 仅在 `provider=llm_prompt` 且 `rows` 非空时：`table_id` 为空 → `ensure_job_table`；`_persist_rows` 传 `auto_add_fields=is_table_empty(...)`、`auto_match_keys=not job.match_keys`；推断出键后回填 `job.match_keys` 持久化；`run.detail` 增加 `auto_fields` / `auto_match_keys`。
- 判定顺序：Key 解析 →（可选）自动建表 → 提示词求值 / 模型请求 → JSON 解析 → 字段与幂等键推断 → upsert → 留痕。
- **CLI** `src/cndb/cli/sync.py`：`sync preview` 与 `sync run --dry-run` 也传 `db`，同样应用工作区连接默认值 / Key，并在 JSON 输出里带 `suggested_match_keys`（终端预览可直接看到自动识别建议）。

### 3. API 变更清单（`/api/v1/workspaces/{wid}/datasource`）

| 端点 | 变更 |
|---|---|
| `GET /llm-config` | 新增：返回 `configured / base_url / model / has_api_key / system_prompt / default_system_prompt`；**不回显 api_key**；VIEWER 可读 |
| `PUT /llm-config` | 新增：保存连接（EDITOR）；`base_url` 必须 http(s)、`model` 非空；`api_key` 非空才更新、`clear_api_key=true` 清除；密钥 Fernet 加密 |
| `POST /sync-jobs`、`PUT /sync-jobs/{id}` | `llm_prompt` 只强制 `prompt.user_template`；缺省 `url_template` / `llm.model` 由连接补齐；cron 不再强制 `match_keys`；目标表可留空；无可用 Key（会话 + 连接都没有）时 400 并提示去配置大模型连接 |
| `POST /test-connection` | `session_id` 可省略：回退工作区连接的 Key 与默认 url/model；未配置连接时返回明确提示 |
| `POST /sync-jobs/{id}/preview` | 响应新增 `suggested_match_keys`（预览阶段建议的幂等键），供前端展示 |

### 4. 边界与例外

1. 自动建表只在模型返回非空行后触发；同名未删除表直接复用，不重复建表；任务失败不留下空表。
2. 自动补字段只在目标表为空（无字段或无数据行）时启用；已有数据表不自动加字段，未知列按既有策略处理。
3. 自动幂等键基于本轮结果行推断：显式 `match_keys` 优先；无唯一组合时退化为追加，`run.detail.auto_match_keys=[]` 留痕，不静默覆盖。
4. 工作区连接未配置或没有可用 API Key（会话与连接都没有）时：保存 / 更新任务直接 400「请先在「大模型连接」配置 API Key」，前端在保存 / 预览前先弹连接配置引导；避免把配置缺失误判为 401 / 网络故障。
5. 连接配置是工作区级唯一记录；任务的高级设置可显式覆盖 `url_template` / `llm.model` / `system_prompt`（兼容旧任务与特殊模型）。
6. 仅 `llm_prompt` 触发自动建表 / 补字段 / 自动幂等键；`http_json`、行情、RSS 等 provider 行为不变。
7. 备份不导出 API Key；导入 v6 备份后连接配置恢复但 Key 留空，需重新填写。导入端继续接受 v1-v5（无连接配置按默认值还原）。
8. 模型输出不可解析 / 为空时运行记 `failed`，不建表、不写行。
9. `system_prompt` 三层优先级：任务显式配置 > 工作区连接 > 内置默认；页面可查看内置默认全文。
10. 提示词模板宽松求值仅限 `llm_prompt` 的 system / user 提示词：用户可直接在提示词里写 `{"rows": [...]}` 这类 JSON 示例，不需要手动转义；`{{` / `}}` 仍等价于字面花括号（前端推荐提示词已按转义写法提供，两种都能用）。`llm_prompt` 的 URL / headers 模板仍严格；其它 provider 的 URL / headers / body 模板也保持严格模式，缺参仍报错。

### 5. 迁移

- 单条 alembic 迁移 `5e6f7a8b9c01_add_datasource_llm_config.py` 新建 `datasource_llm_config`（`workspace_id` 唯一、外键级联删除）：upgrade 幂等建表 / 索引，downgrade 幂等删表，目标表缺失时跳过；存量零迁移。
- 备份格式 v5 → v6：导出（`workspaces/routers/workspaces.py`）新增 `llm_config` 键（不含 Key）；导入端版本白名单扩到 `"1"`-`"6"`，旧备份按空连接还原，已有连接保留现有配置。
- 迁移 head 同步：`tests/test_migration_missing_model_columns.py` 的 `HEAD_REVISION` 已更新为 `5e6f7a8b9c01`，与 alembic head 一致。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 类型 / 封装 | `frontend/src/api/datasource.ts` | 新增 `LlmConfig` 类型、`getLlmConfig` / `updateLlmConfig`；`TestConnection` 的 `session_id` 可省略；`PreviewResult` 增 `suggested_match_keys` |
| 推荐提示词 | `frontend/src/pages/datasource/llmPromptPresets.ts` | 5 组预设（名称 / 说明 / 建议目标表字段 / 建议幂等键 / prompt 示例），独立单测校验 |
| 连接配置弹窗 | `frontend/src/pages/datasource/DatasourcePage.tsx` | 页头「大模型连接」按钮 + 已配置 / 未配置 Tag；弹窗配置 base_url / model / api_key（只写不回显）/ 可选 system_prompt（留空用内置默认并展示默认全文），支持「测试连接」 |
| 任务抽屉 | `frontend/src/pages/datasource/DatasourcePage.tsx` | `llm_prompt` 主表单只留任务名称 / 用户提示词 / 目标表（留空自动建表）；系统提示词、幂等键、调度、时间区间、凭证会话、temperature / max_tokens / json_mode 收进高级设置；「推荐提示词」一键套用并展示说明；预览展示自动识别的幂等键 |
| 页面测试 | `frontend/src/pages/datasource/DatasourcePage.test.tsx`、`frontend/src/pages/datasource/llmPromptPresets.test.ts` | 极简表单、预设套用、保存 payload、连接弹窗保存 / 测试、预览幂等键、非 LLM 任务回归 |

### 7. 测试清单

**判定层（单测）**：
- 连接默认值 / 显式值优先 / Key 解密失败按未配置；缺省 url/model 的 `request_spec` 可解析。
- `infer_match_keys`：单列唯一、组合唯一、无唯一返回空、空行 / 空候选、不超过 3 列、名称启发式排序。
- `ensure_job_table`：留空建表、同名复用、回填 `table_id`；`is_table_empty`：无字段 / 无行 / 有行。
- `upsert_rows`：空表自动补字段、自动幂等键首轮 inserted / 次轮 updated、无键追加；显式 `match_keys` 优先。
- 未配置 system 时请求体使用内置默认系统提示词。
- 宽松模板：提示词含 JSON 裸花括号可原样保存 / 运行；`{"date": "{today}"}` 的内层变量仍被替换；未注册 `{xxx}`、孤立 `}` 原样保留；`{{` / `}}` 转义为字面花括号；严格 `render_text` 对未知占位符仍报错（非 llm_prompt 回归）。

**接口层**：
- `GET / PUT llm-config`：CRUD、viewer 读 / editor 写、密钥不回显、`clear_api_key`、非法 base_url 400。
- `sync-jobs`：只填用户提示词可保存；缺 Key 400；cron 不配 `match_keys` 可保存；显式 match_keys 仍校验目标表字段。
- `test-connection`：未传 session 回退工作区连接；未配置连接返回明确提示。
- `preview`：响应含 `suggested_match_keys`。
- CLI `sync preview` / `sync run --dry-run`：传入 `db` 后使用工作区连接默认值，JSON 输出含 `suggested_match_keys`（`tests/test_datasource_cli.py` 回归）。
- 既有 `llm_prompt` 任务与其它 provider 回归。

**迁移 / 备份**：新迁移 upgrade / downgrade / 重复执行幂等；`tests/test_migration_missing_model_columns.py` 的 `HEAD_REVISION` 同步到 `5e6f7a8b9c01`；备份 v6 往返（连接配置保留、Key 不导出）；v1-v5 旧备份可导入。

**前端（单测）**：`tests` 对应 `frontend/src/pages/datasource/DatasourcePage.test.tsx`、`llmPromptPresets.test.ts` 覆盖 C1/C5/C6 与连接弹窗。

**e2e（前端）**：既有 `datasource.spec.ts` 默认 provider 流程保持通过；LLM 流程只校验保存与表单，不触发真实模型调用。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 工作区级大模型连接（模型 / 迁移 / GET·PUT 端点 / 连接解析）+ 内置系统提示词 + prompt-only 校验 / 连通测试回退 / 备份 v6 | 中（模型 + 迁移 + 备份格式） |
| **P1** | 自动建表、空表补字段、自动幂等键（`auto_table` + `write` + `runner` + 预览建议键） | 中（写路径改动，需既有落表回归） |
| **P2** | 前端极简表单 + 5 组推荐提示词 + 测试与文档 | 中（跨前后端契约） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案 | 工作区级连接一次配置 + 任务只填用户提示词 + 空表自动落表 | 配置复杂度集中在「每个任务都要重复填连接和模型」；把不变的部分上提、把可推断的部分交给系统（I1） | 继续逐任务全量配置（C1 未解决）；只做提示词模板但字段不减（换皮不减压） | `services/connection.py`、`routers/llm_config.py` |
| D2 | 连接归属层级 | 工作区级唯一记录，任务可在高级设置显式覆盖 url/model | 同一工作区的模型端点通常一致；工作区隔离符合多租户与权限模型 | 全局环境变量（多工作区不可分别配置）；任务级复用连接（仍需逐任务选） | `models.DatasourceLlmConfig`、`routers/llm_config.py` |
| D3 | 系统提示词默认值 | 内置完整默认 + 连接覆盖 + 任务高级覆盖三层优先级 | 用户不写 system 也要保证 JSON 结构、命名与「不得编造」（I2） | 要求用户每条任务填写（C1 未解决）；只保留一句 JSON 指令（缺字段与日期约束） | `providers/llm_prompt.py`、`routers/llm_config.py` |
| D4 | API Key 存储 | 连接内 Fernet 加密、只写不回显、不随备份导出；运行期会话 Key 优先 | 复用既有加密能力与保密口径（I5）；保留会话以兼容旧任务 | 明文入库；导出备份带 Key；只保留会话（每任务绑定偏重） | `services/connection.py`、`routers/llm_config.py`、`workspaces/services/backup_io.py` |
| D5 | 目标表自动化 | 留空按任务名建表（同名复用）；已有空表自动补字段 | 「空数据表自动新增和更新」的直接落点；同名复用避免重复建表 | 强制先手建表（C3 未解决）；每次运行重建表（丢历史与幂等基础） | `services/auto_table.py`、`services/runner.py` |
| D6 | 幂等键来源 | 显式配置优先；缺省时从结果行自动识别（单列唯一优先，最多 3 列组合）；无唯一组合退化为追加并留痕 | 去掉 cron 强制手填（C3），同时不伪造键（I4） | cron 强制手填（原 ADR 0014 D6 口径，复杂且易错）；固定取首列（可能不唯一）；为 match_keys 建复合唯一索引（ADR 0006 D8 已否决） | `services/auto_table.py`、`services/write.py`、`services/runner.py` |
| D7 | 自动化触发范围 | 仅 `provider=llm_prompt` | 其它 provider 有确定的目标表与字段语义，隐式建表是意外副作用（I3） | 所有 provider 统一自动建表（改变既有行为，回归面不可控） | `services/runner.py` |
| D8 | 备份版本 | 升 v6 导出 `llm_config`（不含 Key）；导入接受 1-6 | 连接配置属于工作区配置，不导出则迁移工作区后需重配；Key 导出违反保密口径 | 不进备份（迁移丢配置）；复用 v5 原地加键（版本号不再可信） | `workspaces/services/backup_io.py`、`workspaces/schemas/models.py` |
| D9 | 旧任务兼容 | 显式 url/model/api_key 优先级高于连接默认值；旧备份按空连接还原 | 不强制迁移存量任务（I7） | 批量重写旧任务 `request_spec`（不可逆、风险高） | `services/connection.py`、`services/runner.py` |
| D10 | 提示词模板求值严格度 | `llm_prompt` 专用宽松入口 `render_text_lenient`：仅替换已注册变量，未知 `{xxx}` / 裸花括号原样保留；其它 provider 仍用严格 `render_text` | 用户会直接在提示词里写 JSON 示例，要求先转义违背「只配提示词即可」（C1/C2）；宽松只作用于提示词，不影响 URL / body 的缺参保护 | 全链路放宽（其它 provider 的 URL / body 模板失去缺参保护）；要求用户手动转义（C1 未解决） | `providers/template.py`、`providers/llm_prompt.py` |

门禁：本表无「待定」；需求方已于 2026-10-22 确认简化方案并要求实现，Status 定稿 `Implemented`。

## Consequences

- **正向**：新建 `llm_prompt` 任务只需「任务名 + 一句提示词」，系统自动建表、补字段、识别幂等键并持续更新；连接与模型参数只维护一份；系统提示词默认可用，模型输出结构更稳定；旧任务与旧备份不受影响。
- **负向**：新增一张连接表与一条迁移；写路径多一层自动建表 / 补字段 / 推断键的分支，runner 与 write 的复杂度上升；自动推断幂等键存在「推断错误」的小概率，需要 `run.detail` 留痕排查。
- **风险与缓解**：自动建表产生非预期表 → 仅 `llm_prompt` 且行非空时触发，任务失败不建表；推断键不唯一 → 退化为追加并留痕，不静默更新错误行；连接 Key 泄露 → 加密、不回显、不导出；旧任务回归 → 显式配置优先 + 既有测试全跑。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 数据同步框架（Provider × SyncJob × Cursor × Normalizer） | `plugins/datasource/` | 自动化只在 `llm_prompt` 内实现，框架层不动 | ADR 0006 |
| 凭证管理 | `datasource_session` → 新增 `datasource_llm_config` | 会话 Key 保留并优先，工作区连接作为默认来源 | ADR 0006 D6、本 ADR D4 |
| 幂等落库 | `upsert_rows` 应用层先查后写 | 沿用应用层 upsert，不引入复合唯一索引；新增自动键推断 | ADR 0006 D8、本 ADR D6 |
| 备份格式 | 工作区备份 v5 → v6 | 追加 `llm_config`（不含 Key），导入端向下兼容 1-5 | ADR 0006、本 ADR D8 |
| `llm_prompt` provider | `providers/llm_prompt.py` | 本 ADR 简化其配置门槛并新增默认系统提示词 / 空表自动化；provider 协议不变 | ADR 0014 |
| cron 与幂等键 | `ScheduleMode.CRON` | **简化口径见 ADR 0019**：`llm_prompt` + cron 不再强制 `match_keys`，改为自动识别 | ADR 0014 D6 → 本 ADR D6 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/datasource/models.py`、`src/cndb/plugins/datasource/services/connection.py`、`src/cndb/plugins/datasource/routers/llm_config.py`、`src/cndb/plugins/datasource/routers/__init__.py`、`src/cndb/plugins/datasource/routers/sync_jobs.py`、`src/cndb/plugins/datasource/providers/llm_prompt.py`、`src/cndb/plugins/datasource/providers/template.py`、`src/cndb/plugins/datasource/schemas.py`、`src/cndb/plugins/workspaces/routers/workspaces.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/workspaces/schemas/models.py`、`src/cndb/alembic/versions/5e6f7a8b9c01_add_datasource_llm_config.py` | `tests/test_datasource_llm_config.py`、`tests/test_datasource_llm_provider.py`、`tests/test_datasource_api.py`、`tests/test_datasource_backup.py`、`tests/test_datasource_migration.py`、`tests/test_migration_missing_model_columns.py` | TBD |
| P1 | 已落地 | `src/cndb/plugins/datasource/services/auto_table.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/cli/sync.py` | `tests/test_datasource_auto_table.py`、`tests/test_datasource_runner.py`、`tests/test_datasource_cli.py` | TBD |
| P2 | 已落地 | `frontend/src/api/datasource.ts`、`frontend/src/pages/datasource/llmPromptPresets.ts`、`frontend/src/pages/datasource/DatasourcePage.tsx` | `frontend/src/pages/datasource/DatasourcePage.test.tsx`、`frontend/src/pages/datasource/llmPromptPresets.test.ts` | TBD |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系；提交列由 Lead 在提交后回填 sha。

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地（后端连接 / 系统提示词 / 自动落表 + 前端极简表单与 5 组预设），等待提交回填 sha
- 已完成：P0 工作区级大模型连接 + 内置默认系统提示词 + prompt-only 校验 / 连通测试回退 + 备份 v6 + 提示词宽松模板（`render_text_lenient`，JSON 裸花括号可直接写）；P1 自动建表 / 空表补字段 / 自动幂等键 + 预览建议键 + CLI `preview` / `run --dry-run` 同步输出 `suggested_match_keys`；P2 前端极简表单 + 5 组推荐提示词 + 测试与文档
- 下一步：Lead 回填三期提交 sha；人工确认后保持 `Status: Implemented`；如后续要支持「自动幂等键人工纠错入口 / 多连接」另立 ADR
- 已知坑：自动幂等键只在结果行内可判定，无唯一组合时退化为追加（看 `run.detail.auto_match_keys`）；自动补字段只在空表启用，已有表未知列按原策略；备份不导出 Key，导入后需重填；工作区连接未配置时运行错误文案指向「大模型连接」而非 401；宽松模板只作用于 `llm_prompt` 的 system / user 提示词，URL 与 headers 仍严格；CLI 预览需传 `db` 才会应用连接默认值并给出 `suggested_match_keys`
- 最近一次全绿：`make check-docs`（2026-10-22，文档检查）；代码门禁以本轮提交为准

## 附录：5 组推荐用户提示词说明

页面「推荐提示词」与本节保持同一份口径（预设定义见 `frontend/src/pages/datasource/llmPromptPresets.ts`；prompt 中的 `{{` / `}}` 是后端模板语法里的字面花括号，运行时还原为 `{` / `}`）。

| 预设 id | 场景 | 建议目标表字段 | 建议幂等键 |
|---|---|---|---|
| `daily_news` | 每日新闻摘要 | `date`、`category`、`title`、`summary`、`source`、`url`、`importance` | `date` + `category` + `title` |
| `city_weather` | 城市天气预报 | `date`、`city`、`weather`、`temp_high`、`temp_low`、`precip_prob`、`wind`、`aqi_level` | `date` + `city` |
| `market_snapshot` | 股票 / 基金行情快照 | `trade_date`、`symbol`、`name`、`close`、`change_pct`、`volume`、`amount`、`turnover_rate` | `trade_date` + `symbol` |
| `ecommerce_price` | 电商竞品价格监控 | `date`、`platform`、`product_id`、`title`、`price`、`list_price`、`promotion`、`sales` | `date` + `platform` + `product_id` |
| `policy_tracker` | 行业政策公告跟踪 | `date`、`agency`、`title`、`summary`、`policy_type`、`effective_date`、`url` | `date` + `agency` + `title` |

### 1. 每日新闻摘要（`daily_news`）

- **适用场景**：每天汇总国内要闻 / 财经 / 科技三个板块的重点新闻，按 `date + category + title` 去重，适合资讯看板。
- **建议目标表字段**：`date`（日期 `YYYY-MM-DD`）、`category`（板块）、`title`（标题）、`summary`（摘要 ≤120 字）、`source`（来源媒体）、`url`（原文链接）、`importance`（重要度 1-5 整数）。
- **建议幂等键**：`date` + `category` + `title`。
- **prompt 示例**（节选，实际含完整字段说明）：

```text
请汇总 {today} 的每日新闻摘要，覆盖国内要闻、财经、科技三个板块。
每个板块挑选最重要的 3-5 条，按重要度从高到低排列；每条给出一句话摘要（不超过 120 字）。
字段要求（全部使用英文 snake_case）：date、category、title、summary、source、url、importance。
只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。不要输出 Markdown 代码围栏或任何解释文字。
```

### 2. 城市天气预报（`city_weather`）

- **适用场景**：按城市 + 日期生成当天及未来两天的天气预报，适合天气日报表；`date + city` 即天然幂等键。
- **建议目标表字段**：`date`、`city`、`weather`、`temp_high`（℃ 整数）、`temp_low`、`precip_prob`（0-100 整数）、`wind`（风向风力）、`aqi_level`（空气质量等级）。
- **建议幂等键**：`date` + `city`。
- **prompt 示例**（节选）：

```text
请生成城市天气预报，基准日期：{today}。默认覆盖北京、上海、广州、深圳。
每个城市给出当天及未来 2 天（共 3 天）的预报：天气现象、最高/最低气温、降水概率、风向风力、空气质量等级。
字段要求（全部使用英文 snake_case）：date、city、weather、temp_high、temp_low、precip_prob、wind、aqi_level。
同一城市同一日期只能有一条记录，date + city 为稳定键。
只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。
```

### 3. 股票 / 基金行情快照（`market_snapshot`）

- **适用场景**：抓取指定标的的收盘行情快照（价格 / 涨跌幅 / 成交量），`trade_date + symbol` 去重，适合行情日表与趋势分析。
- **建议目标表字段**：`trade_date`、`symbol`（证券代码）、`name`、`close`、`change_pct`（百分比数值，1.23 表示 +1.23%）、`volume`（股）、`amount`（元）、`turnover_rate`（换手率百分比）。
- **建议幂等键**：`trade_date` + `symbol`。
- **prompt 示例**（节选）：

```text
请整理 {today} 的股票 / 基金行情收盘快照。默认覆盖沪深 300 成分股中市值前 10 的标的。
每个标的给出：证券代码、证券名称、收盘价、涨跌幅、成交量、成交额、换手率。
字段要求（全部使用英文 snake_case）：trade_date、symbol、name、close、change_pct、volume、amount、turnover_rate。
同一标的同一交易日只能有一条记录，trade_date + symbol 为稳定键。
只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。
```

### 4. 电商竞品价格监控（`ecommerce_price`）

- **适用场景**：按平台 + 商品监控竞品售价与促销信息，`date + platform + product_id` 去重，适合价格波动看板与调价提醒。
- **建议目标表字段**：`date`、`platform`（如 `jd` / `taobao`）、`product_id`（平台商品 ID）、`title`、`price`（元）、`list_price`（划线价）、`promotion`（无则空串）、`sales`（整数）。
- **建议幂等键**：`date` + `platform` + `product_id`。
- **prompt 示例**（节选）：

```text
请监控 {today} 的电商竞品价格。默认覆盖 3 个主要竞品，可替换为指定商品 ID / 链接列表。
每个竞品给出：平台、平台商品 ID、商品标题、当前售价、划线价、优惠信息、销量。
字段要求（全部使用英文 snake_case）：date、platform、product_id、title、price、list_price、promotion、sales。
同一平台同一商品同一日期只能有一条记录，date + platform + product_id 为稳定键。
只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。
```

### 5. 行业政策公告跟踪（`policy_tracker`）

- **适用场景**：跟踪部委 / 地方 / 行业协会发布的政策公告，`date + agency + title` 去重，适合政策台账与合规提醒。
- **建议目标表字段**：`date`、`agency`（发文机构）、`title`、`summary`（≤200 字）、`policy_type`（通知 / 征求意见 / 办法 / 规划等）、`effective_date`（暂无空串）、`url`（原文链接）。
- **建议幂等键**：`date` + `agency` + `title`。
- **prompt 示例**（节选）：

```text
请跟踪 {today} 发布的行业政策与监管公告，覆盖国家部委、地方主管部门和行业协会官网。
每条记录给出：发布日期、发文机构、政策标题、政策摘要、政策类型、生效日期、原文链接。
字段要求（全部使用英文 snake_case）：date、agency、title、summary、policy_type、effective_date、url。
同一机构同一日期同一标题只能有一条记录，date + agency + title 为稳定键。
只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。
```