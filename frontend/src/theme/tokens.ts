/** 设计标尺（Design Tokens）— 间距 / 字号 / 圆角 / 控件高度 / 断点的唯一数值来源。
 *
 * 全站视觉由三部分组成，本模块是它们共用的那把尺子：
 *   1. antd v5 Design Token（CSS-in-JS）— 组件内部尺寸，按主题下发，见 presets/
 *   2. `--cn-*` 主题变量 — 颜色 / 圆角，随 body class 切换，见 index.css
 *   3. 行内 style — 页面级微调，读本模块常量而不是随手写字面量
 *
 * 约定：
 *   - 间距 = 4px 网格；`hairline`(2) 与 `sm`(6) 是仅用于紧凑容器（单元格 / 胶囊）的半步
 *   - 字号 = t-shirt 六级；`md`(14) 与 antd 默认正文一致，CSS 里不要再出现 9/15/17px 之类离散步长
 *   - 圆角不写死：基础圆角由主题 borderRadius 决定，运行时以 `--cn-radius-base` 下发，
 *     `sm` = base-2、`lg` = base+2，保证 10 套主题的卡片/输入框圆角同步变化
 *
 * 与 CSS 的同步：index.css 的 `:root` 用同名变量声明默认值，`tokens.test.ts` 解析
 * index.css 逐条比对，双写漂移会在单测里直接失败。
 */

/* ─────────────── 间距（4px 网格） ─────────────── */

export const SPACE = {
  /** 2px — 描边内侧微调、图标与文字的最小间隙 */
  hairline: 2,
  /** 4px */
  xs: 4,
  /** 6px — 紧凑容器内边距（表格单元格、胶囊、Tag） */
  sm: 6,
  /** 8px */
  md: 8,
  /** 12px — 同组控件间距 */
  lg: 12,
  /** 16px — 卡片/分区内边距 */
  xl: 16,
  /** 20px */
  '2xl': 20,
  /** 24px — 分区间距 */
  '3xl': 24,
  /** 32px — 页面级留白（仅空状态与大标题周围） */
  '4xl': 32,
} as const

/* ─────────────── 字号 ─────────────── */

export const TEXT = {
  /** 10px — 角标 / 图标内文字（下限，再小影响中文可读性） */
  '3xs': 10,
  /** 11px — 计数、极简辅助文字 */
  '2xs': 11,
  /** 12px — 表头、标签、辅助说明 */
  xs: 12,
  /** 13px — 密集正文、页签、胶囊按钮 */
  sm: 13,
  /** 14px — 正文（与 antd 默认 fontSize 一致） */
  md: 14,
  /** 16px — 页面级标题 */
  lg: 16,
  /** 20px — KPI 数字、空状态标题 */
  xl: 20,
} as const

/* ─────────────── 圆角（`base` 由主题决定，其余由它派生） ─────────────── */

export const RADIUS = {
  /** 2px — 极简主题的基准值，也用于内嵌小标签 */
  xs: 2,
  /** base - 2 */
  sm: 4,
  /** 主题 borderRadius 默认值（index.css 的 :root 兜底） */
  base: 6,
  /** base + 2 */
  lg: 8,
  /** 12px — 浮层 / 对话框等大面 */
  xl: 12,
  /** 胶囊 */
  pill: 999,
} as const

/** 由主题基础圆角派生 sm / lg，供运行时下发 `--cn-radius-*`。 */
export function radiusFamily(base: number): { sm: number; lg: number } {
  const safe = Math.round(base)
  return { sm: Math.max(RADIUS.xs, safe - 2), lg: safe + 2 }
}

/* ─────────────── 控件高度 ─────────────── */

export const CONTROL = {
  /** 20px — 迷你按钮 / xs 控件 */
  xs: 20,
  /** 24px — small 控件 */
  sm: 24,
  /** 30px — 默认控件（antd 默认 32，收紧 2px） */
  md: 30,
  /** 36px — large 控件 */
  lg: 36,
} as const

/* ─────────────── 字重（四档，CSS 与 TSX 共用） ─────────────── */

export const WEIGHT = {
  /** 400 — 正文、表格单元格、表单值 */
  regular: 400,
  /** 500 — 表头、行名、实体名、计数 */
  medium: 500,
  /** 600 — 页面/分区/卡片标题、激活态 */
  semibold: 600,
  /** 700 — 大标题、品牌字、语义符号 */
  bold: 700,
} as const

/* ─────────────── 行高 / 断点 ─────────────── */

export const LINE = {
  /** 标题类 */
  tight: 1.4,
  /** 正文：14 × 1.5714 ≈ 22px，与 antd 默认一致 */
  base: 1.5714,
  /** 长文阅读（文档正文） */
  relaxed: 1.75,
} as const

/** 字体族：正文 / 展示 / 等宽。CSS 与 antd token 共用同一份，避免组件与正文分叉。 */
export const FONT = {
  /** 正文与 UI */
  sans: "'Inter', 'Noto Sans SC', sans-serif",
  /** 展示位（品牌字、KPI 数字、纯拉丁大标题）；中文自动回退 Noto Sans SC */
  display: "'Outfit', 'Noto Sans SC', sans-serif",
  /** 代码、编号列、等宽场景 */
  mono: "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
} as const

/** 字距：仅用于展示位的纯拉丁 / 纯数字内容，中文不加负字距 */
export const TRACKING = {
  display: '-0.02em',
} as const

/** 断点（px）— CSS 侧 media query 用 `B - 0.02px` 的写法避免边界重叠。 */
export const BREAKPOINT = {
  /** antd xs/sm 分界，也是本项目「移动端」口径 */
  mobile: 768,
  /** 平板 */
  tablet: 992,
} as const

/* ─────────────── CSS 变量名映射（供 index.css 与单测共用） ─────────────── */

function px(value: number): string {
  return `${value}px`
}

/** :root 中必须存在的标尺变量 → 期望值；tokens.test.ts 据此校验 index.css。 */
export const CSS_VARS: Readonly<Record<string, string>> = {
  '--cn-space-hairline': px(SPACE.hairline),
  '--cn-space-xs': px(SPACE.xs),
  '--cn-space-sm': px(SPACE.sm),
  '--cn-space-md': px(SPACE.md),
  '--cn-space-lg': px(SPACE.lg),
  '--cn-space-xl': px(SPACE.xl),
  '--cn-space-2xl': px(SPACE['2xl']),
  '--cn-space-3xl': px(SPACE['3xl']),
  '--cn-space-4xl': px(SPACE['4xl']),
  '--cn-text-3xs': px(TEXT['3xs']),
  '--cn-text-2xs': px(TEXT['2xs']),
  '--cn-text-xs': px(TEXT.xs),
  '--cn-text-sm': px(TEXT.sm),
  '--cn-text-md': px(TEXT.md),
  '--cn-text-lg': px(TEXT.lg),
  '--cn-text-xl': px(TEXT.xl),
  '--cn-radius-base': px(RADIUS.base),
  '--cn-radius-sm': px(radiusFamily(RADIUS.base).sm),
  '--cn-radius-lg': px(radiusFamily(RADIUS.base).lg),
  '--cn-radius-xl': px(RADIUS.xl),
  '--cn-radius-pill': px(RADIUS.pill),
  '--cn-weight-regular': String(WEIGHT.regular),
  '--cn-weight-medium': String(WEIGHT.medium),
  '--cn-weight-semibold': String(WEIGHT.semibold),
  '--cn-weight-bold': String(WEIGHT.bold),
  '--cn-font-sans': FONT.sans,
  '--cn-font-display': FONT.display,
  '--cn-font-mono': FONT.mono,
  '--cn-tracking-display': TRACKING.display,
}
