/** 引用修复的下拉选项与原因文案（ADR 0156）.
 *
 * 单一来源：移动弹窗（选修复策略）与引用修复弹窗（选策略 / 展示原因）共用，
 * 避免两处文案漂移。默认策略 `none`，其余两档都要在界面里说清「会改正文」。
 */

import type { ReferenceIssue, ReferenceRepairStrategy } from '@/api/documents'

export const REPAIR_STRATEGY_OPTIONS: Array<{ value: ReferenceRepairStrategy; label: string }> = [
  { value: 'none', label: '不处理（引用保持原样）' },
  { value: 'annotate', label: '注释说明（改写为「已移至…」）' },
  { value: 'snapshot', label: '表格快照（数据表落为静态表格）' },
]

const REASON_LABELS: Record<ReferenceIssue['reason'], string> = {
  target_left_behind: '目标留在原工作区',
  target_moved: '目标已移入本工作区',
  target_not_found: '目标不存在',
  table_in_other_workspace: '数据表在其它工作区',
  table_deleted: '数据表已删除',
}

export function repairReasonLabel(reason: ReferenceIssue['reason']): string {
  return REASON_LABELS[reason] ?? reason
}
