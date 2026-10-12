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
}
