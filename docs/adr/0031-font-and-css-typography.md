# ADR 0031: 全站字体与 CSS 排版口径（默认标准字号 / 正文常规字重 / Outfit + JetBrains Mono）

Status: Accepted
Date: 2026-10-25
Related: `frontend/src/theme/fonts.ts`、`frontend/src/theme/ThemeProvider.tsx`、`frontend/src/theme/tokens.ts`、`frontend/src/theme/theme.ts`、`frontend/src/theme/presets/common.ts`、`frontend/src/index.css`、`frontend/src/main.tsx`、`frontend/package.json`、`frontend/src/pages/settings/SettingsModal.tsx`、`frontend/src/theme/tokens.test.ts`、`frontend/src/theme/ThemeProvider.test.tsx`、`frontend/src/theme/fontAssets.test.ts`、`frontend/tests/e2e/critical/typography.spec.ts`、`frontend/index.html`
需求卡片: `docs/requirements/0031-typography-defaults.md`

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 默认字体为标准 | 默认 `scale=standard` 现状已满足，本期只加回归锁：`DEFAULT_FONT_SETTINGS.scale` 与 `body.fontSize=14px` 双向断言 |
| C2 | 不加粗 | `DEFAULT_FONT_SETTINGS.bold=false`；`body.fontWeight` 未开启加粗时显式 `400`，开启时 `600`；antd `fontWeightStrong` 默认 600、开启加粗时 700 |
| C3 | 对照 docs.trae.cn 的字体与风格优势 | 取「Inter 正文 / 400 正文 + 600 标题 + 700 仅大标题 / 阅读 1.7-1.75 行高 / 拉丁大标题负字距 / Outfit 展示字体 / JetBrains Mono 等宽」七点；逐点映射见 §3-§5 与「行业对照」 |
| C4 | 制定字体和CSS改进计划 | P0 默认口径 → P1 字重与层级标尺 → P2 字体族与 Outfit → P3 JetBrains Mono 与阅读打磨；每期给文件、测试与验收，见 §7-§8 |
| C5 | （隐含）保留用户可选偏好 | 开关语义不变；仅未持久化用户受影响，已显式选加粗的用户保持原值，见 §6 |
| C6 | 引入 Outfit 与 JetBrains Mono | npm 运行时依赖 `@fontsource/outfit` 与 `@fontsource/jetbrains-mono`，入口只导入 latin 子集 400/500/600/700 的 CSS；不引 CDN、不用变量字体，见 §4 |

## Context

现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `DEFAULT_FONT_SETTINGS = { scale: 'standard', bold: true }` | `frontend/src/theme/fonts.ts:30` | 新用户首进即「全局加粗」，与「默认不加粗」相反 | 确认（C2 根因） |
| 2 | 字体设置生效时默认把 `document.body.style.fontWeight` 写成 `600` | `frontend/src/theme/ThemeProvider.tsx:91-94` | `body` 的 600 被全站继承，正文、表格、表单标签全部变重 | 确认（C2 直接后果） |
| 3 | 开启加粗时 antd `fontWeightStrong` 抬到 700 | `frontend/src/theme/ThemeProvider.tsx:119-124` | 加粗态下标题与强调再叠一层，层级更平 | 确认（C2 附带） |
| 4 | 默认字号档位已是 `standard`（14px） | `frontend/src/theme/fonts.ts:16-21`、`frontend/src/theme/tokens.ts:52-53` | C1 现状已满足，无需改值 | 排除（C1 仅需回归锁） |
| 5 | `index.css` 共 51 条 `font-weight` 规则：600×27、500×15、400×5、700×3，无变量与门禁 | `frontend/src/index.css` | 字重靠各规则各自决定，无法统一审计；`tokens.test.ts` 只拦字号 / 圆角 / 间距 | 确认（C3/C4 缺口） |
| 6 | 行内 `fontWeight` 字面量 64 处，分布在 25 个文件（FieldManager 6、FileImportPreview 5 等） | `frontend/src/pages/**/*.tsx` | 行内写死 500/600，页面之间同层级粗细不一致 | 确认（C4 缺口） |
| 7 | antd token 的 `fontFamily` 是系统栈，`body` 是 Inter + Noto Sans SC | `frontend/src/theme/presets/common.ts:27-28`、`frontend/src/index.css:126` | antd 组件（按钮 / 表格 / 表单）与正文可能显示不同字体，中英混排跳变 | 确认（C3 字体族） |
| 8 | `--cn-font-sans` 与 `--cn-mono` 被引用但从未定义，等宽字体字面量重复 9 处 | `frontend/src/index.css:545`、`frontend/src/components/Document/MarkdownLiveEditor.tsx:510` | 等宽栈各写各的，注释里写的「统一兜底」实际未生效 | 确认（C3 等宽） |
| 9 | 文档阅读区已是 1.75 行高，编辑器标题 700 且 em 级字号 | `frontend/src/components/Document/MarkdownPreview.tsx:258`、`frontend/src/components/Document/MarkdownLiveEditor.tsx:511-521` | 阅读节奏已接近 docs.trae.cn，不需要推翻 | 排除（C3 行高已达标） |
| 10 | 本地字体目录只有 Inter（8 文件 244KB）与 Noto Sans SC（4 文件 132KB），无 Outfit / JetBrains Mono，也未声明相关依赖 | `frontend/public/fonts/`、`frontend/package.json` | 无法使用 docs.trae.cn 的展示与等宽字体 | 确认（C6 缺口） |
| 11 | docs.trae.cn 主页：`--body:'Inter',-apple-system,"PingFang SC","Microsoft YaHei"`、`--disp:'Outfit','Instrument Sans'`、`--mono:'JetBrains Mono'`；body 400 / line-height 1.7；大标题 700 且 `letter-spacing:-0.02em`；正文页 14px / line-height 1.6 | 外部站点（2026-10-25 抓取其 CSS 变量） | 提供「正文常规、层级清晰、阅读松弛、展示与等宽分工」的完整参照 | 确认（C3/C6 参照） |
| 12 | `index.html` 无任何字体 preload，字体全部 `font-display: swap` | `frontend/index.html`、`frontend/src/index.css:19-111` | 新增字体沿用同一加载策略，不阻塞首屏 | 新增（C6 加载策略） |

**核心缺陷**：默认把正文钉在 600，导致「正文 = 标题」的字重层级塌陷；同时字重没有标尺、字体族在 antd 与 `body` 之间分叉、缺少展示与等宽两档字体，使 docs.trae.cn 那套「400 正文 + 600 标题 + 700 大标题 + Outfit 展示 + JetBrains Mono 等宽」的层级无法稳定复现。

设计目标（不变量）：

- **I1 默认常规**：未持久化字体偏好时，正文计算字重为 400，全站默认不出现 600 继承。
- **I2 字重四档**：只允许 400 / 500 / 600 / 700；CSS 走 `var(--cn-weight-*)`，TSX 走 `WEIGHT.*`，`@font-face` 例外。
- **I3 层级唯一**：正文 400、次级标签与表头 500、标题与实体名 600、仅大标题（文档 h1 与空态标题）700。
- **I4 字号不变**：默认 14px 与用户字号档位语义保持不变，不因本次调整改变控件尺寸。
- **I5 行高分工**：密集 UI 保持 1.5714，文档阅读保持 1.75；不把表格行高拉松。
- **I6 字体全本地**：Inter / Outfit / JetBrains Mono 全部走 npm 运行时依赖（`@fontsource/*`）并被打进产物；仓库不保留 `public/fonts` 本地字体，中文由系统字体回退；零外链，不使用变量字体（Chrome 81 安全）。

## Decision

### 1. 默认字体口径（前端）

| 项 | 现状 | 改为 | 验收 |
|---|---|---|---|
| 默认设置 | `{ scale:'standard', bold:true }` | `{ scale:'standard', bold:false }` | `theme.test.ts` 默认值断言 |
| 未加粗时 `body.fontWeight` | `''`（继承 UA 默认） | 显式 `'400'` | `ThemeProvider.test.tsx` 断言 |
| 加粗时 `body.fontWeight` | `'600'` | 保持 `'600'` | 同上 |
| antd `fontWeightStrong` | 加粗时 700；否则 antd 默认 600 | 未加粗显式 600，加粗 700 | 主题 token 断言 |
| 设置页「恢复默认」 | 依赖 `DEFAULT_FONT_SETTINGS` | 自动变为「标准 + 不加粗」 | `SettingsModal.test.tsx` |

### 2. 字重标尺

`tokens.ts` 新增：

```ts
export const WEIGHT = {
  regular: 400,
  medium: 500,
  semibold: 600,
  bold: 700,
} as const
```

`CSS_VARS` 同步新增 `--cn-weight-regular` / `--cn-weight-medium` / `--cn-weight-semibold` / `--cn-weight-bold`，并在 `index.css` 的 `:root` 标尺块声明。`tokens.test.ts` 增加两条：

1. 四个字重变量存在且数值一致；
2. `index.css` 的 `font-weight` 只允许 `var(--cn-weight-*)`，**扫描前先剥离 `@font-face` 块**（字体资源必须写字面量）。

### 3. 字重层级收敛

| 类目 | 目标字重 | 现有落点 |
|---|---|---|
| 正文 / 段落 / 表格单元格 / 表单值 | 400 | `body` 继承，`Table.cellFontSize` 等 |
| 表头、行名、实体名、计数 | 500 | `.cn-table-list .ant-table-thead > tr > th`、`.cn-table-crumb-name`、`.cn-ws-row-name`、`.cn-user-card-name`、`.cn-table-list-card-name`、`.cn-agg-count`、`.cn-selection-count` |
| 页面 / 分区 / 卡片标题、激活态 | 600 | `.cn-ws-group-head`、`.cn-ws-detail-section-head`、`.cn-myviews-title`、`.cn-admin-title`、`.cn-admin-rail-title`、`.cn-admin-pill-active`、`.cn-help-docs-heading`、`.cn-help-docs-brand`、`.cn-an-head-title`、`.cn-an-box-title`、`.cn-gs-group-title`、`.driver-popover-title` |
| 大标题 / 品牌字 / 语义符号 | 700 | `.cn-brand-mark`、文档 h1、`.cn-fielddiff-sign-add` / `.cn-fielddiff-sign-del`（符号对比度需要） |

行内 style 同步按同一张表替换为 `WEIGHT.*`；**不保留任何「全文加粗」式用法**。

### 4. 字体资产、字体族与等宽

**资产来源（npm 运行时依赖，仅 Latin 子集）**

| 字体 | 依赖 | 版本 | 导入文件（`frontend/src/main.tsx`） | 许可 |
|---|---|---|---|---|
| Inter | `@fontsource/inter` | `^5.3.0`（lock 5.3.0） | `@fontsource/inter/latin-{400,500,600,700}.css` | SIL OFL 1.1（随包分发） |
| Outfit | `@fontsource/outfit` | `^5.3.0`（lock 5.3.0） | `@fontsource/outfit/latin-{400,500,600,700}.css` | SIL OFL 1.1（随包分发） |
| JetBrains Mono | `@fontsource/jetbrains-mono` | `^5.3.0`（lock 5.3.0） | `@fontsource/jetbrains-mono/latin-{400,500,600,700}.css` | SIL OFL 1.1（随包分发） |

字体文件由 Vite 打进构建产物；离线部署随 `pnpm install` 与镜像构建进入 `dist`，无需改动部署链路。原 `frontend/public/fonts/`（Inter 4 文件 97KB + Noto Sans SC 4 文件 126KB）已整体删除：Inter 迁到 `@fontsource/inter`，Noto Sans SC 实测仅覆盖 177 个字符（远不足 CJK 常用字），中文改由浏览器按系统字体逐字回退。

**字体栈与变量**

| 项 | 现状 | 改为 |
|---|---|---|
| `body` | 硬编码 `'Inter', 'Noto Sans SC', sans-serif` | `var(--cn-font-sans)` |
| antd `fontFamily` | `system-ui, -apple-system, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif` | 与 `body` 相同的 `var(--cn-font-sans)` |
| `:root` 字体变量 | `--cn-font-sans` / `--cn-mono` 未定义 | `--cn-font-sans: 'Inter', system-ui, sans-serif`、`--cn-font-display: 'Outfit', system-ui, sans-serif`、`--cn-font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` |
| 等宽引用 | 9 处重复字面量 + 未定义变量 | 统一 `var(--cn-font-mono)` |

**Outfit 落点（只做展示层，不替换正文）**

新增 `.cn-display` 工具类（只设字体族）与 `.cn-display-tight`（叠加 `--cn-tracking-display`，仅用于纯拉丁 / 纯数字内容）：

| 落点 | 现状 | 改为 |
|---|---|---|
| 顶栏品牌字 `cndb` | 行内 `fontWeight:700` + `letterSpacing:-0.2px`（`frontend/src/layouts/MainLayout.tsx:418`） | 新增 `.cn-brand-word`（`cn-display cn-display-tight`，700） |
| 品牌方块字母 | `.cn-brand-mark`（`index.css`） | 字号与字重不变，字体族取 `--cn-font-display` |
| KPI 大数字 | `.ts-stat-num`（`index.css:2322`） | `--cn-font-display` + 600 + `tabular-nums` |
| 未来拉丁大标题 | 无统一类 | 使用 `.cn-display`，中文段落回退系统字体 |

中文标题不套 Outfit：Outfit 只覆盖 Latin，中文会回退系统字体，混合标题的 metrics 会跳变，因此只在「品牌字 / 数字 / 拉丁大标题」这类确定内容上使用。

**JetBrains Mono 落点**

| 落点 | 现状 | 改为 |
|---|---|---|
| 文档代码块 / 行内代码 | `.cn-codeblock`、`.cm-md-code` 等字面量 | `var(--cn-font-mono)` |
| Markdown 编辑器 | `MarkdownLiveEditor.tsx:510-585` 的 mono 字面量 | `var(--cn-font-mono)` |
| 树 / 甘特 / WBS 的编号列 | `TreeView.tsx:380`、`ganttLeftColumn.tsx:101,146`、`WbsView.tsx:442` | `var(--cn-font-mono)` |
| 表格数字列 | `.font-num`（Inter + tabular-nums） | 不变（数字对齐用 Inter 即可，避免数字列观感突变） |

**加载策略**

1. `@font-face` 由 `@fontsource/*/latin-*.css` 提供，`font-display: swap`、`unicode-range` 为 latin 段，中文由系统字体逐字回退。
2. **不新增 preload**：Inter / Outfit 仅用于正文与品牌字 / KPI，JetBrains Mono 只在代码 / 编号场景按需加载；为 4 个字重加 preload 会挤占首屏带宽。
3. 依赖字体由 Vite 处理为带 hash 的静态资源，走既有静态资源链路与离线镜像，无需改 nginx。

### 5. 行高与字距

1. UI 行高继续由 `LINE.base = 1.5714` 与 antd token 下发，表格密度不变。
2. 文档阅读区保持 1.75（`MarkdownPreview` / `MarkdownLiveEditor`）。
3. 新增 `--cn-tracking-display: -0.02em`（对齐 docs.trae.cn 大标题），只用于 `.cn-display-tight`（品牌字、KPI 数字、纯拉丁大标题）；**中文标题不加负字距**。
4. `font-smoothing: antialiased` 已存在，不动。

### 6. 迁移

无数据库迁移、无存档兼容问题。

- 字体偏好只存浏览器 `cndb_font`：键不存在（绝大多数用户）→ 采用新默认 400；键存在且 `bold:true`（用户主动开过）→ 保留；字段非法 → 沿用 `loadFontSettings` 回退。
- 字体资产随前端构建产物与离线镜像分发，部署链路不变；字体由 `@fontsource/*` 打进 `dist`，不再依赖 `public/fonts/`。

### 7. 测试清单

**判定层（单测）**

- `theme.test.ts`：默认值改为 `{ scale:'standard', bold:false }`；无存储时回退同为不加粗。
- `ThemeProvider.test.tsx`：默认 `body.fontWeight='400'`；点击「开加粗」后 `'600'`；持久化 `bold:true`；已有 `bold:true` 存量保持 600。
- `SettingsModal.test.tsx`：默认开关为关；开启后持久化；「恢复默认」回到关（更新 stale 注释）。
- `tokens.test.ts`：四个字重变量 + 三个字体变量同步；`index.css` 剥离 `@font-face` 后不得出现字面量字重。
- 新增 `frontend/src/theme/fontAssets.test.ts`：三个 `@fontsource` 依赖已声明；各 4 个 latin woff2 已安装且非空；`main.tsx` 按字重导入三族 CSS；`public/fonts` 目录已不存在。

**接口层 / 迁移 / 备份**

- 无后端改动，不适用（写「无」）。

**e2e（前端）**

- 新增 `frontend/tests/e2e/critical/typography.spec.ts`：
  1. 登录后 `body` 计算字重 400、正文段落 400；
  2. 打开设置开启加粗后 600、刷新仍 600；
  3. 品牌字计算 `font-family` 含 `Outfit`，`document.fonts.check('700 16px Outfit')` 为真；
  4. `document.fonts.check("400 13px 'JetBrains Mono'")` 为真（等宽字体已加载）。

**构建 / 离线**

- `make frontend-build` 后确认 `dist/assets/` 含两族字体的 woff2（hash 命名）；`bundle:budget` 的 JS 基线不变；`make docker-export` 产物抽查含两族字体。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 默认值、`body` / antd 字重、设置页复位、存量单测与 e2e 口径 | 低（行为变更集中在一处） |
| **P1** | 字重标尺（`WEIGHT` + CSS 变量 + 门禁）、`index.css` 51 条与行内 64 处替换、层级收敛（表头 / 行名 600→500） | 中（全站视觉回归，需逐屏目检） |
| **P2** | `@fontsource/outfit` 依赖与 latin 四档导入、`--cn-font-*` 变量、antd / `body` 字体族统一、`.cn-display` 与品牌字 / KPI 落点 | 中（FOUT 与字体回退观感） |
| **P3** | `@fontsource/jetbrains-mono` 依赖与 9 处等宽替换、`--cn-tracking-display`、文档标题层级复核、`DESIGN_SYSTEM.md` 同步 | 中低（代码区观感变化） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 默认是否加粗 | 默认 `bold=false`，正文 400 | 卡片 C2；现状 600 使正文与标题同重 | 保留 `true` 只改文案（不解决根因）；把存量 `true` 批量改 `false`（覆盖用户显式选择） | `frontend/src/theme/fonts.ts` |
| D2 | 「全局加粗」开关去留 | 保留为可选无障碍偏好 | 卡片 C5；低视力用户需要 | 删除开关（破坏既有能力） | `frontend/src/theme/ThemeProvider.tsx`、`frontend/src/pages/settings/SettingsModal.tsx` |
| D3 | 字重是否进标尺 | 四档常量 + CSS 变量 + 测试门禁 | 现状 51 条 CSS + 64 处行内无约束 | 只改默认值（散落字面量继续漂移）；仅靠 antd token（CSS 规则不受 token 管） | `frontend/src/theme/tokens.ts`、`frontend/src/index.css` |
| D4 | 层级映射 | 正文 400 / 次级 500 / 标题 600 / 大标题 700 | 对齐 docs.trae.cn 的 400-600-700 层级 | 全站 600（现状，层级塌陷）；全站 500（标题失去区分度） | `frontend/src/index.css`、`frontend/src/pages/**` |
| D5 | antd 字体族 | 与 `body` 同为 Inter + 系统字体回退 | 现状组件与正文分叉，中英混排跳变 | 保持系统栈（与本地字体策略冲突）；各组件单独设字体（重复且易漏） | `frontend/src/theme/presets/common.ts` |
| D6 | 是否引入 Outfit / JetBrains Mono | 引入两族，作为 npm 运行时依赖（`@fontsource/outfit`、`@fontsource/jetbrains-mono`），入口只导入 latin 子集 400/500/600/700 | 卡片 C6；用户 2026-10-25 决策（改为运行时依赖）；docs.trae.cn 同款分工 | 不引入（放弃展示与等宽优势）；走 CDN / Google Fonts（离线部署与隐私不合规）；变量字体单文件（Chrome 81 与字体回退风险）；手工下载 woff2 入库（用户明确要求运行时依赖） | `frontend/package.json`、`frontend/src/main.tsx` |
| D7 | 行高 | UI 1.5714、阅读 1.75 保持 | 数据密集型界面对表格密度敏感；阅读区已达标 | 全站 1.7（表格变松，一屏少行） | `frontend/src/theme/tokens.ts` |
| D8 | 字距 | 仅 `.cn-display-tight`（品牌字 / KPI / 拉丁大标题）`-0.02em` | docs.trae.cn 大标题负字距的观感收益，但 CJK 收紧伤可读性 | 全站 `-0.02em`（中文挤压、标点碰撞） | `frontend/src/index.css` |
| D9 | 字体许可与来源 | 许可随 fontsource 包分发（SIL OFL 1.1）；锁 `5.3.0`；不手工入库字体文件。Inter 同样迁到 `@fontsource/inter`，`public/fonts` 整体删除，中文改由系统字体回退 | 分发字体必须附许可；离线环境不能靠 CDN；原 Noto Sans SC 仅覆盖 177 个字符，托管价值低于维护成本 | 手工下载 woff2 入库不带许可（合规缺口）；不锁版本（字体字形可能漂移）；继续保留 `public/fonts`（Inter 双份来源、Noto 覆盖率名不副实） | `frontend/package.json`、`frontend/pnpm-lock.yaml`、`frontend/src/main.tsx` |
| D10 | 字体加载 | 不新增 preload；沿用 `font-display: swap`；只导入 latin 四档 | 品牌字仅 16px，preload 4 字重会挤占首屏 | preload 全部字重（浪费带宽）；改为 `font-display: block`（首屏文字不可见）；导入全语言子集（体积翻数倍） | `frontend/src/main.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：默认阅读负担下降；正文 / 标题 / 强调重新有层级；字重、字体族与字体资产成为可测口径；品牌字、KPI 与代码区获得 docs.trae.cn 同类的展示 / 等宽质感。
- **负向**：新增三个前端运行时依赖；新增字体首次命中会有一次 `swap` 闪动；表头与行名 600→500 属可感知观感变化。
- **风险与缓解**：FOUT 只在品牌字 / KPI / 代码区出现 → P2/P3 逐屏目检，必要时只对品牌字加 1 个 14KB 的 preload；字体加载失败 → 栈内 `system-ui` / 系统等宽兜底；离线包增大 → 确认 `bundle:budget` 不统计字体，并在 `make docker-export` 后抽查产物；依赖缺失或文件被裁剪 → `fontAssets.test.ts` 断言依赖声明、安装文件非空与入口导入齐全。

## 行业对照（可选）

| 维度 | docs.trae.cn | 本仓现状 | 本设计 |
|---|---|---|---|
| 正文字体族 | Inter + PingFang SC / Microsoft YaHei 回退 | `body` Inter + Noto；antd 系统栈 | D5：全站统一 Inter + 系统字体回退 |
| 展示字体 | Outfit（`--disp`） | 无 | D6：`@fontsource/outfit`，用于品牌字 / KPI / 拉丁大标题 |
| 等宽字体 | JetBrains Mono（`--mono`） | 未定义变量 + 9 处字面量 | D6：`@fontsource/jetbrains-mono` 统一等宽 |
| 正文字重 | 400 | 默认 600（`bold` 默认开） | D1：默认 400 |
| 标题字重 | 700（大标题）/ 600（导航） | 600 为主，700 仅品牌字 | D4：600 标题、700 大标题 |
| 行高 | landing 1.7；正文页 1.6 | UI 1.5714；文档 1.75 | D7：维持分工 |
| 大标题字距 | `-0.02em`（拉丁展示字体） | 无 | D8：`.cn-display-tight` `-0.02em` |

来源：`https://docs.trae.cn/` 页面内联样式与 CSS 变量（`--body` / `--disp` / `--mono`，2026-10-25 读取）；正文页 `https://docs.trae.cn/ide/what-is-trae`。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 老内核兼容 | woff2 / `unicode-range` / `font-display: swap` | 本 ADR 不使用变量字体与 CSS Fonts Level 4 字重范围，全部为 Chrome 81 可用特性 | ADR 0026 |
| 设计标尺 | `tokens.ts` ↔ `index.css` | 字重与字体族纳入同一把尺子，延续双写 + 单测比对机制 | 本 ADR D3 / D5 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/theme/fonts.ts`、`frontend/src/theme/ThemeProvider.tsx` | `frontend/src/theme/theme.test.ts`、`frontend/src/theme/ThemeProvider.test.tsx`、`frontend/src/pages/settings/SettingsModal.test.tsx` | cb2eacfb |
| P1 | 已落地 | `frontend/src/theme/tokens.ts`、`frontend/src/index.css`、`frontend/src/pages/**` | `frontend/src/theme/tokens.test.ts` | cb2eacfb |
| P2 | 已落地 | `frontend/package.json`、`frontend/src/main.tsx`、`frontend/src/theme/presets/common.ts`、`frontend/src/index.css`、`frontend/src/layouts/MainLayout.tsx` | `frontend/src/theme/fontAssets.test.ts` | cb2eacfb |
| P3 | 已落地 | `frontend/src/index.css`、`frontend/src/components/Document/MarkdownLiveEditor.tsx`、`frontend/src/components/Document/MarkdownPreview.tsx`、`frontend/src/pages/grid/views/TreeView.tsx`、`frontend/src/pages/grid/views/WbsView.tsx`、`frontend/src/pages/grid/views/gantt/ganttLeftColumn.tsx`、`docs/DESIGN_SYSTEM.md` | `frontend/tests/e2e/critical/typography.spec.ts` | cb2eacfb |
| P4 | 已落地 | `frontend/package.json`、`frontend/src/main.tsx`、`frontend/src/index.css`、`frontend/src/theme/tokens.ts`、`frontend/src/theme/fontAssets.test.ts` | `frontend/src/theme/fontAssets.test.ts` | 0e7eaae7 |

## 交接（会话结束更新）

- 当前阶段：P0-P4 全部落地，ADR 已 Accept
- 已完成：默认口径改为「标准字号 + 不加粗」；字重四档标尺与门禁；CSS 51 条 + 行内 64 处字面量收敛；antd 与 body 字体族统一；Inter / Outfit / JetBrains Mono 全部以运行时依赖引入（`@fontsource/*`，只导 latin 四档），`frontend/public/fonts` 整体删除、中文改走系统字体回退；`DESIGN_SYSTEM.md` 同步
- 下一步：无（后续如需完整中文 web font 子集或中文等宽，另立 ADR）
- 已知坑：`@fontsource` latin 子集不含中文，中文与中文代码注释回退系统字体，属预期；`tokens.test.ts` 禁字面量前会剥离 `@font-face`，新增字体样式不要绕开变量；依赖版本锁在 `pnpm-lock.yaml`（5.3.0），升级需目检字形；`public/fonts` 已删，不要再往里放字体文件（`fontAssets.test.ts` 会失败）
- 最近一次全绿：`make check`（后端 5303 passed / 覆盖率 97.00%，前端 2154 passed / 双门槛达标，前端静态含 Chrome 81 兼容检查 0 warning）与 `make frontend-build`（产物含三族拉丁 woff2，无 `/fonts/` 引用）
