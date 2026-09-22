/** 公开分享 API — /api/v1/public/*（全局挂载，匿名访问） */

import api from './client'
import type { FieldType, RowResponse } from './types'

export const publicApi = {
    /** 匿名只读分享 Grid */
    getShare: (slug: string, limit = 100, offset = 0) =>
        api.get<{
            view: { id: number; name: string; view_type: string; filters: unknown; sortings: unknown }
            table: { id: number; name: string; description: string | null; fields: Array<{ id: number; name: string; field_type: FieldType; config: unknown; required?: boolean; is_unique?: boolean; hidden?: boolean }> }
            rows: RowResponse[]; total: number
        }>(`/v1/public/share/${slug}`, { params: { limit, offset } }).then(r => r.data),
    /** 公开表单元数据（获取表结构渲染表单） */
    getForm: (slug: string) =>
        api.get<{
            view: { id: number; name: string; view_type: string }
            table: { id: number; name: string; description: string | null; fields: Array<{ id: number; name: string; field_type: FieldType; config: unknown; required?: boolean; is_unique?: boolean; hidden?: boolean }> }
        }>(`/v1/public/forms/${slug}`).then(r => r.data),
    /** 匿名提交公开表单行 */
    submitForm: (slug: string, values: Record<string, unknown>) =>
        api.post<{ id: number; status: string }>(`/v1/public/forms/${slug}`, values).then(r => r.data),
}
