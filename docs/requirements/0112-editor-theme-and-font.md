# 需求卡片：DSL / 流水线编辑器可配置配色与字体

- 编号：0112
- 来源 / 提出人：用户（会话 2026-11-06）
- 日期：2026-11-06
- 关联 ADR：无（S1，方案并入本卡片；编辑器底座见 ADR 0076 与需求 0110 / 0111）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> DSL编辑器和流水线编辑器的配色和字体太难看，请结合编辑器的最佳实践设计可用的主题供选用，并在用户个人设置的主题面板提供配置项。

## 方案（口径）

**问题现状**：`design/DslEditor.tsx` 与 `pipelines/PipelineDslEditor.tsx` 都硬编码 `oneDark` + `defaultHighlightStyle`，且 `.cn-dsl-editor .cm-scroller` 写死字号；个人设置里只能切换全站主题与正文字号，两个编辑器不跟随、也无法单独调。

**分层**：新增 `frontend/src/theme/editorThemes.ts`（配色色板 + CodeMirror 6 主题 / 语法高亮）与 `frontend/src/theme/editorSettings.ts`（设置类型、默认值、localStorage 读写），由 `ThemeProvider` 统一持有并暴露 `updateEditorSettings`；编辑器通过 `useEditorAppearance()` 订阅，用 `Compartment.reconfigure` 热更新，不重建视图。

**主题集合**（编辑器最佳实践：一套浅色 + 一套深色为底，再给低对比护眼与无障碍选项）：

| ID | 名称 | 明暗 | 定位 |
|---|---|---|---|
| `auto` | 跟随应用 | 随全站 | 默认；按应用主题明暗落到 GitHub 同族 |
| `github-light` | GitHub 浅色 | 浅 | 白底低饱和，长读不刺眼 |
| `github-dark` | GitHub 深色 | 深 | 与 GitHub 代码视图一致 |
| `one-dark` | One Dark | 深 | Atom 经典深色，分层明显 |
| `solarized-light` | Solarized 浅色 | 浅 | 米色底低对比，护眼 |
| `solarized-dark` | Solarized 深色 | 深 | 深青底暖关键字 |
| `high-contrast` | 高对比 | 深 | 纯黑底高亮文字，弱光 / 视力辅助 |

每个色板同时定义背景 / 行号槽 / 当前行 / 选区 / 光标 / 边框 / 关键字 / 字符串 / 注释 / 数字 / 函数 / 类型 / 运算符 / 属性 / 变量 / 错误色，并覆盖补全弹层、搜索命中、括号匹配与面板，避免只换背景导致浮层仍为亮色。

**字体**：提供 `JetBrains Mono`（默认，带连字）、`Cascadia Code`、`Maple Mono`、`系统等宽` 四档；Cascadia Code / Maple Mono 随设置面板 / 编辑器 chunk 按需加载，不进首屏入口；字号提供「跟随全站」与 12 / 13 / 14 / 15 / 16 px。字号跟随全站时取 `1em`，与个人设置里的全站字号档位联动。`Inter` 只作为全站 UI 字体，不再作为编辑器字族提供。

**设置入口**：个人设置新增独立的「编辑器」页签（排在「文档」之后）：配色 / 字体 / 字号三个下拉 + 一段实时预览（纯 DOM 渲染，不加载 CodeMirror）；页签内「恢复默认」只重置编辑器设置，不影响全站主题与字体。

**持久化**：`localStorage['cndb_editor_settings'] = { theme, font: { family, size } }`；读取时逐字段校验，脏数据 / 异常回退默认（`auto` / `jetbrains` / `auto`）。

**口径边界**：只影响两个 CodeMirror 编辑器；文档 Markdown 编辑器与全站字体设置不在本期范围。

**分期**：P0 色板与外观扩展 + 两个编辑器接入热更新；P1 个人设置「编辑器」节 + 预览 + 恢复默认；P2 单测补齐与门禁。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「配色和字体太难看」 | 两个编辑器不再硬编码 `oneDark` / `defaultHighlightStyle` / 固定字号，改为读取编辑器外观设置；全站主题变化时 `auto` 即时重算 | `DslEditor.tsx`、`PipelineDslEditor.tsx`、`theme/editorThemes.ts` | 前端单测：`auto` 明暗解析；编辑器重配不重建视图 |
| C2 | 「结合编辑器的最佳实践设计可用的主题」 | 至少 6 套固定主题（浅 / 深各 ≥ 2）+ `auto`；每套完整定义编辑区、行号槽、当前行、选区、光标、补全弹层与语法语义色 | `theme/editorThemes.ts` | 前端单测：主题清单 / 元信息 / 色板完整性 |
| C3 | 「字体」 | 字体族 4 档（JetBrains Mono 默认 / Cascadia Code / Maple Mono / 系统等宽），字号 5 档 + 跟随全站；通过 CodeMirror 主题下发，CSS 不再写死 `.cm-scroller` 字号 | `theme/editorSettings.ts`、`theme/editorFontAssets.ts`、`index.css` | 前端单测：设置读写与默认值、字体资产 / 按需加载；lint / 构建门禁 |
| C4 | 「在用户个人设置提供编辑器配置」 | 「编辑器」独立页签（位于「文档」之后）：配色 / 字体 / 字号三项可独立选择、即时生效、自动持久化、附实时预览；「恢复默认」只重置编辑器设置 | `pages/settings/SettingsModal.tsx` | 组件测试：选项变更写 `cndb_editor_settings`、预览随配色变化、恢复默认 |
| C5 | （容错） | `localStorage` 缺失 / 损坏 / 旧字段不合法时逐字段回退默认，不白屏；设置项变更不触发编辑器重建 | `theme/editorSettings.ts`、`ThemeProvider.tsx` | 前端单测：脏数据回退；编辑器视图实例复用 |
| C6 | （测试与文档） | 覆盖色板 / 设置读写 / Provider 状态 / 设置面板 / 编辑器接入；CHANGELOG 记条目 | `frontend/src/theme/`、`pages/settings/`、`CHANGELOG.md` | `make flow` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 设计 DSL 编辑器外观 | `frontend/src/pages/design/DslEditor.tsx` | 原有 oneDark 与诊断行底色保持可用 |
| 2 | 流水线 DSL 编辑器外观 | `frontend/src/pages/pipelines/PipelineDslEditor.tsx` | 补齐行号 / 补全不动 |
| 3 | 个人设置主题页 | `frontend/src/pages/settings/SettingsModal.tsx` | 新增节不影响既有主题卡片与字体节 |
| 4 | 全站主题与字体 | `frontend/src/theme/theme.ts`、`ThemeProvider.tsx` | 编辑器设置独立持久化，不改全站口径 |
