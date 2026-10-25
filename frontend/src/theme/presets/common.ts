/** 10 套主题共用的 token 片段。
 *
 * 分三层：
 *   1. `switchTokens`   — 颜色无关的组件尺寸修正（历史沿用）
 *   2. `baseTokens`      — 全局标尺：字号 / 行高 / 控件高度 / 基础间距，10 套主题统一继承
 *   3. `compactComponents` — 组件级紧凑化：把 antd 默认偏松的 padding / 行高收到数据密集型口径
 *
 * 主题预设只负责「配色 + borderRadius + Layout 底色」，尺寸一律在这里定义，
 * 避免 10 个预设文件各写一份 padding（历史上就出现过只有 modern 收紧、其余主题照旧的问题）。
 * 合并顺序见 theme.ts `getThemeConfig()`：baseTokens → 主题 token，主题显式声明的键仍然优先。
 */

import type { ThemeConfig } from 'antd'

import { CONTROL, FONT, LINE, RADIUS, SPACE, TEXT } from '../tokens'

/* ─────────────── Switch 组件统一 token ─────────────── */
const switchTokens = {
  trackHeight: 24,
  trackMinWidth: 48,
  trackHeightSM: 18,
  trackMinWidthSM: 36,
  handleSize: 20,
  handleSizeSM: 14,
}

// antd 组件与 body 共用同一字体栈，避免组件与正文中英混排时字形跳变
const commonFont = FONT.sans

/* ─────────────── 全局标尺 ───────────────
 * 字号档位：正文 14 / 小号 12 / 大号 16，与 --cn-text-* 同一把尺子。
 * 用户「字体大小」设置会把 token.fontSize 再覆盖一次（ThemeProvider），这里只定默认档。 */
const baseTokens: NonNullable<ThemeConfig['token']> = {
  fontSize: TEXT.md,
  fontSizeSM: TEXT.xs,
  fontSizeLG: TEXT.lg,
  fontSizeXL: TEXT.xl,
  fontSizeHeading1: 24,
  fontSizeHeading2: TEXT.xl,
  fontSizeHeading3: TEXT.lg,
  fontSizeHeading4: TEXT.md,
  fontSizeHeading5: TEXT.sm,
  lineHeight: LINE.base,

  // 控件高度整体收 2px：32 → 30，工具栏一行能多放一个按钮而不显挤
  controlHeight: CONTROL.md,
  controlHeightSM: CONTROL.sm,
  controlHeightXS: CONTROL.xs,
  controlHeightLG: CONTROL.lg,

  // 基础间距：antd 由 padding 派生 paddingXS/MD（8/16），这里只收窄 LG/XL 一档
  padding: SPACE.xl,
  paddingSM: SPACE.lg,
  paddingLG: SPACE['2xl'],
  paddingXL: SPACE['3xl'],
  margin: SPACE.xl,
  marginSM: SPACE.lg,
  marginMD: SPACE['2xl'],
  marginLG: SPACE['3xl'],
  marginXL: SPACE['4xl'],
}

/* ─────────────── 组件级紧凑化 ───────────────
 * 只放尺寸类 token（颜色由主题决定），便于审计「哪些组件被收紧了」。 */
const compactComponents: NonNullable<ThemeConfig['components']> = {
  Button: {
    paddingInline: SPACE.lg,
    paddingInlineSM: SPACE.md,
    paddingInlineLG: SPACE.xl,
    onlyIconSize: 14,
    contentFontSize: TEXT.sm,
    contentFontSizeSM: TEXT.xs,
    contentFontSizeLG: TEXT.md,
  },
  Table: {
    // middle（默认档）上下 6px：48px 行高 → 40px 上下，一屏多两行
    cellPaddingBlock: SPACE.md,
    cellPaddingInline: 10,
    cellPaddingBlockMD: SPACE.sm,
    cellPaddingInlineMD: 10,
    cellPaddingBlockSM: 4,
    cellPaddingInlineSM: SPACE.md,
    cellFontSize: TEXT.sm,
    cellFontSizeMD: TEXT.sm,
    cellFontSizeSM: TEXT.xs,
    headerBorderRadius: 0,
  },
  Card: {
    bodyPadding: 14,
    headerPadding: 14,
    headerHeight: 40,
    headerFontSize: TEXT.sm,
    headerFontSizeSM: TEXT.sm,
    bodyPaddingSM: 10,
    headerPaddingSM: 10,
  },
  Form: {
    itemMarginBottom: 14,
    labelFontSize: TEXT.sm,
    verticalLabelPadding: '0 0 4px',
  },
  Tabs: {
    horizontalItemGutter: SPACE['3xl'],
    horizontalItemPadding: '8px 0',
    titleFontSize: TEXT.sm,
    titleFontSizeSM: TEXT.xs,
  },
  Menu: {
    itemHeight: 34,
    itemMarginBlock: SPACE.hairline,
    itemMarginInline: SPACE.xs,
    itemBorderRadius: RADIUS.base,
    iconSize: 14,
    groupTitleFontSize: TEXT['2xs'],
  },
  Select: {
    optionHeight: 28,
    optionFontSize: TEXT.sm,
    optionPadding: '4px 10px',
  },
  Pagination: {
    itemSize: 28,
    itemSizeSM: CONTROL.sm,
  },
  Descriptions: {
    itemPaddingBottom: SPACE.md,
    titleMarginBottom: SPACE.md,
  },
  Dropdown: {
    paddingBlock: SPACE.xs,
  },
  // Tag 的字号/行高是内部派生 token（tagFontSize ← fontSizeSM），
  // 已在 baseTokens 里统一为 12px，这里不再重复声明。
}

export { commonFont, switchTokens, baseTokens, compactComponents }
