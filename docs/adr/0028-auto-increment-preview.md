# ADR 0028: 新增行自动编号：预览数值与手动修改（按库内已有数据往后排）

Status: Implemented（2026-10-27 人工评审通过）
Date: 2026-10-24（追加 2026-10-25）
Related: `src/cndb/plugins/tables/field_types/text.py`、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/routers/records.py`、`src/cndb/plugins/tables/schemas/models.py`、`frontend/src/pages/grid/cells/AutoIncrementCell.tsx`、`frontend/src/pages/grid/cells/buildColumns.tsx`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/layout/RowDetailDrawer.tsx`、`frontend/src/utils/fieldIncrement.ts`、`frontend/src/api/records.ts`、`docs/requirements/0028-auto-increment-preview.md`
需求卡片: `docs/requirements/0028-auto-increment-preview.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」段落；ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用，不在仓库保留 `Superseded` / `Deprecated` 文档。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 在新增行时显示自动编号的数值 | 新增只读端点 `GET /records/auto-increment-preview` 返回 `{values: {字段名: 编号}}`；网格新增行的自动编号单元格与抽屉新建模式的禁用输入框都取该值展示。预览与建行共用 `next_increment_value`，保证展示值即保存后生成值（I1）。 |
| C2 | 不要显示过多信息 | 删除 `autoIncrementHint` 与 `NumberOutlined`；单元格只渲染编号文本（未加载时最简占位「自动」），抽屉只渲染禁用输入框的 `value`，不加 Tooltip / 说明段落。 |
| C3 | 新增行的自动编号的推断需要增强，要适应当前已有数据往后排 | 推算前对库内值与 `extra_seen` 先 `strip()` 再匹配 `^{前缀转义}(\d+)$`，兼容导入 / 历史数据带空白的值；下一编号 = `max(max + 1, increment_start)`，按前缀与补零位数格式化；软删行计入 max（与唯一索引口径一致）。 |
| C4 | 新增时自动生成编号的旁边提供编辑图标按钮 | 新增行自动编号值旁渲染渐变编辑图标按钮（`EditOutlined`）：网格单元格点击后切换为文本输入框（`data-testid=auto-increment-edit-toggle-{fieldId}`），抽屉点击后把禁用输入框切换为可编辑并预填预览编号。编辑态只对当前新增行生效，不写字段配置。 |
| C5 | 允许手动修改编辑的字段 | 手动值走既有建行 `values` 通道：仅当用户实际改过且最终值非空时提交；后端 `_apply_auto_increment_defaults` 的 `f.name in values` 分支已保证显式值不被覆盖（I4）。未编辑 / 清空则不提交，仍由后端自动生成。手动值按单行文本原样保存，不匹配编号前缀时不参与后续 max 推算（既有口径），唯一冲突沿用建行既有错误。 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状核对（以代码为准，标注 `文件:行号`）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 建行时已有编号推算：扫描物理列非 NULL 值取前缀数字最大值，下一编号 `max(max+1, start)` | `src/cndb/plugins/tables/field_types/text.py:45-85`、`src/cndb/plugins/tables/services/core/records.py:186-265` | 推算口径可靠，可直接复用为预览，避免两套逻辑漂移 | 确认（C1/C3 落点） |
| 2 | 扫描时直接 `str(value)` 匹配，未去首尾空白 | `src/cndb/plugins/tables/field_types/text.py:72-82` | 导入数据里的 ` PRJ-0041 ` 不命中，编号会从头开始 | 确认（C3 主缺口） |
| 3 | 新增行内自动编号列渲染只读数值 span，无编辑入口 | `frontend/src/pages/grid/cells/buildColumns.tsx:270-282` | 用户能看到下一个编号，但无法手动改号 | 确认（C4 主缺口） |
| 4 | 抽屉新建模式用禁用输入框展示预览，提交前一律剔除自动编号字段 | `frontend/src/pages/grid/layout/RowDetailDrawer.tsx:145-149`、`RowDetailDrawer.tsx:181-193` | 无法手动改号；即便改了值也会被剔除 | 确认（C4/C5 主缺口） |
| 5 | 前端没有任何「下一个编号」数据源，只能按 config 拼静态示例 | `frontend/src/utils/fieldIncrement.ts:13-25`、`frontend/src/api/records.ts` | 展示值与库内实际数据脱节 | 新增（C1 需新增端点） |
| 6 | 行内新增行与抽屉新建的提交体都不含自动编号字段（由后端生成） | `frontend/src/pages/grid/GridPage.tsx:722-728`、`frontend/src/pages/grid/layout/RowDetailDrawer.tsx:145-149` | 预览只用于展示，不参与写入，无「预占号」副作用 | 确认（C1 只读语义） |
| 7 | 新增行草稿不预填自动编号（`defaultValueForNewRow` 返回 undefined） | `frontend/src/pages/grid/cells/fieldOps.ts:12-16` | 编辑态初值需从预览值注入，不能依赖草稿预填 | 新增（C4 落点） |
| 8 | 后端建行对显式传值跳过自动生成 | `src/cndb/plugins/tables/services/core/records.py:202` | 手动值无需新增后端入参或端点 | 确认（C5 基础） |
| 9 | 后端已有显式传值 / 非格式值不推进计数器用例 | `tests/test_text_auto_increment.py:250-260` | C5 的后端口径已被既有测试锁定 | 确认（C5 验收） |

**核心缺陷**：新增行里的自动编号只有「看」的入口，没有「改」的入口；即便用户在别处填入手动值，前端建行体也会主动剔除该字段，导致手动修改无法落库。

设计不变量：

- **I1 展示值 = 生成值**：预览与建行必须调用同一个 `next_increment_value`，禁止前端另算 max。
- **I2 预览只读**：预览不写库、不占号；未手动修改时自动编号字段不进入提交体。
- **I3 后移口径一致**：已有编号（含软删行、带首尾空白的值）都计入 max；`increment_start` 仍是下限。
- **I4 手动值优先且仅显式提交**：只有用户实际编辑且值非空时才随建行发送；后端对显式值不覆盖，清空则回退自动生成。

## Decision

### 1. 数据模型

无。复用 `DataTable` / `DataField` 与 `TextFieldConfig`（`default_mode` / `increment_prefix` / `increment_padding` / `increment_start`）。

### 2. 判定算法（唯一入口）

`TextFieldType.next_increment_value(engine, table, field, extra_seen=())` 保持唯一推算入口：

1. 配置非 `auto_increment` → 返回 `None`；
2. 物理表不存在 → 返回 `increment_start` 补零兜底；
3. 扫描物理列全部非 NULL 值，`str(value).strip()` 后按 `^{前缀转义}(\d+)$` 全匹配，取最大数字；
4. `extra_seen`（批量创建已分配未落库值）同样 `strip()` 后参与取最大；
5. 下一编号 = `max(max_seen + 1, increment_start)`，按 `increment_prefix + zfill(increment_padding)` 输出。

新增只读入口 `preview_auto_increment_values(engine, table) -> dict[str, str]`（`services/core/records.py`）：

- 跳过 `trashed` 字段、无物理列的字段类型；
- 对每个字段调用上述 `next_increment_value`，非 `None` 才写入结果；
- 建行路径 `_apply_auto_increment_defaults` 与本函数共用该入口，保证 I1。

建行的手动值口径沿用既有判定，不新增分支：`_apply_auto_increment_defaults` 遇到 `f.name in values` 直接跳过，显式值经 `_normalize_values` 校验后落库（I4）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{workspace_id}/tables/{table_id}/records/auto-increment-preview` | 既有（C1）：返回 `{"values": {"字段名": "编号"}}`；权限 = 表级 `READ`；必须注册在 `/{record_id}` 之前 |
| `POST /api/v1/workspaces/{workspace_id}/tables/{table_id}/records` | **无变更**：手动值复用既有 `values` 字段，显式传值优先语义已存在 |

响应模型 `AutoIncrementPreviewResponse(values: dict[str, str])`（`schemas/models.py`），`values` 默认空字典。

### 4. 边界与例外

1. **未启用 / 已删除字段**：不出现在 `values` 中，前端按普通字段处理。
2. **物理表尚未创建**：返回 `increment_start` 补零值（与建行兜底一致）。
3. **并发新增**：两个窗口可能看到同一编号；预览是提示，保存时后端重新推算并以实际值为准（I2），出现唯一冲突时按既有建行错误返回。
4. **路由顺序**：`/auto-increment-preview` 必须在 `/{record_id}` 之前注册，否则被按 int 解析成 422。
5. **缓存**：前端查询键 `['auto-increment-preview', wid, tid]`，建行成功后必须失效；`staleTime: 0` 保证每次新增行重新取。
6. **手动编辑后清空**：前端不提交该字段（视为未编辑），后端重新自动生成；不把空串当作手动值。
7. **手动值格式**：不做前端额外校验，任何单行文本均可保存；与编号前缀 / 数字格式不符的值不会推进后续自动编号（既有 max 扫描口径）。
8. **手动值重复**：字段启用唯一约束时由数据库唯一索引拒绝，沿用建行既有错误提示；未启用唯一约束时允许多行同号（字段语义如此）。
9. **退出编辑态**：新增行取消 / 保存成功 / 抽屉关闭后清空编辑态标记，重新进入新增时回到只读预览 + 编辑入口。

### 5. 迁移

无。无表结构变更，存量数据零迁移。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/records.ts`、`frontend/src/api/types/records.ts` | 既有 `nextIncrementPreview(wid, tid)` 与 `AutoIncrementPreview` 类型，无改动 |
| 字段判定 | `frontend/src/utils/fieldIncrement.ts` | 保留 `isAutoIncrementField` / `formatIncrementExample`；无改动 |
| 新增单元格组件 | `frontend/src/pages/grid/cells/AutoIncrementCell.tsx` | 新增：只读态渲染预览编号 + 编辑图标按钮；点击切换为 `Input`，初值取草稿值 ?? 预览值，`onChange` 写回草稿（`data-testid=auto-increment-input-{fieldId}`） |
| 网格列 | `frontend/src/pages/grid/cells/buildColumns.tsx` | 新增行自动编号分支改为渲染 `AutoIncrementCell`，透传 `previewValue` / 草稿值 / `onFieldChange` |
| 网格页 | `frontend/src/pages/grid/GridPage.tsx` | `saveInline` 已按「非空草稿才提交」收集字段，手动值自动进入提交体；无需额外分支（仅补注释与测试） |
| 行抽屉 | `frontend/src/pages/grid/layout/RowDetailDrawer.tsx` | 新建模式自动编号渲染禁用输入框 + `EditOutlined` 编辑按钮；点击后解除禁用、把预览值写入表单并记录该字段已手动编辑；提交时仅剔除「未手动编辑」或「手动编辑后为空」的自动编号字段 |

### 7. 测试清单

**判定层（单测）**

- 空表返回 `increment_start`；已有 `PRJ-0007` 返回 `PRJ-0008`；
- 软删行计入 max；带首尾空白的导入值计入 max；
- 未启用自动编号 / 已删除字段不出现在预览结果；
- 预览值与随后建行的实际编号一致；
- 显式传值不被自动编号覆盖，且非格式值不推进计数器（既有用例）。

**接口层**

- 空表预览 `{"values": {"编号": "PRJ-0001"}}`；
- 建两行后预览为 `PRJ-0003`（同时验证路由未被 `/{record_id}` 吞掉）；
- 表不存在 → 404；非工作区成员 → 403；
- POST 手动值原样落库（既有接口路径，补断言或复用既有服务层用例）。

**前端**

- `GridPage.newRowPrefill.test.tsx`：新增行自动编号单元格显示预览编号；编辑图标存在；点击后出现输入框且初值为预览编号；输入手动值后保存，`recordApi.create` 收到的 `values` 含该字段；不编辑直接保存时不发送该字段；
- `RowDetailDrawer.test.tsx`：新建模式禁用输入框 + 编辑按钮；点击解除禁用并预填预览编号；提交体含手动值；未点击编辑时提交体不含该字段；编辑后清空则不含；
- `fieldIncrement.test.ts`：保留字段判定与示例编号。

**迁移 / 备份 / e2e**

- 无迁移、无备份口径变更；e2e 无需新增（既有新增行用例覆盖保存成功路径）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 后端 `strip()` 推算增强 + 预览函数 + 预览端点 + schema | 低 |
| **P1** | 网格新增行只读展示 + 预览查询 + 缓存失效 | 低 |
| **P2** | 行详情抽屉新建模式只读展示 + 删除冗余提示文案 | 低 |
| **P3** | 网格新增行编辑图标 + 可编辑单元格 + 手动值进入提交体 | 低 |
| **P4** | 抽屉新建编辑图标 + 手动值提交口径（未编辑 / 清空剔除） | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 展示值的来源 | **后端预览端点复用 `next_increment_value`** | 与建行同源（I1）；一次请求即可覆盖软删 / 空白 / 补零口径 | ① 前端拉全量行自行算 max（分页 / 筛选 / 缓存不一致，且拿不到软删行）；② 继续显示静态示例值（与实际编号脱节，不满足 C1） | `services/core/records.py`、`routers/records.py` |
| D2 | 展示形态 | **默认纯数值展示，值旁提供编辑图标切换手动输入** | 满足 C1/C2/C4：平时信息最简，需要时一键修改 | ① 始终渲染普通输入框（与「自动编号」语义冲突，用户易误以为必须手填）；② 加 Tooltip / 说明段落（违反 C2） | `buildColumns.tsx`、`AutoIncrementCell.tsx`、`RowDetailDrawer.tsx` |
| D3 | 推算增强方式 | **匹配前 `strip()` 首尾空白** | 导入 / 历史数据常带空格；不改变前缀与数字口径 | 放宽为「包含前缀即可」（会把 `PRJ-1A` 等误计）；逐个 try/except 清理数据（需写库，超出只读范围） | `field_types/text.py` |
| D4 | 路由注册位置 | **放在 `/{record_id}` 之前** | FastAPI 按声明顺序匹配，`auto-increment-preview` 会被 int 路径参数解析成 422 | 单独挂到 `/records/preview/...`（多一层无意义路径）；用字符串 `record_id` 再分支（污染既有行接口类型） | `routers/records.py` |
| D5 | 缓存失效时机 | **建行成功后失效预览查询** | 下一次新增行必须基于最新库内数据（I3） | 依赖 `staleTime` 自然过期（期间新增行显示旧编号） | `GridPage.tsx`、`RowDetailDrawer.tsx` |
| D6 | 手动值提交口径 | **仅用户实际编辑且非空时提交；未编辑 / 清空不提交，仍由后端生成** | 满足 C5 且保持 I1/I2：不编辑时展示值 = 生成值；避免把过期预览当作手动值写库 | ① 新增行激活即以预览值预填草稿并随建行提交（并发下会把旧编号固化，且所有新增都变成手动值）；② 后端新增「忽略与预览相同的值」特判（无法区分用户是否真改过，且污染建行语义） | `AutoIncrementCell.tsx`、`GridPage.tsx`、`RowDetailDrawer.tsx` |
| D7 | 手动值格式校验 | **沿用单行文本校验，不强制前缀 + 数字** | 字段本质是文本；既有后端已允许显式「手动值」且不推进计数器（有测试锁定） | 前端强制 `前缀 + 数字`（用户可能需要自定义临时编号，且与既有字段语义不一致） | `services/core/records.py`（无改动）、`AutoIncrementCell.tsx` |

门禁：本表无「待定」。`Status` 仍为 `Proposed`，待人工评审后转 `Accepted` / `Implemented`。

## Consequences

- **正向**：新增行能看到真实的下一个编号，且随已有数据（含软删、导入空白值）正确后移；需要时可在编号旁一键改为自定义值，自动编号不再是「只能看不能改」；展示与保存同源，不会出现「看到 PRJ-0008、保存成 PRJ-0001」的错位。
- **负向**：新增行激活时多一次轻量查询（扫描单个物理列）；手动编辑增加一个单元格交互态，需覆盖取消 / 清空 / 保存三条路径。
- **风险与缓解**：大表全列扫描随行数线性增长 → 仅新增行激活时触发、结果不落库；预览与生成之间插入新行 → 保存时后端重新推算，预览只作提示；手动值重复 → 唯一约束字段由数据库拒绝并沿用既有错误。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 后端推算 + 预览端点 | 已落地 | `src/cndb/plugins/tables/field_types/text.py`、`src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/routers/records.py`、`src/cndb/plugins/tables/schemas/models.py`、`src/cndb/plugins/tables/schemas/__init__.py` | `tests/test_text_auto_increment.py` | `08c922c` |
| P1 网格新增行只读展示 | 已落地 | `frontend/src/pages/grid/cells/buildColumns.tsx`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/api/records.ts`、`frontend/src/api/types/records.ts` | `frontend/src/pages/grid/GridPage.newRowPrefill.test.tsx` | `08c922c` |
| P2 行抽屉新建只读展示 | 已落地 | `frontend/src/pages/grid/layout/RowDetailDrawer.tsx`、`frontend/src/utils/fieldIncrement.ts` | `frontend/src/pages/grid/layout/RowDetailDrawer.test.tsx`、`frontend/src/utils/fieldIncrement.test.ts` | `08c922c` |
| P3 网格新增行手动修改 | 已落地 | `frontend/src/pages/grid/cells/AutoIncrementCell.tsx`、`frontend/src/pages/grid/cells/buildColumns.tsx`、`frontend/src/pages/grid/GridPage.tsx` | `frontend/src/pages/grid/GridPage.newRowPrefill.test.tsx` | `2286cce5` |
| P4 抽屉新建手动修改 | 已落地 | `frontend/src/pages/grid/layout/RowDetailDrawer.tsx` | `frontend/src/pages/grid/layout/RowDetailDrawer.test.tsx` | `2286cce5` |

## 交接（会话结束更新）

- 当前阶段：P0-P4 全部落地，`Status` 已于 2026-10-27 经人工评审确认改 `Implemented`
- 已完成：`strip()` 推算增强、`preview_auto_increment_values`、`GET /records/auto-increment-preview`、网格与抽屉的新增行只读数值展示、冗余提示文案删除、建行后预览缓存失效、P3/P4 手动改号（网格 `AutoIncrementCell` + 抽屉编辑图标，手动值仅显式提交）
- 下一步：无（功能完结）
- 已知坑：预览端点必须保持在 `/{record_id}` 之前；预览是只读提示，并发窗口可能同号，以保存结果为准；前端预览查询键为 `['auto-increment-preview', wid, tid]`，新增建行路径时要同步失效；手动值只有在用户实际编辑后才允许进入提交体（D6）
- 最近一次全绿：`make check`（lint + typecheck + cov + frontend-coverage）@ 2026-10-25
