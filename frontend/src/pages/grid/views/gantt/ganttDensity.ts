/** 甘特图密度 → 行高/字号/左列宽等尺寸预设. */

import type { Density } from '@/theme/tableSettings'

export function densityStyle(density: Density) {
  if (density === 'compact') {
    return {
      rowHeight: 32,
      headerHeight: 32,
      leftColWidth: 220,
      barHeight: 18,
      titleFontSize: 12,
      metaFontSize: 10,
      headerFontSize: 11,
      groupHeaderHeight: 34,
      wbsIndent: 16,
    }
  }
  if (density === 'spacious') {
    return {
      rowHeight: 56,
      headerHeight: 40,
      leftColWidth: 280,
      barHeight: 28,
      titleFontSize: 14,
      metaFontSize: 12,
      headerFontSize: 13,
      groupHeaderHeight: 44,
      wbsIndent: 20,
    }
  }
  return {
    rowHeight: 44,
    headerHeight: 36,
    leftColWidth: 250,
    barHeight: 24,
    titleFontSize: 13,
    metaFontSize: 11,
    headerFontSize: 12,
    groupHeaderHeight: 38,
    wbsIndent: 18,
  }
}
