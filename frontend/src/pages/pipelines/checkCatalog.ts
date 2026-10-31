/** 质量检查页共用元数据 —— 状态 / 严重度 / 触发来源文案，以及检查目录插入片段生成.
 *
 * 后端 `checks` 目录只提供 `uses` + 输入 schema；这里把「插入到 YAML 第几层」的
 * 缩进与占位值固化，避免页面与运行详情各写一份。
 */

import type {
  PipelineCheckSpec, PipelineRunStatus, PipelineSeverity, PipelineTrigger, PipelineWorkflow,
} from '@/api'

/** 运行状态 → 标签文案与颜色 */
export const PIPELINE_STATUS_META: Record<PipelineRunStatus, { label: string; color: string }> = {
  pending: { label: '排队中', color: 'default' },
  running: { label: '运行中', color: 'processing' },
  success: { label: '通过', color: 'success' },
  partial: { label: '有告警', color: 'warning' },
  failed: { label: '未通过', color: 'error' },
  canceled: { label: '已取消', color: 'default' },
}

/** 触发来源 → 中文文案 */
export const PIPELINE_TRIGGER_LABEL: Record<PipelineTrigger, string> = {
  manual: '手动',
  event: '事件',
  schedule: '定时',
}

/** 严重度 → 中文文案与颜色（finding 列表 / step 行共用） */
export const PIPELINE_SEVERITY_META: Record<PipelineSeverity, { label: string; color: string }> = {
  error: { label: '错误', color: 'error' },
  warn: { label: '告警', color: 'warning' },
  info: { label: '提示', color: 'default' },
}

/** 检查类别 → 中文标签（后端 category 为自由字符串，未知类别原样展示） */
export const CHECK_CATEGORY_LABEL: Record<string, string> = {
  table: '数据表',
  document: '文档',
}

/** 运行是否仍可能推进（用于运行详情轮询） */
export function isActiveRun(status: PipelineRunStatus): boolean {
  return status === 'pending' || status === 'running'
}

/** 定义触发方式摘要（列表项副标题） */
export function describeTriggers(on: PipelineWorkflow['compiled']['on']): string {
  const parts: string[] = []
  if (on?.manual !== false) parts.push('手动')
  if (on?.events?.length) parts.push(`事件 ${on.events.join(' / ')}`)
  if (on?.schedule) parts.push(`定时 ${on.schedule}`)
  return parts.join(' · ') || '未配置触发'
}

/** 输入类型 → 占位值（供插入片段可直接编译通过） */
function inputPlaceholder(spec: PipelineCheckSpec, name: string, type: string): string {
  if (type === 'array' || name === 'fields' || name.endsWith('_ids')) return '[值]'
  if (name === 'table' || name === 'table_id') return '表名'
  if (name === 'document_id') return '文档 ID'
  if (type === 'number' || type === 'integer') return '0'
  if (type === 'boolean') return 'false'
  // 目标类型只有一个时给出可用的默认（如 table/null-rate 的 target 省略）
  return spec.target_types[0] ?? '值'
}

/** 生成可插入 jobs.steps 下的 YAML 片段（缩进 6 空格，与编辑器示例同口径） */
export function buildStepSnippet(spec: PipelineCheckSpec): string {
  const lines = [`      - uses: ${spec.uses}`]
  const required = spec.inputs.filter(input => input.required || input.default != null)
  if (required.length === 0) return lines.join('\n')
  lines.push('        with:')
  for (const input of required) {
    const value = input.default !== null && input.default !== undefined
      ? String(input.default)
      : inputPlaceholder(spec, input.name, input.type)
    lines.push(`          ${input.name}: ${value}`)
  }
  return lines.join('\n')
}

/** 最小可运行 DSL 模板（新建抽屉初始内容） */
export function defaultWorkflowContent(): string {
  return [
    'name: 数据质量巡检',
    'on:',
    '  manual: true',
    'jobs:',
    '  体检:',
    '    steps:',
    '      - uses: table/null-rate',
    '        with:',
    '          table: 表名',
    '          fields: [字段]',
  ].join('\n')
}
