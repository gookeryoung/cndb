/** 导入预览的类型下拉选项 —— 页面与 FieldsList 共用（纯中文标签，value 保持后端英文类型）. */

import { FIELD_TYPE_META, PREVIEW_FIELD_TYPE_VALUES } from '@/utils/fieldTypeMeta'

export const PREVIEW_TYPE_OPTIONS = PREVIEW_FIELD_TYPE_VALUES.map(v => ({
  value: v,
  label: FIELD_TYPE_META[v]?.label ?? v,
}))
