/** 导出模板表单的选项与口径（ADR 0152）.
 *
 * 单一来源：模板面板的下拉选项、字号中文号名映射、预览文案都从这里取，
 * 避免同一枚举在多个组件里各写一份（D14：界面显示中文号数，存磅值）。
 */

import type {
  ExportTemplateConfig,
  TemplateAlign,
  TemplateHeadingNumbering,
  TemplateLineRule,
  TemplateListMarker,
  TemplateNumberingMode,
  TemplatePageNumber,
  TemplatePaper,
  TemplateTableStyle,
} from '@/api'

export interface Option<T> {
  value: T
  label: string
}

export const PAPER_OPTIONS: Option<TemplatePaper>[] = [
  { value: 'A4', label: 'A4（210×297mm）' },
  { value: 'A3', label: 'A3（297×420mm）' },
  { value: 'Letter', label: 'Letter（216×279mm）' },
]

export const ALIGN_OPTIONS: Option<TemplateAlign>[] = [
  { value: 'left', label: '靠左' },
  { value: 'center', label: '居中' },
  { value: 'right', label: '靠右' },
  { value: 'justify', label: '两端对齐' },
]

export const LINE_RULE_OPTIONS: Option<TemplateLineRule>[] = [
  { value: 'multiple', label: '倍数行距' },
  { value: 'fixed', label: '固定磅值' },
]

export const PAGE_NUMBER_OPTIONS: Option<TemplatePageNumber>[] = [
  { value: 'none', label: '不显示' },
  { value: 'plain', label: '1' },
  { value: 'page', label: '第 X 页' },
  { value: 'page_of_total', label: '第 X 页 共 Y 页' },
]

/** 编号叠加时机（ADR 0186）：编号权威只在模板一处，正文自带序号时默认让位 */
export const NUMBERING_MODE_OPTIONS: Option<TemplateNumberingMode>[] = [
  { value: 'auto', label: '自动（正文已有序号时不重复）' },
  { value: 'force', label: '总是叠加（可能重复）' },
  { value: 'off', label: '不编号' },
]

/** 标题编号方案：标注推荐文体，避免「各类文件套错序数」 */
export const NUMBERING_OPTIONS: Option<TemplateHeadingNumbering>[] = [
  { value: 'none', label: '不编号（宣传报道 / 周报 / 便函）' },
  { value: 'arabic_multilevel', label: '1 / 1.1 / 1.1.1（研究报告 / 技术报告 / 趋势分析）' },
  { value: 'chapter_chinese', label: '第一章 / 1.1 / 1.1.1（论文 / 专著）' },
  { value: 'cn_ordinal', label: '一、 / （一）/ 1./（1）（公文 / GB/T 9704）' },
]

export const TABLE_STYLE_OPTIONS: Option<TemplateTableStyle>[] = [
  { value: 'single', label: '全网格' },
  { value: 'three_line', label: '三线表' },
]

export const LIST_MARKER_OPTIONS: Option<TemplateListMarker>[] = [
  { value: 'bullet', label: '圆点 •' },
  { value: 'dash', label: '短横 -' },
  { value: 'dot', label: '中点 ·' },
]

export const CELL_VALIGN_OPTIONS: Option<'top' | 'center'>[] = [
  { value: 'top', label: '顶端对齐' },
  { value: 'center', label: '垂直居中' },
]

export const CAPTION_POSITION_OPTIONS: Option<'above' | 'below'>[] = [
  { value: 'above', label: '题注在上' },
  { value: 'below', label: '题注在下' },
]

export const CAPTION_NUMBERING_OPTIONS: Option<'n' | 'n-n'>[] = [
  { value: 'n', label: '图 1 / 表 1' },
  { value: 'n-n', label: '图 1-1 / 表 1-1' },
]

/** 中文字号名 ↔ 磅值（企业排版按号数沟通，存储仍用磅值） */
export const CHINESE_FONT_SIZES: { label: string; pt: number }[] = [
  { label: '初号', pt: 42 },
  { label: '小初', pt: 36 },
  { label: '一号', pt: 26 },
  { label: '小一', pt: 24 },
  { label: '二号', pt: 22 },
  { label: '小二', pt: 18 },
  { label: '三号', pt: 16 },
  { label: '小三', pt: 15 },
  { label: '四号', pt: 14 },
  { label: '小四', pt: 12 },
  { label: '五号', pt: 10.5 },
  { label: '小五', pt: 9 },
  { label: '六号', pt: 7.5 },
]

/** 磅值 → 「小四 12pt」样式的标签（无匹配号数时只显示磅值） */
export function fontPtLabel(pt: number): string {
  const named = CHINESE_FONT_SIZES.find(item => Math.abs(item.pt - pt) < 0.01)
  return named ? `${named.label} ${pt}pt` : `${pt}pt`
}

/** 常用中文字体候选（可自由输入，Word 端按本机字体回落） */
export const EAST_ASIA_FONTS = [
  '宋体',
  '仿宋',
  '黑体',
  '楷体',
  '微软雅黑',
  '思源宋体',
  '思源黑体',
  'Calibri',
]

/** 常用西文字体候选 */
export const LATIN_FONTS = [
  'Times New Roman',
  'Calibri',
  'Arial',
  'Cambria',
  'Courier New',
  'Consolas',
]

/** 等宽代码字体候选 */
export const CODE_FONTS = ['Courier New', 'Consolas', 'Menlo', 'Source Code Pro']

/** 面板内 CSS 等比预览用：把模板配置折成一组内联样式（不追求与 Word 完全一致） */
/** 标题编号前缀（与后端 `heading_prefix` 同口径，仅用于预览） */
export function numberingPrefix(
  scheme: TemplateHeadingNumbering,
  level: number,
  counters: number[],
): string {
  if (scheme === 'none') return ''
  const numbers = counters.slice(0, level)
  if (scheme === 'arabic_multilevel') return numbers.join('.')
  if (scheme === 'chapter_chinese') {
    if (level === 1) return `第${chineseNumber(counters[0])}章`
    return numbers.join('.')
  }
  if (level === 1) return `${chineseNumber(counters[0])}、`
  if (level === 2) return `（${chineseNumber(counters[1])}）`
  if (level === 3) return `${counters[2]}.`
  if (level === 4) return `（${counters[3]}）`
  return numbers.join('.')
}

const CN_DIGITS = '零一二三四五六七八九'

/** 1..99 中文数字（与后端一致，超出范围原样返回） */
function chineseNumber(value: number): string {
  if (value <= 0 || value >= 100) return String(value)
  if (value < 10) return CN_DIGITS[value]
  const tens = Math.floor(value / 10)
  const ones = value % 10
  const prefix = tens === 1 ? '十' : `${CN_DIGITS[tens]}十`
  return ones === 0 ? prefix : `${prefix}${CN_DIGITS[ones]}`
}

/** 预览用：页脚页码文案（与导出侧 `plain / page / page_of_total` 同义） */
export function pageNumberText(mode: string, page = 1, total = 3): string {
  if (mode === 'none') return ''
  if (mode === 'plain') return String(page)
  if (mode === 'page') return `第 ${page} 页`
  return `第 ${page} 页 共 ${total} 页`
}

/**
 * 面板内 CSS 等比预览用：把模板配置折成一组内联样式（不追求与 Word 逐像素一致）。
 *
 * 覆盖模板真正控制的每一组要素：页面（纸张 / 页边距）、页眉页脚、H1–H6、正文段落、
 * 列表、表格（全网格 / 三线表 / 斑马纹 / 表头配色）、图表题注、代码块、引用块。
 */
export function previewStyles(config: ExportTemplateConfig) {
  const { body, table, headings, page, header_footer: hf, code, lists, captions } = config
  const heading = (level: number) => headings[Math.min(level, headings.length) - 1] ?? body
  const fontStack = `${body.east_asia_font}, ${body.latin_font}, serif`
  const threeLine = table.style === 'three_line'

  return {
    page: {
      maxWidth: page.paper === 'A3' ? 660 : page.paper === 'Letter' ? 600 : 580,
      // 页边距按 1cm ≈ 3.4px 缩放，保持「边距越大正文越窄」的相对关系
      paddingTop: Math.max(6, page.margin_top * 3.4),
      paddingBottom: Math.max(6, page.margin_bottom * 3.4),
      paddingLeft: Math.max(8, page.margin_left * 3.4),
      paddingRight: Math.max(8, page.margin_right * 3.4),
      fontSize: body.size,
      color: body.color,
    },
    header: {
      fontFamily: fontStack,
      fontSize: hf.font_size,
      textAlign: 'center' as const,
      color: 'var(--cn-text-secondary)',
      paddingBottom: 4,
      marginBottom: 8,
      borderBottom: '1px solid var(--cn-border-soft)',
      visibility: hf.header_text ? ('visible' as const) : ('hidden' as const),
    },
    footer: {
      fontFamily: fontStack,
      fontSize: hf.font_size,
      textAlign: 'center' as const,
      color: 'var(--cn-text-secondary)',
      paddingTop: 4,
      marginTop: 8,
      borderTop: '1px solid var(--cn-border-soft)',
    },
    body: {
      fontFamily: fontStack,
      fontSize: body.size,
      fontWeight: body.bold ? 600 : 400,
      lineHeight: body.line_spacing_rule === 'fixed' ? `${body.line_spacing_pt}pt` : body.line_spacing,
      letterSpacing: body.char_spacing ? `${body.char_spacing}pt` : undefined,
      textAlign: body.align === 'justify' ? ('justify' as const) : body.align,
      textIndent: body.first_line_indent_chars ? `${body.first_line_indent_chars}em` : undefined,
      marginTop: body.space_before,
      marginBottom: body.space_after,
      color: body.color,
    },
    headings: (level: number) => {
      const cfg = heading(level)
      return {
        fontFamily: `${cfg.east_asia_font}, ${cfg.latin_font}, serif`,
        fontSize: cfg.size,
        fontWeight: cfg.bold ? 700 : 400,
        textAlign: cfg.align === 'justify' ? ('justify' as const) : cfg.align,
        color: cfg.color,
        marginTop: cfg.space_before,
        marginBottom: cfg.space_after,
        textIndent: cfg.first_line_indent_chars ? `${cfg.first_line_indent_chars}em` : undefined,
        lineHeight: 1.35,
      }
    },
    list: {
      fontFamily: fontStack,
      fontSize: body.size,
      color: body.color,
      margin: 0,
      paddingLeft: lists.indent_pt,
      lineHeight: body.line_spacing_rule === 'fixed' ? `${body.line_spacing_pt}pt` : body.line_spacing,
    },
    listItem: {
      marginBottom: lists.space_after,
    },
    table: {
      borderCollapse: 'collapse' as const,
      fontSize: table.size,
      color: body.color,
      width: '100%',
      marginTop: 4,
      marginBottom: 4,
    },
    cell: {
      border: threeLine ? 'none' : `1px solid ${table.border_color}`,
      borderBottom: threeLine ? 'none' : `1px solid ${table.border_color}`,
      padding: '3px 6px',
      textAlign: 'left' as const,
      verticalAlign: table.cell_valign === 'center' ? ('middle' as const) : ('top' as const),
    },
    headerCell: {
      border: threeLine ? 'none' : `1px solid ${table.border_color}`,
      borderTop: `1.5px solid ${threeLine ? table.border_color : '#000'}`,
      borderBottom: `1px solid ${threeLine ? table.border_color : '#000'}`,
      background: threeLine ? 'transparent' : table.header_bg,
      color: table.header_color,
      fontWeight: table.header_bold ? 600 : 400,
      padding: '3px 6px',
      textAlign: 'left' as const,
      verticalAlign: table.cell_valign === 'center' ? ('middle' as const) : ('top' as const),
    },
    zebraRow: {
      background: table.zebra ? 'var(--cn-bg-subtle)' : 'transparent',
    },
    caption: (kind: 'figure' | 'table') => {
      const cfg = kind === 'figure' ? captions.figure : captions.table
      return {
        fontFamily: fontStack,
        fontSize: cfg.size,
        color: body.color,
        textAlign: cfg.align,
        marginTop: 4,
        marginBottom: 4,
        fontStyle: 'normal' as const,
      }
    },
    code: {
      fontFamily: `${code.latin_font}, ${code.east_asia_font}, monospace`,
      fontSize: code.size,
      lineHeight: 1.5,
      margin: '6px 0',
      padding: code.left_bar ? '6px 8px 6px 10px' : '6px 8px',
      background: code.bg,
      border: `1px solid ${code.border}`,
      borderLeft: code.left_bar ? `3px solid ${code.border}` : `1px solid ${code.border}`,
      borderRadius: 4,
      whiteSpace: 'pre-wrap' as const,
      color: body.color,
    },
    quote: {
      fontFamily: fontStack,
      fontSize: body.size,
      color: 'var(--cn-text-secondary)',
      borderLeft: '3px solid var(--cn-border)',
      paddingLeft: 8,
      margin: '6px 0',
      fontStyle: 'italic' as const,
    },
  }
}
