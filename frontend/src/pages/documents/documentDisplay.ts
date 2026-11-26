/** 文档状态展示映射与时间格式化（列表页、目录树与搜索抽屉共用）. */

import type { ComponentType, CSSProperties } from 'react'
import { CheckCircleOutlined, EditOutlined, InboxOutlined } from '@ant-design/icons'

export function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

/** 紧凑列表 / 卡片用短日期（YYYY-MM-DD）；完整时间仍留在 title 悬停提示里 */
export function formatDate(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export const STATUS_COLORS: Record<string, string> = {
  draft: 'default',
  published: 'green',
  archived: 'orange',
}

export const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  archived: '归档',
}

/** 状态图标 + 色义：目录树与移动端单行列表共用，颜色只作辅助、语义在图标与 aria-label */
export interface DocumentStatusMeta {
  Icon: ComponentType<{ style?: CSSProperties; 'aria-label'?: string; 'data-testid'?: string }>
  color: string
  label: string
}

export const DOC_STATUS_META: Record<string, DocumentStatusMeta> = {
  draft: { Icon: EditOutlined, color: 'var(--cn-text-muted, #999)', label: '草稿' },
  published: { Icon: CheckCircleOutlined, color: 'var(--cn-success, #52c41a)', label: '已发布' },
  archived: { Icon: InboxOutlined, color: 'var(--cn-warning, #faad14)', label: '归档' },
}
