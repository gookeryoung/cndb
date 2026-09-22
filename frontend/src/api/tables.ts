/** 表与字段 API — /api/v1/workspaces/{wid}/tables/* 及字段/权限/审计/成员子资源 */

import api from './client'
import type {
    TableCreate, TableUpdate, TableSummary, TableDetail,
    FieldCreate, FieldUpdate, FieldImportRequest, FieldImportResponse, Field,
    AuditLog, Reference,
    TablePermission,
    TableMember, MemberCreate, MemberUpdate, OwnerTransferPayload,
} from './types'

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
    references: (wid: number | string, tid: number | string, recordId: number | string) =>
        api.get<Reference[]>(`/v1/workspaces/${wid}/tables/${tid}/records/${recordId}/references`).then(r => r.data),
}

export const fieldApi = {
    list: (wid: number | string, tid: number | string, includeTrashed = false) =>
        api.get<Field[]>(`/v1/workspaces/${wid}/tables/${tid}/fields`, { params: { include_trashed: includeTrashed } }).then(r => r.data),
    create: (wid: number | string, tid: number | string, data: FieldCreate) =>
        api.post<Field>(`/v1/workspaces/${wid}/tables/${tid}/fields`, data).then(r => r.data),
    update: (wid: number | string, tid: number | string, fid: number | string, data: FieldUpdate) =>
        api.patch<Field>(`/v1/workspaces/${wid}/tables/${tid}/fields/${fid}`, data).then(r => r.data),
    remove: (wid: number | string, tid: number | string, fid: number | string) =>
        api.delete(`/v1/workspaces/${wid}/tables/${tid}/fields/${fid}`).then(r => r.data),
    /** 从其他表引入字段 schema 到当前表 */
    importFields: (wid: number | string, tid: number | string, data: FieldImportRequest) =>
        api.post<FieldImportResponse>(`/v1/workspaces/${wid}/tables/${tid}/fields/import`, data).then(r => r.data),
    /** 批量调整字段顺序（按传入顺序赋值 order 字段） */
    reorder: (wid: number | string, tid: number | string, fieldIds: Array<number | string>) =>
        api.post<Field[]>(`/v1/workspaces/${wid}/tables/${tid}/fields/reorder`, { field_ids: fieldIds }).then(r => r.data),
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
