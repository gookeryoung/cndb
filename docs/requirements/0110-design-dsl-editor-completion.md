# 需求卡片：设计结构 DSL 编辑器功能增强（自动完成 + 代码片段 + 高亮口径对齐）

- 编号：0110
- 来源 / 提出人：用户（会话 2026-11-06）
- 日期：2026-11-06
- 关联 ADR：无（S1，方案并入本卡片）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 请针对设计结构DSL编辑器的功能增强制定方案。包括但不限于自动完成（变量、关键字），代码片段插入等。

## 方案（口径）

**选型**：CodeMirror 官方 `@codemirror/autocomplete` 扩展（`autocompletion` + `snippet()` + `Completion`），不引入自研补全框架，不新增后端端点。

**单一语法口径**：补全与高亮共用 `designLang.ts` 导出的关键字常量，常量表与后端 `src/cndb/plugins/design/services/dsl/parse.py` 的 `KEYWORD_* / BOOLEANS / TRANSFORMS / PRIMITIVES / CONSTRAINT_TYPES / CONSTRAINT_ANCHORS / _FUNCTION_NAMES` 逐项对齐（当前前端缺 `use` / `as` / `constraint` / 约束类型 / 锚点，属 ADR 0086 后的既有偏差，本期修正）。

**结构**：新增 `frontend/src/pages/design/designCompletion.ts`：

- `dslCompletionSource(context: CompletionContext)`：按光标上下文返回候选；
- `dslSnippets`：骨架片段集（param / module / system / use / constraint / 变换块 / 图元带签名模板）；
- `extractSymbols(doc: string)`：轻量扫描当前文档提取 `param` 名、`module` 名 + 形参表、`use ... as` 实例标签（标识符与注释剥离口径同后端 lexer）。

**上下文判定**（轻量规则，不做完整前端解析器）：行首列 0 / 顶层 → 语句关键字 + 骨架片段；`(`/`,`/`=` 之后或块内 → 参数名 + 函数 + `PI`；模块调用括号内 → 该模块形参名；`constraint` 行 → 约束类型 + 实例标签锚点；`use "` 字符串内 → 零件名跨文件补全（P2，见下）。扫描误差不阻断输入，语法正确性由后端诊断兜底。

**零件名跨文件补全（P2，已确认纳入）**：`use "` 字符串位异步补全零件名（展示 `file_key`）。数据复用既有 `designsApi.list(wid, { kind, folder })`（ADR 0086 文件库列表，无新端点）；由 `DesignEditorPage` 注入获取函数（首次触发懒加载 + 会话内缓存），`DslEditor` 保持展示组件定位（函数经 props 传入，不直接 import api 层）。

**交互**：标识符字符输入自动触发 + `Ctrl+Space` 手动唤起；候选 `detail` 用中文一句话说明（如 `box` → `size=[x,y,z] 或 w/h/d`）；只读 viewer 不挂补全扩展。

**分期**：P0 关键字 / 图元 / 函数补全 + 片段 + 高亮对齐 + 触发交互；P1 上下文感知 + 变量提取（param / module / 形参 / 实例标签）；P2 零件名跨文件补全（`use "` 字符串位异步补全）。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「自动完成（…关键字）」 | 关键字补全覆盖后端语法面全集：语句 `param/module/system/use/as/constraint`、布尔 `union/difference/intersection`、变换 `translate/rotate/scale/mirror`、图元六种、约束类型 `fixed/coincident/concentric/distance/angle`、锚点 `origin/x/y/z`、白名单函数 14 个 + `PI`；口径以 `parse.py` 为准 | `frontend/src/pages/design/designCompletion.ts`、`designLang.ts` | 前端单测：候选集合与后端常量逐项一致（硬编码期望清单） |
| C2 | 「自动完成（变量…）」 | 变量补全从当前文档本地提取：顶层 `param` 名（表达式位）、`module` 名（调用位）及其形参名（调用括号内）、`use ... as` 实例标签（`constraint` 引用端）；不新增后端端点 | `designCompletion.ts` | 前端单测：示例 DSL（含注释 / 嵌套干扰行）提取结果正确 |
| C3 | 「自动完成」 | 上下文感知：顶层位只出语句关键字 + 骨架片段；表达式位出变量 + 函数 + `PI`；`constraint` 行出约束类型 + 锚点；判定用行首缩进与前文 token 轻量规则，误差不阻断输入（后端诊断兜底） | `designCompletion.ts` | 前端单测：同一文档不同光标位候选集合分流正确 |
| C4 | 「代码片段插入等」 | 片段集：`param`/`module`/`system`/`use`/`constraint` 骨架 + 六图元带签名模板（`box(size = [w, d, h])` / `cyl(d, h)` / `sphere(r)` / `cone(d1, d2, h)` / `torus(r, tube)` / `tube(od, id, h)`，与 `_eval_*` 形参一致）+ 四变换骨架；用 `snippet()` 槽位语法，`Tab` 跳转 | `designCompletion.ts` | 前端单测：片段展开文本与槽位位置；e2e 触发补全并插入 |
| C5 | 「功能增强」 | 交互：标识符输入自动触发 + `Ctrl+Space` 手动；候选 `detail` 中文一句话；只读 viewer 不挂补全扩展 | `DslEditor.tsx` | 前端单测：readOnly 下无补全扩展；e2e 输入触发补全菜单 |
| C6 | （高亮口径对齐） | `designLang.ts` 关键字表补 `use/as/constraint/约束类型/锚点`（ADR 0086 后端口径），补全与高亮共用同一导出常量（单一来源） | `designLang.ts` | 前端单测：`identStyle` 对新增关键字返回 `keyword`/`atom` |
| C7 | （依赖） | 新增依赖 `@codemirror/autocomplete`（CodeMirror 官方包，版本 6.x） | `frontend/package.json`、`uv` 无涉 | `make check-fast`（lock 更新 + 前端构建门禁） |
| C8 | （测试与门禁） | 测试分层：`designCompletion.test.ts`（上下文判定 / 候选集合 / 变量提取 / 片段展开）、`designLang.test.tsx` 更新、e2e 新增 1 条（输入 → 补全菜单 → 选择插入 → 预览不回归） | `frontend/src/pages/design/`、`frontend/tests/e2e/critical/` | `make flow` 全绿 |
| C9 | （文档口径） | CHANGELOG 记增强条目；帮助文档快速上手补一句补全用法（可选） | `CHANGELOG.md`、`frontend/src/pages/help/content/quickStart.tsx` | `make check-docs` |
| C10 | 「等」（用户确认纳入，P2） | 零件名跨文件补全：`use "` 字符串位异步补全零件 `file_key`；数据复用既有 `designsApi.list(wid, { kind, folder })`，无新端点；`DesignEditorPage` 注入获取函数（首次触发懒加载 + 会话内缓存），`DslEditor` 经 props 接收不 import api 层；请求失败静默降级为无候选（不弹错） | `DesignEditorPage.tsx`、`DslEditor.tsx`、`designCompletion.ts`、`frontend/src/api/design.ts`（只读引用） | 前端单测：mock list 返回后字符串位候选正确、请求失败空候选；e2e 并入 C8 用例 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 编辑器扩展数组（挂补全入口） | `frontend/src/pages/design/DslEditor.tsx:75-89` | C5 在 extensions 数组按 readOnly 条件挂 `autocompletion` |
| 2 | 高亮关键字表落后于后端 | `frontend/src/pages/design/designLang.ts:14-27` | C6：缺 `use`/`as`/`constraint`/约束类型/锚点（ADR 0086 D2-D4 新增） |
| 3 | 后端语法常量（口径来源） | `src/cndb/plugins/design/services/dsl/parse.py:43-63` | C1/C6 对齐基准，只读引用不改 |
| 4 | 图元求值签名（片段模板来源） | `src/cndb/plugins/design/services/dsl/compile.py:253-349` | C4 片段形参与 `_eval_*` 一致 |
| 5 | 编辑器宿主页 | `frontend/src/pages/design/DesignEditorPage.tsx` | P0/P1 补全在 DslEditor 内部闭环；P2 由宿主注入零件名获取函数（C10） |
| 6 | 依赖清单 | `frontend/package.json:36-41` | C7 已有 5 个 codemirror 包，缺 `@codemirror/autocomplete` |
| 7 | 既有设计 e2e（回归面） | `frontend/tests/e2e/critical/design-*.spec.ts` | C8 新增用例不破坏既有编辑器流程 |
| 8 | 文件库列表 API（P2 数据源） | `frontend/src/api/design.ts:214-215`（`designsApi.list`，含 `kind`/`folder` 过滤与 `file_key`） | C10 复用，无新端点 |

## 未决问题（已确认）

- [x] ① `use "..."` 字符串内的零件名跨文件补全：**结论**纳入本期 P2（2026-11-06 用户拍板），复用 `designsApi.list`，宿主页注入获取函数 + 缓存（C10）。
- [x] ② 方案分级：**结论** S1（纯前端交互增强，无数据模型 / 权限 / 架构分叉，方案并入本卡片，不写 ADR，2026-11-06 用户确认）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-06 用户拍板）
