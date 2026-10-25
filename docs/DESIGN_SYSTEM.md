# 视觉与样式规范（Design System）

本文是前端视觉的唯一口径：**标尺在哪里、颜色怎么取、组件怎么紧凑、为什么不用 Tailwind**。
改样式前先读这一页，能避免 80% 的「同一个东西三种写法」。

---

## 1. 三层结构

| 层 | 位置 | 负责 | 谁在改 |
| --- | --- | --- | --- |
| antd Design Token | `src/theme/presets/*.ts` + `getThemeConfig()` | 组件内部尺寸（padding / 控件高度 / 字号）、配色 | 主题维护 |
| `--cn-*` 主题变量 | `src/index.css` 的 `:root` 与 `body.theme-*` | 颜色语义、圆角档位 | 主题维护 |
| 设计标尺 | `src/theme/tokens.ts` ↔ `index.css` 的 `:root` 标尺块 | 间距 / 字号 / 圆角 / 控件高度 / 断点的**数值** | 全员（新增档位先改这里） |

标尺是双写的（TS 常量给行内 style 与 antd token 用，CSS 变量给样式表用），
`src/theme/tokens.test.ts` 会解析 `index.css` 逐条比对，**漂移即测试失败**。

## 2. 标尺

### 间距（4px 网格）

| 变量 | 值 | 用途 |
| --- | --- | --- |
| `--cn-space-hairline` | 2px | 描边内侧微调、图标与文字的最小间隙 |
| `--cn-space-xs` | 4px | 图标旁、紧凑行内 |
| `--cn-space-sm` | 6px | 表格单元格、Tag、胶囊的紧凑内边距 |
| `--cn-space-md` | 8px | 控件组、工具栏内元素 |
| `--cn-space-lg` | 12px | 同组元素间距、次级页面纵向留白 |
| `--cn-space-xl` | 16px | 卡片 / 分区内边距、页面根留白 |
| `--cn-space-2xl` | 20px | 分区间 |
| `--cn-space-3xl` | 24px | 空态、大分组 |
| `--cn-space-4xl` | 32px | 页面级（仅空状态与大标题） |

### 字号

`--cn-text-3xs 10` / `2xs 11` / `xs 12` / `sm 13` / `md 14` / `lg 16` / `xl 20`

- `md`(14) = 正文，与 antd 默认 `fontSize` 一致
- 表头 / 标签用 `xs`(12)，密集正文与页签用 `sm`(13)
- **不存在的档位**：9 / 15 / 17 / 18px —— 历史代码用过，已全部收进上表
- 用户的「字体大小」设置只驱动 antd token（`FONT_SCALE_META`）；
  样式表里的字号是页面骨架，按固定档位走，不跟着缩放

### 字重

`--cn-weight-regular 400` / `--cn-weight-medium 500` / `--cn-weight-semibold 600` / `--cn-weight-bold 700`

- 正文、表格单元格、表单值：`regular`(400)。「全局加粗」是用户可选偏好，默认关闭
- 表头、行名、实体名、计数：`medium`(500)
- 页面 / 分区 / 卡片标题、激活态：`semibold`(600)
- 大标题、品牌字、语义符号（+/-）：`bold`(700)
- CSS 写 `var(--cn-weight-*)`，TSX 写 `WEIGHT.*`；只有 `@font-face` 允许字面量，
  由 `tokens.test.ts` 守卫

### 字体族

| 变量 | 值 | 用途 |
| --- | --- | --- |
| `--cn-font-sans` | Inter + 系统字体 | 正文与全部 antd 组件（同一栈，避免混排跳变；中文按系统字体逐字回退） |
| `--cn-font-display` | Outfit + 系统字体 | 品牌字、KPI 数字、纯拉丁大标题；中文回退系统字体 |
| `--cn-font-mono` | JetBrains Mono + 系统等宽 | 代码块、行内代码、树 / 甘特 / WBS 编号列 |

- 正文字体与展示 / 等宽字体统一走 npm 运行时依赖 `@fontsource/inter`、
  `@fontsource/outfit` 与 `@fontsource/jetbrains-mono`，**只导入 latin 子集四档字重**（`main.tsx`），
  不引 CDN、不保留 `public/fonts` 本地字体，离线部署随依赖安装
- 展示位负字距 `--cn-tracking-display: -0.02em` 只用于 `.cn-display-tight`；
  中文标题不加负字距（CJK 收紧伤可读性）

### 圆角

主题的 `borderRadius` 是基准，运行时由 `ThemeProvider` 下发：

| 变量 | 值 | 说明 |
| --- | --- | --- |
| `--cn-radius-xs` | 2px | 内嵌小标签 |
| `--cn-radius-sm` | base - 2 | 输入框内嵌、小胶囊 |
| `--cn-radius-base` | 主题值（2/4/6/8/10） | 按钮、输入框 |
| `--cn-radius-lg` | base + 2 | 卡片、浮层、表格容器 |
| `--cn-radius-xl` | 12px | 对话框等大面 |
| `--cn-radius-pill` | 999px | 胶囊 |

> 为什么圆角要跟随主题：此前 CSS 里的卡片写死 8/10px，而「极简」主题的 antd 组件是 2px 圆角，
> 同一页面出现两套圆角语言。现在卡片用 `--cn-radius-lg`，极简主题会自动变成 4px。

## 3. 组件紧凑化（antd token）

统一在 `src/theme/presets/common.ts`，10 套主题继承，**不要在页面里再写 padding 去补**：

| 组件 | 关键 token | 变化 |
| --- | --- | --- |
| 全局 | `controlHeight` 32→30、`fontSizeSM` 12、`lineHeight` 1.5714 | 控件整体收 2px |
| Table | `cellPaddingBlockMD` 8→6、`cellPaddingInlineMD` 10、`cellFontSizeMD` 13 | 标准行高 ~48→40px |
| Card | `bodyPadding` 16→14、`headerHeight` 56→40 | 卡片头部更薄 |
| Form | `itemMarginBottom` 24→14 | 表单纵向省 40% |
| Tabs | `horizontalItemGutter` 32→24、`horizontalItemPadding` 8px 0 | 页签行更矮 |
| Menu | `itemHeight` 40→34 | 与侧栏 `.cn-table-nav` 一致 |
| Select / Pagination / Descriptions / Dropdown | 选项高 28、分页项 28、描述项 8、下拉上下 4 | 弹层更紧 |

合并顺序：`baseTokens → 主题 token → 组件 token`，主题显式声明的键优先（配色不会被标尺覆盖）。

### 代码高亮（`--cn-code-*`）

文档里的围栏代码块与实时编辑器共用一套 token 类名（`.cn-tok-keyword` / `.cn-tok-string` / `.cn-tok-comment` …），
语言词法见 `frontend/src/components/Document/codeHighlight.ts`，配色只在 `index.css` 定义一次：

| 变量 | 浅色（`:root` / modern 系） | 深色（midnight / oled / github-dark） | 用途 |
| --- | --- | --- | --- |
| `--cn-code-block-bg` / `--cn-code-block-border` | `#f6f8fa` / `#d0d7de` | `#0d1117` / `#30363d` | 代码块容器底色与描边 |
| `--cn-code-keyword` | `#cf222e` | `#ff7b72` | 关键字（`const` / `def` / `SELECT`） |
| `--cn-code-string` | `#0a3069` | `#a5d6ff` | 字符串 / 模板串 |
| `--cn-code-comment` | `#6e7781` | `#8b949e` | 注释 |
| `--cn-code-number` | `#0550ae` | `#79c0ff` | 数字、布尔、颜色值 |
| `--cn-code-function` | `#8250df` | `#d2a8ff` | 函数 / 方法调用 |
| `--cn-code-type` | `#953800` | `#ffa657` | 类型 / 类名 |
| `--cn-code-tag` / `--cn-code-attr` | `#116329` / `#0550ae` | `#7ee787` / `#79c0ff` | HTML/XML 标签与属性 |
| `--cn-code-builtin` / `--cn-code-property` | `#0550ae` | `#79c0ff` | 内建对象、JSON/YAML/CSS 键名 |

浅色系取 GitHub Light 口径，深色系取 GitHub Dark 口径；其余主题（ocean / forest / sepia / sakura / minimal）
沿用浅色一套，不再单独配色 —— 换主题时只改背景，不重排语法色，避免「每套主题一套高亮」的维护成本。
新增语言只加词法配置，**不要在组件里写死颜色**。

## 4. 硬规则

1. **CSS 里不写数字间距 / 字号 / 圆角**（例外：`0` / `auto` / `1px` 光学微调 / `50%`）。
   需要新档位 → 先加进 `tokens.ts` 与 `:root`，再用变量。`tokens.test.ts` 会拦。
2. **页面根容器用 `.cn-page`**（16px + 12px 节奏，窄屏自动 12px），
   空态 / 加载态用 `.cn-state`。不要再 `style={{ padding: 16 }}`。
3. **不新增 `[style*="..."]` 兜底**。`index.css` 里还有 281 条这类规则，
   它们是行内写死颜色的历史债（深色模式补丁），新增一条就是新增一处隐性耦合。
4. **断点只有两档**：`767.98px`（移动）、`575.98px`（紧凑弹窗）。
   写 `max-width: 767px` 会与 antd 的 768 边界重叠，测试里已列为非法值。
5. **颜色只从 `var(--cn-*)` 取**。主题差异靠 `body.theme-*` 覆盖变量，不靠选择器分支。

## 5. 为什么没有引入 Tailwind CSS

结论：**暂不引入**。不是立场问题，是这套代码的约束和 Tailwind 的假设对不上。

### 有利的一面（也确实是痛点）

- 行内 style 有 1276 处、字号字面量 250+ 处，确实需要「有约束的工具」；
- 工具类能消灭 `index.css` 里 416 条手写规则的一部分。

### 决定性阻碍

1. **与 antd v5 的 CSS-in-JS 抢占同一块地**。项目视觉主体是 antd 组件，
   它们的尺寸由 Design Token 运行时生成、类名带 hash。Tailwind 的 `p-2`/`text-sm`
   打在 antd 组件上要么被组件内联样式盖掉（需要 `!important` 变体），
   要么绕开 token 体系，等于在 10 套主题之上再叠一层不受主题控制的尺寸。
2. **Preflight 会打掉 antd 的排版基线**。`@tailwind base` 的 reset（button/input 归零、
   标题字号重置、border 默认色）与 antd 依赖的 UA 默认样式冲突，
   本项目已有 800+ 行深色/浅色兜底规则，reset 一进来就是大面积回归。
3. **主题是运行时的、多维的**。10 套主题 × 字号档位 × 表格密度三档，全部通过
   CSS 变量与 token 切换。Tailwind 的 `dark:` 只支持二元、且编译期固定，
   要表达 10 主题得写 10 组变体（或用 `data-theme` 插件 + 每个颜色都配变量，最后仍回到 CSS 变量）。
4. **体积与流水线**。当前构建有 `bundle:budget` 门禁与 4 分片 E2E；加 Tailwind 要新增
   PostCSS 链、content 扫描、preflight 取舍，收益（少写几个类名）抵不上回归面。
5. **迁移是重写而不是重构**。1276 处行内 style + 3341 行 index.css，
   没有机械映射（`padding: '6px 10px'` 对应 `py-1.5 px-2.5`，但业务语义是「单元格内边距」），
   一次性迁移会产生一个无法 review 的巨型 diff。

### 替代方案（本次已落地）

- **标尺 + 变量**：`tokens.ts` / `--cn-space-*` 提供 Tailwind 式的「只能从尺子上取值」的约束，
  但没有 preflight、不侵入 antd、天然支持 10 主题。
- **原子级工具类**：只补装真正高频的几个（`.cn-page` / `.cn-state` / `.cn-num`），
  用 class 而不是拼凑行内 style。
- **测试即 lint**：`tokens.test.ts` 把「不许写游离字面量」变成 CI 门禁，
  这比引入一套框架更能防住回归。

### 如果将来一定要引入

按这个顺序做，且只在**新页面**上试点，不动存量：

1. `tailwind.config.js` 设 `corePlugins: { preflight: false }`，`prefix: 'tw-'`（避开 antd 类名）；
2. `theme.extend` 全部映射到 `var(--cn-*)`，禁止出现裸色值；
3. 只开 `spacing / fontSize / borderRadius`（与标尺一一对应），关掉 `colors / shadows` 的自由取值；
4. 试点范围：`pages/analytics` 或某个新插件页面，用 2 周观察 E2E 与包体变化；
5. 存量 `index.css` 与行内 style **不迁移**，等页面自然重写时替换。

## 6. 后续收敛清单（按收益排序）

| 项 | 现状 | 建议 |
| --- | --- | --- |
| 行内 style 收敛 | 1276 处 | 优先收敛「重复出现 ≥3 次」的样式块为 `.cn-*` 类，用 `pnpm lint` + review 拦新增 |
| `[style*="..."]` 兜底 | 281 条 | 每修一个组件就删掉对应兜底；目标是把深色补丁缩到「第三方组件」范围 |
| 颜色字面量 | CSS 内约 300 处 | 只保留 `body.theme-*` 变量定义块与认证页固定舞台 `:root` 块（`--cn-auth-bg` / `--cn-auth-ink` / `--cn-auth-accent` / `--cn-auth-accent-alt`，不随主题）里的字面量，其余换 `var(--cn-*)` |
| 字号档位 | 已统一 | 行内 `fontSize: 11/12/13` 仍散落，新增代码请用 `TEXT.*` 常量 |
| 空态/加载态 | 三套写法 | 统一 `.cn-state`，同时去掉各页 `padding: 24 + textAlign: center` |
