/** AiFillFieldDrawer 单测 —— 建议生成 / 错误 / 逐行应用与 202 修改申请（ADR 0020 P2）.
 *
 * 用 MSW 拦截两个真实端点：
 * - `POST .../ai/actions/fill_field`（只生成建议，不写库）；
 * - `PATCH .../records/{rid}`（既有记录更新接口，逐行调用；202 = 修改申请）。
 *
 * 断言重点：应用时逐行调用既有更新接口 N 次，绝不打批量写端点。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'

import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import type { Field, RowResponse } from '@/api'
import AiFillFieldDrawer from './AiFillFieldDrawer'

const FIELD: Field = { id: 5, name: '摘要', field_type: 'longtext' }
const ROWS: RowResponse[] = [
  { id: 1, 姓名: '张三', 摘要: '' },
  { id: 2, 姓名: '李四', 摘要: '旧摘要' },
]

interface FillHandlerOptions {
  values?: Array<{ row_id: number; value: string | number | boolean | null }>
  skipped?: number[]
  status?: number
  detail?: string
}

/** 注册 fill_field 的 MSW handler，返回请求体收集数组 */
function mockFillField(options: FillHandlerOptions = {}) {
  const bodies: any[] = []
  server.use(
    http.post('/api/v1/workspaces/:wid/tables/:tid/ai/actions/fill_field', async ({ request }) => {
      bodies.push(await request.json())
      if (options.status && options.status >= 400) {
        return HttpResponse.json({ detail: options.detail ?? 'AI 调用失败' }, { status: options.status })
      }
      return HttpResponse.json({
        action: 'table.fill_field',
        run_id: 11,
        model: 'mock-model',
        usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
        result: { values: options.values ?? [{ row_id: 1, value: '新摘要 A' }, { row_id: 2, value: '新摘要 B' }] },
        skipped_row_ids: options.skipped ?? [],
        row_count: 2,
      })
    }),
  )
  return bodies
}

function renderDrawer(overrides: Partial<Parameters<typeof AiFillFieldDrawer>[0]> = {}) {
  const onClose = vi.fn()
  const onApplied = vi.fn()
  const utils = renderProviders(
    <AiFillFieldDrawer
      open
      wid="10"
      tid="100"
      field={FIELD}
      rows={ROWS}
      rowIndexBase={0}
      onClose={onClose}
      onApplied={onApplied}
      {...overrides}
    />,
  )
  return { ...utils, onClose, onApplied }
}

describe('AiFillFieldDrawer', () => {
  it('打开即请求 fill_field：展示行 → 建议值、用量与跳过行提示', async () => {
    const bodies = mockFillField({ skipped: [3] })
    renderDrawer()

    expect(screen.getByTestId('ai-fill-loading')).toBeInTheDocument()
    expect(await screen.findByTestId('ai-fill-value-1')).toHaveTextContent('新摘要 A')
    expect(screen.getByTestId('ai-fill-value-2')).toHaveTextContent('新摘要 B')

    // 请求契约：单字段 + 当前页行 id（≤20）
    expect(bodies).toHaveLength(1)
    expect(bodies[0].field_name).toBe('摘要')
    expect(bodies[0].row_ids).toEqual([1, 2])
    expect(screen.getByTestId('ai-fill-meta')).toHaveTextContent('mock-model')
    expect(screen.getByTestId('ai-fill-meta')).toHaveTextContent('留痕 #11')
    expect(screen.getByTestId('ai-fill-skipped')).toHaveTextContent('已跳过：3')
  })

  it('请求行只取当前页前 20 行（超出由前端分片，不一次发全页）', async () => {
    const manyRows: RowResponse[] = Array.from({ length: 25 }, (_, i) => ({ id: i + 1, 姓名: `name-${i}` }))
    const bodies = mockFillField({ values: [{ row_id: 1, value: 'x' }] })
    renderDrawer({ rows: manyRows })

    await screen.findByTestId('ai-fill-value-1')
    expect(bodies[0].row_ids).toHaveLength(20)
    expect(bodies[0].row_ids[0]).toBe(1)
    expect(bodies[0].row_ids[19]).toBe(20)
  })

  it('后端错误取 detail 展示（不静默失败，也不改动行）', async () => {
    mockFillField({ status: 400, detail: '隐藏字段不支持 AI 填充' })
    renderDrawer()

    expect(await screen.findByTestId('ai-fill-error')).toHaveTextContent('隐藏字段不支持 AI 填充')
    // 失败时禁用应用
    expect(screen.getByTestId('ai-fill-apply')).toBeDisabled()
  })

  it('应用：逐行调用既有记录更新接口，202 计入修改申请，汇总 toast 成功/申请数', async () => {
    mockFillField()
    const patchCalls: string[] = []
    const bulkCalls: string[] = []
    server.use(
      http.patch('/api/v1/workspaces/:wid/tables/:tid/records/:rid', ({ params }) => {
        patchCalls.push(String(params.rid))
        if (String(params.rid) === '2') {
          // 查看者 / 无直编资格：既有双轨制返回 202 修改申请
          return HttpResponse.json(
            { change_request: { id: 88, workspace_id: 10, table_id: 100, title: 'AI 填充', status: 'open' } },
            { status: 202 },
          )
        }
        return HttpResponse.json({ id: Number(params.rid), 摘要: '新摘要 A' })
      }),
      http.post('/api/v1/workspaces/:wid/tables/:tid/records/bulk-update', () => {
        bulkCalls.push('bulk-update')
        return HttpResponse.json({ updated: 2 })
      }),
    )

    const { onApplied, onClose } = renderDrawer()
    await screen.findByTestId('ai-fill-value-1')
    fireEvent.click(screen.getByTestId('ai-fill-apply'))

    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1))
    // 逐行两次既有 PATCH（不是批量写端点）
    expect(patchCalls).toEqual(['1', '2'])
    expect(bulkCalls).toHaveLength(0)
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(await screen.findByText(/AI 填充应用完成：成功 1 行；已提交修改申请 1 行（#88）/)).toBeInTheDocument()
  })

  it('null 建议值不参与应用（不会清空原值）', async () => {
    mockFillField({ values: [{ row_id: 1, value: null }, { row_id: 2, value: '新摘要 B' }] })
    const patchCalls: string[] = []
    server.use(
      http.patch('/api/v1/workspaces/:wid/tables/:tid/records/:rid', ({ params }) => {
        patchCalls.push(String(params.rid))
        return HttpResponse.json({ id: Number(params.rid) })
      }),
    )
    renderDrawer()

    expect(await screen.findByTestId('ai-fill-value-1')).toHaveTextContent('未给出建议')
    expect(screen.getByTestId('ai-fill-apply')).toHaveTextContent('应用到 1 行')
    fireEvent.click(screen.getByTestId('ai-fill-apply'))

    await waitFor(() => expect(patchCalls).toEqual(['2']))
  })
})
