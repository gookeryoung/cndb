# 导入参考列智能推荐 + DIFF 识别增强与 datetime 序列化 Bug 修复 — 开发计划

## Summary

围绕"导入到已有表"的两阶段导入流水线（analyze → preview → confirm，入口 [ImportExportDialog.tsx](file:///f:/Dev/cndb/frontend/src/pages/modals/ImportExportDialog.tsx) "导入到当前表" Tab），做三件事：

1. **参考列智能推荐**：analyze 阶段分析文件列画像 + 目标表现有数据统计，产出 `match_key_recommendations`；前端参考列下拉展示推荐项（★），禁用不推荐项并展示原因。
2. **DIFF 识别增强**：upsert 匹配与字段级 diff 改用 RowValidator 归一化值（复用 `field_types.validate_value` 类型转换能力），解决"文件侧字符串 vs 库内 date/datetime/数字"类型不一致导致的漏匹配与误报 diff。
3. **Bug 修复**：日期类对象进入 `validation_report` 后 `json.dumps` 抛 `Object of type datetime is not JSON serializable`，任务转 failed。在 `DiffReporter.build` 输出做 JSON 安全化，`import_tasks.py` 三处 dumps 加 `default=str` 兜底。

## Current State Analysis

### 导入两阶段链路（已探明）

```
POST /import/analyze (bulk.py:349) → create_import_task → 后台线程
  → analyze_import_task (import_tasks.py:70) → Importer.analyze (importer.py:126)
  → json.dumps(report) → ImportTask.validation_report   [import_tasks.py:106]
reanalyze（改参考列重算 DIFF）: import_tasks.py:396 同样 dumps
confirm → execute_import_task → Importer.execute → json.dumps  [import_tasks.py:225]
前端轮询 GET /import/async/{task_id} 拿 validation_report 渲染预览面板
```

- 参考列（match_keys）在 `Importer._build_upsert_result`（[importer.py:349](file:///f:/Dev/cndb/src/cndb/plugins/tables/importer.py#L349-L445)）做 upsert 分类，产出 `new_preview`/`update_preview`/`field_diffs`。
- 前端参考列选择区 `renderDiffControls`（[ImportExportDialog.tsx:272](file:///f:/Dev/cndb/frontend/src/pages/modals/ImportExportDialog.tsx#L272-L337)）：非 link 字段平铺成 options，**无推荐、无禁用、无原因**。

### Bug 根因（datetime is not JSON serializable）

| 环节 | 位置 | 说明 |
|---|---|---|
| xlsx 日期单元格 | [importer.py:707](file:///f:/Dev/cndb/src/cndb/plugins/tables/importer.py#L707-L724) `_parse_xlsx` | openpyxl 返回 `datetime`/`date` 对象，仅做长数字保护，日期对象原样保留 |
| 原始值进报告 | [row_validator.py:137](file:///f:/Dev/cndb/src/cndb/plugins/tables/row_validator.py#L137) | `r.values` 保存原始值；归一化值在 `r.normalized`（keyed by db_column_name），upsert 路径未使用 |
| upsert 预览 | [importer.py:406-435](file:///f:/Dev/cndb/src/cndb/plugins/tables/importer.py#L406-L435) | `match_key_values`/`field_sample`/`field_diffs.new` 全部取自 `r.values` |
| 库侧旧值 | [importer.py:447-480](file:///f:/Dev/cndb/src/cndb/plugins/tables/importer.py#L447-L480) | `_fetch_old_rows_by_ids` 查物理列，date/datetime 字段返回 date/datetime 对象 → `field_diffs.old` |
| 序列化崩溃 | [import_tasks.py:106](file:///f:/Dev/cndb/src/cndb/plugins/tables/import_tasks.py#L106)、[:225](file:///f:/Dev/cndb/src/cndb/plugins/tables/import_tasks.py#L225)、[:396](file:///f:/Dev/cndb/src/cndb/plugins/tables/import_tasks.py#L396) | `json.dumps(report, ensure_ascii=False)` 无 `default` → TypeError → task 转 failed → 前端 Alert 显示该错误 |

### DIFF 识别缺陷（漏匹配 / 误 diff）

- [records.py:559](file:///f:/Dev/cndb/src/cndb/plugins/tables/records.py#L559) `find_rows_by_key` 的 `values_list` 是原始值：CSV `"2024-01-15"` 字符串对 DateTime 物理列做 SQL 等值比较不命中 → **误判为新增（产生重复行）**。
- 即使 SQL 命中，`exact_map` 的 key tuple 来自库返回类型（date/datetime 对象），文件侧 tuple 是字符串 → `exact_map.get(key_tup)` 不命中 → 仍归为新增。
- [importer.py:504](file:///f:/Dev/cndb/src/cndb/plugins/tables/importer.py#L504-L525) `_values_equal` 无日期归一比较 → 已有行被误报字段级 diff（并把 datetime 带进报告，与 Bug 同源）。

### 可复用资产

- `RowValidator.validate_row` 已产出 `r.normalized`（经 `field_types.validate_value` 归一化，keyed by db_column_name）——正是"导入解析能力"的复用点。
- [column_profiler.py](file:///f:/Dev/cndb/src/cndb/plugins/tables/column_profiler.py) `profile_columns` 已产出每列 `unique_count`/`null_ratio`/`inferred_type` —— 参考列文件侧指标直接复用。
- `DateFieldType.validate_value` 返回 `date` 对象、`DateTimeFieldType` 返回 `datetime` 对象（[types.py:253/293](file:///f:/Dev/cndb/src/cndb/plugins/tables/field_types/types.py#L253-L315)），与库侧反序列化类型一致，归一后可比较。

## Proposed Changes

### 1. 新模块 `src/cndb/plugins/tables/match_key_advisor.py` — 参考列推荐

- `recommend_match_keys(engine, table, rows, file_columns, column_profiles, *, field_mapping=None) -> list[dict]`
- 候选 = `table.active_fields()`；**禁用类型**：`link`/`attachment`/`multiselect`/`json`，disabled=True，reason="该字段类型不适合做参考列"。
- 文件侧指标：`field_mapping`（None 时文件列名==字段名）对齐 `column_profiles` 取 `unique_count`/`null_ratio`，算文件侧唯一率 = unique_count / 非空数。
- 表侧指标：单条聚合 SQL（`COUNT(*)`, `COUNT(col)`, `COUNT(DISTINCT col)` … WHERE `_trashed=0`），一次查所有候选列；表空时跳过表侧评估，reason 标注"表内暂无数据，仅按文件侧评估"。
- `score`（0~1）= 0.6×两侧唯一率最小值 + 0.4×两侧非空率最小值。
- `recommended = 类型允许 且 score ≥ 0.9 且 两侧唯一率 ≥ 0.99`；不推荐但类型允许的项不禁用（可选），仅全空列（文件或表侧空值率≥1）追加 disabled + reason。
- 返回项：`{field, field_type, score, recommended, disabled, reason, stats: {file_unique_ratio, file_null_ratio, table_unique_ratio, table_null_ratio, table_rows}}` —— 全标量，天然 JSON 安全。

### 2. `diff_reporter.py` — JSON 安全化 + 新报告字段

- 新增模块级 `_json_safe(obj)` 递归清洗：`datetime/date/time → isoformat()`、`Decimal → float`、`bytes → decode(errors="replace")`、`tuple/set → list`，其余原样。
- `DiffReporter.build()` 增加可选参数 `match_key_recommendations`，写入报告键 `match_key_recommendations`；**返回前整体套 `_json_safe`** —— 单点覆盖 analyze/reanalyze/execute 三条链路。

### 3. `importer.py` — 匹配与 diff 用归一化值（识别增强）

- `_build_upsert_result`：为每行构造 `norm_by_name = {f.name: r.normalized[f.db_column_name] for f in active_fields if f.db_column_name in r.normalized}`（缺失回退 `r.values`）：
  - 传给 `find_rows_by_key` 的 `values_list` 用归一化替换后的 dict（keyed by field name，签名不变）；
  - `match_key_values` / `field_diffs.new` / `field_sample` 取归一化值优先。
- **落库路径不动**：`to_import`/`new_rows`/`update_rows` 仍用 `r.values`（`bulk_create`/`bulk_update_rows` 内部有 `_normalize_values`），风险最小。
- `_values_equal` 增强：一侧为 `date/datetime` 时，将另一侧字符串尝试按 ISO 解析后比较；`date vs datetime` 转 date 比较；布尔与数字字符串归一比较保留现状。

### 4. `importer.py` — analyze 接线

- `analyze()` 在 `profile_columns` 之后调用 `recommend_match_keys`，结果经 `DiffReporter.build(..., match_key_recommendations=...)` 进报告（reanalyze 复用同一 analyze，自动生效）。

### 5. `import_tasks.py` — dumps 兜底

- 三处 `json.dumps(..., ensure_ascii=False)` 增加 `default=str`（纵深防御；正常路径已被 `_json_safe` 覆盖）。

### 6. 前端 `ImportExportDialog.tsx` — 参考列推荐 UI

- `renderDiffControls` 读取 `report.match_key_recommendations`（旧任务无此键时回退现状）：
  - `recommended` 项 label 加 `★` + 绿色 Tag「推荐」；
  - `disabled` 项 option `disabled: true`，label 灰显并后缀原因（Tooltip 展示完整 reason）；
  - 提示文案补充："灰色选项不适合做参考列，悬停查看原因"。
- **不自动选中推荐列**（保持用户显式选择语义，待用户复核）。
- 不改 `handleRunDiff`/`confirmImport` 流程；`types.ts` 无需改动（validation_report 走 any 旁路）。

### 7. 测试

后端（新建 `tests/test_match_key_advisor.py` + 扩展 `tests/test_import_pipeline.py`）：
- **Bug 回归**：构造 xlsx（含日期列、date 字段做参考列、已有一行同值数据）→ analyze → `json.dumps(report)` 成功且日期值均为 ISO 字符串。
- **识别增强**：表内已有 date 字段行，CSV 用 `"2024-01-15"` 匹配 → 归为 update；`field_diffs` 无该字段伪差异。
- **推荐逻辑**：唯一列 recommended / 文件侧全空列 disabled+原因 / link 字段 disabled+类型原因 / 文件侧重复列不推荐 / 空表 fallback / 表侧重复列 reason。
- 既有测试零放宽全绿。

前端：`make check` 已含 `frontend-check`（typecheck + lint + test:coverage）兜底；不新增前端单测（改动集中在渲染函数，避免过度设计），辅以手工验证。

## Assumptions & Decisions

1. "已有数据表的导入到当前表" = ImportExportDialog 文件导入流程（match_keys 两阶段）；"从其他表引入字段"（field_ops，schema-only）不在本次范围。
2. 推荐仅在 analyze（含 reanalyze）时计算；表侧统计一次聚合查询，SQLite/PG 兼容（`COUNT(DISTINCT)` 通用）。
3. JSON 安全化放 `DiffReporter.build` 出口单点，`import_tasks` `default=str` 兜底双保险。
4. 不改 `find_rows_by_key` 签名与 `records.py`；无包 facade（`__init__.py`）变更。
5. 参考列可选项仍以目标表字段为主（与现状一致），推荐信息只做增强展示。
6. 新模块职责化命名 `match_key_advisor.py`，与 `column_profiler.py` 同模式。

## Implementation Steps

1. `diff_reporter.py`：`_json_safe` + `match_key_recommendations` 参数（先修 Bug 主链）
2. `importer.py`：归一化值接入匹配/diff + `_values_equal` 增强 + `analyze` 接线
3. 新建 `match_key_advisor.py`
4. `import_tasks.py`：三处 `default=str`
5. 后端测试：`tests/test_match_key_advisor.py` 新建 + `tests/test_import_pipeline.py` 扩展
6. 前端 `ImportExportDialog.tsx` 推荐 UI
7. 全量回归 + `make check`

## Verification

```powershell
# 1. 新增测试
uv run pytest tests/test_match_key_advisor.py tests/test_import_pipeline.py -v
# 2. 导入链路回归（不放宽断言）
uv run pytest tests/test_import_pipeline.py tests/test_import_async.py tests/test_column_profiler.py -x
# 3. 全套门禁（lint + typecheck + frontend-check + cov 95%）
make check
```

验收标准：
- xlsx 日期列 + date 参考列导入 analyze 不再报 "Object of type datetime is not JSON serializable"，报告内日期为 ISO 字符串
- CSV 日期字符串能正确匹配库内日期行（update 而非误判新增），无伪字段级 diff
- 前端参考列下拉：推荐项带 ★ 标识，不推荐项禁用并可悬停查看原因
- `make check` 全绿（本地通过 `make check` 后方可提交）
