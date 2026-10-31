/** 行记录、视图、审计日志、引用与回收站、CSV 结果. */

import type { ID } from './common'

export type RowValues = Record<string, unknown>

/** 后端返回的行数据 — 扁平 dict，业务字段直接以字段名作为 key，不再嵌套 values.
 * 例如：{ id: 1, '姓名': '张三', '薪资': 15000, created_at: '...' }
 */
export interface RowResponse {
  id: ID
  created_at?: string
  updated_at?: string
  created_by?: ID | null
  updated_by?: ID | null
  /** 业务字段以字段名直接作为 key，类型由各字段定义决定 */
  [fieldName: string]: unknown
}

export type RowDetail = RowResponse

/** 创建行的请求体：values 字段承载业务值 */
export interface RowCreate { values: RowValues }

/** 更新行的请求体：values 字段承载待更新的业务值子集 */
export interface RowUpdate { values: RowValues }
export interface RowListResponse { items: RowResponse[]; total: number; offset: number; limit: number }
/** 自动编号预览：字段名 → 建行时将生成的编号值（只读，不落库） */
export interface AutoIncrementPreview { values: Record<string, string> }
export interface RecordListParams {
  offset?: number; limit?: number
  filters?: string | Record<string, unknown> | Array<Record<string, unknown>>
  sorts?: string | Record<string, unknown> | Array<Record<string, unknown>>
  filter_logic?: 'AND' | 'OR'
}

/** 视图可见性档位（对齐后端 ViewVisibility，ADR 0003）
 *  - `table`：表内可见（继承表权限），存量视图与「全部」默认视图的档位
 *  - `shared`：仅创建者 + 指定成员可见
 *  - `private`：仅创建者可见（新建默认）
 *  视图权限永不超过表权限（表权限是硬天花板）。
 */
export type ViewVisibility = 'table' | 'shared' | 'private'
export interface View {
  id: ID; name: string; view_type: string
  filters?: Record<string, unknown> | Array<{ field_name: string; op: string; value?: unknown }> | null
  /** 视图级排序规则（后端字段名 sortings） */
  sortings?: Record<string, unknown> | Array<{ field_name: string; direction: 'asc' | 'desc' }> | null
  /** 多条件组合方式（后端字段名 filter_type） */
  filter_type?: 'AND' | 'OR'
  field_order?: string[] | null; view_options?: Record<string, unknown> | null
  /** 是否默认视图（对齐后端 ViewResponse.is_default）—— 仅 `table` 档视图可持有 */
  is_default: boolean; created_at?: string
  /** 最后更新时间（UTC）：画布保存时作为乐观并发令牌（ADR 0023 §2） */
  updated_at?: string
  /** 可见性档位（对齐后端 ViewResponse.visibility） */
  visibility?: ViewVisibility
  /** 视图创建者：null=创建者已注销的孤儿视图（对所有人不可见，ADR 0003 决策 D3） */
  owner_id?: number | null
  /** 排序权重（后端 DataView.order） */
  order?: number
  /** 当前用户能否改该视图配置（后端按三档 + 表 EDIT_VIEWS 判定，见 ADR 0003 I7）。
   *  **前端不要自己用 visibility + owner_id 推断** —— 口径只有后端一处。 */
  can_edit?: boolean
  /** 当前用户能否改可见性 / 名单 / 删除 / 设默认（后端 VIEW_MANAGE） */
  can_manage?: boolean
  /** 共享名单人数（仅 `shared` 档有意义） */
  grantee_count?: number
}
export type ViewDetail = View

/** 共享名单条目（开档时随 visibility 一起提交，全量替换） */
export interface ViewMemberInput { user_id: number; role: ViewMemberRole }
/** 授权角色：viewer=只能看；editor=在自身表 EDIT_VIEWS 范围内可改配置 */
export type ViewMemberRole = 'viewer' | 'editor'
export interface ViewMember {
  user_id: number; username: string; nickname: string; role: ViewMemberRole
  /** 授权当前是否有效（目标账号存在且仍有表 READ/EDIT_VIEWS）；
   *  false = 已失效的残留授权（实时求值，可安全收回） */
  available: boolean
}
/** 可被授权者（共享选择器数据源） */
export interface ShareableMember {
  user_id: number; username: string; nickname: string
  /** 该成员是否有该表 EDIT_VIEWS —— false 时禁用 editor 选项（选了后端也会 422） */
  can_edit_views: boolean
}
export interface ViewVisibilityUpdate {
  visibility: ViewVisibility
  /** 仅目标档位为 `shared` 时接受；全量替换名单。省略表示不动既有名单 */
  members?: ViewMemberInput[]
}
export interface ViewCreate {
  name: string; view_type?: string
  filters?: Record<string, unknown> | Array<{ field_name: string; op: string; value?: unknown }> | null
  sortings?: Record<string, unknown> | Array<{ field_name: string; direction: 'asc' | 'desc' }> | null
  filter_type?: 'AND' | 'OR'
  field_order?: string[] | null; view_options?: Record<string, unknown> | null
  /** 是否设为默认视图（对齐后端 ViewCreate.is_default）—— 会清掉同表其它默认视图 */
  is_default?: boolean
  /** 可见性档位；省略时为 `private`（仅本人可见）；`table` 档需表 EDIT_VIEWS */
  visibility?: ViewVisibility
}
export interface ViewUpdate {
  name?: string; view_type?: string
  filters?: Record<string, unknown> | Array<{ field_name: string; op: string; value?: unknown }> | null
  sortings?: Record<string, unknown> | Array<{ field_name: string; direction: 'asc' | 'desc' }> | null
  filter_type?: 'AND' | 'OR' | null
  field_order?: string[] | null; view_options?: Record<string, unknown> | null
  /** 是否设为默认视图（对齐后端 ViewUpdate.is_default） */
  is_default?: boolean
  /** 乐观并发令牌（ADR 0023 §2）：与库内 updated_at 不一致时后端返回 409 */
  expected_updated_at?: string | null
}

/** dashboard 批量取数（ADR 0023 §4） */
export interface DashboardDataRequest {
  widget_ids?: string[]
  globals?: Record<string, unknown>
  force?: boolean
}

export interface DashboardDataMeta {
  scanned: number
  total: number
  truncated: boolean
  cached: boolean
}

export interface DashboardDataItem {
  widget_id: string
  /** Dataset 结构由 dashboard/chart/types.ts 定义，API 层保持弱类型避免反向依赖 */
  dataset: Record<string, unknown>
  meta: DashboardDataMeta
}

export interface DashboardDataErrorItem {
  widget_id: string
  detail: string
}

export interface DashboardDataResponse {
  items: DashboardDataItem[]
  errors: DashboardDataErrorItem[]
}

export interface AuditLog {
  id: ID; table_id?: ID; row_id?: ID; action: string
  actor_id?: ID | null; actor_name?: string
  payload?: Record<string, unknown> | null; created_at?: string
}
export interface Reference {
  id: ID
  from_table_id: ID; from_row_id: ID; from_field_id: ID
  to_table_id: ID; to_row_id: ID; to_field_id: ID; created_at?: string
  /** 前端便捷展示用：被引用表 ID（同 to_table_id） */
  table_id?: ID
  /** 前端便捷展示用：被引用行 ID（同 to_row_id） */
  row_id?: ID
  /** 前端便捷展示用：被引用表名称 */
  table_name?: string
  /** 前端便捷展示用：被引用行摘要 */
  row_summary?: string
}

/** 回收站中的行 — 同样扁平结构 */
export interface TrashedRow {
  id: ID
  original_id?: ID
  deleted_at?: string
  /** 软删时间（后端可能返回 _trashed_at 或 deleted_at） */
  _trashed_at?: string
  [fieldName: string]: unknown
}

export interface CsvAnalyzeResult { columns: string[]; total_rows: number }
export interface CsvImportResult { table_id: ID; imported_rows: number; table_name?: string; imported?: number }

/** 通用文件导入分析结果（新） */
