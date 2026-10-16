/** 视图 API — /api/v1/workspaces/{wid}/tables/{tid}/views/*（含看板/日历/导入导出） */

import api from './client'
import type {
    ViewCreate, View, ViewUpdate, RowResponse,
    ViewVisibilityUpdate, ViewMemberInput, ViewMember, ShareableMember, ViewMemberRole,
} from './types'

export const viewApi = {
    list: (wid: number | string, tid: number | string) =>
        api.get<View[]>(`/v1/workspaces/${wid}/tables/${tid}/views`).then(r => r.data),
    get: (wid: number | string, tid: number | string, vid: number | string) =>
        api.get<View>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}`).then(r => r.data),
    create: (wid: number | string, tid: number | string, data: ViewCreate) =>
        api.post<View>(`/v1/workspaces/${wid}/tables/${tid}/views`, data).then(r => r.data),
    /** 批量导入视图（JSON 数组，同名自动跳过） */
    importViews: (wid: number | string, tid: number | string, data: ViewCreate[]) =>
        api.post<View[]>(`/v1/workspaces/${wid}/tables/${tid}/views/import`, data).then(r => r.data),
    /** 批量导出视图（返回 ViewCreate 兼容数组，无内部元数据；不传 ids 导出全部） */
    exportViews: (wid: number | string, tid: number | string, ids?: Array<number | string>) => {
        const params = ids && ids.length ? { ids } : undefined
        return api.get<ViewCreate[]>(`/v1/workspaces/${wid}/tables/${tid}/views/export`, { params }).then(r => r.data)
    },
    update: (wid: number | string, tid: number | string, vid: number | string, data: ViewUpdate) =>
        api.patch<View>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}`, data).then(r => r.data),
    remove: (wid: number | string, tid: number | string, vid: number | string) =>
        api.delete(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}`).then(r => r.data),
    /** 批量调整视图顺序（按传入顺序赋值 order 字段） */
    reorder: (wid: number | string, tid: number | string, viewIds: Array<number | string>) =>
        api.post<View[]>(`/v1/workspaces/${wid}/tables/${tid}/views/reorder`, viewIds).then(r => r.data),
    /** 按视图的 filters/sorts 查行 */
    rows: (wid: number | string, tid: number | string, vid: number | string, limit = 100, offset = 0) =>
        api.get<{ rows: RowResponse[]; total: number; view_id: number }>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/rows`, { params: { limit, offset } }).then(r => r.data),
    /** 看板视图（按 view_options.group_field 分组） */
    kanban: (wid: number | string, tid: number | string, vid: number | string, limit = 500) =>
        api.get<{ columns: Record<string, RowResponse[]>; total: number; group_field: string }>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/kanban`, { params: { limit } }).then(r => r.data),
    /** 日历视图 */
    calendar: (wid: number | string, tid: number | string, vid: number | string, start?: string, end?: string, limit = 500) =>
        api.get<{ rows: RowResponse[]; total: number; start_field: string }>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/calendar`, { params: { start, end, limit } }).then(r => r.data),

    // ── 可见性与共享名单（ADR 0003 P3）──────────────────
    /** 切换可见性档位；`members` 仅目标档位为 shared 时接受（全量替换名单，省略=不动名单） */
    setVisibility: (wid: number | string, tid: number | string, vid: number | string, data: ViewVisibilityUpdate) =>
        api.post<View>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/visibility`, data).then(r => r.data),
    /** 共享名单（需 VIEW_MANAGE） */
    listMembers: (wid: number | string, tid: number | string, vid: number | string) =>
        api.get<ViewMember[]>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/members`).then(r => r.data),
    /** 新增 / 改权（仅 shared 档；editor 需对方有该表 EDIT_VIEWS） */
    setMember: (wid: number | string, tid: number | string, vid: number | string, userId: number, role: ViewMemberRole) =>
        api.put<ViewMember>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/members/${userId}`, { role }).then(r => r.data),
    /** 收回授权 */
    removeMember: (wid: number | string, tid: number | string, vid: number | string, userId: number) =>
        api.delete(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/members/${userId}`).then(r => r.data),
    /** 可授权者（工作区成员 ∧ 该表 READ，排除自己与创建者）—— 共享选择器数据源 */
    shareableMembers: (wid: number | string, tid: number | string, vid: number | string) =>
        api.get<ShareableMember[]>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/shareable-members`).then(r => r.data),
    /** 便捷封装：开 shared 档并一次性写入名单 */
    share: (wid: number | string, tid: number | string, vid: number | string, members: ViewMemberInput[]) =>
        api.post<View>(`/v1/workspaces/${wid}/tables/${tid}/views/${vid}/visibility`, { visibility: 'shared', members }).then(r => r.data),
}
