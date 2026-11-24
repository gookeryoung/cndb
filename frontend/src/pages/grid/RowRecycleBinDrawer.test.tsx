/** 行回收站抽屉（ADR 0139 C8）—— 列表 / 摘要 / 恢复 / 彻底删除二次确认 / 空态. */

import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'

import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import RowRecycleBinDrawer, { rowSummary } from './RowRecycleBinDrawer'

const WID = 10
const TID = 2
const BASE = `/api/v1/workspaces/${WID}/tables/${TID}/records`

const TRASHED = [
  {
    id: 7,
    名称: '待恢复的行',
    数量: 3,
    _trashed_at: '2026-11-20T09:00:00Z',
    _trashed_by: 1,
    _trashed_by_name: 'owner',
    _etag: 'v1-7-2',
  },
  {
    id: 8,
    名称: '要彻底删的行',
    数量: 0,
    _trashed_at: '2026-11-19T08:00:00Z',
    _trashed_by: null,
    _trashed_by_name: null,
    _etag: 'v1-8-1',
  },
]

function stub(isolated = [...TRASHED]) {
  const calls = { restore: 0, purge: 0, restoreMany: 0, purgeMany: 0 }
  server.use(
    http.get(BASE, ({ request }) => {
      expect(new URL(request.url).searchParams.get('trashed')).toBe('only')
      return HttpResponse.json({ rows: isolated, items: isolated, total: isolated.length, limit: 200, offset: 0 })
    }),
    http.post(`${BASE}/:rid/restore`, () => {
      calls.restore += 1
      return HttpResponse.json({ id: 7 })
    }),
    http.post(`${BASE}/:rid/purge`, () => {
      calls.purge += 1
      return HttpResponse.json({ id: 8, purged: true })
    }),
    http.post(`${BASE}/restore`, () => {
      calls.restoreMany += 1
      return HttpResponse.json({ restored: 1 })
    }),
    http.post(`${BASE}/purge`, () => {
      calls.purgeMany += 1
      return HttpResponse.json({ purged: 1 })
    }),
  )
  return calls
}

function render(open = true) {
  return renderProviders(
    <RowRecycleBinDrawer open={open} wid={WID} tid={TID} tableName="回收站表" onClose={() => { }} />,
  )
}

describe('RowRecycleBinDrawer', () => {
  beforeEach(() => {
    server.resetHandlers()
  })

  it('列出已删行：摘要 / 删除时间 / 操作人 / 未知操作人', async () => {
    stub()
    render()

    const modal = await screen.findByTestId('row-recycle-bin')
    expect(await within(modal).findByText('待恢复的行 · 3')).toBeInTheDocument()
    expect(within(modal).getByText('#7')).toBeInTheDocument()
    expect(within(modal).getByText('owner')).toBeInTheDocument()
    // 无操作人时展示「未知」标签
    expect(within(modal).getAllByText('未知').length).toBeGreaterThan(0)
    expect(within(modal).queryByText('回收站是空的')).toBeNull()
  })

  it('恢复行会调用 restore 端点', async () => {
    const calls = stub()
    render()

    const modal = await screen.findByTestId('row-recycle-bin')
    const rowScope = (await within(modal).findByText('#7')).closest('tr') as HTMLElement
    fireEvent.click(within(rowScope).getByRole('button', { name: /恢复/ }))

    await waitFor(() => expect(calls.restore).toBe(1))
    expect(calls.purge).toBe(0)
  })

  it('彻底删除需要二次确认后才调用 purge', async () => {
    const calls = stub()
    render()

    const modal = await screen.findByTestId('row-recycle-bin')
    const row = await within(modal).findByText('#8')
    const rowScope = row.closest('tr') as HTMLElement
    fireEvent.click(within(rowScope).getByRole('button', { name: /彻底删除/ }))

    expect(calls.purge).toBe(0)
    const popconfirm = await waitFor(() => {
      const el = document.querySelector('.ant-popconfirm')
      expect(el).not.toBeNull()
      return el as HTMLElement
    })
    expect(popconfirm).toHaveTextContent('彻底删除后不可恢复')
    fireEvent.click(within(popconfirm).getByRole('button', { name: /彻底删除/ }))
    await waitFor(() => expect(calls.purge).toBe(1))
  })

  it('空回收站显示空态', async () => {
    stub([])
    render()
    expect(await screen.findByText('回收站是空的')).toBeInTheDocument()
  })
})

describe('rowSummary', () => {
  it('跳过系统键与空值，最多取 limit 个非空值', () => {
    const row = { id: 1, 名称: 'A', 备注: '', 金额: 0, _trashed_at: 'x', _etag: 'e' }
    expect(rowSummary(row)).toBe('A · 0')
    expect(rowSummary(row, 1)).toBe('A')
  })

  it('link 摘要数组转成顿号连接；无内容时给占位符', () => {
    expect(rowSummary({ id: 1, 关联: [{ id: 2, value: '甲' }, { id: 3, value: '乙' }] })).toBe('甲、乙')
    expect(rowSummary({ id: 1, 空: '', _etag: 'x' })).toBe('（无内容）')
  })
})
