# 需求卡片：流水线 DSL 编辑器智能自动缩进与空白显示

- 编号：0115
- 来源 / 提出人：用户（会话 2026-11-06）
- 日期：2026-11-06
- 关联 ADR：无（S1，方案并入本卡片；编辑器底座见需求 0111 / 0112）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 流水线需要实现智能自动缩进，并增加空白显示，默认缩进采用空格。

## 方案（口径）

**空白显示**：流水线 DSL 编辑器常显空白（不新增开关），复用 CodeMirror `highlightWhitespace()`：空格显示为弱化圆点、Tab 显示为箭头；点 / 箭头的颜色跟随当前编辑器主题的 `muted` 色，深浅主题均可见。

**缩进口径**：固定 2 空格（YAML 口径），`indentUnit` 与 `tabSize` 都设为 2；Tab / Shift+Tab 走 `indentWithTab`，只写空格，任何操作都不写入制表符。

**智能自动缩进**（回车时按 YAML 结构计算下一行缩进）：

| 当前行 | 下一行缩进 |
|---|---|
| `key:` 结尾（含行尾 `#` 注释） | 当前缩进 + 2 空格 |
| `- key:`（列表项内的映射块） | 列表内容列 + 2 空格（如 6 空格行 → 10 空格） |
| 普通列表项 `- uses: ...` | 同一层延续 `- ` |
| 裸 `-` / `- ` | 列表内容层（当前缩进 + 2 空格） |
| 空行 / 纯空白行 | 回退一级（最少 0 空格） |
| 纯注释行 / 其他行 | 继承当前缩进 |

非空选区仍按普通回车替换选区，不猜缩进。

**边界**：只改流水线 DSL 编辑器，设计结构 DSL 编辑器与文档 Markdown 编辑器不在本期范围；零后端改动、零迁移、无新增依赖。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「智能自动缩进」 | 回车按 YAML 结构计算缩进：`key:` 进一级、`- key:` 按内容列进一级、普通列表项延续 `- `、裸短横进入内容层、空行回退一级、纯注释 / 其他行继承 | `frontend/src/pages/pipelines/pipelineDsl.ts` | 前端单测：各结构行回车后的下一行缩进 |
| C2 | 「默认缩进采用空格」 | 缩进单位固定 2 空格，`indentUnit` / `tabSize` 一致；Tab 与 Shift+Tab 只写空格 | `pipelineDsl.ts`、`PipelineDslEditor.tsx` | 前端单测：Tab 后的文档文本为空格且 `tabSize=2` |
| C3 | 「增加空白显示」 | 流水线编辑器常显空白：空格点、Tab 箭头；颜色跟随编辑器主题弱化色 | `PipelineDslEditor.tsx`、`frontend/src/theme/editorAppearance.ts` | 前端单测：渲染 `.cm-highlightSpace` |
| C4 | （边界） | 非空选区回车只替换选区，不套用智能缩进；设计 / 文档编辑器不受影响 | `pipelineDsl.ts` | 前端单测：选区替换结果 |
| C5 | （测试与文档） | 覆盖新增缩进分支与空白显示；CHANGELOG 记条目 | `pipelineDsl.test.ts`、`PipelineDslEditor.test.tsx`、`CHANGELOG.md` | `make flow` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 回车缩进判定 | `frontend/src/pages/pipelines/pipelineDsl.ts:149-167` | 原实现只判 `key:` 与列表延续，新增空行回退与 `- key:` 内容列 |
| 2 | 编辑器扩展 | `frontend/src/pages/pipelines/PipelineDslEditor.tsx:64-79` | 新增 `highlightWhitespace()` 与 `tabSize` |
| 3 | 编辑器主题 | `frontend/src/theme/editorAppearance.ts:97-109` | 为空白标记补主题弱化色 |
| 4 | 既有测试 | `pipelineDsl.test.ts`、`PipelineDslEditor.test.tsx` | 原有用例保持，新增分支用例 |

## 未决问题（已确认）

- [x] ① 空白显示形态：**结论** 编辑器内常显，不新增开关（2026-11-06 用户拍板）。
- [x] ② 缩进口径：**结论** 固定 2 空格，Tab 也只写空格（2026-11-06 用户拍板）。
- [x] ③ 智能缩进范围：**结论** YAML 结构感知（`key:` 进级 / 列表延续 / 空行回退 / Tab·Shift+Tab 整行缩进）（2026-11-06 用户拍板）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-06 用户拍板）

## 落地记录

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/pipelines/{pipelineDsl.ts,PipelineDslEditor.tsx}`、`frontend/src/theme/editorAppearance.ts` | `pipelineDsl.test.ts`、`PipelineDslEditor.test.tsx` | 本轮提交 |

- 最近一次全绿：`make flow`（`check-fast` + `test`）@ 2026-11-06
