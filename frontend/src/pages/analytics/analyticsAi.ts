/** 分析 AI 纯逻辑层 —— 解读输入构造 / 生成结果归一化（ADR 0020 P3）.
 *
 * 说明：页面只做请求编排与状态展示，可单测的转换集中在这里（与 `analyticsModel.ts`
 * 同思路），避免把「传哪些行给模型」「AI 配置怎么进编辑态」埋进 JSX。
 *
 * 硬约束（ADR 0020 附录 F）：
 * - 生成结果只填编辑态，**不自动保存**；保存仍走既有模板接口；
 * - 解读只读，`summary_rows` ≤ 50，只传结果行、不传整表。
 */

import type {
  AnalyticsAiExplainPayload,
  AnalyticsAiTemplateSuggestion,
  AnalyticsChart,
  AnalyticsComputeResponse,
  AnalyticsFormula,
  AnalyticsSummary,
  AnalyticsTemplateConfig,
} from '@/api/analytics'
import { normalizeChart, normalizeFormulas, normalizeSummary } from './analyticsModel'

/** 解读输入行上限（与后端 `analytics/services/ai.py` 的 MAX_EXPLAIN_ROWS 对齐） */
export const MAX_AI_EXPLAIN_ROWS = 50

/** AI 生成结果的提醒上限（后端 schema 已限制 ≤5，前端再兜一层避免渲染异常数据） */
export const MAX_AI_WARNINGS = 5

/**
 * 从当前计算结果取「结论解读」输入行：
 * - 配了分组汇总 → 用分组汇总行（与「分析结论」语义一致，行数已被 Top N 收敛）；
 * - 未配分组汇总 → 退回派生数据行（仍是结果而非整表输入，同样截断 50 行）。
 * 结果行全部浅拷贝，避免调用方后续编辑结果对象影响请求体。
 */
export function buildExplainRows(
  result: AnalyticsComputeResponse | null | undefined,
): Array<Record<string, unknown>> {
  if (!result) return []
  const rows = result.summary?.rows ?? result.rows ?? []
  return rows.slice(0, MAX_AI_EXPLAIN_ROWS).map(row => ({ ...row }))
}

/** 组装解读请求：无汇总行时返回空数组（页面据此提示「先运行分析」） */
export function buildExplainPayload(input: {
  result: AnalyticsComputeResponse | null | undefined
  chartType?: string | null
  templateId?: number | null
}): AnalyticsAiExplainPayload {
  const payload: AnalyticsAiExplainPayload = { summary_rows: buildExplainRows(input.result) }
  const chartType = (input.chartType ?? '').trim()
  if (chartType) payload.chart_type = chartType
  if (input.templateId != null) payload.template_id = Number(input.templateId)
  return payload
}

export interface AnalyticsAiEditorConfig {
  formulas: AnalyticsFormula[]
  chart: AnalyticsChart
  summary: AnalyticsSummary
}

/**
 * AI 生成的 `TemplateConfig` → 页面编辑态。
 * 与「载入模板」同口径走 `normalize*`：过滤脏数据、补默认键与聚合方式，
 * 保证后端已校验过的配置在前端也满足编辑器结构（不产生半成品）。
 */
export function applySuggestionConfig(
  config: AnalyticsTemplateConfig | null | undefined,
): AnalyticsAiEditorConfig {
  // 后端已校验过配置，这里再兜一层：丢掉空键 / 空表达式，避免模型给出占位行
  const formulas = (config?.formulas ?? []).filter(
    formula => formula && typeof formula.key === 'string' && typeof formula.expr === 'string'
      && formula.key.trim() !== '' && formula.expr.trim() !== '',
  )
  return {
    formulas: normalizeFormulas(formulas),
    chart: normalizeChart(config?.chart),
    summary: normalizeSummary(config?.summary),
  }
}

/** 生成结果的提醒文案：去空行、去重并截断到上限（供 Alert 直接渲染） */
export function suggestionWarnings(
  suggestion: Pick<AnalyticsAiTemplateSuggestion, 'warnings'> | null | undefined,
): string[] {
  const seen = new Set<string>()
  const warnings: string[] = []
  for (const item of suggestion?.warnings ?? []) {
    const text = typeof item === 'string' ? item.trim() : ''
    if (!text || seen.has(text)) continue
    seen.add(text)
    warnings.push(text)
    if (warnings.length >= MAX_AI_WARNINGS) break
  }
  return warnings
}

/** 生成结果的展示名（空名回退到前端默认名，避免保存弹窗出现空值） */
export function suggestionName(
  suggestion: Pick<AnalyticsAiTemplateSuggestion, 'name'> | null | undefined,
  fallback: string,
): string {
  return (suggestion?.name ?? '').trim() || fallback
}
