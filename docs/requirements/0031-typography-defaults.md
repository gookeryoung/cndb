# 需求卡片：默认字体口径与全站排版改进

- 编号：0031（与 ADR `docs/adr/0031-font-and-css-typography.md` 同号）
- 来源 / 提出人：用户反馈（本地会话）
- 日期：2026-10-25
- 关联 ADR：`docs/adr/0031-font-and-css-typography.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 默认字体为标准、不加粗。请对照`https://docs.trae.cn/`，页面的字体和风格优势，制定字体和CSS改进计划。

补充决策（2026-10-25，用户评审）：

> 引入 docs.trae.cn 的展示字体（Outfit）与等宽字体（JetBrains Mono），继续完善ADR

补充决策（2026-10-25，用户评审）：

> `/root/cndb/frontend/public/fonts`还有无用途，是否可移除。
>
> 结论：改用 `@fontsource/inter` 运行时依赖后删除整个目录（Latin 字形不变，中文改用系统字体）。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 默认字体为标准 | 新用户 / 未持久化字体偏好时，字号档位固定为 `standard`（14px），首帧与 `localStorage` 回读结果一致 | `frontend/src/theme/fonts.ts`、`frontend/src/theme/ThemeProvider.tsx` | 单测断言默认 `scale=standard`、`body.fontSize=14px` |
| C2 | 不加粗 | 未持久化字体偏好时，正文默认字重 400；不得通过 `body` 继承或 antd token 把全站默认抬到 600 | `frontend/src/theme/fonts.ts`、`frontend/src/theme/ThemeProvider.tsx`、`frontend/src/theme/presets/common.ts` | 单测断言默认 `bold=false`、`body.fontWeight=400`、antd `fontWeightStrong=600` |
| C3 | 对照 `https://docs.trae.cn/` 页面的字体和风格优势 | 按「字体族 / 字重层级 / 行高 / 字距 / 等宽」五个维度给出对照结论，并逐项落到本仓可执行改动 | `frontend/src/index.css`、`frontend/src/theme/` | ADR「行业对照」表 + 字体栈 / 字重变量断言 |
| C4 | 制定字体和CSS改进计划 | 输出分期计划（默认口径 → 字重与字体族标尺 → 字体资产与展示字体 → 等宽与阅读打磨），每期含改动文件、测试与验收；计划评审通过前不改代码 | `docs/adr/0031-font-and-css-typography.md` | ADR 评审 + `make check-docs` |
| C5 | （隐含）保留用户可选偏好 | 「全局加粗」开关与字号档位仍可手动切换并持久化；已显式选择加粗的用户不被迁移为不加粗 | `frontend/src/pages/settings/SettingsModal.tsx`、`frontend/src/theme/ThemeProvider.tsx` | 单测覆盖开 / 关双向持久化；`loadFontSettings` 旧值兼容 |
| C6 | 引入 Outfit 与 JetBrains Mono | 两套字体以 npm 运行时依赖引入（`@fontsource/outfit`、`@fontsource/jetbrains-mono`），入口按 latin 子集四档字重（400/500/600/700）导入 CSS；不引 CDN、不用变量字体 | `frontend/package.json`、`frontend/src/main.tsx`、`frontend/src/index.css` | `fontAssets.test.ts`（依赖声明 / 安装文件非空 / 入口字重导入）+ e2e `document.fonts.check` |
| C7 | `public/fonts` 是否可移除 | Inter 同样改为 `@fontsource/inter` 运行时依赖（latin 四档），删除 `frontend/public/fonts` 整个目录；中文不再由 web font 覆盖，改由浏览器按系统字体逐字回退；字体栈同步去掉 Noto Sans SC | `frontend/package.json`、`frontend/src/main.tsx`、`frontend/src/index.css`、`frontend/src/theme/tokens.ts` | `fontAssets.test.ts`（三依赖声明 / 入口导入 / 目录不存在）+ `make frontend-build` 产物无 `/fonts/` 引用 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 字体默认值 | `frontend/src/theme/fonts.ts:30` | `DEFAULT_FONT_SETTINGS.bold = true` |
| 2 | 全站正文继承字重 | `frontend/src/theme/ThemeProvider.tsx:91-94` | 默认把 `body.fontWeight` 设为 600 |
| 3 | antd 强调字重 | `frontend/src/theme/ThemeProvider.tsx:119-124` | 加粗时 `fontWeightStrong` 抬到 700 |
| 4 | 字重字面量 | `frontend/src/index.css`、`frontend/src/**/*.tsx` | 51 条 CSS 规则 + 64 处行内 `fontWeight` 无标尺约束 |
| 5 | 字体族不一致 | `frontend/src/theme/presets/common.ts:27-28` | antd token 用系统栈，`body` 用 Inter/Noto，组件与正文可能不同字体 |
| 6 | 等宽字体变量 | `frontend/src/index.css` | `--cn-mono` / `--cn-font-sans` 引用但未定义 |
| 7 | 字体资产 | `frontend/public/fonts/`、`frontend/package.json` | 仅有 Inter / Noto Sans SC 的 woff2，无 Outfit / JetBrains Mono 依赖与文件 |

## 未决问题

- [x] 是否引入 docs.trae.cn 的展示字体（Outfit）与等宽字体（JetBrains Mono）？结论：引入（用户 2026-10-25 决策）；本地托管静态子集，附 OFL 1.1，详见 ADR D6 / D9。
- [x] 引入后是否新增运行时依赖？结论：新增 `@fontsource/outfit` 与 `@fontsource/jetbrains-mono` 两个运行时依赖（用户 2026-10-25 决策），只导入 latin 子集，版本随 lock 锁定。
- [x] `frontend/public/fonts` 是否仍有用途？结论：无。Inter 迁到 `@fontsource/inter`，Noto Sans SC 实测仅覆盖 177 个字符，整个目录删除，中文改走系统字体（用户 2026-10-25 决策）。

## 卡点

- [x] 每条需求句都有 C 编号约束（C1..C7）
- [x] 未决问题全部有结论，待需求方确认卡片

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。
