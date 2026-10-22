# ADR 0018: 导入表头行自动识别（顶部合并行兼容 + 概率提示 + 人工改选）

Status: Implemented
Date: 2026-10-22
Related: `plugins/tables/services/transfer/header_detect.py`、`plugins/tables/services/transfer/spreadsheet.py`、`plugins/tables/services/importing/importer.py`、`plugins/tables/services/importing/import_tasks.py`、`plugins/tables/routers/import_csv.py`、`plugins/tables/routers/bulk_import.py`、`frontend/src/pages/import-export/FileImportPreview.tsx`、`frontend/src/pages/import-export/ImportExportDialog/ImportPanel.tsx`
需求卡片: `docs/requirements/0018-import-header-row-detection.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」段落；ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用，不在仓库保留 `Superseded` / `Deprecated` 文档。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 导入数据表 | 新建表链路（`parse_file_to_rows_with_detection` / `create_table_from_file_with_detection`）与已有表链路（`Importer._parse`）共用 `header_detect.detect_header_row`；端点都新增可选 `header_row` 参数。 |
| C2 | 自动识别表头所在行 | `detect_header_row(rows, preferred_index=...)` 对前 20 个非空行打分（覆盖率 / 文本率 / 唯一性 / 与下方数据的类型反差 / 上方行稀疏度），softmax 归一为概率。 |
| C3 | 兼容导入表有顶部合并行 | 合并标题行只有 A1 有值 → 低覆盖率、高空洞率、`title_penalty`，且下方表头行获得 `above_bonus`；双重信号保证跳过标题行。同时「文件最后一个非空行」不得被选为表头，避免表头本身有空列时误选数据行、绕过空列名守卫。 |
| C4 | 提示用户识别结果 | 两个 analyze 入口返回 `header_detection`（`row` / `confidence` / `requires_review` / `skipped_rows` / `message` / `candidates`）；前端提示条 + 候选下拉。 |
| C5 | 对应概率 | `confidence` = 概率分布中该行的 softmax 概率，再按绝对合理性封顶（无后续数据行 ≤0.55、单列 ≤0.7、整行数值/日期 ≤0.45、≤0.99）；`requires_review = confidence < 0.6`。候选里最优行的概率与最终 `confidence` 一致。 |
| C6 | 提示用户识别结果（可纠正） | 新建表：`header_row` 走 Form 参数贯穿 analyze / create；已有表：analyze 自动识别结果写入 `ImportTask.validation_report`（既有 analyze→execute 载体），reanalyze / confirm 可覆盖，execute 从报告读取该行解析。 |
| C7 | 自动识别表头所在行 | JSON 格式跳过识别，`header_detection = null`、`header_row = null`（JSON 对象数组无表头概念）。 |
| C8 | 导入数据表 | 识别只缓冲前 20 个非空行（`HEADER_SCAN_ROWS`），之后继续流式消费，不改变 20 万行上限与 WPS 虚假范围防护。 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 新建表 XLSX 解析把第一个非空行固定当表头 | `plugins/tables/services/transfer/spreadsheet.py`（`_parse_xlsx_bytes`） | 顶部合并标题行会被当表头 → 空列名报错或整表列名错误 | 确认（C2/C3 主缺口） |
| 2 | 新建表 CSV/TSV 解析用 `csv.DictReader`，首行即表头 | `spreadsheet.py`（`_parse_delimited_text`） | 同上 | 确认 |
| 3 | 已有表导入解析（CSV / XLSX）同样首行即表头 | `plugins/tables/services/importing/importer.py`（`_parse_csv` / `_parse_xlsx`） | 两个入口口径分裂，任一处都要修 | 确认（C1） |
| 4 | analyze 返回列推断与样本，无表头元信息 | `plugins/tables/routers/import_csv.py`、`routers/bulk_import.py` | 前端无法提示识别结果 | 新增（C4/C5） |
| 5 | 导入任务已有 `validation_report`（analyze 产物，持久化到任务） | `plugins/tables/models.py`（`ImportTask.validation_report`） | 可作为「本次采用哪一行解析」的跨阶段载体，无需新增列 | 复用（C6） |
| 6 | 空列名 / 重复列名有明确结构守卫 | `spreadsheet.py`（`_validate_csv_structure` / `_validate_xlsx_header`） | 识别结果必须继续受守卫约束，不能靠误选数据行绕过 | 确认（C3） |
| 7 | XLSX 有界流式读取（跳过空行、真实行号） | `transfer/xlsx_rows.py` | 识别可复用 `(sheet_row, values)` 流，不需要另开 workbook | 确认（C8） |
| 8 | 前端两个导入入口都直接消费 analyze 结果 | `frontend/src/pages/import-export/FileImportPreview.tsx`、`.../ImportExportDialog/ImportPanel.tsx` | 需加提示条 / 下拉 / 改选后重算 | 确认（C4/C6） |
| 9 | 已有表导入两阶段 analyze → confirm，任务按 phase 后台执行 | `importing/import_tasks.py` | 表头行必须随任务持久化，reanalyze / confirm 能改 | 确认（C6，复用 validation_report） |

**核心缺陷（需求要补的）**：解析层把「文件第一个非空行」硬编码为表头，既没有「哪一行才是表头」的判定，也没有把判定结果与概率暴露给用户；顶部带合并标题行的表因此不可导入。

设计目标（不变量）：

- **I1 判定单入口**：新建表与已有表导入必须复用 `detect_header_row`，禁止各自实现启发式。
- **I2 结构守卫不退化**：识别不能把「表头有空洞」的文件洗成「数据行当表头」；空列名 / 重复列名 / 行溢出仍按原文报错。
- **I3 预览与落库同口径**：analyze 采用的行号必须原样传到 execute（已有表经 `ImportTask.header_row` 落库；新建表经 Form 参数传递）。
- **I4 概率可解释**：`confidence` 与候选概率同源（同一 softmax），低置信度必须显式建议人工确认。
- **I5 有界成本**：识别只看前 20 个非空行，不整表物化。

## Decision

### 1. 数据模型

**无新表、无新列、无迁移**。表头行复用 `ImportTask.validation_report`（analyze 阶段已经持久化的报告）：

- analyze 阶段把自动识别结果写入 `report["header_row"]`（同时带 `report["header_detection"]` 供前端提示）；
- execute 阶段从 `validation_report` 读取 `header_row` 并按同一行解析，保证预览与实际入库一致；
- reanalyze 通过种子报告把用户改选行传给后台任务，confirm 把覆盖行写回报告；
- JSON 导入与历史任务报告里没有 `header_row`（execute 回退为自动识别，行为兼容）。

这样复用了既有 analyze→execute 载体，避免新增列与迁移，也不影响历史任务（旧报告无该键即自动识别）。

### 2. 判定算法（唯一入口）

```python
# transfer/header_detect.py
@dataclass(frozen=True)
class HeaderDetection:
    index: int              # 0 基（非空行序列）
    confidence: float       # 0~1
    requires_review: bool
    candidates: list[HeaderCandidate]

def detect_header_row(
    rows: Sequence[Sequence[Any]],
    *,
    max_scan: int = HEADER_SCAN_ROWS,     # 20
    preferred_index: int | None = None,   # 用户指定行优先
) -> HeaderDetection | None
```

打分项（每行独立计算，再 softmax）：

```
coverage        非空单元格 / 有效列宽     （表头通常铺满各列）
text_ratio      文本型单元格占比           （表头几乎全是文本）
unique_ratio    去重后占比                 （数据行常有重复值）
short_ratio     长度 ≤40 的占比            （表头简短）
contrast        与下方 ≤5 行的类型反差     （表头文本 vs 数据数值/日期）
above_bonus     上方行更稀疏 → 更像表头
title_penalty   本行稀疏（覆盖率 ≤0.4）而下一行密（≥0.75）→ 标题/合并行
hole_ratio      非空单元格之间的空洞占比
value_ratio     数值/日期占比（越高越不像表头）
no_data_below   无后续数据行
+ 首行先验      常规文件表头在第一行（标题行已被 title_penalty 压掉）
− 末行先验      文件最后一个非空行不可能是表头（单行文件除外）
```

概率与校准：

```
probabilities = softmax(scores / 0.5)
confidence = probabilities[best]
if 无后续数据行: confidence = min(confidence, 0.55)
if 有效列宽 < 2: confidence = min(confidence, 0.70)
if 文本率 <0.5 且数值率 >0.5: confidence = min(confidence, 0.45)
confidence = clamp(0, 0.99)
requires_review = confidence < 0.6 或无后续数据行
```

坐标口径（唯一）：`header_row` = **文件中非空行的 1 基序号**（`read_xlsx_rows` 已跳过空行；无空行时等于 Excel 行号）。JSON 无该坐标。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /{wid}/import-file/analyze` | form 新增可选 `header_row`（1 基）；响应新增 `header_detection`（null 表示 JSON）与 `header_row` |
| `POST /{wid}/import-file` | form 新增可选 `header_row`；响应新增 `header_detection` / `header_row` |
| `POST /{wid}/tables/{tid}/import/analyze` | `validation_report` 新增 `header_detection` / `header_row`（自动识别） |
| `POST /{wid}/tables/{tid}/import/{task_id}/reanalyze` | query 新增可选 `header_row`（改选后重算） |
| `POST /{wid}/tables/{tid}/import/{task_id}/confirm` | query 新增可选 `header_row`（确认时覆盖） |

`header_detection` 载荷：

```json
{
  "row": 2,
  "confidence": 0.93,
  "requires_review": false,
  "skipped_rows": 1,
  "message": "已自动识别第 2 行为表头（置信度 93%，已跳过上方 1 行标题/合并行）",
  "candidates": [{"row": 2, "confidence": 0.93, "values": ["产品", "价格", "库存"]}]
}
```

### 4. 边界与例外

1. 用户指定的行号：`0` / 负数 → 400「从 1 开始」；超过文件非空行数 → 400；≥20（超出扫描窗口）→ 400 并提示只在前 20 个非空行内识别 / 指定。
2. 用户指定的行若为完全空行 → 400。识别算法本身已跳过空行，正常候选不会为空。
3. 顶部只有标题、没有任何数据行：可识别但概率封顶 0.55 并建议人工确认。
4. 表头本身存在空列：识别仍停在表头行（末行先验阻止误选数据行），由既有空列名守卫报 400，不静默改名。
5. 多级表头（两行表头）：识别取「更密、更像表头」的下一行，上一行被跳过；不合并两级列名（本轮不做，需求未要求）。
6. JSON 导入：`header_detection = null`，不改变任何现有行为。
7. 大文件 / WPS 虚假范围：识别只缓冲 20 行，其余继续流式。

### 5. 迁移

无。表头行写在既有 `validation_report` 文本列中，零 DDL、零存量迁移；历史任务无该键时回退自动识别。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 类型 | `frontend/src/api/types/files.ts`、`types/imports.ts` | 新增 `HeaderDetection` / `HeaderDetectionCandidate`；analyze / import 结果与 `ValidationReport` 增字段 |
| API 封装 | `frontend/src/api/importExport.ts` | `analyzeFile` / `createFromFile` / `previewAnalyze` / `reanalyzeImport` / `confirmImport` 追加可选 `headerRow` |
| 新建表预览 | `frontend/src/pages/import-export/FileImportPreview.tsx` | 提示条（文案 + 置信度 Tag，低置信 warning）+ 候选下拉；改选后重新 analyze 并刷新字段 / 样本；建表传 `header_row` |
| 已有表导入 | `frontend/src/pages/import-export/ImportExportDialog/ImportPanel.tsx` | 预览区顶部提示条 + 候选下拉；改选触发 reanalyze；确认导入传 `header_row` |

### 7. 测试清单

**判定层（单测）**：`tests/test_import_header_detection.py`

- 常规首行表头（高置信、无人工确认）
- 顶部合并标题行 / 多行标题 → 跳过并识别正确行
- 全文本表格仍保持较高置信度；纯数值无表头 → 低置信 + `requires_review`
- 单行文件概率封顶；空输入返回 None
- `preferred_index` 覆盖与越界报错；候选数量上限与概率降序；最优候选概率 = 最终 confidence

**解析层**：CSV / XLSX 标题行跳过、显式 `header_row` 生效、越界 / 0 / 超扫描窗口报错、JSON 无识别、旧三返回值入口兼容、`Importer` 两条解析路径同口径。

**接口层**：新建表 analyze / create（自动识别、显式覆盖、非法行号、JSON null）；已有表 analyze（报告含识别与概率）、confirm（按识别行导入）、reanalyze（改行后报告更新）、confirm 覆盖行号、非法行号 400。

**迁移**：无新迁移（表头行走 validation_report，不做 DDL）。

**前端（单测）**：`FileImportPreview.test.tsx`、`ImportPanel.test.tsx` 覆盖提示条与置信度、候选改选触发重新分析 / reanalyze、建表与确认带 `header_row`、`requires_review` warning、JSON(null) 不渲染。

**e2e**：不新增（两入口 UI 已有单测覆盖；识别算法由后端判定层与接口层锁定）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 判定入口 `header_detect.py` + 判定层单测 | 低（纯函数，无 IO） |
| **P1** | 解析链路接入（新建表 / 已有表）+ `ImportTask.header_row` 迁移 + 任务执行按行解析 | 中（改动共用解析层，需既有结构守卫回归） |
| **P2** | 端点参数与响应、前端两个入口提示 / 改选、接口 + 前端测试 | 中（跨前后端契约） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 表头识别放在哪一层 | 新建表与已有表共用一个纯函数 `transfer/header_detect.py` | 两入口解析实现本来就重复（`spreadsheet` / `importer`），再各写一套必然漂移（I1） | 只改 XLSX 合并单元格解析 / 只改新表入口：都不满足 C1 | `transfer/header_detect.py` |
| D2 | 概率怎么定义与展示 | softmax 相对概率 + 绝对合理性校准，对外显示百分比，<0.6 建议人工确认 | 单一分值无法表达「多个候选都像表头」的歧义；校准避免「无表头纯数值表」被展示成 99% | 固定阈值打分（无概率，无法满足 C5）；LLM/OCR 识别（离线、成本与确定性不可接受） | `header_detect.py`（`_softmax` / 校准段） |
| D3 | 行号坐标 | 文件非空行的 1 基序号，与 `read_xlsx_rows` 的跳过空行语义一致 | 前后端与落库共用同一坐标；无空行时即 Excel 行号 | 物理 sheet_row（CSV 无对应概念，两格式口径分裂） | `header_detect.py`、`spreadsheet.py` |
| D4 | 已有表导入如何跨阶段传递表头行 | 复用 `ImportTask.validation_report`：analyze 写入 `header_row`，execute 读取；reanalyze 用种子报告、confirm 回写覆盖 | execute 在独立线程 / 独立 Session 重新解析，必须持久化才能保证 I3；报告本就是 analyze→execute 的既定载体 | 新增 `header_row` 列 + alembic 迁移（与并行开发中的迁移产生多 head，收益仅为存储位置更"纯"）；仅存进程内缓存（重启丢失） | `import_tasks.py`（`_header_row_from_report`）、`routers/bulk_import.py` |
| D5 | 识别是否会绕过空列名守卫 | 不会：文件最后一个非空行禁止作为表头；用户显式指定行仍走原守卫 | 否则「表头有空洞」的文件会静默把数据行当表头，列名从业务名退化为数据值（I2） | 自动填充空列名为 `col_N`（静默改名，违背既有守卫决策） | `header_detect.py`（末行先验）、`spreadsheet.py` |
| D6 | 多级表头 | 本轮只识别「表头所在行」，取更密的下一行，上一行跳过；不合并两级列名 | 需求只要求兼容顶部合并行；合并多级表头涉及列名拼接规则与冲突策略，属独立需求 | 两级表头拼名（容易产生 `分类/产品` 这类无依据列名） | — |
| D7 | JSON 导入 | 不参与识别，`header_detection = null` | JSON 对象数组自带键名，无表头行概念（C7） | 给 JSON 造表头元信息（无意义且污染契约） | `spreadsheet.py`、`importer.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：顶部带合并标题行的 Excel/CSV 可直接导入；用户看得到「识别为第几行 + 概率」，并可在两个入口纠正；两入口共用一套判定，口径不再分裂；`ImportTask.header_row` 让预览与落库严格一致。
- **负向**：解析层多一次 20 行打分（O(20×列数)，可忽略）；`ImportTask` 加一列；前端两个组件各多一块状态与请求逻辑。
- **风险与缓解**：启发式在「全文本表格」上概率天然偏低 → 前端以「建议人工确认」而非报错呈现；多级表头只取一行 → 在 ADR 明确边界（D6）；用户指定行超出扫描窗口 → 明确 400 而不是静默忽略。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 表头结构守卫（空列名 / 重复列名） | `_validate_*_header` | 识别不得绕过，守卫继续报错 | 本 ADR I2 |
| XLSX 有界流式读取 | `transfer/xlsx_rows.py` | 复用其非空行流，不新增全量读取 | 本 ADR C8 |
| 导入两阶段（analyze → confirm） | `routers/bulk_import.py` | 表头行作为任务配置持久化，随两阶段流转 | 本 ADR D4 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `plugins/tables/services/transfer/header_detect.py` | `tests/test_import_header_detection.py` | `3162f66b` |
| P1 | 已落地 | `plugins/tables/services/transfer/spreadsheet.py`、`plugins/tables/services/importing/importer.py`、`plugins/tables/services/importing/import_tasks.py` | `tests/test_import_header_detection.py` | `3162f66b` |
| P2 | 已落地 | `plugins/tables/routers/import_csv.py`、`plugins/tables/routers/bulk_import.py`、`frontend/src/pages/import-export/FileImportPreview.tsx`、`frontend/src/pages/import-export/ImportExportDialog/ImportPanel.tsx` | `tests/test_import_header_detection.py`、`frontend/src/pages/import-export/FileImportPreview.test.tsx`、`frontend/src/pages/import-export/ImportExportDialog/ImportPanel.test.tsx` | `3162f66b` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P2 已完成（两个导入入口 + 前端提示 / 改选 + 测试）
- 已完成：P0 判定入口与概率校准；P1 两条解析链路接入 + `validation_report` 跨阶段携带表头行；P2 端点 / 前端 / 判定层·接口层·前端单测
- 下一步：人工评审后按需补 e2e（带合并标题行的真实文件导入）；若后续要做多级表头合并列名，另立 ADR
- 已知坑：`header_row` 坐标是「非空行序号」，无空行时等于 Excel 行号；人工指定行只允许前 20 个非空行；全文本表格概率天然中等（会提示人工确认）属预期
- 最近一次全绿：`make flow` @ `3162f66b`（2026-10-22）
