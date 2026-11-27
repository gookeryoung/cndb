/** 表与字段 API — /api/v1/workspaces/{wid}/tables/* 及字段/权限/审计/成员子资源 */

import api from './client'
import type {
    TableCreate, TableUpdate, TableSummary, TableDetail, TableGroup,
    TableDictionaryScore, TableDictionaryParams,
    FieldCreate, FieldUpdate, FieldImportRequest, FieldImportResponse, Field,
    FieldDetectOptionsRequest, FieldDetectOptionsResponse,
    AuditLog, Reference,
    TablePermission,
    TableMember, MemberCreate, MemberUpdate, OwnerTransferPayload,
    RowPermissionRule, RowRuleSubject, RowRulePreviewResponse,
    RowRuleCreatePayload, RowRuleUpdatePayload,
    LinkGraph,
} from './types'

// ─────────────────── AI 动作（ADR 0020 P2）：只生成建议，不写库 ───────────────────

/** 表格字段批量填充的模型用量（与平台 `usage` 结构一致） */
export interface TableAiUsage {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
}

/** 单行字段填充建议值；`row_id` 由后端按请求行集合过滤，多余行丢弃 */
export interface TableAiFieldFillValue {
    row_id: number
    value: string | number | boolean | null
}

/** 字段批量填充请求：单字段、最多 20 行；`instruction` 为可选的生成要求 */
export interface TableAiFillFieldPayload {
    field_name: string
    row_ids: number[]
    instruction?: string
}

/** 字段批量填充响应（只读建议，不写任何行；确认后由前端逐行走既有更新接口） */
export interface TableAiFillFieldResponse {
    action: 'table.fill_field'
    run_id: number
    model: string
    usage: TableAiUsage
    result: { values: TableAiFieldFillValue[] }
    /** 不存在 / 已软删 / 行级权限外的行（未进入模型输入） */
    skipped_row_ids: number[]
    /** 实际进入模型输入的行数 */
    row_count: number
}

export const tableApi = {
    list: (wid: number | string, includeTrashed = false) =>
        api.get<TableSummary[]>(`/v1/workspaces/${wid}/tables`, { params: { include_trashed: includeTrashed } }).then(r => r.data),
    create: (wid: number | string, data: TableCreate) =>
        api.post<TableDetail>(`/v1/workspaces/${wid}/tables`, data).then(r => r.data),
    get: (wid: number | string, tid: number | string) =>
        api.get<TableDetail>(`/v1/workspaces/${wid}/tables/${tid}`).then(r => r.data),
    update: (wid: number | string, tid: number | string, data: TableUpdate) =>
        api.patch<TableDetail>(`/v1/workspaces/${wid}/tables/${tid}`, data).then(r => r.data),
    remove: (wid: number | string, tid: number | string) =>
        api.delete(`/v1/workspaces/${wid}/tables/${tid}`).then(r => r.data),
    /** 复制表 — 支持三种模式:
     * - mode='structure'（默认）: 仅复制表结构
     * - mode='all': 复制结构 + 全部数据
     * - mode='view': 复制结构 + 指定视图过滤后的数据（需传 viewId）
     */
    copy: (wid: number | string, tid: number | string, opts?: { mode?: 'structure' | 'all' | 'view'; viewId?: number | string }) => {
        const mode = opts?.mode ?? 'structure'
        const params: Record<string, unknown> = { mode }
        if (opts?.viewId != null) params.view_id = opts.viewId
        return api.post<TableDetail>(`/v1/workspaces/${wid}/tables/${tid}/copy`, null, { params }).then(r => r.data)
    },
    move: (wid: number | string, tid: number | string, targetWorkspaceId: number | string) =>
        api.post<TableDetail>(`/v1/workspaces/${wid}/tables/${tid}/move`, null, { params: { target_workspace_id: targetWorkspaceId } }).then(r => r.data),
    reorder: (wid: number | string, tableIds: Array<number | string>) =>
        api.post<TableSummary[]>(`/v1/workspaces/${wid}/tables/reorder`, tableIds).then(r => r.data),
    /** 工作区数据表关联图（需求 0187 P0）：可读表为节点、link 字段为边，只读聚合 */
    linkGraph: (wid: number | string, maxNodes?: number) =>
        api
            .get<LinkGraph>(`/v1/workspaces/${wid}/tables/link-graph`, { params: maxNodes != null ? { max_nodes: maxNodes } : undefined })
            .then(r => r.data),
    references: (wid: number | string, tid: number | string, recordId: number | string) =>
        api.get<Reference[]>(`/v1/workspaces/${wid}/tables/${tid}/records/${recordId}/references`).then(r => r.data),
    /** AI 字段批量填充建议（只生成建议，不写库；确认后由前端逐行走既有更新接口） */
    aiFillField: (wid: number | string, tid: number | string, payload: TableAiFillFieldPayload) =>
        api.post<TableAiFillFieldResponse>(`/v1/workspaces/${wid}/tables/${tid}/ai/actions/fill_field`, payload).then(r => r.data),
}

/** 工作区级表分组（需求 0137）：分组成员可读；建组 / 改名 / 排序 / 删除要求 EDITOR */
export const tableGroupApi = {
    list: (wid: number | string) =>
        api.get<TableGroup[]>(`/v1/workspaces/${wid}/table-groups`).then(r => r.data),
    create: (wid: number | string, data: { name: string; order?: number }) =>
        api.post<TableGroup>(`/v1/workspaces/${wid}/table-groups`, data).then(r => r.data),
    update: (wid: number | string, gid: number | string, data: { name?: string; order?: number }) =>
        api.patch<TableGroup>(`/v1/workspaces/${wid}/table-groups/${gid}`, data).then(r => r.data),
    remove: (wid: number | string, gid: number | string) =>
        api.delete(`/v1/workspaces/${wid}/table-groups/${gid}`).then(r => r.data),
    reorder: (wid: number | string, groupIds: Array<number | string>) =>
        api.post<TableGroup[]>(`/v1/workspaces/${wid}/table-groups/reorder`, groupIds).then(r => r.data),
}

// ─────────────────── 数据表字段字典（ADR 0188）：只读导出 ───────────────────

/** 从 Content-Disposition 解析下载文件名（优先 filename*，回退 filename） */
export function parseDictionaryFilename(disposition: string | undefined, fallback: string): string {
    if (!disposition) return fallback
    const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
    if (utf8?.[1]) {
        try { return decodeURIComponent(utf8[1]) } catch { /* 非法编码回退 */ }
    }
    const plain = /filename="([^"]+)"/i.exec(disposition)
    return plain?.[1] || fallback
}

export const dictionaryApi = {
    /** 单表字段字典（返回 blob + 解析出的文件名） */
    exportTable: async (wid: number | string, tid: number | string, params: TableDictionaryParams) => {
        const resp = await api.get(`/v1/workspaces/${wid}/tables/${tid}/dictionary`, {
            params: { format: params.format, include_internal: params.include_internal ?? false, ...(params.template ? { template: params.template } : {}) },
            responseType: 'blob',
        })
        return {
            blob: resp.data as Blob,
            filename: parseDictionaryFilename(resp.headers['content-disposition'] as string | undefined, `数据字典.${params.format}`),
        }
    },
    /** 工作区合订字段字典；tableIds 为空 = 全部未删表 */
    exportWorkspace: async (wid: number | string, params: TableDictionaryParams & { tableIds?: Array<number | string> }) => {
        const resp = await api.get(`/v1/workspaces/${wid}/tables/dictionary`, {
            params: {
                format: params.format,
                include_internal: params.include_internal ?? false,
                ...(params.tableIds?.length ? { table_ids: params.tableIds.join(',') } : {}),
                ...(params.template ? { template: params.template } : {}),
            },
            responseType: 'blob',
        })
        return {
            blob: resp.data as Blob,
            filename: parseDictionaryFilename(resp.headers['content-disposition'] as string | undefined, `数据字典.${params.format}`),
        }
    },
    /** 标准符合度指标（只读） */
    score: (wid: number | string, tid: number | string) =>
        api.get<TableDictionaryScore>(`/v1/workspaces/${wid}/tables/${tid}/dictionary/score`).then(r => r.data),
}

export const fieldApi = {
    /** 字段列表；`full=true` 返回全量 options（表详情 / 字段列表默认截断，ADR 0046 D6） */
    list: (wid: number | string, tid: number | string, includeTrashed = false, full = false) =>
        api.get<Field[]>(`/v1/workspaces/${wid}/tables/${tid}/fields`, { params: { include_trashed: includeTrashed, full } }).then(r => r.data),
    create: (wid: number | string, tid: number | string, data: FieldCreate) =>
        api.post<Field>(`/v1/workspaces/${wid}/tables/${tid}/fields`, data).then(r => r.data),
    /** 大表 DDL 影响预估（需求 0150）：只读，返回行数 / 空值行数 / 抽样耗时 / 预计耗时 */
  ddlImpact: (
    wid: number | string,
    tid: number | string,
    params: { action: 'change_type' | 'add_field' | 'add_index'; fieldId?: number | string; fieldType?: string; sample?: number },
  ) =>
    api
      .get<DdlImpact>(`/v1/workspaces/${wid}/tables/${tid}/fields/ddl-impact`, {
        params: {
          action: params.action,
          field_id: params.fieldId,
          field_type: params.fieldType,
          sample: params.sample,
        },
      })
      .then(r => r.data),
    update: (wid: number | string, tid: number | string, fid: number | string, data: FieldUpdate, force = false) =>
        api
            .patch<Field>(
                `/v1/workspaces/${wid}/tables/${tid}/fields/${fid}`,
                data,
                force ? { params: { force: true } } : undefined,
            )
            .then(r => r.data),
    remove: (wid: number | string, tid: number | string, fid: number | string) =>
        api.delete(`/v1/workspaces/${wid}/tables/${tid}/fields/${fid}`).then(r => r.data),
    /** 从其他表引入字段 schema 到当前表 */
    importFields: (wid: number | string, tid: number | string, data: FieldImportRequest) =>
        api.post<FieldImportResponse>(`/v1/workspaces/${wid}/tables/${tid}/fields/import`, data).then(r => r.data),
    /** 批量调整字段顺序（按传入顺序赋值 order 字段） */
    reorder: (wid: number | string, tid: number | string, fieldIds: Array<number | string>) =>
        api.post<Field[]>(`/v1/workspaces/${wid}/tables/${tid}/fields/reorder`, { field_ids: fieldIds }).then(r => r.data),
    /** 识别字段存量数据可作为单选/多选选项的唯一值（只读，不持久化） */
    detectOptions: (wid: number | string, tid: number | string, fid: number | string, data: FieldDetectOptionsRequest) =>
        api.post<FieldDetectOptionsResponse>(`/v1/workspaces/${wid}/tables/${tid}/fields/${fid}/detect-options`, data).then(r => r.data),
}

export const auditApi = {
    list: (wid: number | string, tid: number | string, action?: string, limit = 100, rowId?: number | string) =>
        api.get<AuditLog[]>(`/v1/workspaces/${wid}/tables/${tid}/audit`, { params: { action, limit, row_id: rowId } }).then(r => r.data),
}

export const permissionApi = {
    get: (wid: number | string, tid: number | string) =>
        api.get<TablePermission>(`/v1/workspaces/${wid}/tables/${tid}/permissions`).then(r => r.data),
    /** 创建或全量更新 */
    upsert: (wid: number | string, tid: number | string, data: TablePermission) =>
        api.put<TablePermission>(`/v1/workspaces/${wid}/tables/${tid}/permissions`, data).then(r => r.data),
    /** 部分字段更新 */
    patch: (wid: number | string, tid: number | string, data: Partial<TablePermission>) =>
        api.patch<TablePermission>(`/v1/workspaces/${wid}/tables/${tid}/permissions`, data).then(r => r.data),
}

export const tableMembersApi = {
    list: (wid: number | string, tid: number | string) =>
        api.get<TableMember[]>(`/v1/workspaces/${wid}/tables/${tid}/members`).then(r => r.data),
    add: (wid: number | string, tid: number | string, data: MemberCreate) =>
        api.post<TableMember>(`/v1/workspaces/${wid}/tables/${tid}/members`, data).then(r => r.data),
    update: (wid: number | string, tid: number | string, userId: number, data: MemberUpdate) =>
        api.patch<TableMember>(`/v1/workspaces/${wid}/tables/${tid}/members/${userId}`, data).then(r => r.data),
    remove: (wid: number | string, tid: number | string, userId: number) =>
        api.delete(`/v1/workspaces/${wid}/tables/${tid}/members/${userId}`),
    transferOwner: (wid: number | string, tid: number | string, data: OwnerTransferPayload) =>
        api.post(`/v1/workspaces/${wid}/tables/${tid}/owner`, data),
}

/** 行级权限规则（ADR 0004 §5）：均要求表 EDIT_SCHEMA，属敏感配置 */
export const rowPermissionApi = {
    /** 列出规则（需 EDIT_SCHEMA） */
    list: (wid: number | string, tid: number | string) =>
        api.get<RowPermissionRule[]>(`/v1/workspaces/${wid}/tables/${tid}/row-permissions`).then(r => r.data),
    /** 创建规则（每主体每动作至多一条） */
    create: (wid: number | string, tid: number | string, data: RowRuleCreatePayload) =>
        api.post<RowPermissionRule>(`/v1/workspaces/${wid}/tables/${tid}/row-permissions`, data).then(r => r.data),
    /** 修改规则条件（主体 / 动作不可改） */
    update: (wid: number | string, tid: number | string, ruleId: number, data: RowRuleUpdatePayload) =>
        api.patch<RowPermissionRule>(`/v1/workspaces/${wid}/tables/${tid}/row-permissions/${ruleId}`, data).then(r => r.data),
    /** 删除规则 */
    remove: (wid: number | string, tid: number | string, ruleId: number) =>
        api.delete(`/v1/workspaces/${wid}/tables/${tid}/row-permissions/${ruleId}`),
    /** 可授权主体列表（选择器数据源） */
    subjects: (wid: number | string, tid: number | string) =>
        api.get<RowRuleSubject[]>(`/v1/workspaces/${wid}/tables/${tid}/row-permissions/subjects`).then(r => r.data),
    /** 规则命中行 dry-run 预览 */
    preview: (wid: number | string, tid: number | string, data: { filters: Array<{ field_name: string; op: string; value?: unknown }>; filter_type: 'AND' | 'OR' }) =>
        api.post<RowRulePreviewResponse>(`/v1/workspaces/${wid}/tables/${tid}/row-permissions/preview`, data).then(r => r.data),
}

/** 大表 DDL 影响预估（需求 0150） */
export interface DdlImpact {
  action: 'change_type' | 'add_field' | 'add_index'
  table_id: number
  table_name: string
  field: string | null
  target_type: string | null
  row_count: number
  field_null_count: number | null
  sampled_rows: number
  sample_size: number
  sample_ms: number
  factor: number
  estimated_ms: number
  threshold_rows: number
  force_required: boolean
}
