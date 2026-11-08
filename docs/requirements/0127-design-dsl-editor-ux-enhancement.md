# 需求卡片：结构设计 DSL 编辑器体验增强（变量补全 / 空白显示 / 花括号对齐）

- 编号：0127
- 来源 / 提出人：用户（会话 2026-11-09）
- 日期：2026-11-09
- 关联 ADR：无（S1，方案并入本卡片；编辑器底座见需求 0110 / 0111 / 0112 / 0115）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 结构设计，变量自动完成，空格显示，{括号自动对齐等功能需增强。请给出建议。

## 方案（口径）

**范围**：仅「设计 → 结构设计」的 DSL 编辑器（`frontend/src/pages/design/`），不涉及左侧结构树、预览画布、后端接口与数据模型；零迁移、零新增依赖（所需扩展均在既有 `@codemirror/*` 包内，见 `frontend/package.json:38-44`）。块折叠、参数值提示等列为 P2 可选打磨，不改变本期主口径。

**空白显示**（用户 2026-11-09 拍板）：挂 CodeMirror `highlightWhitespace()`，空格显示为弱化圆点、Tab 显示为箭头；**仅编辑态常显**，只读 viewer 不挂该扩展。颜色复用 `editorAppearance.ts` 已定义的 `.cm-highlightSpace` / `.cm-highlightTab`，不新增 CSS。

**缩进口径**（用户 2026-11-09 拍板）：固定 2 空格。`indentUnit.of('  ')` + `EditorState.tabSize.of(2)`，Tab / Shift+Tab 走 `indentWithTab`，任何操作都不写入制表符；现有片段模板中的 `\t` 全部改为 2 空格，保证「插入片段」与「回车自动缩进」同宽。

**括号自动对齐**（用户 2026-11-09 拍板）：

- 配对范围 `{}` / `()` / `[]`，用 `closeBrackets({ brackets: '()[]{}' })` + `closeBracketsKeymap`；**不自动补引号**，避免干扰 `use "` 字符串位补全。
- 匹配高亮：`bracketMatching()`，主题 `.cm-matchingBracket` 已就绪。
- 智能回车（新增 `insertDslNewline`，优先于 `defaultKeymap`）：

| 当前行 / 光标场景 | 下一行缩进 |
|---|---|
| 行尾 `{`（含行尾 `//` 或块注释后的 `{`） | 当前缩进 + 2 空格 |
| 光标位于自动配对的 `{}` 之间 | 展开三行：`{` / +2 空格空行 / 与 `{` 对齐的 `}` |
| 行首已有或新输入 `}` | 对齐到匹配 `{` 所在列 |
| 空行 / 纯空白行 | 继承当前缩进（花括号 DSL 不自动回退） |
| 非空选区 | 按普通回车替换选区，不猜缩进 |

- `}` 自动回退：用轻量「括号深度缩进服务 + `indentOnInput: /^\s*\}$/`」实现；计算前复用 `designCompletion.stripCommentsAndStrings` 剥离字符串与注释，`[` 向量不参与缩进计算。

**变量补全增强**（在 0110 既有 `dslCompletionSource` 上做上下文细化，不新建补全框架）：

| 场景 | 现状 | 增强后 |
|---|---|---|
| 模块体表达式位 | 只出顶层 `param` / 函数 / `PI`，不出本模块形参 | 定位光标所在 `module name(...) { }` 块，补该模块形参（求值环境确实包含形参，见 `compile.py:824-827`） |
| 模块调用括号内 | 只出裸形参名 | 出 `形参 = ` 命名实参片段；已绑定实参可后置或过滤 |
| 变换后的实例位 | `translate([...]) b` 落到表达式候选 | 识别 `translate/rotate/scale/mirror(...)` 之后位置，出图元 / 模块名 / 实例片段 |
| `constraint` 行 | 整行统一出「类型 + 标签 + 锚点」 | `constraint 名` 后只出类型；`类型(` 内与 `=` 后出标签 + 锚点 + 参数 / 函数；`标签.` 后只出 `origin/x/y/z` |

**候选质量**：本地符号（形参 / `param` / 实例标签）优先于关键字与片段；同名候选去重；`detail` 维持中文一句话。

**交互边界**：只读 viewer 不挂补全与空白显示；补全、缩进、配对均不阻断输入，语法正确性仍由后端编译诊断兜底。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「结构设计」 | 本期只改结构设计 DSL 编辑器；不改结构树、预览画布、后端接口与数据；不新增依赖 | `frontend/src/pages/design/` | 变更文件清单核对；`make check-fast` |
| C2 | 「空格显示」 | 编辑态挂 `highlightWhitespace()`，空格点 / Tab 箭头；只读 viewer 不挂；颜色复用既有主题 | `DslEditor.tsx`、`editorAppearance.ts`（只读引用） | 前端单测：编辑态渲染 `.cm-highlightSpace`，只读态不渲染 |
| C3 | （默认缩进） | 固定 2 空格：`indentUnit` / `tabSize` 一致；Tab / Shift+Tab 只写空格；片段模板 `\t` 改 2 空格 | `DslEditor.tsx`、`designCompletion.ts` | 前端单测：Tab 后文档为空格、`tabSize=2`、片段展开无制表符 |
| C4 | 「{括号自动对齐」 | `closeBrackets` 覆盖 `{}` / `()` / `[]`，不补引号；智能回车与 `}` 回退按「方案」表执行；非空选区走默认替换 | `DslEditor.tsx`、新增 `designIndent.ts` | 前端单测：各缩进场景逐条断言 |
| C5 | 「括号自动对齐」 | 挂 `bracketMatching()`，匹配 / 不匹配括号按主题着色 | `DslEditor.tsx` | 前端单测：挂载后 `{}` 匹配装饰可用 |
| C6 | 「变量自动完成」 | 模块体内表达式位补当前模块形参；嵌套布尔块不影响作用域判定 | `designCompletion.ts` | 前端单测：模块体内外候选分流正确 |
| C7 | 「变量自动完成」 | 模块调用括号内出 `形参 = ` 命名实参片段；不在调用括号内不触发 | `designCompletion.ts` | 前端单测：候选 `apply` 文本与位置 |
| C8 | 「变量自动完成」 | 变换后的内联实例位出图元 / 模块名 / 实例片段，不再落到表达式候选 | `designCompletion.ts` | 前端单测：`translate(...) ` 后候选集合 |
| C9 | 「变量自动完成」 | `constraint` 上下文细分：类型位 / 参数位 / `标签.` 锚点位，各出对应候选 | `designCompletion.ts` | 前端单测：同一文档不同光标位候选分流 |
| C10 | 「等功能需增强」 | 候选排序与去重：本地符号优先、同名去重；`detail` 中文一句话；P2 可补 `param` 当前值说明 | `designCompletion.ts` | 前端单测：排序 / 去重 / detail |
| C11 | （测试） | 新增 `designIndent.test.ts`；更新 `designCompletion.test.ts`、`designLang.test.ts`、`DslEditor.test.tsx`；e2e 新增 1 条（输入 `{` → 回车 → `}` 对齐 + 模块体内补全 + 保存不回归） | `frontend/src/pages/design/`、`frontend/tests/e2e/critical/` | `make flow` 全绿；收尾 `make frontend-coverage` |
| C12 | （文档与口径） | CHANGELOG 记增强条目；不涉及帮助文档改动时可不改 | `CHANGELOG.md` | `make check-docs` |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 编辑器扩展数组（空白 / 缩进 / 配对 / 回车入口） | `frontend/src/pages/design/DslEditor.tsx:99-130` | C2-C5 按只读态条件挂载 |
| 2 | 只读切换仓 | `frontend/src/pages/design/DslEditor.tsx:140-150` | 空白显示随 readonly 同步摘除 |
| 3 | 片段模板（含 `\t`） | `frontend/src/pages/design/designCompletion.ts:93-121` | C3 改 2 空格 |
| 4 | 符号提取（param / module 形参 / 实例标签） | `frontend/src/pages/design/designCompletion.ts:177-201` | C6/C7 复用，不新写扫描器 |
| 5 | 表达式 / 语句候选 | `frontend/src/pages/design/designCompletion.ts:231-245` | C6 增模块形参作用域 |
| 6 | 约束上下文分支 | `frontend/src/pages/design/designCompletion.ts:325-347` | C9 细分 |
| 7 | 调用括号 / 实例位判定 | `frontend/src/pages/design/designCompletion.ts:349-379` | C7/C8 |
| 8 | 语法常量与注释剥离口径 | `frontend/src/pages/design/designLang.ts:19-51、76-133` | 缩进扫描复用；关键字表不改 |
| 9 | 主题空白 / 括号样式 | `frontend/src/theme/editorAppearance.ts:100-117` | 已具备，无需新增 CSS |
| 10 | 流水线同款实现（参考口径） | `frontend/src/pages/pipelines/pipelineDsl.ts:145-202`、`PipelineDslEditor.tsx:65-84` | C3/C4 参考，不共享代码（YAML 与花括号语义不同） |
| 11 | 后端语法基准 | `src/cndb/plugins/design/services/dsl/parse.py:203-250、309-320、382-390` | 只读引用，不改 |
| 12 | 模块形参求值环境 | `src/cndb/plugins/design/services/dsl/compile.py:824-827` | C6 语义依据 |
| 13 | 既有单测 / e2e（回归面） | `frontend/src/pages/design/DslEditor.test.tsx`、`designCompletion.test.ts`、`frontend/tests/e2e/critical/design-*.spec.ts` | C11 不破坏既有流程 |
| 14 | 依赖清单 | `frontend/package.json:38-44` | 无新增依赖 |

## 未决问题（已确认）

- [x] ① 缩进单位：**结论**固定 2 空格，Tab 也只写空格（2026-11-09 用户拍板）。
- [x] ② 空白显示范围：**结论**仅编辑态常显，只读 viewer 不显示（2026-11-09 用户拍板）。
- [x] ③ 括号配对范围：**结论**`{}` / `()` / `[]`，不自动补引号（2026-11-09 用户拍板）。
- [x] ④ 方案分级：**结论**S1（纯前端交互增强，无数据 / 权限 / 架构分叉，方案并入本卡片，不写 ADR，2026-11-09 用户确认）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-09 用户拍板）

## 落地记录

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0（C2-C5） | 已完成 | `frontend/src/pages/design/{DslEditor.tsx,designIndent.ts,designLang.ts}` | `designIndent.test.ts` 8 例、`DslEditor.test.tsx` 2 例 | 待提交 |
| P1（C6-C9） | 已完成 | `frontend/src/pages/design/designCompletion.ts` | `designCompletion.test.ts` 新增 7 例 | 待提交 |
| P2（C10） | 已完成（去重 / 本地优先；`param` 当前值说明为可选项，未纳入） | `frontend/src/pages/design/designCompletion.ts` | `designCompletion.test.ts` 去重用例 | 待提交 |
| 测试 / 文档（C11-C12） | 已完成 | `CHANGELOG.md`、`frontend/tests/e2e/critical/design-dsl-editor-ux.spec.ts` | `make flow` 全绿 | 待提交 |

- 最近一次全绿：2026-11-09 `make flow`（后端 6739 passed / 3 skipped；前端设计编辑器相关 47 例通过；`pnpm typecheck` / `pnpm lint` 通过）。
