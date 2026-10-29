# 需求卡片：主题支持「跟随系统」（auto 模式）

- 编号：0066（与 ADR `docs/adr/0066-*.md` 同号，卡片存 `docs/requirements/0066-follow-system-theme.md`）
- 来源 / 提出人：用户（GitHub 对齐分析 · 差距 1：主题不跟随系统）
- 日期：2026-10-29
- 关联 ADR：<立项后回填>

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 主题支持持久化 auto 模式：跟随系统明暗（prefers-color-scheme）自动在浅色/深色主题间切换，来源为上一轮 GitHub 对齐分析差距 1。

（上下文补充——上一轮方案原句：「`THEME_MODES` 增加虚拟主题 `'auto'`（meta 标记 `isVirtual`），`ThemeProvider` 监听 `matchMedia('(prefers-color-scheme: dark)')`，浅色落 `github-light`（或 modern）、深色落 `github-dark`，系统切换时实时切换；默认主题改为 `auto`，用户显式选择后覆盖。不新增任何 CSS 变量，复用既有 10 套预设。」）

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 持久化 auto 模式 | `THEME_MODES` 增加 `'auto'` 作为可选持久化值；`loadThemeMode` 接受并返回它，`saveThemeMode` 可写入；localStorage 存 `auto` 本身（存解析结果则系统切换后失效） | `frontend/src/theme/`（meta.ts、theme.ts） | `theme.test.ts` 新增用例：写入/读回 `auto`；非法值仍兜底 |
| C2 | 虚拟主题 meta 标记 | `auto` 不进入 10 套实际主题集合：`THEME_META` 不含 `auto`（或含仅用于 UI 的虚拟条目），`getThemeConfig('auto')` 无效；body class / CSS 变量始终由解析后的实际主题驱动 | `frontend/src/theme/meta.ts`、`theme.ts`、`ThemeProvider.tsx` | `theme.test.ts`：`THEME_META` 键集合断言；`tokens.test.ts` 不受影响 |
| C3 | 跟随系统明暗自动切换 | `ThemeProvider` 内部维护「持久化值」与「生效主题」两层状态：持久化值为 `auto` 时，按 `matchMedia('(prefers-color-scheme: dark)')` 实时解析为 `github-dark` / `github-light`，监听 change 事件实时重渲染；持久化值为具体主题时行为与现状完全一致 | `frontend/src/theme/ThemeProvider.tsx` | `ThemeProvider.test.tsx`：mock matchMedia，切换 change 事件断言 body class 跟随；显式主题用例回归 |
| C4 | 浅色落点 | auto 解析的浅色主题 = `github-light`（非 modern：与深色落点同族，避免 auto 两态观感割裂） | `frontend/src/theme/ThemeProvider.tsx` | 单测断言浅色解析结果 |
| C5 | 默认主题改为 auto | `DEFAULT_THEME_MODE` 改为 `'auto'`（首次访问无 localStorage 时跟随系统）；「恢复默认」按钮同步落到 auto | `theme.ts`、`SettingsModal.tsx` | `theme.test.ts` 默认值断言更新 |
| C6 | 用户显式选择后覆盖 | 用户在设置弹窗或用户菜单选中任一具体主题（含本次已上线的三档快捷项）即持久化该具体主题，auto 不再生效，直到用户再次选择「跟随系统」 | `ThemeProvider.tsx`、`SettingsModal.tsx`、`MainLayout.tsx` | `ThemeProvider.test.tsx`：显式 setMode 后 matchMedia 变化不影响生效主题 |
| C7 | 主题选择 UI 补 auto 档 | 设置弹窗主题选择器与用户菜单「主题」子菜单的「跟随系统」项均写入 `auto`（快捷菜单三档语义从「点一下落具体主题」升级为「跟随系统=持久化 auto」）；选择器需展示 auto 当前解析到的实际主题 | `SettingsModal.tsx`、`MainLayout.tsx` | 组件单测 |
| C8 | 不新增 CSS 变量 | 复用既有 10 套预设与 `--cn-*` 变量，`index.css` 无新增主题块 | `frontend/src/index.css` | `tokens.test.ts` 全绿即视为满足 |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 主题持久化读写 | `frontend/src/theme/theme.ts:58-77`（`DEFAULT_THEME_MODE`、`loadThemeMode`/`saveThemeMode`） | 增加 `auto` 合法值与默认值 |
| 2 | 主题元信息 | `frontend/src/theme/meta.ts`（`THEME_MODES`、`THEME_META`） | `auto` 为虚拟档，不挂 bodyClass |
| 3 | 主题生效逻辑 | `frontend/src/theme/ThemeProvider.tsx:49-105` | 两层状态 + matchMedia 监听 |
| 4 | 设置弹窗主题选择器 | `frontend/src/pages/settings/SettingsModal.tsx:267-313` | 增加 auto 档 + 「恢复默认」落 auto |
| 5 | 用户菜单主题三档（本次 0b83cca3 新增） | `frontend/src/layouts/MainLayout.tsx:384-401` | 「跟随系统」改写 `auto`（C7） |
| 6 | 兼容老值 | `theme.ts:64-66` `LEGACY_MAP` | `auto` 不影响 legacy 映射 |
| 7 | e2e 关键路径 | `frontend/tests/e2e/` | 主题无 e2e 断言，预计不受影响（ADR 核实） |

## 未决问题

- [x] auto 的浅色落点用哪套？→ 结论：`github-light`（C4，与深色落点同族；如需 modern 可后续只改一处映射）。
- [x] 默认主题是否改 auto？→ 结论：改（C5），与 GitHub 首访行为一致；老用户 localStorage 已有具体值，不受影响。
- [x] 首帧闪烁风险？→ 结论：`ThemeProvider` 已用 `useLayoutEffect` 同步挂 class（ThemeProvider.tsx:83-89），matchMedia 解析在 layout effect 内完成即可，无新增闪烁面；ADR 精查确认。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（用户已在方案评审中批准按序推进，本卡按已确认口径编写；如对 C4/C5 有异议请指出，改卡后再进 ADR）
