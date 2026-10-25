# 需求卡片：数据表新增行自动编号的预览数值与手动修改

- 编号：0028（与 ADR `docs/adr/0028-auto-increment-preview.md` 同号）
- 来源 / 提出人：产品需求（用户提报）
- 日期：2026-10-24（追加 2026-10-25）
- 关联 ADR：`docs/adr/0028-auto-increment-preview.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 数据表，自动编号字段，在新增行时显示自动编号的数值，不要显示过多信息。新增行的自动编号的推断需要增强，要适应当前已有数据往后排。

### 追加需求原句（2026-10-25，逐字）

> 数据表，自动编号字段，新增时自动生成编号的旁边提供编辑图标按钮，允许手动修改编辑的字段。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 在新增行时显示自动编号的数值 | 新增行（行内新增行与行详情抽屉新建）里的自动编号字段以**只读数值**展示：网格单元格显示编号文本，抽屉显示禁用输入框的 `value`；数值必须等于保存后后端实际生成的编号 | `tables/records`、`frontend/src/pages/grid` | `test_text_auto_increment.py` 预览接口用例；`GridPage.newRowPrefill.test.tsx`、`RowDetailDrawer.test.tsx` 断言编号文本 / 输入值 |
| C2 | 不要显示过多信息 | 去掉「保存时自动生成（如 PRJ-0001）」等解释性占位文案与图标；未拿到预览值时只显示最简占位「自动」，不加 Tooltip / 说明段落 | `frontend/src/pages/grid`、`frontend/src/utils/fieldIncrement.ts` | 前端用例断言不出现「保存时自动生成」；`autoIncrementHint` 已删除 |
| C3 | 新增行的自动编号的推断需要增强，要适应当前已有数据往后排 | 预览与建行共用同一推算入口：扫描库内已有值（含软删行、带首尾空白的导入值）取前缀编号最大值，下一编号 = `max(max + 1, increment_start)`，按前缀与补零位数格式化 | `src/cndb/plugins/tables/field_types/text.py`、`services/core/records.py`、`routers/records.py` | `test_text_auto_increment.py` 单测（空表 / 已有 max / 软删 / 空白值 / 预览与建行一致）与接口用例（空表 / 已有两行 / 404 / 403） |
| C4 | 新增时自动生成编号的旁边提供编辑图标按钮 | 新增行（网格新增行与抽屉新建）的自动编号值旁渲染**编辑图标按钮**；点击后切换为可编辑文本输入框，初始值为当前预览编号（抽屉为禁用输入框解除禁用），不改动字段配置 | `frontend/src/pages/grid/cells/buildColumns.tsx`、`frontend/src/pages/grid/layout/RowDetailDrawer.tsx` | 前端用例：图标存在；点击后出现可输入控件且初值为预览编号 |
| C5 | 允许手动修改编辑的字段 | 仅当用户实际修改且值非空时，该值随建行提交体发送，后端建行对显式传值**不覆盖**（既有语义）；未编辑或清空则不提交，仍由后端自动生成；手动值格式不做前端额外限制，唯一冲突沿用既有后端错误 | `frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/layout/RowDetailDrawer.tsx`、`services/core/records.py` | `GridPage` / `RowDetailDrawer` 用例断言提交体含 / 不含手动值；`test_text_auto_increment.py::test_explicit_value_not_overridden` 既有后端用例 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 建行时自动编号生成 | `src/cndb/plugins/tables/services/core/records.py:186` | 已有 `next_increment_value` 推算，可直接复用为预览 |
| 2 | 编号推算的扫描口径 | `src/cndb/plugins/tables/field_types/text.py:45` | 值未 strip，带空格的历史值会漏计 |
| 3 | 新增行内自动编号单元格 | `frontend/src/pages/grid/cells/buildColumns.tsx:271` | 原先显示提示文案而非数值 |
| 4 | 行详情抽屉新建模式 | `frontend/src/pages/grid/layout/RowDetailDrawer.tsx:181` | 原先禁用框 + 提示占位 |
| 5 | 前端判定 / 示例文案单一真相源 | `frontend/src/utils/fieldIncrement.ts:13` | 含已废弃的提示文案函数 |
| 6 | 新增行自动编号单元格无编辑入口 | `frontend/src/pages/grid/cells/buildColumns.tsx:271` | 只读 span，无法手动改号 |
| 7 | 抽屉新建自动编号禁用框无编辑入口，且提交前一律剔除该字段 | `frontend/src/pages/grid/layout/RowDetailDrawer.tsx:145`、`RowDetailDrawer.tsx:181` | 剔除逻辑会丢弃手动值 |
| 8 | 后端建行显式传值优先 | `src/cndb/plugins/tables/services/core/records.py:202` | `f.name in values` 时跳过自动生成，手动值无需后端改动 |

## 未决问题

- [x] 编号展示口径：只显示编号数值，按库内已有数据往后排（需求方确认）。
- [x] 手动修改的作用范围：仅新增行（网格新增行 + 行详情抽屉新建）；存量行编辑沿用既有可编辑语义，不额外改造。
- [x] 手动修改后清空：不提交该字段，回退为后端自动生成（避免「空值占号」）。
- [x] 手动值格式：不强制前缀 + 数字，按单行文本原样提交；与既有编号格式不符的值不参与后续 max 推算（既有口径）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
