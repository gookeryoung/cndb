/** 批量查找替换对话框（需求 0149）测试：字段候选 / 预览 / 确认替换 / 错误处理. */

import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'

import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import type { Field } from '@/api'
import BulkReplaceDialog, { MATCH_OPTIONS, TEXT_LIKE_FIELD_TYPES } from './BulkReplaceDialog'

const WID = 10
const TID = 2
const URL = `/api/v1/workspaces/${WID}/tables/${TID}/records/bulk-replace`

const FIELDS = [
  { id: 1, name: '名称', field_type: 'text', order: 0 },
  { id: 2, name: '邮箱', field_type: 'email', order: 1 },
  { id: 3, name: '金额', field_type: 'number', order: 2 },
  { id: 4, name: '派生', field_type: 'formula', order: 3 },
] as unknown as Field[]

function stubPreview(overrides: Record<string, unknown> = {}) {
  const bodies: Array<Record<string, unknown>> = []
  server.use(
    http.post(URL, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      bodies.push(body)
      const dryRun = body.dry_run !== false
      return HttpResponse.json({
        field: body.field,
        match: body.match,
        dry_run: dryRun,
        matched: 2,
        updated: dryRun ? 0 : 2,
        skipped: 0,
        preview: [{ row_id: 7, old: '北京分公司', new: '北京市分公司' }],
        ...overrides,
      })
    }),
  )
  return bodies
}

function renderDialog() {
  return renderProviders(
    <BulkReplaceDialog
      open
      wid={WID}
      tid={TID}
      fields={FIELDS}
      filters={[{ field_name: '名称', op: 'contains', value: '公司' }]}
      filterLogic="AND"
      onClose={() => { }}
    />,
  )
}

/** 选字段（antd Select：点开 + 选项点击） */
async function pickField(name: string) {
  // antd 6：Select 根节点即 data-testid 宿主，mousedown 根节点打开下拉
  fireEvent.mouseDown(screen.getByTestId('bulk-replace-field'))
  fireEvent.click(await screen.findByText(name, { selector: '.ant-select-item-option-content' }))
}

describe('BulkReplaceDialog', () => {
  beforeEach(() => {
    server.resetHandlers()
  })

  it('只列出文本类字段（数字 / 派生字段不出现在候选里）', async () => {
    stubPreview()
    renderDialog()
    fireEvent.mouseDown(screen.getByTestId('bulk-replace-field'))
    expect(await screen.findByText('名称', { selector: '.ant-select-item-option-content' })).toBeInTheDocument()
    expect(screen.getByText('邮箱', { selector: '.ant-select-item-option-content' })).toBeInTheDocument()
    expect(screen.queryByText('金额', { selector: '.ant-select-item-option-content' })).toBeNull()
    expect(screen.queryByText('派生', { selector: '.ant-select-item-option-content' })).toBeNull()
  })

  it('预览：把筛选范围与匹配方式一起提交，展示将替换行数与前后值', async () => {
    const bodies = stubPreview()
    renderDialog()

    await pickField('名称')
    fireEvent.change(screen.getByTestId('bulk-replace-find'), { target: { value: '北京' } })
    fireEvent.change(screen.getByTestId('bulk-replace-with'), { target: { value: '北京市' } })
    fireEvent.click(screen.getByTestId('bulk-replace-preview-btn'))

    const panel = await screen.findByTestId('bulk-replace-preview')
    expect(within(panel).getByText('将替换 2 行')).toBeInTheDocument()
    expect(within(panel).getByText('北京分公司')).toBeInTheDocument()
    expect(within(panel).getByText('北京市分公司')).toBeInTheDocument()

    expect(bodies[0]).toMatchObject({
      field: '名称',
      find: '北京',
      replace: '北京市',
      match: 'contains',
      dry_run: true,
      filter_logic: 'AND',
      filters: [{ field_name: '名称', op: 'contains', value: '公司' }],
    })
  })

  it('确认替换：dry_run=false 落库并回调 onApplied', async () => {
    const bodies = stubPreview()
    const applied: unknown[] = []
    renderProviders(
      <BulkReplaceDialog
        open
        wid={WID}
        tid={TID}
        fields={FIELDS}
        onClose={() => { }}
        onApplied={result => applied.push(result)}
      />,
    )

    await pickField('名称')
    fireEvent.change(screen.getByTestId('bulk-replace-find'), { target: { value: '北京' } })
    fireEvent.click(screen.getByTestId('bulk-replace-preview-btn'))
    await screen.findByTestId('bulk-replace-preview')

    const applyBtn = screen.getByTestId('bulk-replace-apply-btn')
    expect(applyBtn).not.toBeDisabled()
    fireEvent.click(applyBtn)

    await waitFor(() => expect(applied).toHaveLength(1))
    expect(bodies.at(-1)).toMatchObject({ dry_run: false, field: '名称' })
  })

  it('未预览时「确认替换」禁用（避免跳过预览直接落库）', async () => {
    stubPreview()
    renderDialog()
    expect(screen.getByTestId('bulk-replace-apply-btn')).toBeDisabled()
  })

  it('后端 400（如字段不允许）时提示错误且不落库', async () => {
    server.use(http.post(URL, () => HttpResponse.json({ detail: '字段「金额」不是文本类型' }, { status: 400 })))
    renderDialog()

    await pickField('名称')
    fireEvent.change(screen.getByTestId('bulk-replace-find'), { target: { value: '1' } })
    fireEvent.click(screen.getByTestId('bulk-replace-preview-btn'))

    expect(await screen.findByText('字段「金额」不是文本类型')).toBeInTheDocument()
    expect(screen.queryByTestId('bulk-replace-preview')).toBeNull()
  })

  it('常量与后端口径对齐', () => {
    expect([...TEXT_LIKE_FIELD_TYPES]).toEqual(['text', 'email', 'url', 'phone'])
    expect(MATCH_OPTIONS.map(o => o.value)).toEqual(['contains', 'exact', 'regex'])
  })
})
