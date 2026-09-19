# 提高数据表导入时的转换识别能力 — 开发计划

## Summary

提升 CSV/XLSX/JSON 导入时字段类型转换识别能力，覆盖两端：

1. **推断层**（`transfer.py`）：修复科学计数法 Bug，增强日期/数字/百分比/布尔/JSON 字符串识别，新增非法日期拦截；
2. **落库校验层**（`field_types/types.py`）：`validate_value` 值域与推断值域对齐（当前 `percentage`/`date`/`datetime` 推断出的多数格式导入时直接失败，`boolean` 中文值静默存 False）——这是本次最关键的脱节问题。

配套 ≥40 组参数化测试矩阵 + `examples/datasets/工作区-低质量数据/` 新增 4 个 CSV 做端到端 seed 验证。

## Current State Analysis

### 架构链路（已探明）

```
文件 → parse_file_to_rows/decode_bytes_auto/sniff_csv_delimiter   （解析层 transfer.py）
     → analyze_csv_columns / analyze_json_columns                 （推断层 transfer.py，表驱动检查器）
     → create_table_from_* → DataField(field_type=推断结果)
     → import_rows_from_* → rec.bulk_create → _normalize_values → ft.validate_value（落库转换 types.py）
```

- 推断检查器优先级（[transfer.py:269](file:///f:/Dev/cndb/src/cndb/plugins/tables/transfer.py#L269)）：boolean → email → url → percentage → datetime → date → phone → long_integer(text) → number → float → text
- 推断与落库是**两层独立逻辑**，无共享格式清单 —— 脱节根因

### 已确认缺陷清单

| # | 缺陷 | 位置 | 后果 |
|---|------|------|------|
| B1 | 科学计数法 `1.5e10`：点被当千分位删除 → `15e10`（**值错误 10 倍**） | [transfer.py:194-202](file:///f:/Dev/cndb/src/cndb/plugins/tables/transfer.py#L194-L202) `_normalize_numeric` | 推断为 float 但值错 |
| B2 | 非法日期 `2024-02-30`/`2024-13-01` 被 `_GENERIC_DATE_RE` 命中 → date 字段 | transfer.py 推断 | 导入行校验报错 |
| B3 | percentage 推断 `85%` → `PercentageFieldType.validate_value("85%")` → `float("85%")` raise | [types.py:506-515](file:///f:/Dev/cndb/src/cndb/plugins/tables/field_types/types.py#L506-L515) | **自动建表整体失败**（bulk_create raise → cleanup 整表回滚） |
| B4 | date 推断支持 `2024年1月1日`/`2024.1.15`/`1/15/2024` 等，但 `DateFieldType.validate_value` 仅接受 `%Y-%m-%d`/`%Y/%m/%d` | [types.py:184-200](file:///f:/Dev/cndb/src/cndb/plugins/tables/field_types/types.py#L184-L200) | 中文/点分隔/美式日期导入**整体失败** |
| B5 | datetime 推断支持微秒/时区变体，validate 仅 4 种无微秒格式 | [types.py:231](file:///f:/Dev/cndb/src/cndb/plugins/tables/field_types/types.py#L231) | 变体格式导入失败 |
| B6 | boolean 推断值域 `是/否/真/…`，但 `BooleanFieldType.validate_value` 仅认 `true/yes/1/on` → "是" **静默存 False** | [types.py:138](file:///f:/Dev/cndb/src/cndb/plugins/tables/field_types/types.py#L138) | 数据静默损坏 |
| B7 | 识别缺口：紧凑日期 `20240115`、英文月名 `Jan 15, 2024`、斜杠+时间 `2024/1/15 10:30`、会计负数 `(1,234)`、全角数字 `１２３`、全角％ `85.5％`、布尔 `真/假`/`Y/N`/`√/×`、JSON 字符串 `{"a":1}` | transfer.py 推断 | 全部落 text |

### 约束与既有资产

- 现有测试不可放宽：`tests/test_transfer_csv_infer.py`、`tests/test_column_profiler.py`（`_try_float("1.234,56")==1.23456` 锁定了简单行为，**不改 `_try_float`**）
- datasets CSV 由 `seed.py` 按 `工作区-` 前缀建工作区、文件名建表（utf-8-sig 读取）
- 覆盖率门禁 95%+（`make check` = lint + typecheck + cov）
- 批量导入单批上限 200 行、`percentage` 存储约定为 0~1 比例值

## Proposed Changes

### 1. 推断层增强 — `src/cndb/plugins/tables/transfer.py`

**(a) 修 B1 科学计数法**：`_normalize_numeric` 入口处短路检测 `^[+-]?\d*\.?\d+[eE][+-]?\d+$`，命中直接小写化返回原文（`1.5e10` → `1.5e10`，不再走千分位逻辑）。

**(b) 修 B2 非法日期**：新增 `_is_valid_date(y: int, m: int, d: int) -> bool`（用 `datetime.date` 构造校验）。`_ISO_DATE_RE`/`_CN_DATE_RE`/`_GENERIC_DATE_RE` 及新增紧凑日期命中后必须通过合法性复核，非法 → 继续后续检查（最终 text）。

**(c) 日期识别增强**（新正则 + 检查器表插入 date 组）：
- `_COMPACT_DATE_RE`：`^\d{8}$`，拆解 yyyymmdd 后走 `(b)` 合法性校验（月 01-12、日合法，非法自动回落 number）
- `_EN_DATE_RE`：`Jan 15, 2024` / `15 Jan 2024`（12 个月英文缩写+全称映射表）
- `_GENERIC_DATETIME_RE`：`2024/1/15 10:30(:ss)`（斜杠日期+时间 → datetime）

**(d) 数字归一增强**（`_normalize_numeric` 内）：
- 会计负数：整体 `(...)` 包裹且内部合法 → 取负
- 全角归一：`０-９`、`．`、`－`、`＋`、`％` → 半角后再走既有逻辑

**(e) 百分比**：`_check_percentage` 先做全角 `％`→`%` 替换。

**(f) 布尔值域扩展**：提取模块级常量 `_BOOLEAN_TRUE = {...}` / `_BOOLEAN_FALSE = {...}`（含 `true/yes/1/on/是/真/对/y/t/√` 与 `false/no/0/off/否/假/错/n/f/×`），`_is_boolean` 与 `_is_select_candidate` 两处重复定义改为共用（消除现有重复）。

**(g) JSON 字符串**：`_infer_single_value` 检查器表在 email 之后插入 json 检查（`{`/`[` 开头且 `json.loads` 成功 → `json`）。

**新增公开辅助** `normalize_value_for_inference` 不引入 —— 全部内部函数，`__all__` 不变。

### 2. 落库校验层对齐 — `src/cndb/plugins/tables/field_types/types.py`

**(a) `DateFieldType.validate_value`**：格式清单扩展为 `%Y-%m-%d`、`%Y/%m/%d`、`%Y.%m.%d`、`%Y年%m月%d日`、`%Y%m%d`、`%m/%d/%Y`、`%b %d, %Y`、`%d %b %Y`（与推断层一一对应；strptime 的 `%m/%d` 接受无前导零）。

**(b) `DateTimeFieldType.validate_value`**：现有 4 格式 + 微秒变体 `%Y-%m-%d %H:%M:%S.%f`、`%Y-%m-%dT%H:%M:%S.%f` + 斜杠日期时间 `%Y/%m/%d %H:%M`、`%Y/%m/%d %H:%M:%S`。

**(c) `PercentageFieldType.validate_value`**：字符串以 `%`/`％` 结尾 → 剥离后 `float` 再 `/100` 返回；纯数字维持 `0<=v<=1` 现状（无 % 的 0.85 列不会被推断为 percentage，两侧行为自洽）。

**(d) `BooleanFieldType.validate_value`**：字符串 lower+strip 后查 `_TRUE_STRINGS`/`_FALSE_STRINGS` 映射表（与 transfer 的 `_BOOLEAN_*` 值域一致）；未匹配值**维持现状返回 False**（向后兼容，不引入 raise，测试锁定）。

**(e) 年月格式**（`2024年1月`/`2024-01`）：date 字段无法表达"月"语义，**不识别、保持 text**，测试矩阵锁定该预期防止回归。

### 3. 测试矩阵 ≥40 组 — 新建 `tests/test_transfer_inference_matrix.py`

`INFERENCE_MATRIX: list[tuple[str, list[str], str]]`（组号, 列样本值, 期望 field_type）参数化，走 `analyze_csv_columns` 列级推断（含 select 提升路径）；单值类场景直接断言 `analyze` 结果。分组清单：

| 组 | 场景 | 期望 |
|----|------|------|
| 01-12 | ISO 日期 / ISO datetime / 中文日期 / 斜杠日期 / 美式日期 / 点分隔日期 / **紧凑日期** / **非法日期→text** / **非法月→text** / **斜杠+时间→datetime** / **英文月名(前置)** / **英文月名(后置)** | date/datetime/text |
| 13-22 | 千分位整数 / 欧元小数 / 货币 / 负数 / **科学计数法 1.5e10（值正确性断言）** / 纯指数 1e5 / **会计负数** / **全角数字** / 前导零长编号→text / 15 位以上→text | number/float/text |
| 23-26 | 整数% / 小数% / 负% / **全角％** | percentage |
| 27-32 | 是/否列 / true/false 列 / **真/假列** / **Y/N 列** / **√/×列** / on/off 列 | boolean |
| 33-36 | 中国手机号 / +86 手机号 / email / url | phone/email/url |
| 37-38 | **JSON 对象列 `{"a":1}`** / **JSON 数组列 `[1,2]`** | json |
| 39-40 | 低基数 select 提升（含 options 断言）/ 高基数→text | select/text |
| 41-42 | 混合列主导类型（9 数字+1 文本→number）/ 全空列→text | number/text |
| 43-44 | GBK 编码 bytes 解码 / 分号分隔符嗅探 | — |

**落库对齐用例**（同文件，复用 `csv_workspace` fixture 模式）：含 `85%` 列、中文日期列、`是/否` 列、`{"a":1}` 列的 CSV 走 `create_table_from_csv` **端到端导入成功**且值正确（85% → 0.85；是 → True；修复前 B3/B4/B6 会失败）——这是本次修复的直接验收。

### 4. datasets 补充 — `examples/datasets/工作区-低质量数据/` 新增 4 个 CSV（utf-8-sig）

| 文件 | 内容（每列一个场景） |
|------|---------------------|
| `16-日期格式大全.csv` | ISO/中文/斜杠/点分隔/紧凑/美式/英文月名/非法日期 8 列 × 6 行 |
| `17-数字格式大全.csv` | 千分位/欧元/货币/科学计数法/会计负数/全角数字/前导零编号/15位长号 8 列 × 6 行 |
| `18-布尔与百分比.csv` | 是/否、true/false、真/假、Y/N、85%、85.5%、全角％、负% 8 列 × 6 行 |
| `19-特殊值杂项.csv` | JSON 串、email、url、手机号、低基数状态、高基数文本、混合主导、空值混合 8 列 × 6 行 |

验证方式：`uv run python -m cndb.runner seed`（或项目 seed 命令）后确认 4 张新表建成、行数正确、字段类型符合预期。

## Assumptions & Decisions

1. **紧凑日期 8 位数字存在误判风险**（订单号 `20241231` 类）：接受 —— 月/日合法性校验过滤绝大多数编号（`20240001` 月=00 → 回落 number），多数投票机制兜底；测试锁定。
2. **年月格式不识别为 date**（无法表达日语义），保持 text。
3. **boolean 未匹配值维持 False** 不改为 raise（向后兼容现有行为与测试）。
4. **不改 `_try_float`**（column_profiler 测试锁定其简单行为）；不动 `_coerce_long_numeric_to_text`、编码检测、分隔符嗅探（已完善）。
5. **multiselect 识别不在本次范围**（逗号分隔列表误判风险高，记为遗留）。
6. 新增格式清单在推断层与 validate 层各自实现但由测试矩阵双向锁定（不做跨模块常量共享，避免 transfer ↔ field_types 循环导入）。
7. 现有测试若因新识别能力产生冲突（如某现有用例样本恰好命中新格式），以**调整用例样本**（而非放宽断言）方式处理，并逐个说明。

## Implementation Steps

1. `transfer.py`：按 1(a)→(g) 顺序实现（先修 Bug 后增强），每步跑 `pytest tests/test_transfer_csv_infer.py` 快速回归
2. `types.py`：按 2(a)→(d) 实现 validate_value 值域扩展
3. 新建 `tests/test_transfer_inference_matrix.py`（≥40 组矩阵 + 端到端对齐用例）
4. 新增 4 个 datasets CSV；seed 冒烟验证建表
5. 全量回归 + `make check`（lint + typecheck + cov 全绿）

## Verification

```powershell
# 1. 新矩阵
uv run pytest tests/test_transfer_inference_matrix.py -v
# 2. 既有导入相关回归（不放宽断言）
uv run pytest tests/test_transfer_csv_infer.py tests/test_column_profiler.py tests/test_import_pipeline.py tests/test_field_types.py tests/test_import_format_encoding.py -x
# 3. datasets seed 冒烟：确认 16~19 号新表建成、类型正确
uv run python -m cndb.runner seed
# 4. 全套门禁
make check
```

验收标准：
- 矩阵 ≥40 组全绿，含科学计数法值正确性、非法日期回落 text、85%→0.85 端到端落库
- 既有测试零放宽全绿；`make check` 三项全绿
- 新 CSV seed 建表成功且字段类型符合矩阵预期
