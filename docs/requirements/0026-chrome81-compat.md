# 需求卡片：Chrome 81 兼容基线

- 编号：0026（与 ADR `docs/adr/0026-chrome81-compat.md` 同号）
- 来源 / 提出人：用户（2026-10-24 会话）
- 日期：2026-10-24
- 关联 ADR：`docs/adr/0026-chrome81-compat.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 重大需求，最低需要支持CHROME 81版本也能打开

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「也能打开」 | Chrome 81 打开生产构建首页不白屏、无未捕获 JS 异常；登录后可进入工作区 | `frontend` 构建与入口 | Chromium 81 冒烟脚本 |
| C2 | 「支持」 | antd 5 运行时样式不得因 `:where()` / 逻辑属性 / `inset` 在 Chrome 81 整条失效，组件视觉与现版一致 | `frontend/src/theme/ThemeProvider.tsx` | 生成样式断言 + 视觉快照 |
| C3 | 「支持」 | 10 套主题下 `color-mix()` 派生颜色在 Chrome 81 与现版一致 | `frontend/src/index.css`、`frontend/src/theme/` | 颜色单测 + 主题视觉快照 |
| C4 | 「支持」 | flex 布局 `gap`（含 antd Space / Grid 与业务内联样式）在 Chrome 81 与现版一致；grid gap 原生支持不处理 | `frontend/src/compat/`、`frontend/src/index.css` | 布局尺寸断言 + 视觉快照 |
| C5 | 「支持」 | 登录、工作区 / 数据表浏览与编辑、视图切换、文档打开、PDF / 截图导出在真实 Chromium 81 上通过 | `frontend/scripts/`、`frontend/tests/` | `pnpm e2e:chrome81` |
| C6 | 「最低 CHROME 81」 | 基线为 Chrome / Edge 81+ 及 Chromium 81+ 内核（360、QQ 等按内核版本对齐）；不承诺 Firefox / Safari | `frontend/.browserslistrc`、README | 基线文档 + 门禁 |
| C7 | 「重大需求」 | 构建后静态检查 + 真实 Chromium 81 冒烟；新增越界语法 / API / CSS 特性必须失败 | `frontend/scripts/check-browser-compat.mjs`、CI | 门禁命令退出码 |
| C8 | 「支持」 | 现代浏览器不回归：现有 Playwright e2e 全绿；关键 chunk 包体不超基线（调整须按 bundle-budget 流程记录理由） | `frontend/tests/e2e/`、`frontend/scripts/bundle-budget.mjs` | `make e2e`、`pnpm bundle:budget` |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 构建目标 | `frontend/vite.config.ts:154` | `target: 'es2022'`，Chrome 81 无法解析部分 ES2022 语法 |
| 2 | antd CSS-in-JS | `frontend/src/theme/ThemeProvider.tsx:102` | `:where()`（Chrome 88+）、逻辑属性（87+）、`inset`（87+）会导致整条规则失效 |
| 3 | 运行时 API | `frontend/src/utils/webVitals.ts:14`、`frontend/src/pages/import-export/ImportExportDialog/exportPdf.ts:198` | `Object.hasOwn`、`structuredClone`、`Array.prototype.at`、`Intl.Segmenter` 在 Chrome 81 缺失 |
| 4 | 主题派生色 | `frontend/src/index.css:176` 等 95 处、TSX 28 处 | `color-mix()` 需 Chrome 111+ |
| 5 | flex 间距 | `frontend/src/index.css` 124 处、TSX 209 处 | flex `gap` 需 Chrome 84+；antd Space / Grid 也使用 `rowGap` / `columnGap` |
| 6 | 焦点样式 | `frontend/src/index.css:534` 等 5 处 | `:focus-visible` 需 Chrome 86+ |
| 7 | 兼容门禁 | `frontend/package.json:8`、`Makefile` 的 `frontend-build` | 当前无任何浏览器基线检查 |

## 未决问题

- [x] 兼容深度：视觉一致（2026-10-24 已确认）
- [x] 浏览器口径：Chromium 系为主（2026-10-24 已确认）
- [x] 回归方式：真实 Chromium 81 + 静态门禁（2026-10-24 已确认）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认
