/** 文档状态展示映射与时间格式化（列表页与搜索抽屉共用）. */

export function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
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
