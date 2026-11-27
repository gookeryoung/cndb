# 需求卡片：数据表字段字典与设计规范文档导出

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0188（与 ADR `docs/adr/0188-table-field-dictionary.md` 同号）
- 来源 / 提出人：用户（会话 2026-11-26）
- 日期：2026-11-26
- 关联 ADR：`docs/adr/0188-table-field-dictionary.md`

## 需求原句（逐字）

> 数据表，表设置，对于字段的配置需要支持导出文档，能够阐明当前的字段设计规范，便于维护企业的数据标准。请结合最佳实践，给出可行的建议。

> 执行P0-P2

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「对于字段的配置需要支持导出文档」 | 新增只读端点 `GET /{wid}/tables/{tid}/dictionary?format=md\|xlsx\|json\|docx\|pdf`：把该表「字段契约」渲染成文档下载；无写路径（只 `GET`）；文件名沿用 `工作区-表名-数据字典-YYYYMMDD_HHMMSS.ext` 口径 | `tables/routers/dictionary.py` | 接口测试：五种格式各 200 + `Content-Disposition` 正确；`POST` 该路径 405 |
| C2 | 「阐明当前的字段设计规范」 | 文档固定章节骨架：表基本信息 / 字段清单 / 枚举字典 / 校验与规则 / 关联与派生 / 可见性 / 变更记录 / 设计规范附录；**缺内容输出「未填写」占位而不是省略章节**（否则看不出治理缺口） | `tables/services/dictionary/` | 单测：空表仍出全部章节；字段说明为空时该单元格为「未填写」 |
| C3 | 「维护企业的数据标准」 | 字段的业务元数据落库：`business_meaning`（口径）/ `unit`（单位）/ `sensitivity`（`public\|internal\|confidential`）/ `owner_id`（责任人）/ `standard_ref`（标准来源）/ `example_value`；新增列由迁移 `0188` 幂等补，`downgrade` 可还原；存量行为空即「未填写」，旧行为逐条不变 | `tables/models.py`、`migrations`、`schemas/models.py`、`routers/fields.py` | 迁移幂等 + downgrade 测试；接口测试：`PATCH /fields/{fid}` 可写这些字段并回读 |
| C4 | （C3 派生：标准符合度） | `GET /{wid}/tables/{tid}/dictionary/score` 返回可度量指标：有业务说明字段占比、枚举受控率、命名规范命中率、必填覆盖率、敏感级标注率、示例值覆盖率 + 逐项缺口字段名；只读、`READ` 权限 | `tables/services/dictionary/score.py` | 单测：给定字段集合各指标数值与缺口清单正确 |
| C5 | （C1 派生：合订与裁剪） | 工作区级合订端点 `GET /{wid}/tables/dictionary?table_ids=`；**必须复用 `get_hidden_field_names`** 剔除当前用户不可见字段（含「字段名本身」），禁止另写裁剪；不含任何行数据 | `tables/routers/dictionary.py` | 接口测试：viewer 导出不含 hidden 字段名；无表 READ 权限 404 |
| C6 | （C1 派生：内部列开关） | `include_internal`（默认 `false`）控制是否输出 `db_column_name` / 物理表名 / order；默认不输出实现细节；`confidential` 字段在默认口径下把 `business_meaning` / `example_value` 脱敏为「（受限）」 | 同 C1 | 单测：两种开关下 JSON 契约差异符合预期 |
| C7 | （C1 派生：契约与防漂移） | `format=json` 输出 `kind=cndb-table-dictionary` + `version=1` + `schema_hash`（结构指纹）；`md` / `docx` / `pdf` 文档尾部同样带 `schema_hash` 与生成时间，便于比对「文档是否过期」 | 同 C1 | 单测：同结构两次导出 hash 相同；改字段名后 hash 变化 |
| C8 | （C1 派生：docx / pdf 的边界） | `tables` 不得 import `documents`（ADR 0130 插件方向 + H69）；`docx` / `pdf` 渲染能力上提到共享层 `cndb/render/markdown_export/`（纯渲染、无领域语义），`documents` 与 `tables` **都向下依赖**；`documents.services.export` 保留兼容再导出（H28） | `src/cndb/render/`、`documents/services/export/` | 既有 `tests/test_cov_documents_extra.py` / `test_pdf_fonts.py` / `test_export_templates.py` 零改动通过 |
| C9 | （C1 派生：审计） | 导出写统一事件 `table.dictionary_export`，`summary` 只含表名与格式，`detail` 只含表 id / 格式 / 字段数 / `include_internal`，**不落字段说明与示例值**（H38 口径） | `tables/routers/dictionary.py`、`core/events.py` | 接口测试：导出后 `GET /api/v1/events` 可查到该 action 且 detail 无业务文本 |
| C10 | （C3 派生：备份往返） | 新字段元数据随工作区备份往返：导出写进 `fields[]`，导入按缺省（旧包无键 → 空值）还原；不新增备份版本号（未知键对旧包无害，新包旧程序按额外键忽略的既有口径） | `workspaces/services/workspace_backup.py`、`backup_io.py` | 备份往返测试：新字段值经导出→导入后一致；旧包（无键）导入导出字段为空 |
| C11 | （前端） | ① 字段配置面板新增「业务属性」分区（说明 / 口径 / 单位 / 示例值 / 敏感级 / 标准来源 / 责任人），`description` 提示「会进入导出的数据字典，请写业务口径」；② 表设置「字段」页签工具条新增「导出字段文档」对话框（格式 / 合订范围 / `include_internal`）；③ 文档结构变化时提示「上次导出后结构已变更」 | `frontend/src/pages/fields/FieldManager/`、`frontend/src/pages/settings/TableSettingsPage.tsx` | 前端单测：新分区渲染与提交 payload；导出对话框参数正确；e2e 导出 xlsx 可打开 |
| C12 | （门禁与文档） | 同轮补后端 / 前端 / e2e 测试；`CONTEXT.md`、`docs/USER_DOC_MAP.md`、帮助教程、`CHANGELOG.md`、ADR 落地状态回填 | 文档、测试 | `make flow` / `make check-frontend` / `make check-docs` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 字段元数据 | `src/cndb/plugins/tables/models.py:213` `DataField` | 只有技术属性，无业务属性 |
| 2 | 字段业务说明的「占位」 | `field_types/base.py:26` `FieldTypeConfig.description` | 已能被 config 保留（`routers/fields.py:214` exclude 计算），但前端无编辑入口 |
| 3 | 校验规则 | `services/core/field_rules.py`（需求 0146） | 导出需把 `validation` / `required_when` 翻译成人话 |
| 4 | 枚举 | `field_types/select.py` `options[{label,value,color}]` | 缺「每个选项的业务含义」 |
| 5 | 关联 / 派生 | `field_types/{relation,lookup,formula}.py` | 导出需解析目标表名 / 引用链 |
| 6 | 字段隐藏 | `services/core/access.py:316` `get_hidden_field_names` | 导出必须复用，不另写 |
| 7 | 行数据导出（对照） | `routers/bulk_export.py` | 文件名 / 权限 / 隐藏裁剪范式可复用 |
| 8 | docx / pdf 渲染器 | `documents/services/export/{docx,pdf}.py` | `tables` 不能反向 import；需上提共享层 |
| 9 | 类型中文标签 | `field_types/*.py` 的 `label`（后端）+ `frontend/src/utils/fieldTypeMeta.ts` | 后端已有 label，导出直接取 registry |
| 10 | 备份字段序列化 | `workspaces/services/workspace_backup.py:262`、`backup_io.py:257` | 新字段需进出备份 |

## 未决问题

- [x] ① 业务元数据落 `config` 还是新列？→ 新列（C3）：`config` 是字段类型 schema 的严格闭包（`routers/fields.py:214` 会丢弃 schema 外键），放业务口径会被静默丢弃；且 `owner_id` 需外键、`sensitivity` 需索引与跨表查询。
- [x] ② docx / pdf 是否必须做？→ 做，但先上提渲染层（C8），否则 `tables` 反向依赖 `documents` 违反插件方向。
- [x] ③ 基线快照表是否本期做？→ **不做**（P2 只做 `schema_hash` + 符合度评分）；快照表需新表 + 备份 + 保留策略，收益低于评分指标。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论
