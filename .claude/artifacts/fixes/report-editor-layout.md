# Bug: 报表编辑器三栏布局错乱

> Status: FIXED
> Mode: --quick
> Severity: functional（视觉/布局）
> Author: user
> Last updated: 2026-09-25

## Symptom
报表功能页面布局混乱，编辑器弹窗内三栏（字段面板/代码编辑器/预览）错位。

## Expected
三栏各自保持盒模型：左 220px 字段面板、中间自适应 CodeMirror、右 340px 预览面板。

## Reproduction
- 步骤：打开报表模板 → 编辑任意模板 → 弹窗内三栏布局散架
- 测试位置：`frontend/src/components/report-editor/reportEditorCss.test.ts:29`
- 复现稳定性：稳定（CSS 静态规则，非时序问题）

## Hypotheses & diagnosis
| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | `.report-template-editor > * { display: contents }` 命中字段面板/编辑器根节点使其盒模型失效 | confirmed (root cause) | dnd-kit 的 DndContext/SortableContext 不渲染 DOM，`.report-template-editor` 的直接子元素就是 `.report-field-panel` 与 dropzone 根节点，`display: contents` 使其 width/flex/background/border 全部失效 |

## Root cause
注释假设「DndContext 可能渲染出 wrapper div」是错的——dnd-kit 的 DndContext 与 SortableContext 均为纯 context provider，不产生 DOM。因此 `> * { display: contents }` 直接命中两个真实面板节点，破坏 flex 布局。

## Fix
- 改动文件：`frontend/src/components/report-editor/reportEditor.css`
- 删除 `.report-template-editor > * { display: contents; }` 规则，替换为说明性注释。

## Verification
- V-1: 新增回归测试先 RED（复现规则存在）→ 修复后 GREEN ✓
- V-2: `git stash` 移除修复 → 测试重新 RED ✓；`stash pop` 恢复 → GREEN ✓
- V-3: `pnpm vitest run src/components/report-editor/ src/pages/reports/` 8 文件 63 用例全 GREEN ✓
- V-4: `make check` exit 0（后端 2297 passed，覆盖率 98.39%）✓

## Regression test
- 路径：`frontend/src/components/report-editor/reportEditorCss.test.ts:29`
- 名称：三栏布局子元素不得使用 contents 型 display 声明

## Pattern analysis
- `grep "display: contents"` 全仓库仅此一处（已移除），无同类隐患。

## Open questions / Follow-ups
无
