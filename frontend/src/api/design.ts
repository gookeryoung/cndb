/** 设计模块 API — /api/v1/workspaces/{wid}/designs
 *
 * 类型与后端 `design/schemas.py` 对齐；`compiled` 为结构 DSL 编译快照（IR），
 * 前端只消费 IR 渲染，不做任何 DSL 解析 / 求值（ADR 0079 I1 / D3）。
 */

import api from './client'

/** 编译诊断（编辑器 gutter 按行 / 列定位） */
export interface DesignDiagnostic {
  severity: 'error' | string
  line: number
  col: number
  message: string
}

/** IR 参数项（params[]） */
export interface DesignIRParam {
  name: string
  value: number
}

/** 变换栈（先外后内下推到图元；kind 与 DSL 四种变换一致） */
export interface DesignTransform {
  ops: Array<[DesignTransformKind, [number, number, number]]>
}

export type DesignTransformKind = 'translate' | 'rotate' | 'scale' | 'mirror'

/** 图元节点（六种，op 与 DSL 图元名一致；box 无 fn，其余 fn 为分段数） */
export type DesignPrimitiveNode = (
  | { op: 'box'; size: [number, number, number] }
  | { op: 'cyl'; d: number; h: number; fn: number }
  | { op: 'sphere'; r: number; fn: number }
  | { op: 'cone'; d1: number; d2: number; h: number; fn: number }
  | { op: 'torus'; r: number; tube: number; fn: number }
  | { op: 'tube'; od: number; id: number; h: number; fn: number }
) & { transform?: DesignTransform }

/** 布尔节点（children 首个为保留体，difference 其余为切割体） */
export interface DesignBooleanNode {
  op: 'union' | 'difference' | 'intersection'
  children: DesignIRNode[]
}

export type DesignIRNode = DesignPrimitiveNode | DesignBooleanNode

/** 设计 IR（v1，双端契约；单位固定 mm / deg，I5） */
export interface DesignIR {
  version: number
  units: { length: string; angle: string }
  params: DesignIRParam[]
  nodes: DesignIRNode[]
}

/** 即时编译结果（preview 端点；无落库） */
export interface DesignPreviewResult {
  ok: boolean
  ir: DesignIR | null
  diagnostics: DesignDiagnostic[]
}

/** 设计列表项（不含原文与 IR） */
export interface DesignListItem {
  id: number
  workspace_id: number
  title: string
  description: string
  version_count: number
  created_at: string | null
  updated_at: string | null
}

/** 设计详情（原文唯一真相源 + IR 快照 + 当前版本号） */
export interface DesignDetail extends DesignListItem {
  content: string
  compiled: DesignIR | Record<string, never>
  version_number: number
}

/** 版本列表项（回看 / 恢复属 P2，本期只列表） */
export interface DesignVersionItem {
  id: number
  design_id: number
  version_number: number
  comment: string
  created_by_id: number | null
  created_at: string | null
}

const base = (wid: number | string) => `/v1/workspaces/${wid}/designs`

export const designsApi = {
  /** 设计列表（过滤软删，按更新时间倒序） */
  list: (wid: number | string, params?: { q_title?: string }) =>
    api.get<DesignListItem[]>(base(wid), { params }).then(r => r.data),
  /** 新建（原文必经编译，失败 400 + 诊断） */
  create: (wid: number | string, data: { title: string; content?: string; description?: string }) =>
    api.post<DesignDetail>(base(wid), data).then(r => r.data),
  /** 详情（含原文与 IR） */
  get: (wid: number | string, designId: number | string) =>
    api.get<DesignDetail>(`${base(wid)}/${designId}`).then(r => r.data),
  /** 改名 / 描述（不触发重编译） */
  update: (wid: number | string, designId: number | string, data: { title?: string; description?: string }) =>
    api.put<DesignDetail>(`${base(wid)}/${designId}`, data).then(r => r.data),
  /** 保存原文（编译通过才落库并生成新版本；失败旧 IR 不动） */
  saveContent: (wid: number | string, designId: number | string, data: { content: string; comment?: string }) =>
    api.put<DesignDetail>(`${base(wid)}/${designId}/content`, data).then(r => r.data),
  /** 软删 */
  remove: (wid: number | string, designId: number | string) =>
    api.delete<void>(`${base(wid)}/${designId}`).then(r => r.data),
  /** 即时编译（编辑器防抖 / 参数面板共用；无落库） */
  preview: (wid: number | string, data: { content: string; overrides?: Record<string, number> | null }) =>
    api.post<DesignPreviewResult>(`${base(wid)}/preview`, data).then(r => r.data),
  /** 版本列表（按版本号倒序） */
  listVersions: (wid: number | string, designId: number | string) =>
    api.get<DesignVersionItem[]>(`${base(wid)}/${designId}/versions`).then(r => r.data),
}
