# select / multiselect 选项变更 → 存量数据同步

来源：用户反馈"单选/多选类别字段，修改选项后，已有数据没有同步变更"（`.trae/req/req-17-选项变更同步存量数据.md`）。

## 背景

`config.options` 有两个同步方向，本设计只覆盖第二个：

1. 数据 → options：导入/批量创建时从行数据补全选项（`prefill_select_options_from_rows` / `sync_select_options_from_table`，既有实现）。
2. options → 数据：字段编辑器修改选项保存后，存量行数据迁移（本设计）。

## 接口定义

### `diff_select_options(old_raw, new_raw) -> (rename_map, removed)`

`src/cndb/plugins/tables/services/fields/field_ops.py`。

- 入参：新旧 `config.options` 原始列表（兼容 str / dict / SelectOption 三种形态）。
- 出参：`rename_map: dict[str, str]`（旧值 → 新值）、`removed: list[str]`（被移除值，保序去重）。
- 值语义：按选项 `value` 对比（dict 缺省回退 label），与 `_allowed_values_from_config` 一致。

### `sync_select_data_on_options_change(db, table, field, old_config) -> int`

同文件。返回受影响行数；物理表/物理列缺失时返回 0 并告警，不抛错。

### 路由接入

`PATCH /{workspace_id}/tables/{table_id}/fields/{field_id}`（`routers/fields.py:update_field`）：
仅当 `config` 参与 update、新旧 field_type 均为 select/multiselect 时触发；DML 在 metadata 保存的同一 Session 事务内执行（先同步后 commit，原子生效）；同步异常 → rollback + 500，config 与数据保持变更前状态。

## 算法与流程

1. diff（`difflib.SequenceMatcher`，`autojunk=False`）：
   - 值集合相等（纯重排/仅颜色/纯重复）→ 空迁移；
   - `replace` 段：等长段按顺序一一配对；不等长段配对 `min(旧, 新)` 个，多余旧值落删除；
   - 配对双重保险：仅当"旧值不在新列表且新值不在旧列表"才认定改名（防重排/重复值误判）。
2. 数据迁移：
   - select：逐对 `UPDATE SET col=new WHERE col=old`（改名目标必属新增集合，与旧值不相交，无级联）；删除值 `UPDATE SET col=NULL WHERE col=v`。
   - multiselect：按主键读全部非空行 → `split_multi_select_string` 拆分 → 未引用变更选项的行跳过 → 套用改名/摘除 + 保序去重 → 重组逗号串，按主键 executemany 写回；拆空的行置 NULL。

## 边界条件

- 前端选项编辑器为就地编辑（value 恒等于 label），改名保留位置、删除使后项左移、新增追加尾部——上述启发式对该编辑器产出的 diff 均正确。
- 已知启发式盲区：同一次保存中"删除项在前、改名项在后且相邻"时，按顺序配对会把被删值的行改写为改名后的新值（保守保留数据而非清空）；设计上接受该歧义。
- 删除选项清空存量值后，required 字段可能出现 NULL：物理层无 NOT NULL 约束，应用层写入校验不受影响，不拦截。
- 软删除行（_trashed）一并迁移，保证恢复后数据一致。

## 异常处理

- 同步 DML 异常：路由层 rollback 并返回 500「选项变更同步存量数据失败」，metadata 未提交、无半成品状态。
- 物理表/列缺失：告警日志 + 返回 0，不阻断字段保存（与 `sync_select_options_from_table` 容错口径一致）。

## 依赖项描述

- 复用 `split_multi_select_string`（分隔符集与 validate_value 一致）、`get_reflected_table`（engine 级反射缓存）。
- 测试：`tests/test_sync_select_data_on_options_change.py`（单元 18 例）、`tests/test_api_e2e_select_options.py::TestFieldOptionsChangeSyncsData`（E2E 4 例）。
