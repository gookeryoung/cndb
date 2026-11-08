/** 管理台分项定义 —— MainLayout 侧栏导航与页内内容共用同一份 key / 文案 / 图标. */

import {
  TeamOutlined, HistoryOutlined, HddOutlined, InfoCircleOutlined,
  CloudDownloadOutlined, CloudUploadOutlined,
} from '@ant-design/icons'
import type { ReactNode } from 'react'

export type AdminSectionKey = 'users' | 'events' | 'storage' | 'info' | 'backup' | 'restore'

export interface AdminSection {
  key: AdminSectionKey
  label: string
  desc: string
  icon: ReactNode
}

export const ADMIN_SECTIONS: readonly AdminSection[] = [
  { key: 'users', label: '用户管理', desc: '账号资料、角色与启停状态，变更全部写入操作日志。', icon: <TeamOutlined /> },
  { key: 'events', label: '事件流', desc: '跨插件统一事件视图，可按动作与关键词追溯一次请求。', icon: <HistoryOutlined /> },
  { key: 'storage', label: '空间分配', desc: '按工作区分配存储上限（默认 100MB），查看已用空间与使用率。', icon: <HddOutlined /> },
  { key: 'info', label: '系统信息', desc: '版本、数据库与存储路径等运行期信息。', icon: <InfoCircleOutlined /> },
  { key: 'backup', label: '系统备份', desc: '整库打包为 .tar.gz（含 manifest 元信息与附件目录）。', icon: <CloudDownloadOutlined /> },
  { key: 'restore', label: '系统恢复', desc: '校验备份包后覆盖式还原，操作不可撤销。', icon: <CloudUploadOutlined /> },
] as const

/** URL 的 ?section= 归一化：未知 / 缺失一律落到「用户管理」. */
export function normalizeAdminSection(value: string | null | undefined): AdminSectionKey {
  return ADMIN_SECTIONS.some(s => s.key === value)
    ? (value as AdminSectionKey)
    : 'users'
}
