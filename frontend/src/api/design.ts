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
  /** 库模块引用（ADR 0118 P1；依赖面板数据源） */
  library_items: DesignLibraryDependencyItem[]
  referrers: DesignDependencyItem[]
}

/** 设计直接引用的复用模块（锁定版本 + 是否可升级） */
export interface DesignLibraryDependencyItem {
  module_id: number
  module_key: string
  name: string
  version_number: number
  latest_version: number
  has_update: boolean
  visibility: 'public' | 'workspace' | string
  is_archived: boolean
  owner_workspace_id: number | null
  bundle_hash: string
}

/** 模块参数签名项 */
export interface LibraryParam {
  name: string
  default: number
}

/** 模块库列表项（ADR 0118 §6） */
export interface LibraryModuleItem {
  id: number
  module_key: string
  name: string
  description: string
  visibility: 'public' | 'workspace' | string
  owner_workspace_id: number | null
  is_archived: boolean
  version_count: number
  latest_version: number
  params: LibraryParam[]
  updated_at: string | null
}

export interface LibraryVersionItem {
  id: number
  version_number: number
  content_hash: string
  bundle_hash: string
  comment: string
  created_by_id: number | null
  created_at: string | null
}

export interface LibraryModuleDetail extends LibraryModuleItem {
  versions: LibraryVersionItem[]
  can_manage: boolean
}

export interface LibraryVersionDetail extends LibraryVersionItem {
  content: string
  params: LibraryParam[]
  files: Array<{ file_key: string; kind: string; content_hash: string }>
}

/** 版本来源类型（ADR 0113 / 0125）：manual 主动保存 / auto 兜底检查点 / refresh 依赖刷新 / rollback 版本恢复 */
export type DesignVersionChangeType = 'manual' | 'auto' | 'refresh' | 'rollback'

/** 个人草稿（ADR 0125）：stale 表示开始编辑后设计已前进版本，仅提示不拦截 */
export interface DesignDraftPayload {
  content: string
  content_size: number
  base_version_number: number
  current_version_number: number
  stale: boolean
  updated_at: string | null
}

/** 版本列表项（不含原文；回看走单版本端点） */
export interface DesignVersionItem {
  id: number
  design_id: number
  version_number: number
  change_type: DesignVersionChangeType | string
  comment: string
  created_by_id: number | null
  created_at: string | null
}

/** 版本回看（P2）：该版原文、编译快照与依赖闭包快照 */
export interface DesignVersionDetail extends DesignVersionItem {
  content: string
  compiled: DesignIR | Record<string, never>
  /** 依赖快照：工作区文件带 `file_id`；库文件带 `module_id` / `module_version_id` / `bundle_hash`（ADR 0118 P0） */
  dependencies: Array<{
    source?: 'workspace' | 'library'
    file_id?: number
    file_key: string
    version_number: number
    content_hash: string
    module_id?: number
    module_version_id?: number
    bundle_hash?: string
  }>
}

/** 两版本对比的结构摘要：参数增删改 / 节点数 / 顶层装配增删（ADR 0113 D5 / D8） */
export interface DesignVersionDiffSummary {
  available: boolean
  params: {
    added: string[]
    removed: string[]
    changed: Array<{ name: string; base: number | string | null; head: number | string | null }>
  }
  nodes: { base: number; head: number }
  assemblies: { added: string[]; removed: string[] }
}

/** GET /{id}/diff：unified diff + 增删行数 + 结构摘要 */
export interface DesignVersionDiff {
  base_version: number
  head_version: number
  diff: string
  added: number
  removed: number
  summary: DesignVersionDiffSummary
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
  /** 手动保存原文（编译通过才落库并生成 manual 版本；自动保存走 saveDraft，ADR 0125 D4） */
  saveContent: (wid: number | string, designId: number | string, data: {
    content: string
    comment?: string
  }) =>
    api.put<DesignDetail>(`${base(wid)}/${designId}/content`, data).then(r => r.data),
  /** 读取本人草稿（无草稿 / 与最新版相同返回 null） */
  getDraft: (wid: number | string, designId: number | string) =>
    api.get<DesignDraftPayload | null>(`${base(wid)}/${designId}/draft`).then(r => r.data),
  /** 保存本人草稿：不编译、不落版本；到期由服务端顺带落 auto 检查点 */
  saveDraft: (wid: number | string, designId: number | string, data: {
    content: string
    base_version_number?: number
  }) =>
    api.put<DesignDraftPayload | null>(`${base(wid)}/${designId}/draft`, data).then(r => r.data),
  /** 丢弃本人草稿（幂等） */
  discardDraft: (wid: number | string, designId: number | string) =>
    api.delete<void>(`${base(wid)}/${designId}/draft`).then(r => r.data),
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
  /** 两版本对比：unified diff + 结构摘要（成员可读，ADR 0113 §3） */
  getDiff: (wid: number | string, designId: number | string, baseVersion: number, headVersion: number) =>
    api.get<DesignVersionDiff>(`${base(wid)}/${designId}/diff`, {
      params: { base: baseVersion, head: headVersion },
    }).then(r => r.data),
  /** 装配大纲（组件 / 分组 / 零件树 + 1 基源位置；成员可读，ADR 0083 D4） */
  outline: (wid: number | string, designId: number | string) =>
    api.get<DesignOutlineResult>(`${base(wid)}/${designId}/outline`).then(r => r.data),
  /** 发布为复用模块（仅 part；ADR 0118 P0 / P1） */
  publish: (wid: number | string, designId: number | string, data: {
    visibility: 'public' | 'workspace'
    name?: string
    description?: string
    comment?: string
  }) =>
    api.post<{
      module_id: number
      module_key: string
      version_number: number
      visibility: string
      name: string
    }>(`${base(wid)}/${designId}/publish`, data).then(r => r.data),
}

const libraryBase = (wid: number | string) => `/v1/workspaces/${wid}/design-library`

/** 复用模块库 API —— /api/v1/workspaces/{wid}/design-library（ADR 0118 §6） */
export const designLibraryApi = {
  /** 浏览可见模块：公开 + 当前工作区发布 */
  list: (wid: number | string, params?: {
    q?: string
    visibility?: 'public' | 'workspace'
    owned_only?: boolean
    include_archived?: boolean
  }) =>
    api.get<LibraryModuleItem[]>(`${libraryBase(wid)}/modules`, { params }).then(r => r.data),
  /** 模块详情 + 版本列表；designId 用于既有引用的私有 / 归档授权 */
  get: (wid: number | string, moduleId: number | string, designId?: number | string) =>
    api.get<LibraryModuleDetail>(`${libraryBase(wid)}/modules/${moduleId}`, {
      params: designId != null ? { design_id: designId } : undefined,
    }).then(r => r.data),
  /** 版本详情（根原文 + 依赖元数据） */
  getVersion: (wid: number | string, moduleId: number | string, version: number, designId?: number | string) =>
    api.get<LibraryVersionDetail>(`${libraryBase(wid)}/modules/${moduleId}/versions/${version}`, {
      params: designId != null ? { design_id: designId } : undefined,
    }).then(r => r.data),
  /** 只读预览（参数覆盖，无落库） */
  preview: (
    wid: number | string,
    moduleId: number | string,
    version: number,
    data: { overrides?: Record<string, number> | null } = {},
    designId?: number | string,
  ) =>
    api.post<DesignPreviewResult>(
      `${libraryBase(wid)}/modules/${moduleId}/versions/${version}/preview`,
      data,
      { params: designId != null ? { design_id: designId } : undefined },
    ).then(r => r.data),
  /** 改名 / 描述 / 可见性 / 归档（owner 或系统管理员） */
  patch: (wid: number | string, moduleId: number | string, data: {
    name?: string
    description?: string
    visibility?: 'public' | 'workspace'
    is_archived?: boolean
  }) =>
    api.patch<LibraryModuleDetail>(`${libraryBase(wid)}/modules/${moduleId}`, data).then(r => r.data),
}
