/** 工作区类型 —— 展示文案与「按类型开放的功能模块」计算.
 *
 * 创建弹窗、工作区设置、顶部页签与侧栏门控共用，避免文案与判定在多处重复。
 * 三种类型：
 *  - data_doc：数据 + 文档（默认）
 *  - data：仅数据表与数据分析
 *  - doc：仅文档
 */

import type { WorkspaceType } from '@/api'

export const WORKSPACE_TYPE_LABEL: Record<WorkspaceType, string> = {
  data_doc: '数据 + 文档',
  data: '数据',
  doc: '文档',
}

/** 类型一句话说明（创建/设置下拉展示） */
export const WORKSPACE_TYPE_HINT: Record<WorkspaceType, string> = {
  data_doc: '数据表、数据分析与文档全部可用（默认）',
  data: '仅提供数据表与数据分析，不含文档',
  doc: '仅提供文档，不含数据表与数据分析',
}

/** 允许在新增/修改时选用的类型选项（顺序即下拉顺序） */
export const WORKSPACE_TYPE_OPTIONS: Array<{ value: WorkspaceType; label: string }> = (
  ['data_doc', 'data', 'doc'] as WorkspaceType[]
).map(t => ({ value: t, label: WORKSPACE_TYPE_LABEL[t] }))

export interface WorkspaceFeatures {
  /** 数据表功能（列表 / 表详情 / 侧栏导航） */
  tables: boolean
  /** 文档功能（文档页签 / 文档区） */
  documents: boolean
  /** 数据分析功能 */
  analytics: boolean
  /** 数据源同步功能（周期性外部数据接入） */
  datasource: boolean
}

/** 按工作区类型解析开放的功能模块；类型缺失时按默认 data_doc 处理. */
export function workspaceTypeFeatures(type?: WorkspaceType | null): WorkspaceFeatures {
  switch (type) {
    case 'data':
      return { tables: true, documents: false, analytics: true, datasource: true }
    case 'doc':
      return { tables: false, documents: true, analytics: false, datasource: false }
    case 'data_doc':
    default:
      return { tables: true, documents: true, analytics: true, datasource: true }
  }
}

/** 工作区落地页路由段：doc → documents，其余 → tables. */
export function workspaceLandingSegment(type?: WorkspaceType | null): 'tables' | 'documents' {
  return workspaceTypeFeatures(type).tables ? 'tables' : 'documents'
}
