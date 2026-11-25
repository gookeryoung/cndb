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

export const NUMBERING_OPTIONS: Option<TemplateHeadingNumbering>[] = [
  { value: 'none', label: '不编号' },
  { value: 'arabic_multilevel', label: '1 / 1.1 / 1.1.1' },
  { value: 'chapter_chinese', label: '第一章（子级 1.1）' },
  { value: 'cn_ordinal', label: '一、 / （一）' },
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
export function previewStyles(config: ExportTemplateConfig) {
  const { body, table, headings, page } = config
  const heading = (level: number) => headings[Math.min(level, headings.length) - 1] ?? body
  return {
    page: {
      maxWidth: page.paper === 'A3' ? 640 : 560,
    },
    body: {
      fontFamily: `${body.east_asia_font}, ${body.latin_font}, serif`,
      fontSize: body.size,
      fontWeight: body.bold ? 600 : 400,
      lineHeight: body.line_spacing_rule === 'fixed' ? `${body.line_spacing_pt}pt` : body.line_spacing,
      textAlign: body.align === 'justify' ? ('justify' as const) : body.align,
      textIndent: body.first_line_indent_chars ? `${body.first_line_indent_chars}em` : undefined,
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
      }
    },
    table: {
      borderCollapse: 'collapse' as const,
      fontSize: table.size,
      color: body.color,
      width: '100%',
    },
    cell: {
      border: table.style === 'three_line' ? 'none' : '1px solid #888',
      borderBottom: '1px solid #888',
      padding: '4px 6px',
      textAlign: 'left' as const,
    },
    headerCell: {
      border: table.style === 'three_line' ? 'none' : '1px solid #888',
      borderTop: '1.5px solid #000',
      borderBottom: '1px solid #000',
      background: table.style === 'three_line' ? 'transparent' : table.header_bg,
      color: table.header_color,
      fontWeight: table.header_bold ? 600 : 400,
      padding: '4px 6px',
      textAlign: 'left' as const,
    },
  }
}
