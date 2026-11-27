# ADR 0188: 数据表字段字典（字段业务元数据 + 一源三态导出 + 标准符合度）

Status: Implemented（2026-11-28 用户「执行P0-P2」，P0–P2 已落地）
Date: 2026-11-28
Related: `src/cndb/plugins/tables/models.py`、`src/cndb/plugins/tables/routers/dictionary.py`、`src/cndb/plugins/tables/services/dictionary/`、`src/cndb/render/markdown_export/`、`src/cndb/plugins/tables/routers/fields.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`frontend/src/pages/fields/FieldManager/`、`frontend/src/pages/settings/TableSettingsPage.tsx`
需求卡片: `docs/requirements/0188-table-field-dictionary.md`（需求原文与约束编号的唯一副本）
上游：ADR 0130（插件边界：tables 不得依赖 documents）、ADR 0152（导出模板）、ADR 0146（字段校验规则）、ADR 0046（options 展示截断）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字）；约束编号 C1..C12 一律引用卡片，本表只写落地方式。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「字段的配置需要支持导出文档」 | 新增只读路由 `tables/routers/dictionary.py`：`GET /{wid}/tables/{tid}/dictionary` 与 `GET /{wid}/tables/dictionary`，`format ∈ md\|xlsx\|json\|docx\|pdf`；统一入口 `services/dictionary/build.py::build_document`（D1 / D2） |
| C2 | 「阐明当前的字段设计规范」 | 章节骨架固定在 `services/dictionary/markdown.py::SECTION_ORDER`，缺失内容写「未填写」占位而不是省略（D3） |
| C3 | 「维护企业的数据标准」 | `DataField` 新增 6 列（`business_meaning` / `unit` / `sensitivity` / `owner_id` / `standard_ref` / `example_value`），迁移 `a7b8c9d0e1f2` 幂等补列 + downgrade 还原（D4 / D5） |
| C4 | （标准符合度） | `GET /{wid}/tables/{tid}/dictionary/score` → `services/dictionary/score.py`，6 项指标 + 逐项缺口字段名（D6） |
| C5 | （合订与裁剪） | 工作区合订端点复用同一 builder；可见性一律走 `get_hidden_field_names`，禁止另写裁剪（D7） |
| C6 | （内部列开关） | `include_internal`（默认 false）控制物理列名 / 物理表名 / order；`confidential` 字段在默认口径下把口径与示例值脱敏（D8） |
| C7 | （契约与防漂移） | `schema_hash`（结构指纹）写入 JSON 契约与 md / docx / pdf 文档尾部（D9） |
| C8 | （docx / pdf 的边界） | 渲染能力上提 `src/cndb/render/markdown_export/`，`documents` 与 `tables` 都向下依赖；`documents.services.export` 保留兼容再导出（D10） |
| C9 | （审计） | 导出写 `core_event("table.dictionary_export")`，只记表 id / 格式 / 字段数 / `include_internal`（D11） |
| C10 | （备份往返） | 6 个新字段进出 `workspace_backup` 的 `fields[]`，旧包缺键按空还原；不升备份版本号（D12） |
| C11 | （前端） | 字段面板新增「业务属性」分区；表设置「字段」页签新增「导出字段文档」对话框；结构变化提示（D13） |
| C12 | （门禁与文档） | 测试清单见 §7，文档回填见 §落地状态 |

## Context

现状逐条核对（以代码为准）。沿用卡片「现状影响面」编号并逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `DataField` 只有技术属性（name / field_type / config / required / is_unique / default_value / hidden / order） | `plugins/tables/models.py:240` | 无法表达口径、单位、敏感级、责任人，企业数据标准无处落 | 确认（C3） |
| 2 | `FieldTypeConfig.description` 存在且被 `_validate_field_config` 保留 | `field_types/base.py:26`、`routers/fields.py:214` | 曾可作为「字段说明」的零迁移落点；但 `config` 是字段类型 schema 的闭包，schema 外的键（如 `sensitivity` 的结构化取值）会被丢弃，且 `owner_id` 需要外键 | 排除（改用独立列，见 D4） |
| 3 | 校验规则存 `config.validation` / `config.required_when` | `services/core/field_rules.py` | 导出需翻译成人话，否则文档里只有 JSON | 确认（C2） |
| 4 | 枚举是 `config.options[{label,value,color}]`，没有「选项业务含义」 | `field_types/select.py` | 枚举字典章节只能输出 label / value，含义列留「未填写」 | 确认（C2） |
| 5 | `link` / `lookup` / `formula` 的语义散在 config 的 id 上 | `field_types/{relation,lookup,formula}.py` | 导出必须解析成表名 / 字段名，否则文档不可读 | 确认（C2） |
| 6 | 字段隐藏按角色存在 `TablePermission.hidden_fields` | `services/core/access.py:316` | 导出必须复用同一函数，否则「字段名本身」外泄 | 确认（C5） |
| 7 | 行数据导出有完整范式（文件名 / 权限 / 隐藏裁剪 / 上限） | `routers/bulk_export.py` | 字典导出沿用同一文件名与权限口径 | 确认（C1） |
| 8 | docx / pdf 渲染器在 documents 插件内 | `documents/services/export/{docx,pdf}.py` | tables 不能反向 import documents | 确认（C8 / D10） |
| 9 | 类型中文标签后端已有 `FieldType.label`，前端另有 `fieldTypeMeta.ts` | `field_types/registry.py` | 导出取 registry 的 label，不新增第二份映射 | 确认（C2） |
| 10 | 备份 `fields[]` 逐键列举 | `workspaces/services/workspace_backup.py:262`、`backup_io.py:257` | 新列不进备份即丢失 | 确认（C10） |
| 11 | 无任何「字段文档」产物 | — | 用户只能靠截图 / 口头交接维护数据标准 | 新增 |

**核心缺陷（需求要补的）**：字段只有「机器怎么存」，没有「业务什么意思、谁负责、能不能外发」。企业数据标准的载体是一份可评审、可 diff、可度量的字段契约文档，而系统里既没有元数据落点，也没有产物。

设计目标（不变量）：

- **I1 单一构建入口**：所有格式（md / xlsx / json / docx / pdf）都由同一个 `FieldDictionary` 中间模型渲染，禁止某个格式自己再拼一遍字段信息。改口径只改一处。
- **I2 只读且不含行数据**：字典端点只 `GET`，输出不含任何单元格值；「敏感」只影响文本脱敏，不构成新的数据通路（H54 精神）。
- **I3 可见性同源**：字段是否出现在字典里，恒等于 `get_hidden_field_names` 的结论；不得在字典层另写裁剪（H53 / H64 同源口径）。
- **I4 缺内容显式占位**：任何元数据缺失都输出「未填写」，不允许「悄悄省略这一列 / 这一节」——省略会让缺口不可见，而缺口正是要治理的对象。
- **I5 插件方向不变**：`tables` 永不 import `documents`；渲染能力上提到 `cndb/render/`（H69 单向无环）。

## Decision

### 1. 数据模型

`tables_datafield` 新增 6 列（全部可空，存量零迁移）：

| 列 | 类型 | 语义 | 缺省口径 |
|---|---|---|---|
| `business_meaning` | Text | 业务口径（算的是什么 / 含不含税 / 取值范围约定） | 「未填写」 |
| `unit` | String(32) | 计量单位 | 「未填写」 |
| `sensitivity` | String(16) | `public` / `internal` / `confidential` | NULL 按 `internal` |
| `owner_id` | Integer FK → `accounts_user.id` ON DELETE SET NULL | 字段责任人 | 「未指派」 |
| `standard_ref` | String(255) | 标准来源（标准字段库 key / 规范条目） | 「未填写」 |
| `example_value` | String(255) | 示例值 | 「未填写」 |

- 迁移 `a7b8c9d0e1f2`：按列存在性幂等补列 + 补 `ix_tables_datafield_owner_id`；downgrade 逆序删索引与列（H13）。
- 为什么不放 `config`：`config` 由字段类型 `config_schema` 严格校验，schema 外的键在保存时被丢弃（`routers/fields.py::_validate_field_config`）；且 `owner_id` 需要外键级联、`sensitivity` 需要按值查询。放进 `config` 会得到「保存成功但读不到」的静默失败。
- `FieldSensitivity.normalize` 对脏值 / 空值一律回退 `INTERNAL`，不让一条脏数据阻塞整份字典导出。

### 2. 写入口

`PATCH /fields/{fid}` 与 `POST /fields` 接受 6 个新键，统一经 `_validate_business_metadata`：

- 文本键去首尾空白、空串归一 `None`（不存空串噪声）；
- `sensitivity` 非枚举值 400；
- `owner_id` 非存在用户 400；
- `PATCH` 语义：只处理请求里显式出现的键（`exclude_unset=True`），显式传 `null` = 清空。

字段引入（`plan_field_import`）复制这 6 项中的 5 项文本 / 敏感级，**不复制 `owner_id`**：责任人是「这张表这个字段」的归属，随新表重新指派。

### 3. 中间模型与渲染（I1）

```
services/dictionary/build.py    FieldDictionary / TableDictionary / build_table_dictionary / build_workspace_dictionary
services/dictionary/labels.py   类型标签、config → 人话（枚举 / 校验 / 关联 / 公式 / 自动编号）
services/dictionary/markdown.py 中间模型 → Markdown（章节骨架 + 「未填写」占位）
services/dictionary/xlsx.py     中间模型 → 多 sheet 工作簿（字段清单 / 枚举字典 / 校验与规则 / 关联与派生）
services/dictionary/score.py    中间模型 → 标准符合度指标 + 缺口字段
```

`FieldDictionary` 是唯一真相源：xlsx / json / docx / pdf 都从它出发，markdown 只是其中一种渲染（docx / pdf 由 `cndb/render/markdown_export` 吃同一份 Markdown）。

### 4. 章节骨架（C2）

固定 8 节，顺序不可变：表基本信息 → 字段清单 → 枚举字典 → 校验与规则 → 关联与派生 → 可见性 → 变更记录 → 设计规范附录。

- 字段清单列：序号 / 字段名 / 类型 / 业务说明 / 必填 / 唯一 / 默认值 / 取值范围与校验 / 枚举 / 关联与公式 / 可见性 / 示例 / 敏感级 / 责任人。
- 「变更记录」取 `tables_auditlog` 最近 20 条字段级动作；该表当前只记行级动作，为空时明确输出「暂无字段级变更记录」而不是删掉本节。
- 「设计规范附录」是**只读常量**（`services/dictionary/spec.py`）：类型选择建议、日期 vs 日期时间、枚举优先于自由文本、自动编号用法、敏感字段必须设 hidden + sensitivity。让「规范」与「当前实现」出现在同一份文档里对照。

### 5. 内部列与脱敏（C6）

- `include_internal=false`（默认）不输出 `db_column_name`、物理表名、order；`true` 时进入附录「物理实现」一节。
- `confidential` 字段在 `include_internal=false` 下，`business_meaning` 与 `example_value` 输出「（受限）」；`sensitivity` 与「责任人」照常输出（治理需要知道「有这么一个机密字段、谁负责」）。

### 6. 合订与可见性（C5 / I3）

- 工作区合订：`GET /{wid}/tables/dictionary?table_ids=1,2,3`（缺省 = 全部未删表）；输出单文档，每表一章，末尾追加「表间引用索引」（`link` 的目标表 → 反向引用表）。
- 逐表 `get_table_or_404(..., TableAction.READ)`；不可读的表从合订结果里**静默跳过**（不报 404 让整份失败，也不暴露「存在但不可读」）。
- 字段裁剪一律 `get_hidden_field_names(db, table, user)`。

### 7. 契约与防漂移（C7）

- `format=json`：`{"kind": "cndb-table-dictionary", "version": 1, "generated_at": ..., "schema_hash": "sha256:…", "workspace": {...}, "tables": [...]}`。
- `schema_hash` 只覆盖**结构**：表 id + 字段名 + 类型 + 必填 + 唯一 + 默认值 + config + order；不含业务口径文本（改文案不该让「结构已变更」告警）。
- 前端把上次导出的 `schema_hash` 存 `localStorage`（按 `wid/tid`），与当前计算值比对，不一致时在导出入口显示「上次导出后结构已变更」。

### 8. docx / pdf 与插件边界（C8 / I5）

`src/cndb/render/markdown_export/` 承载纯渲染能力（无领域语义）：

- `blocks.py`（Markdown 块解析）、`images.py`（图片解析器协议）、`fonts.py`（CJK 字体发现）、`docx.py`、`pdf.py`、`theme.py`、`numbering.py`、`ref_width.py`、`templates.py`。
- `documents/services/export/` 保留同名模块**再导出**（`from cndb.render.markdown_export.docx import _render_docx`），既有 import 路径与 monkeypatch 目标全部继续有效（H28）。
- `documents` 特有的部分留在原处：`charts/` 图表内联、`table_refs.py` 数据表引用、`images.py` 的 `file:<key>` 解析。
- 图表内联改为渲染器的**可选扩展点**：`render(markdown, ..., chart_renderer=None)`；`documents` 注入图表渲染器，`tables` 不注入（字典文档不含图表）。

### 9. 审计（C9）

`record_event(db, "table.dictionary_export", target_type="table", target_id=table.id, workspace_id=..., summary=f"导出数据字典（{fmt}）", detail={"table_id", "format", "field_count", "include_internal", "table_count"})`。不落字段说明 / 示例值（H38 口径）。

### 10. 备份（C10）

`workspace_backup` 的 `fields[]` 增加 6 个键；`backup_io` 导入时按 `fd.get(...)` 取值（旧包缺键 → None）。不升 `CHUNKED_BACKUP_VERSION`：备份解析对未知键宽容，旧程序读新包只是忽略这些键。

## 落地状态

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/alembic/versions/a7b8c9d0e1f2_add_field_business_metadata.py`；`src/cndb/plugins/tables/models.py`；`src/cndb/plugins/tables/schemas/models.py`；`src/cndb/plugins/tables/routers/fields.py`；`src/cndb/plugins/tables/routers/dictionary.py`；`src/cndb/plugins/tables/services/dictionary/build.py` | `tests/test_table_dictionary.py`、`tests/test_migration_field_business_metadata.py`、`frontend/src/pages/fields/FieldManager/FieldConfigPanel.test.tsx`、`frontend/src/pages/settings/TableSettingsPage.test.tsx` | `2250fb9c` |
| P1 | 已落地 | `src/cndb/plugins/workspaces/services/workspace_backup.py`；`src/cndb/plugins/workspaces/services/backup_io.py`；`src/cndb/render/markdown_export/`；`src/cndb/plugins/documents/plugin.py`；`src/cndb/plugins/tables/services/dictionary/export_render.py` | `tests/test_backup_field_metadata.py`、`tests/test_cov_documents_extra.py`、`frontend/src/pages/settings/TableSettingsPage.test.tsx` | `2250fb9c` |
| P2 | 已落地 | `src/cndb/plugins/tables/services/dictionary/score.py`；`src/cndb/plugins/tables/routers/dictionary.py`（score 与工作区合订） | `tests/test_table_dictionary.py`、`frontend/src/pages/settings/TableSettingsPage.test.tsx` | `2250fb9c` |

## 交接

- 当前阶段：P0–P2 已全部落地并提交（`2250fb9c`，2026-11-28；业务元数据 / 五格式导出 / 符合度 / 合订 / 备份往返）。
- 已知坑（含已知限制）：
  - 枚举选项的「业务含义」没有落点（`config.options[]` 只有 label / value / color），枚举字典该列固定「未填写」；要补齐需扩 `SelectOption`（下一轮，改 `field_types/select.py` 的 schema 与前端选项编辑器）。
  - 「变更记录」章节依赖 `tables_auditlog`，而字段级动作（create / update / delete field）当前**没有**写审计；本节先如实输出「暂无字段级变更记录」。补字段级审计是独立小项。
  - `schema_hash` 只覆盖结构，不含业务口径文本；改口径不会触发「结构已变更」提示（这是刻意的）。
  - 工作区合订对不可读表静默跳过，导出结果里不提示「被跳过了几张表」（避免暴露表存在性）；需要时由调用方按 `GET /tables` 自行比对。
- 下一步（未立项）：
  - 枚举选项业务含义（扩 `SelectOption`）。
  - 字段级审计（`field.create` / `field.update` / `field.delete` 写 `tables_auditlog` + `core_event`），让「变更记录」章节有真实内容。
  - 基线快照表（`tables_dictionary_snapshot`）与「自上次基线以来的变更」章节——需新表 + 备份 + 保留策略，本期明确不做。
  - 标准字段库（把 `fields/field_import.py` 的「从其他表引入」升级为可复用的企业标准字段目录）。
