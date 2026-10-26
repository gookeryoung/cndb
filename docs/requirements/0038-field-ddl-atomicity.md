# 需求卡片：字段 DDL 原子回退（新增必填字段失败不得留下孤儿字段）

- 编号：0038（与 ADR `docs/adr/0038-field-ddl-atomicity.md` 同号）
- 来源 / 提出人：用户（数据表页实操反馈）
- 日期：2026-10-26
- 关联 ADR：`docs/adr/0038-field-ddl-atomicity.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 数据表，已有数据的情况下，新增唯一非空字段。报错：物理加列失败: (sqlite3.OperationalError) Cannot add a NOT NULL column with default value NULL [SQL: ALTER TABLE "table_51243b9d6934" ADD COLUMN "field_f85d82cc02e6" VARCHAR(255) NOT NULL] (Background on this error at: `https://sqlalche.me/e/20/e3q8)`。但是此情况下依然创建了字段。且无法再进行编辑，提示内部服务器错误。请完善此情况的原子回退处理，并分析还有无类似情况。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 已有数据的情况下，新增唯一非空字段。报错：物理加列失败 … Cannot add a NOT NULL column | 非空物理表无法 `ADD COLUMN … NOT NULL`（无默认值）；新增必填字段在保存前拒绝，返回 400 与可操作文案（先建可空字段、补齐数据后再设必填） | `plugins/tables/routers/fields.py` | `tests/test_field_edit_validation.py::TestCreateFieldAtomicity::test_required_unique_field_on_non_empty_table_rejected` |
| C2 | 但是此情况下依然创建了字段 | DDL 先行、metadata 后提交：物理加列/唯一索引失败时撤销本次已建物理对象且不落 DataField，杜绝「有 metadata、无物理列」的孤儿字段 | 同上 | `test_add_column_failure_leaves_no_orphan_metadata`、`test_unique_index_failure_rolls_back_added_column` |
| C3 | 且无法再进行编辑，提示内部服务器错误 | 存量孤儿字段（历史 DDL 失败残留）必须可清理：物理列不存在时删除字段按已删除处理，不再因 `no such column` 500 | 同上 + `services/core/ddl.py` | `test_delete_field_tolerates_missing_physical_column` |
| C4 | 请完善此情况的原子回退处理 | 同类写路径同口径：建表/复制表 DDL 失败回滚 metadata；link↔物理列互转「先建后删」；字段导入非空表必填字段提前 400 | `routers/tables.py`、`routers/fields.py`、`services/fields/field_import.py` | `tests/test_tables_coverage.py::TestCreateTableAtomicity`、`TestCreateFieldAtomicity`、`tests/test_fields_import.py::TestRequiredFieldImportGuard` |
| C5 | 并分析还有无类似情况 | 逐个核对全部「metadata 落库 + 物理 DDL」路径，把仍有缺口的路径补齐并在 ADR Context 表留档 | 全仓 `plugins/tables/` | ADR Context 表逐条结论 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 新增字段 | `src/cndb/plugins/tables/routers/fields.py` | 先 commit metadata，后 add_column；失败留下孤儿字段 |
| 2 | 编辑字段（类型/必填/唯一） | `src/cndb/plugins/tables/routers/fields.py` | 物理重建失败走 metadata 反向恢复；link↔物理列顺序可能先删后建 |
| 3 | 删除字段 | `src/cndb/plugins/tables/routers/fields.py` | 孤儿字段删除时 `DROP COLUMN` 报 no such column，无法自救 |
| 4 | 新建 / 复制数据表 | `src/cndb/plugins/tables/routers/tables.py` | `ddl_create` 失败可能残留孤儿 DataTable |
| 5 | 字段导入 / 导入自动加列 | `services/fields/field_import.py`、`services/importing/importer.py` | 已采用 DDL 先行 + 逆向清理；必填字段进非空表仍报原始 SQL 错 |

## 未决问题

- [x] 非空表新增必填字段：拒绝（400）而非写入占位默认值 —— 占位值会污染必填语义（已确认）
- [x] 非空表引入必填字段：拒绝（400），不自动降级为可空（避免静默改变源字段约束语义）（已确认）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认
