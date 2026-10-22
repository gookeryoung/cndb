/** ImportPanel AI 列映射建议测试（ADR 0020 P2 / 附录 D）.
 *
 * 覆盖：预览步骤按钮显隐/禁用、建议回填映射编辑态、unmapped 提示、
 * 后端 detail 错误展示，以及「建议不自动确认导入」。
 *
 * 说明：上传 analyze 是 multipart（jsdom+MSW 无法拦截），沿用既有测试在 api 层 spyOn；
 * 纯 JSON 的 mapping-suggestion 端点走 MSW 真实拦截，并断言请求体契约。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'

import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { importApi } from '@/api'
import type { ImportTaskInfo, Field } from '@/api'
import type { ValidationReport } from '@/api/types'
import ImportPanel from './ImportPanel'

const csvFile = new File(['姓名,分数\n张三,90'], '客户数据.csv', { type: 'text/csv' })

const FIELDS: Field[] = [
  { id: 1, name: '姓名', field_type: 'text' },
  { id: 2, name: '分数', field_type: 'number' },
]

function makeTask(overrides: Partial<ImportTaskInfo> = {}): ImportTaskInfo {
  return {
    task_id: 77, status: 'pending', progress: 0,
    filename: '客户数据.csv', format: 'csv',
    imported_rows: null, error_message: null,
    validation_report: null,
    ...overrides,
  }
}

const previewReport = {
  total: 3, valid_count: 2, warning_count: 0, error_count: 0,
  new_count: 2, update_count: 1, update_changed_count: 1, multi_key_conflicts: 0,
  skipped_columns: [], missing_required: [],
  planned_columns: [],
  new_preview: [
    { row_number: 1, match_key_values: {}, field_sample: { 姓名: '张三', 分数: '90' } },
    { row_number: 2, match_key_values: {}, field_sample: { 姓名: '李四', 分数: '85' } },
  ],
  update_preview: [
    {
      row_number: 3, match_key_values: { 姓名: '王五' }, existing_row_id: 42,
      field_sample: { 分数: '95' },
      field_diffs: { 分数: { old: '88', new: '95', changed: true } },
    },
  ],
  warnings: [], errors: [],
} as unknown as ValidationReport

const previewTask = makeTask({ status: 'pending_confirm', progress: 60, validation_report: previewReport })

function chooseFile(file: File) {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement
  fireEvent.change(input, { target: { files: [file] } })
}

/** 注册 mapping-suggestion 的 MSW handler；返回请求体收集数组 */
function mockMappingSuggestion(overrides: {
  status?: number
  detail?: string
  mappings?: Array<{ source: string; target: string; confidence: number; reason: string }>
  unmapped?: string[]
} = {}) {
  const bodies: any[] = []
  server.use(
    http.post('/api/v1/workspaces/:wid/import-file/ai/mapping-suggestion', async ({ request }) => {
      bodies.push(await request.json())
      if (overrides.status && overrides.status >= 400) {
        return HttpResponse.json({ detail: overrides.detail ?? 'AI 调用失败' }, { status: overrides.status })
      }
      return HttpResponse.json({
        action: 'import.mapping_suggestion',
        run_id: 99,
        model: 'mock-model',
        usage: { prompt_tokens: 20, completion_tokens: 5, total_tokens: 25 },
        result: {
          mappings: overrides.mappings ?? [
            { source: '姓名', target: '姓名', confidence: 0.93, reason: '列名与目标字段一致' },
            { source: '分数', target: '分数', confidence: 0.55, reason: '数值列' },
          ],
          unmapped: overrides.unmapped ?? ['城市'],
        },
      })
    }),
  )
  return bodies
}

/** 打开预览阶段：analyze 返回 pending → 轮询首个 tick 进入 preview */
async function openPreview(tid = '100') {
  vi.spyOn(importApi, 'previewAnalyze').mockResolvedValue(makeTask())
  vi.spyOn(importApi, 'getTask').mockResolvedValue(previewTask)
  renderProviders(
    <ImportPanel open wid="10" tid={tid} fields={FIELDS} onClose={() => { }} />,
  )
  chooseFile(csvFile)
  await screen.findByText(/选择参考列/, {}, { timeout: 3000 })
}

describe('ImportPanel AI 列映射建议', () => {
  it('预览步骤点击按钮：回填 source→target 映射编辑态、展示置信度与 unmapped，且不自动确认导入', async () => {
    const bodies = mockMappingSuggestion()
    const confirmSpy = vi.spyOn(importApi, 'confirmImport')
    await openPreview()

    const button = screen.getByTestId('ai-mapping-btn')
    expect(button).toBeEnabled()
    fireEvent.click(button)

    expect(await screen.findByTestId('ai-mapping-source-姓名')).toBeInTheDocument()
    expect(screen.getByTestId('ai-mapping-source-分数')).toBeInTheDocument()
    // 置信度以标记展示（reason 在 tooltip 中）
    expect(screen.getByTestId('ai-mapping-confidence-姓名')).toHaveTextContent('93%')
    // unmapped 提示
    expect(screen.getByTestId('ai-mapping-unmapped')).toHaveTextContent('未映射的源列：城市')
    // 映射 target 回填到编辑态（Select 的当前值）
    expect(screen.getByTestId('ai-mapping-target-姓名').textContent).toContain('姓名')
    expect(screen.getByTestId('ai-mapping-meta')).toHaveTextContent('留痕 #99')

    // 请求契约：目标表 id + 源表头 + 抽样行
    expect(bodies).toHaveLength(1)
    expect(bodies[0].target_table_id).toBe(100)
    expect(bodies[0].headers).toEqual(['姓名', '分数'])
    expect(Array.isArray(bodies[0].sample_rows)).toBe(true)
    expect(bodies[0].sample_rows.length).toBeGreaterThan(0)
    expect(bodies[0].sample_rows[0]).toHaveLength(2)

    // 只回填编辑态，绝不自动确认导入
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('预览态没有目标表 id：按钮置灰并提示先选目标表，点击不发请求', async () => {
    const bodies = mockMappingSuggestion()
    await openPreview('')

    const button = screen.getByTestId('ai-mapping-btn')
    expect(button).toBeDisabled()
    expect(screen.getByTestId('ai-mapping-need-table')).toHaveTextContent('请先选择目标表')

    fireEvent.click(button)
    expect(bodies).toHaveLength(0)
  })

  it('后端错误：展示 detail 文案且不产生映射态', async () => {
    mockMappingSuggestion({ status: 502, detail: 'AI 上游服务不可用，请稍后重试' })
    await openPreview()

    fireEvent.click(screen.getByTestId('ai-mapping-btn'))

    expect(await screen.findByTestId('ai-mapping-error')).toHaveTextContent('AI 上游服务不可用')
    expect(screen.queryByTestId('ai-mapping-list')).toBeNull()
  })
})
