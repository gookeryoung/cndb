/** 工作区功能模块 —— 模块元数据与「按模块开放的功能」计算（ADR 0080）.
 *
 * 创建弹窗、工作区设置、顶部页签与侧栏门控共用，与后端
 * `workspaces/modules.py` 语义逐项一致（I2/I3）。
 * 三模块可任意勾选组合；数据分析 / 数据源同步强绑定数据表（派生功能，
 * 不出现在勾选 UI 与 API 字段）；质量检查恒开放（D4）。
 */

export type WorkspaceModule = 'tables' | 'documents' | 'design'

/** 模块清单（有序：决定勾选 UI 与校验归一化顺序） */
export const WORKSPACE_MODULES: readonly WorkspaceModule[] = ['tables', 'documents', 'design']

/** 新建工作区默认模块：三模块全选（ADR 0080 D8） */
export const DEFAULT_WORKSPACE_MODULES: WorkspaceModule[] = ['tables', 'documents', 'design']

/** 模块中文名 */
export const WORKSPACE_MODULE_LABEL: Record<WorkspaceModule, string> = {
  tables: '数据表',
  documents: '文档',
  design: '设计',
}

/** 模块一句话说明（创建/设置卡片展示） */
export const WORKSPACE_MODULE_HINT: Record<WorkspaceModule, string> = {
  tables: '数据表、数据分析与数据源同步（三者强绑定）',
  documents: '结构化文档协作与分享',
  design: '结构 DSL 建模与 3D 实时预览',
}

/** 模块图标（antd 图标组件名，选型卡片渲染用） */
export const WORKSPACE_MODULE_ICON: Record<WorkspaceModule, string> = {
  tables: 'DatabaseOutlined',
  documents: 'FileTextOutlined',
  design: 'ToolOutlined',
}

/** 允许在新增/修改时勾选的模块选项（顺序即展示顺序） */
export const WORKSPACE_MODULE_OPTIONS: Array<{ value: WorkspaceModule; label: string }> =
  WORKSPACE_MODULES.map(m => ({ value: m, label: WORKSPACE_MODULE_LABEL[m] }))

/** 校验并归一模块集合：非空、白名单、去重、按 WORKSPACE_MODULES 固定顺序.
 *  非法输入回退全三模块（容忍旧数据/旧备份），语义对齐后端 workspace_modules_from_meta. */
export function normalizeModules(value: unknown): WorkspaceModule[] {
  if (!Array.isArray(value) || value.length === 0) return [...DEFAULT_WORKSPACE_MODULES]
  const known = new Set<string>(WORKSPACE_MODULES)
  const filtered = value.filter((v): v is WorkspaceModule => typeof v === 'string' && known.has(v))
  if (filtered.length === 0) return [...DEFAULT_WORKSPACE_MODULES]
  return WORKSPACE_MODULES.filter(m => filtered.includes(m))
}

export interface WorkspaceFeatures {
  /** 数据表功能（列表 / 表详情 / 侧栏导航） */
  tables: boolean
  /** 文档功能（文档页签 / 文档区） */
  documents: boolean
  /** 设计功能（结构 DSL + 3D 实时预览） */
  design: boolean
  /** 数据分析功能（数据表派生，强绑定） */
  analytics: boolean
  /** 数据源同步功能（数据表派生，强绑定） */
  datasource: boolean
  /** 质量检查功能：所有工作区恒开放（ADR 0080 D4） */
  quality: boolean
}

/** 按模块集合解析开放的功能模块；缺失/非法时按默认全三模块处理. */
export function workspaceModulesFeatures(modules?: WorkspaceModule[] | null): WorkspaceFeatures {
  const enabled = new Set(normalizeModules(modules))
  return {
    tables: enabled.has('tables'),
    documents: enabled.has('documents'),
    design: enabled.has('design'),
    analytics: enabled.has('tables'),
    datasource: enabled.has('tables'),
    quality: true,
  }
}

/** 工作区落地页路由段：tables → documents → design 取第一个可用段（ADR 0080 D9）. */
export function workspaceLandingSegment(
  modules?: WorkspaceModule[] | null,
): 'tables' | 'documents' | 'design' {
  const enabled = new Set(normalizeModules(modules))
  if (enabled.has('tables')) return 'tables'
  if (enabled.has('documents')) return 'documents'
  return 'design'
}
