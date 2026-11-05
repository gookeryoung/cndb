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

/** 约束条目（IR v4，ADR 0086 D5/D6）：求解状态进 IR，错误走诊断 */
export interface DesignIRConstraint {
  id: string
  type: 'fixed' | 'coincident' | 'concentric' | 'distance' | 'angle'
  a: string
  b?: string
  status: 'ok' | 'warning'
  line: number
  col: number
}

/** 装配大纲 use 实例的引用来源（IR v4） */
export interface DesignOutlineRef {
  file_id: number
  file_key: string
  kind: 'part' | 'assembly' | string
}

/** 设计 IR（v5 = v4 + 大纲 node_index（ADR 0103）；单位固定 mm / deg，I5） */
export interface DesignIR {
  version: number
  units: { length: string; angle: string }
  params: DesignIRParam[]
  nodes: DesignIRNode[]
  /** 装配大纲（ADR 0083 D2 / ADR 0084 D2）；历史 v1 快照可能缺失 */
  outline?: DesignOutline
  /** 组件级装配约束求解结果（v4）；旧 v1-v3 快照缺失 */
  constraints?: DesignIRConstraint[]
}

/** 大纲节点公共字段：`node_index` 为首个所属顶层 `nodes` 下标（IR v5，ADR 0103 D7）.
 * v4 及更早快照无该字段 → 联动高亮静默降级（I2）。 */
interface DesignOutlineIndex {
  node_index?: number | null
  file_id?: number
}

/** 装配大纲节点（ADR 0083 D3 / ADR 0084 D2）：
 * 系统（system 声明，复杂系统级）/ 组件（module 实例，可嵌套）/ 布尔分组 / 零件（图元） */
export interface DesignOutlineSystemNode extends DesignOutlineIndex {
  kind: 'system'
  name: string
  line: number
  col: number
  children: DesignOutlineNode[]
}

export interface DesignOutlineAssemblyNode extends DesignOutlineIndex {
  kind: 'assembly'
  name: string
  line: number
  col: number
  children: DesignOutlineNode[]
  /** use 实例的源文件（IR v4）；当前设计内联组件缺省 */
  ref?: DesignOutlineRef
}

export interface DesignOutlineGroupNode extends DesignOutlineIndex {
  kind: 'group'
  op: 'union' | 'difference' | 'intersection'
  line: number
  col: number
  children: DesignOutlineNode[]
}

export interface DesignOutlinePartNode extends DesignOutlineIndex {
  kind: 'part'
  primitive: 'box' | 'cyl' | 'sphere' | 'cone' | 'torus' | 'tube'
  line: number
  col: number
}

export type DesignOutlineNode =
  | DesignOutlineSystemNode
  | DesignOutlineAssemblyNode
  | DesignOutlineGroupNode
  | DesignOutlinePartNode

export interface DesignOutline {
  children: DesignOutlineNode[]
}

/** 单设计装配大纲（outline 端点；source: compiled 快照 / content 历史快照派生，ADR 0083 D5） */
export interface DesignOutlineResult {
  design_id: number
  version_number: number
  outline: DesignOutline
  source: 'compiled' | 'content'
}

/** 即时编译结果（preview 端点；无落库） */
export interface DesignPreviewResult {
  ok: boolean
  ir: DesignIR | null
  diagnostics: DesignDiagnostic[]
}

/** 设计文件列表项（不含原文与 IR） */
export interface DesignListItem {
  id: number
  workspace_id: number
  title: string
  description: string
  kind: 'part' | 'assembly' | string
  file_key: string
  folder: string
  dependencies_stale: boolean
  version_count: number
  created_at: string | null
  updated_at: string | null
}

/** 设计文件详情（原文唯一真相源；**不含 compiled**，IR 走 getIR，ADR 0086 D10） */
export interface DesignDetail extends DesignListItem {
  content: string
  content_hash: string
  version_number: number
}

/** GET /{id}/ir 响应：IR 快照直用（首屏不重复编译，I6）；ETag = content_hash-version */
export interface DesignIRResponse {
  design_id: number
  version_number: number
  content_hash: string
  ir: DesignIR
}

/** 依赖 / 引用方条目（GET /{id}/dependencies） */
export interface DesignDependencyItem {
  design_id: number
  file_key: string
  title: string
  folder: string
  kind: string
  version_number: number
  dependencies_stale: boolean
}

/** 当前直接引用（items）与引用方清单（referrers） */
export interface DesignDependenciesResponse {
  design_id: number
  items: DesignDependencyItem[]
  referrers: DesignDependencyItem[]
}

/** 版本列表项（不含原文；回看走单版本端点） */
export interface DesignVersionItem {
  id: number
  design_id: number
  version_number: number
  comment: string
  created_by_id: number | null
  created_at: string | null
}

/** 版本回看（P2）：该版原文、编译快照与依赖闭包快照 */
export interface DesignVersionDetail extends DesignVersionItem {
  content: string
  compiled: DesignIR | Record<string, never>
  dependencies: Array<{ file_id: number; file_key: string; version_number: number; content_hash: string }>
}

const base = (wid: number | string) => `/v1/workspaces/${wid}/designs`

export const designsApi = {
  /** 设计文件列表（过滤软删，按更新时间倒序；kind / folder / q_title 过滤） */
  list: (wid: number | string, params?: { q_title?: string; kind?: string; folder?: string }) =>
    api.get<DesignListItem[]>(base(wid), { params }).then(r => r.data),
  /** 新建设计文件（原文必经编译，失败 400 + 诊断；kind/file_key/folder 可选） */
  create: (wid: number | string, data: {
    title: string
    content?: string
    description?: string
    kind?: 'part' | 'assembly'
    file_key?: string
    folder?: string
  }) =>
    api.post<DesignDetail>(base(wid), data).then(r => r.data),
  /** 详情（原文 + 文件身份；不含 compiled，ADR 0086 D10） */
  get: (wid: number | string, designId: number | string) =>
    api.get<DesignDetail>(`${base(wid)}/${designId}`).then(r => r.data),
  /** 改名 / 描述 / 目录（不触发重编译；file_key 不可改） */
  update: (wid: number | string, designId: number | string, data: { title?: string; description?: string; folder?: string }) =>
    api.put<DesignDetail>(`${base(wid)}/${designId}`, data).then(r => r.data),
  /** 保存原文（编译通过才落库并生成新版本；失败旧 IR 不动） */
  saveContent: (wid: number | string, designId: number | string, data: { content: string; comment?: string }) =>
    api.put<DesignDetail>(`${base(wid)}/${designId}/content`, data).then(r => r.data),
  /** 软删 */
  remove: (wid: number | string, designId: number | string) =>
    api.delete<void>(`${base(wid)}/${designId}`).then(r => r.data),
  /** 即时编译（编辑器防抖 / 参数面板共用；带 design_id 解析 use 引用；无落库） */
  preview: (wid: number | string, data: { content: string; overrides?: Record<string, number> | null; design_id?: number | null }) =>
    api.post<DesignPreviewResult>(`${base(wid)}/preview`, data).then(r => r.data),
  /** IR 快照（首屏直用不重复编译，I6；带 ETag 支持条件请求） */
  getIR: (wid: number | string, designId: number | string) =>
    api.get<DesignIRResponse>(`${base(wid)}/${designId}/ir`).then(r => r.data),
  /** 依赖刷新：以最新依赖重编译落新版本并清 stale（editor 权限） */
  refresh: (wid: number | string, designId: number | string, comment?: string) =>
    api.post<DesignDetail>(`${base(wid)}/${designId}/refresh`, { comment: comment ?? '依赖更新' }).then(r => r.data),
  /** 当前直接依赖与引用方清单 */
  dependencies: (wid: number | string, designId: number | string) =>
    api.get<DesignDependenciesResponse>(`${base(wid)}/${designId}/dependencies`).then(r => r.data),
  /** 版本列表（按版本号倒序） */
  listVersions: (wid: number | string, designId: number | string) =>
    api.get<DesignVersionItem[]>(`${base(wid)}/${designId}/versions`).then(r => r.data),
  /** 版本回看：该版原文与 IR 快照（成员可读） */
  getVersion: (wid: number | string, designId: number | string, versionNumber: number) =>
    api.get<DesignVersionDetail>(`${base(wid)}/${designId}/versions/${versionNumber}`).then(r => r.data),
  /** 恢复历史版：以该版原文重编译保存为新版本（editor 权限） */
  restoreVersion: (wid: number | string, designId: number | string, versionNumber: number) =>
    api.post<DesignDetail>(`${base(wid)}/${designId}/versions/${versionNumber}/restore`).then(r => r.data),
  /** 装配大纲（组件 / 分组 / 零件树 + 1 基源位置；成员可读，ADR 0083 D4） */
  outline: (wid: number | string, designId: number | string) =>
    api.get<DesignOutlineResult>(`${base(wid)}/${designId}/outline`).then(r => r.data),
}
