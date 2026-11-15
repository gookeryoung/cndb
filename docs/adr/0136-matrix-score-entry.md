# ADR 0136: 评分矩阵（矩阵视图内按「对象 × 月份」录入）

Status: Accepted（2026-11-15 人工评审通过）
Date: 2026-11-15
Related: `src/cndb/plugins/tables/routers/records.py`、`src/cndb/plugins/tables/routers/views.py`、`src/cndb/plugins/tables/routers/tables.py`、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/services/core/row_access.py`、`src/cndb/plugins/tables/schemas/models.py`、`frontend/src/pages/grid/views/MatrixView.tsx`、`frontend/src/pages/grid/views/matrixBoard.ts`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`frontend/src/pages/grid/GridPage.tsx`
需求卡片: `docs/requirements/0136-matrix-score-entry.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字）；ADR 不复制第二份。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「评分对象都是固定的」「固定下拉」 | 可编辑矩阵的行轴取**单选字段的完整 options**（`fields?full=1`），不依赖已有行；没有数据的对象也显示 |
| C2 | 「评分和月份需要变化」 | 列轴取视图配置的 `period_start` / `period_end` 月份范围（`YYYY-MM`），逐月生成列；范围上限 24 个月 |
| C3 | 「每次新增单个很慢」 | 单元格内直接输入得分，失焦 / 回车保存；无行时保存自动建行，有行时只更新得分 |
| C4 | 「评分对象固定、月份变化」 | 保持长表：一行 = 对象 × 月份；业务键 =（`row_field`, `month_field` 所在月），不改为宽表 |
| C5 | （写入语义） | 新增 `matrix-upsert`：按业务键 upsert；空值不建行；同键多行 409 拒绝写入并返回行 id |
| C6 | 「按通用逻辑」 | 复用 `create_row` / `update_row` 与 `_dispatch_or_403` / `_row_write_decision` / `_cr_response`；表有行级权限规则时矩阵只读 |
| C7 | （边界） | 仅支持 行=单选、月份=日期、值=数字；范围 ≤24；视图不得配筛选；其他必填字段导致新建失败时 400 说明 |
| C8 | （兼容与验收） | 未配置 `value_field` 的矩阵视图行为完全不变；无新表 / 列 / 迁移；备份不变 |

## Context

现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 矩阵视图是只读卡片，行 / 列均由已有行聚合出来 | `frontend/src/pages/grid/views/MatrixView.tsx`、`matrixBoard.ts` | 对象没有数据就不显示行；新月份没有数据就不显示列，无法先建列再填 | C1/C2 确认 |
| 2 | 矩阵无写入交互，单元格只能点开行详情 | `MatrixView.tsx` | 每个对象每月都要先新增行，正是「每次新增单个很慢」 | C3 确认 |
| 3 | 矩阵视图配置仅 `row_field` / `column_field` / `date_granularity` / `title_field` | `viewOptionSchema.ts`、`routers/views.py` | 没有「评分字段」和「月份范围」概念 | C2/C7 新增 |
| 4 | 记录写入已有双轨分派：直编 / 修改申请 / 403 / 404 | `routers/records.py`（`_dispatch_or_403`、`_row_write_decision`、`_cr_response`） | 矩阵无需另造权限模型，直接复用 | C6 确认 |
| 5 | 按业务键查询只有 `find_rows_by_key`（精确 key tuple） | `services/core/records.py` | 月份可能存的是当月任意一天，精确匹配会漏；需要按「月区间」匹配 | C5/C7 新增 |
| 6 | 表详情没有行级权限状态 | `routers/tables.py`、`schemas/models.py` | 前端无法判断矩阵是否因行级规则而必须只读 | C6 新增 |
| 7 | 非 grid 视图一次最多拉 2000 行，且套用视图筛选 | `frontend/src/pages/grid/useGridData.ts` | 若矩阵套筛选，未加载的已有行会被当成空单元格，编辑后产生重复行 | C5 新增 |

**核心缺陷**：矩阵视图只能表达「已有数据的分组」，不能表达「固定对象 × 固定月份」这张待填评分表；同时平台没有按业务键 upsert 的记录写入口，前端无法安全地「空单元格即新建、有值即更新」。

设计目标（不变量）：

- **I1 同键唯一**：同一（对象, 月份）最多一行；矩阵加载发现重复时单元格只读，写入端点返回 409，不静默更新任意一行。
- **I2 口径一致**：矩阵创建 / 更新复用现有记录写路径的字段校验、默认值、自动编号、修改申请与权限判定，不新增第二套写语义。
- **I3 轴不依赖数据**：行轴来自字段 options，列轴来自视图配置的月份范围；空对象、空月份必须可见。
- **I4 行规则安全**：表配置了行级权限（默认档 `row_filters` 或存在 `RowPermission`）时，非豁免用户矩阵只读，避免「看不到已有行 → 重复建行」与存在性泄露。
- **I5 向后兼容**：未配置 `value_field` 的矩阵视图渲染与行为不变；无迁移、无备份变更。

## Decision

### 1. 数据模型

**无新表、新列、枚举、迁移。**

- 评分数据仍是普通记录，字段类型约定：对象=单选（`select`）、月份=日期（`date`）、得分=数字（`number` / `float` / `percentage`）。
- 视图 `view_options` 新增（仅矩阵视图使用，均为可选）：
  - `value_field: string` —— 评分字段名；配置后矩阵进入「可编辑」形态（是否真的可编辑还取决于权限与行规则）。
  - `period_start: string` —— `YYYY-MM`，列范围起始月。
  - `period_end: string` —— `YYYY-MM`，列范围结束月。
- `TableDetailResponse` 新增只读计算字段 `row_rules_active: bool`：默认档 `row_filters` 非空或该表存在任意 `RowPermission` 时为 `true`。不落库，仅供前端判断矩阵编辑入口。
- 月份统一写为当月 1 日（`YYYY-MM-01`）；读取匹配使用 `[当月1日, 次月1日)` 区间，兼容历史数据里当月任意一天。

### 2. 判定算法（唯一入口）

新增服务函数 `find_month_key_rows(engine, table, row_field, row_value, month_field, month_start, month_end)`（`services/core/records.py`）：

1. 只查 `_trashed = false` 的行；
2. 条件：`row_col = row_value AND month_col >= month_start AND month_col < month_end`；
3. 返回 `row_ids`（按 id 升序）与对应 `value` 列表，调用方据此判定 0 / 1 / N。

新增端点逻辑（`routers/records.py`，注册在 `/{record_id}` 之前）：

1. `get_table_or_404(..., READ)`，字段必须存在且类型符合 C7；
2. 行级规则闸门：`row_rules_active` 且当前用户不满足 `row_filters_bypass` → 403「该表配置了行级权限，评分矩阵不支持录入」；
3. 隐藏字段闸门：三个字段任一被当前用户隐藏 → 403；
4. 规范化 key：`month` 解析为当月 1 日；`row_value` 交给字段类型校验（单选 options 外部值 → 400）；
5. `find_month_key_rows`：
   - 0 行且 `value` 为空 → 204 no-op（前端本身不会发这种请求，服务端兜底）；
   - 0 行且有 `value` → 走 `_dispatch_or_403`：可直编则 `create_row`（201，月份写当月 1 日）；不可直编则 `_cr_response(op=create)`（202）；
   - 1 行 → 走 `_row_write_decision`：`direct` 用 `update_row`（200）；`change_request` 用 `_cr_response(op=update)`（202）；`denied` 403；`not_found` 404；
   - N>1 行 → 409，`detail` 给出重复行 id，不写任何行。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /api/v1/workspaces/{wid}/tables/{tid}/records/matrix-upsert` | 新增：按（对象, 月份）upsert 单个评分单元格 |
| `GET /api/v1/workspaces/{wid}/tables/{tid}` | `TableDetailResponse` 新增只读 `row_rules_active` |
| `POST/PATCH /api/v1/workspaces/{wid}/tables/{tid}/views` | 矩阵视图新增 `value_field` / `period_start` / `period_end` 校验；配置 `value_field` 时禁止 `filters` |

`matrix-upsert` 请求：

```json
{
  "row_field": "部门",
  "row_value": "研发部",
  "month_field": "月份",
  "month": "2026-11",
  "value_field": "得分",
  "value": 88
}
```

响应：

| 状态 | 场景 | 载荷 |
|---|---|---|
| 201 | 新建评分行 | `{"action":"created","row_id":123,"row":{...}}` |
| 200 | 更新已有行 | `{"action":"updated","row_id":123,"row":{...}}` |
| 202 | 进入修改申请 | `{"action":"change_request","change_request":{...}}` |
| 204 | 空值且无行（no-op） | 空 |
| 400 | 字段类型不符 / 月份非法 / 其他必填字段缺失 | `{"detail":"..."}` |
| 403 | 表级权限 / 行级规则 / 隐藏字段 | `{"detail":"..."}` |
| 404 | 表或行不可读 | `{"detail":"..."}` |
| 409 | 同键多行 | `{"detail":"...","row_ids":[...]}` |

### 4. 边界与例外

1. **行字段必须是单选**（`select`），不接受多选、关联、文本：固定对象清单以 options 为真相源。options 为空时视图配置保存返回 400（避免退化成「靠数据长行」）。
2. **月份字段必须是日期**（`date`，不含 `datetime`），`date_granularity` 固定 `month`；新建行存当月 1 日。
3. **评分字段仅数字**（`number` / `float` / `percentage`）；空值写 `NULL`，不写 0。
4. `period_start` / `period_end` 必须同时提供、格式 `YYYY-MM`、`start <= end`、跨度 ≤ 24 个月；缺失或非法 → 400。
5. 配置 `value_field` 的视图**不允许筛选**（`filters` 必须为空），排序不参与单元格数据查询；前端隐藏搜索框。可编辑矩阵的数据查询使用专用过滤器（月份范围 + 行 options），不套视图 filters / sorts / search。
6. 表存在**其他无默认值必填字段**时，新建单元格会因 `create_row` 校验失败返回 400；前端在单元格上提示原因，不自动填充占位值。
7. 行级权限：`row_rules_active` 为真且用户不是管理员 / 工作区 OWNER / 超管（`row_filters_bypass`）时，矩阵只读；端点同样 403，防止前端绕过。
8. 隐藏字段：三个矩阵字段任一被当前用户隐藏时端点 403；前端在字段被隐藏时显示只读与原因。
9. 同一单元格并发首次写入仍可能各自新建一行（应用层 0 行判断无法跨库锁）。矩阵下次加载会按 I1 检测为重复并只读；写入端点随后返回 409，不静默修正。当前 20 人以内单评分人场景可接受，后续如需强约束另立唯一索引方案。
10. 软删除行不参与匹配；同键的已删行不会阻止新建。
11. 单元格保存失败时前端恢复旧值并展示 detail；202 时保留旧值，提示「已提交修改申请」，已有行同时刷新待审批标记。
12. 现有只读矩阵（未配置 `value_field`）的所有能力、视图筛选、`title_field` 行为不变。

### 5. 迁移

无。`view_options`、`TableDetailResponse` 均为增量字段；旧视图无新键，按只读矩阵处理。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 视图配置 | `frontend/src/pages/grid/view-config/viewOptionSchema.ts` | `MATRIX_OPTIONS` 增加评分字段 / 起始月 / 结束月；`value_field` 必填时其他项条件显隐 |
| 视图表单 | `frontend/src/pages/grid/view-config/CreateEditViewForm.tsx` | 起止月默认当前年 1 月—12 月；筛选与评分字段互斥提示 |
| 矩阵纯逻辑 | `frontend/src/pages/grid/views/matrixBoard.ts` | 支持显式 `rowKeys` / `columnKeys`（options × 月份范围）；单元格携带 `rowId` / 重复行数 / 当前值 |
| 矩阵组件 | `frontend/src/pages/grid/views/MatrixView.tsx` | 可编辑模式：`InputNumber` 单元格、失焦 / 回车保存、Esc 取消、保存中 / 错误 / 待审批态；只读模式保持现状 |
| 页面接线 | `frontend/src/pages/grid/GridPage.tsx` | 可编辑矩阵使用专用行查询（月份范围 + 行 options，limit 5000），禁用视图筛选 / 搜索；点击行仍可打开详情 |
| API | `frontend/src/api/records.ts`、`frontend/src/api/types/tables.ts` | `matrixUpsert` 封装与类型；表详情 `row_rules_active` |
| 字段全量 | `frontend/src/pages/grid/views/MatrixView.tsx`（或上层 hook） | 可编辑时按 `fields?full=1` 取单选完整 options |

样式沿用 `--cn-text-*` / `--cn-border` / `--cn-bg-*` token；不新增依赖。

### 7. 测试清单

**判定层（单测）**：

- `matrixBoard`：固定 20 行 × 12 列在零数据时仍完整；月份跨年排序；单元格行 id / 重复数 / 空值。
- `find_month_key_rows`：当月任意日期命中、次月不命中、软删忽略、多行返回全部 id。
- 矩阵视图配置校验：合法组合；行字段不是单选 / 月份不是日期 / 值不是数字 / 缺起止月 / 跨度 25 个月 / 配置筛选 / options 为空 → 400。

**接口层**：

- 新建单元格 → 201，库里月份为当月 1 日；
- 更新同月不同日的已有行 → 200，原日期不变、值更新；
- 置空已有行 → 200，值为 NULL；
- 空值且无行 → 204，不建行；
- 同键两行 → 409，值与行数不变；
- 单选非法选项 / 非法月份 / 非法字段类型 → 400；
- 其他必填字段缺失 → 400；
- 表级权限不足 → 403；viewer / 关闭直编 → 202 且值未落库；
- 行级规则表（非豁免）→ 403；管理员豁免可写；
- 隐藏字段 → 403；
- `row_rules_active` 在默认档 / 规则 / 无规则三种场景的返回值。

**迁移 / 备份**：无迁移；备份往返仅验证 `view_options` 新键随视图导出 / 导入不丢（现有备份用例追加断言）。

**e2e（前端）**：

- 建 20 个部门选项 + 月份 + 得分字段 → 建评分矩阵视图 → 录入 2 个单元格 → 刷新后值仍在；
- 无数据的未来月份列可直接录入并生成行；
- viewer 打开同一视图为只读；配置行级规则后矩阵只读。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 视图配置校验 + `matrix-upsert`（创建 / 更新 / 置空）+ 矩阵固定行 / 列 + 单元格录入 + 前后端单测 | 中 |
| **P1** | 重复行 409 / 行级规则与隐藏字段闸门 / 修改申请 202 / `row_rules_active` / 专用行查询 | 中 |
| **P2** | 待审批标记、错误与空态文案、帮助文档、e2e、备份断言 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案 | 扩展现有矩阵视图（`value_field`），不新增视图类型 | 复用矩阵布局 / 配色 / 移动端适配；未配置时行为不变 | 新增 `score_matrix` 视图类型（重复实现一套轴与布局，入口分裂） | `viewOptionSchema.ts`、`MatrixView.tsx` |
| D2 | 行轴来源 | 单选字段 options（全量） | 对象固定，空对象也必须可见；I3 | 已有行 distinct（无数据不显示，无法录入新对象） | `MatrixView.tsx` |
| D3 | 列轴来源 | 视图配置的月份范围 | 可提前建新月份列；I3 | 已有行日期分桶（新月份没有列，无法录入） | `matrixBoard.ts`、视图校验 |
| D4 | 月份存储与匹配 | 新建存当月 1 日，读取按 `[当月1日, 次月1日)` 匹配 | 兼容历史行存任意日期；日期类型可继续用于筛选 / 图表 | 文本 `YYYY-MM`（丢失日期类型能力，手填易漂移）；精确日期相等（漏匹配历史行） | `records.py` |
| D5 | 写入入口 | 新增 `matrix-upsert` 端点，服务端按业务键查找 | 避免前端「先查再建」竞态；重复行可统一 409；I1 | 前端直接 POST/PATCH（看不到全量行时会重复建行） | `routers/records.py` |
| D6 | 权限口径 | 复用 `create_row` / `update_row` + 现有双轨分派 | 与网格单行编辑完全同源；I2 | 为矩阵新开权限或直编旁路（与 ADR 0004 冲突） | `records.py` |
| D7 | 行级权限 | 有行规则且非豁免 → 矩阵只读 / 403 | 隐藏行会导致重复建行与存在性泄露；I4 | 按已加载行判断（不可靠）；允许写并返回 409（泄露行存在） | `row_access.py`、`tables.py` |
| D8 | 重复业务键 | 409 拒绝，返回行 id，不自动合并 | 合并涉及数据取舍，需用户显式处理；I1 | 更新最小 id（静默丢失其他行）；自动删重复行（危险） | `records.py` |
| D9 | 保存时机 | 单元格失焦 / 回车单格保存 | 交互简单、失败隔离；20×12 规模无压力 | 整块「保存矩阵」按钮（需处理部分成功 / 冲突，复杂度高） | `MatrixView.tsx` |
| D10 | 视图筛选 / 搜索 | 可编辑矩阵禁用，数据查询不套 filters / sorts / search | 防「未加载行被当成空」重复建行；I1 | 沿用筛选（必然产生重复行） | `GridPage.tsx`、`routers/views.py` |
| D11 | 支持的字段类型 | 行=单选、月份=日期、值=数字 | 覆盖当前部门评分场景，校验确定 | 首期支持全部类型（文本 / 多选 / 公式的写入语义各不相同） | 视图校验、`records.py` |
| D12 | 空值语义 | 不新建空行；已有行可置 NULL | 单元格「没填」不应产生无意义记录 | 新建 0 分行（占位污染数据） | `records.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：网页内直接完成「固定对象 × 月份」评分，新增行从 N 次操作降为 0；新月份列可直接录入；权限 / 修改申请与网格同源。
- **负向**：矩阵视图从纯展示变成写入口，需要新增端点与视图配置校验；表存在行级权限或其他必填字段时不能直接使用。
- **风险与缓解**：并发首次写入同一单元格可能产生重复行 → 加载检测只读 + 端点 409，必要时后续增加数据库级唯一约束；月份范围 ≤24 控制 DOM 与查询规模。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 行级权限 | ADR 0004 | 矩阵不新增权限模型；有行规则时只读，避免隐藏行造成重复与泄露 | 本 ADR D7 |
| 修改申请双轨 | ADR 0005 / 0004 | 复用 202 申请轨道，矩阵不直编旁路 | 本 ADR D6 |
| 矩阵视图 | 现有矩阵视图（无独立 ADR） | 扩展配置项，只读形态零变化 | 本 ADR D1 |
| 性能 / 读路径 | ADR 0046 | 可编辑矩阵使用专用小范围查询（≤24 月 × 对象 options），不走 2000 行非 grid 全量路径 | 本 ADR D10 |
| 硬约束 | CONSTRAINTS H12 / H17 / H24 / H25 / H29 | 测试同轮、行级无泄露、token 样式 | 本 ADR |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/tables/routers/records.py`、`frontend/src/pages/grid/views/MatrixView.tsx`、`frontend/src/pages/grid/views/matrixBoard.ts`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts` | `tests/test_matrix_score_entry.py`、`frontend/src/pages/grid/views/MatrixView.score.test.tsx`、`frontend/src/pages/grid/views/matrixBoard.test.ts` | 未发布 |
| P1 | 已落地 | `src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/services/core/row_access.py`、`src/cndb/plugins/tables/routers/views.py`、`src/cndb/plugins/tables/routers/tables.py` | `tests/test_matrix_score_entry.py`、`tests/test_views_api.py`、`tests/test_tables_integration.py` | 未发布 |
| P2 | 已落地 | `frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/gridViewBar.tsx`、`frontend/src/pages/help/content/tutorials.tsx` | `frontend/tests/e2e/critical/matrix-score-entry.spec.ts`、`frontend/src/pages/grid/views/MatrixView.score.test.tsx` | 未发布 |

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地（2026-11-15 人工评审通过并确认实现）
- 已完成：视图配置校验、`matrix-upsert`（创建 / 更新 / 置空 / 重复 409）、行级权限与隐藏字段闸门、`row_rules_active`、矩阵固定行列与单元格录入、只读降级、搜索入口隐藏、帮助文案、单测与 e2e 用例
- 下一步：CI 跑 `make cov` / `make e2e`；本地 `make cov` 为 94.84%，HEAD 基线为 94.81%（均低于 95%，非本 ADR 引入）；e2e 未在本地执行（pnpm/bun shim 损坏），用例已提交
- 已知坑：可编辑矩阵必须用专用查询（不能套视图 filters / search）；行级权限表非豁免用户只读；月份按 [当月1日, 次月1日) 匹配历史数据；同一单元格并发首次写入仍可能产生重复行，加载与写入端点会检测并拒绝
- 最近一次全绿：`make test` 6968 passed / 17 skipped（2026-11-15）；前端 `npx vitest run` 3279 passed（2026-11-15）
