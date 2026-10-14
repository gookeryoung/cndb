/** 报表页共用的下拉选项常量（列表页与编辑器弹窗共用）. */

import type { ReportTheme } from '@/api'

export const FORMAT_OPTIONS = [
  { value: 'docx', label: 'Word (.docx)' },
  { value: 'pdf', label: 'PDF (.pdf)' },
  { value: 'xlsx', label: 'Excel (.xlsx)' },
  { value: 'html', label: 'HTML (.html)' },
]
export const THEME_OPTIONS: Array<{ value: ReportTheme; label: string }> = [
  { value: 'minimal', label: '简约' },
  { value: 'business', label: '商务' },
  { value: 'modern', label: '现代' },
  { value: 'engineering', label: '工程' },
  { value: 'academic', label: '学术' },
]
export const PARAM_TYPES = [
  { value: 'string', label: '文本' },
  { value: 'number', label: '数字' },
  { value: 'date', label: '日期' },
  { value: 'boolean', label: '布尔' },
]
