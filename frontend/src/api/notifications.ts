/** 站内通知 API（用户级）：列表 / 未读数 / 标记已读. */
import api from './client'

export interface NotificationItem {
    id: number
    /** 例如 document.collaborator_added */
    type: string
    actor_id?: number | null
    /** 操作者显示名（授权时快照，缺失时后端回查） */
    actor_name?: string
    workspace_id?: number | null
    document_id?: number | null
    /** 授权时快照的文档标题 */
    document_title?: string
    /** 被授予的文档角色（viewer/editor） */
    role?: string
    read: boolean
    created_at?: string
}

export interface NotificationListResult {
    items: NotificationItem[]
    unread_count: number
}

export const notificationsApi = {
    list: (params: { unread_only?: boolean; limit?: number; before_id?: number } = {}) =>
        api.get<NotificationListResult>('/v1/accounts/notifications', { params }).then(r => r.data),

    markRead: (id: number) => api.post(`/v1/accounts/notifications/${id}/read`),

    readAll: () => api.post<{ updated: number }>('/v1/accounts/notifications/read-all').then(r => r.data),
}
