/** 批量设置值对话框（需求 0151 扩展）测试：字段候选 / 影响面提示 / 跨页提交 / 值控件. */

import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'

import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import type { Field } from '@/api'
import BulkUpdateDialog, { BULK_UPDATE_FIELD_TYPES } from './BulkUpdateDialog'

const WID = 10
const TID = 2
const URL = `/api/v1/workspaces/${WID}/tables/${TID}/records/bulk-update`

const FIELDS = [
  { id: 1, name: '名称', field_type: 'text', order: 0 },
  { id: 2, name: '金额', field_type: 'number', order: 1 },
  { id: 3, name: '启用', field_type: 'boolean', order: 2 },
  { id: 4, name: '关联', field_type: 'link', order: 3 },
  { id: 5, name: '派生', field_type: 'formula', order: 4 },
] as unknown as Field[]

function stub() {
  const bodies: Array<Record<string, unknown>> = []
  server.use(
    http.post(URL, async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json({ updated: 2 })
    }),
  )
  return bodies
}

async function pickField(label: string) {
  fireEvent.mouseDown(screen.getByTestId('bulk-update-field'))
  fireEvent.click(await screen.findByText(label, { selector: '.ant-select-item-option-content' }))
}

describe('BulkUpdateDialog', () => {
  beforeEach(() => {
    server.resetHandlers()
  })

  it('只列可写物理字段（link / formula 不出现）', async () => {
    stub()
    renderProviders(<BulkUpdateDialog open wid={WID} tid={TID} fields={FIELDS} rowIds={[1, 2]} onClose={() => { }} />)
    fireEvent.mouseDown(screen.getByTestId('bulk-update-field'))
    expect(await screen.findByText('名称（text）', { selector: '.ant-select-item-option-content' })).toBeInTheDocument()
    expect(screen.getByText('金额（number）', { selector: '.ant-select-item-option-content' })).toBeInTheDocument()
    expect(screen.queryByText(/关联（link）/, { selector: '.ant-select-item-option-content' })).toBeNull()
    expect(screen.queryByText(/派生（formula）/, { selector: '.ant-select-item-option-content' })).toBeNull()
  })

  it('按选中行提交（不带 select_all）', async () => {
    const bodies = stub()
    renderProviders(<BulkUpdateDialog open wid={WID} tid={TID} fields={FIELDS} rowIds={[1, 2]} onClose={() => { }} />)

    expect(screen.getByTestId('bulk-update-impact')).toHaveTextContent('将影响 2 行')
    await pickField('名称（text）')
    fireEvent.change(screen.getByTestId('bulk-update-value-text'), { target: { value: '统一值' } })
    fireEvent.click(screen.getByTestId('bulk-update-apply'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ row_ids: [1, 2], values: { 名称: '统一值' } })
  })

  it('跨页全选：提交 select_all + filters 并展示影响面', async () => {
    const bodies = stub()
    renderProviders(
      <BulkUpdateDialog
        open
        wid={WID}
        tid={TID}
        fields={FIELDS}
        rowIds={[1]}
        selectAll
        total={37}
        filters={[{ field_name: '状态', op: 'eq', value: '完成' }]}
        filterLogic="AND"
        onClose={() => { }}
      />,
    )

    expect(screen.getByTestId('bulk-update-impact')).toHaveTextContent('将影响 37 行')
    expect(screen.getByTestId('bulk-update-impact')).toHaveTextContent('跨页全选')

    await pickField('名称（text）')
    fireEvent.change(screen.getByTestId('bulk-update-value-text'), { target: { value: 'X' } })
    fireEvent.click(screen.getByTestId('bulk-update-apply'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({
      select_all: true,
      filter_logic: 'AND',
      filters: [{ field_name: '状态', op: 'eq', value: '完成' }],
      values: { 名称: 'X' },
    })
  })

  it('数字字段用数字输入、布尔字段用开关', async () => {
    stub()
    renderProviders(<BulkUpdateDialog open wid={WID} tid={TID} fields={FIELDS} rowIds={[1]} onClose={() => { }} />)

    await pickField('金额（number）')
    expect(screen.getByTestId('bulk-update-value-number')).toBeInTheDocument()

    await pickField('启用（boolean）')
    expect(screen.getByTestId('bulk-update-value-bool')).toBeInTheDocument()
  })

  it('未选字段 / 未填值时给提示且不发请求', async () => {
    const bodies = stub()
    renderProviders(<BulkUpdateDialog open wid={WID} tid={TID} fields={FIELDS} rowIds={[1]} onClose={() => { }} />)
    fireEvent.click(screen.getByTestId('bulk-update-apply'))
    expect(await screen.findByText('请选择要设置的字段')).toBeInTheDocument()
    expect(bodies).toHaveLength(0)
  })

  it('字段类型白名单与后端允许集合一致', () => {
    expect([...BULK_UPDATE_FIELD_TYPES]).toContain('text')
    expect([...BULK_UPDATE_FIELD_TYPES]).not.toContain('link')
    expect([...BULK_UPDATE_FIELD_TYPES]).not.toContain('formula')
    expect([...BULK_UPDATE_FIELD_TYPES]).not.toContain('lookup')
  })
})
