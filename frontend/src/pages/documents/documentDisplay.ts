/** 文档状态展示映射与时间格式化（列表页与搜索抽屉共用）. */

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
