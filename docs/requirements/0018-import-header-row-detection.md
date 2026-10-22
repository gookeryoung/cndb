# 需求卡片：导入表头行自动识别（含概率提示与人工改选）

- 编号：0018（与 ADR `docs/adr/0018-import-header-row-detection.md` 同号）
- 来源 / 提出人：产品需求（用户口述）
- 日期：2026-10-22
- 关联 ADR：`docs/adr/0018-import-header-row-detection.md`（Implemented）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 导入数据表，需要实现自动识别表头所在行，以兼容导入表有顶部合并行的情况，并提示用户识别结果和对应概率。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 导入数据表 | **两个导入入口都覆盖**：① 工作区「导入数据表」（上传文件新建表）；② 已有表「导入 / 导出 → 导入」（向已有表追加 / 更新）。两处解析链路都必须走同一表头识别入口 | `tables/services/transfer`、`tables/services/importing`、`tables/routers/{import_csv,bulk_import}` | 两组接口用例：标题行文件均能正确识别表头并导入 |
| C2 | 自动识别表头所在行 | CSV / TSV / XLSX 解析前先对前 20 个非空行打分，返回表头行号（1 基），不再固定取第一行 | `transfer/header_detect.py`、`transfer/spreadsheet.py`、`importing/importer.py` | 判定层单测：常规首行为表头、标题行后移、多行标题、全文本表、无表头表格 |
| C3 | 以兼容导入表有顶部合并行的情况 | 顶部跨列合并标题行（值只写在 A1、其余为空）必须被识别为标题行并跳过；同时**不能**把表头行本身的空列误判成标题（空列名仍按既有结构守卫报错） | `transfer/header_detect.py` | XLSX 真实合并单元格用例 + 空列名守卫回归 |
| C4 | 提示用户识别结果 | analyze 接口返回 `header_detection`（识别行号、跳过行数、中文提示、候选列表）；前端两个入口都展示提示条与「表头行」下拉 | `routers/import_csv.py`、`routers/bulk_import.py`、`frontend/.../FileImportPreview.tsx`、`.../ImportPanel.tsx` | 接口断言 + 前端单测：提示条文案、候选下拉、JSON 不展示 |
| C5 | 对应概率 | 识别结果附 `confidence`（0~1，softmax 归一的相对概率并按绝对合理性校准）；低置信度（<0.6）标记 `requires_review` 并提示人工确认；概率必须与最终采用行一致 | `transfer/header_detect.py` | 判定层单测（置信度排序 / 低置信标记 / 候选与最优一致） |
| C6 | 提示用户识别结果（可纠正） | 用户改选表头行后重新分析并以新行切分；新建表导入时把选择传给建表接口，已有表导入在 reanalyze / confirm 阶段把 `header_row` 写入 `validation_report`（analyze→execute 载体），保证预览与落库同一口径 | `import_csv.py`、`bulk_import.py`、`importing/import_tasks.py` | 接口用例：显式 `header_row` 覆盖、reanalyze / confirm 覆盖后行数变化 |
| C7 | 自动识别表头所在行 | JSON 对象数组没有表头概念：不进入识别，`header_detection` 恒为 `null`，行为与现状一致 | `spreadsheet.py`、`importer.py` | JSON analyze 用例断言 `header_detection is None` |
| C8 | 导入数据表 | 识别只读文件前部（≤20 个非空行），大文件（≤20 万行）仍保持有界流式读取，不因识别引入全量物化 | `transfer/header_detect.py`、`transfer/xlsx_rows.py` | 既有规模/流式回归用例全绿 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 新建表解析固定首行为表头 | `src/cndb/plugins/tables/services/transfer/spreadsheet.py` | `_parse_xlsx_bytes` / `_parse_delimited_text` |
| 2 | 已有表导入解析固定首行为表头 | `src/cndb/plugins/tables/services/importing/importer.py` | `_parse_csv` / `_parse_xlsx` |
| 3 | 新建表 analyze / create 端点 | `src/cndb/plugins/tables/routers/import_csv.py` | 无 header_row 参数 |
| 4 | 已有表 analyze / reanalyze / confirm 端点 | `src/cndb/plugins/tables/routers/bulk_import.py` | 无 header_row 参数 |
| 5 | 导入任务模型 | `src/cndb/plugins/tables/models.py`（ImportTask.validation_report） | 报告已持久化 analyze 结果，可直接承载「本次采用的行号」，无需新增列 |
| 6 | 新建表预览弹窗 | `frontend/src/pages/import-export/FileImportPreview.tsx` | 直接展示列与样本 |
| 7 | 已有表导入面板 | `frontend/src/pages/import-export/ImportExportDialog/ImportPanel.tsx` | 直接展示 diff 报告 |
| 8 | 表头结构守卫 | `transfer/spreadsheet.py`（`_validate_*_header`） | 空列名 / 重复列名报错口径必须保持 |

## 未决问题（2026-10-22 已与需求方确认）

- [x] 覆盖入口 → **两个入口都覆盖**（新建表 + 已有表导入）。
- [x] 「顶部合并行」形态 → 顶部标题行（跨列合并，值只落 A1）与多行标题都跳过。
- [x] 概率口径 → softmax 相对概率 + 绝对合理性校准，展示百分比；低置信度提示人工确认。
- [x] 用户能否纠正 → 能：展示候选行下拉，改选后重新分析并沿用该行落库。
- [x] JSON 导入 → 无表头概念，不参与识别。

## 卡点

无。
