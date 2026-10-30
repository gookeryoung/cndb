/** tableRefNames 单测（0071）：占位符可读名解析缓存 / 失败回退 / 订阅通知 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { tableRefBadge, resetRefNames, subscribeRefNames } from './tableRefNames'
import type { TableRef } from './tableRef'

const { tableGet, viewGet } = vi.hoisted(() => ({
  tableGet: vi.fn(),
  viewGet: vi.fn(),
}))

vi.mock('@/api', () => ({
  tableApi: { get: tableGet },
  viewApi: { get: viewGet },
}))

function ref(partial: Partial<TableRef>): TableRef {
  return { tableId: 7, limit: 20, ...partial }
}

beforeEach(() => {
  resetRefNames()
  tableGet.mockReset()
  viewGet.mockReset()
})

describe('tableRefBadge 名称解析', () => {
  it('首次解析触发拉取并返回 label=null（加载中），名称到位后经订阅通知再取命中', async () => {
    tableGet.mockResolvedValue({ name: '客户表' })
    const notified = vi.fn()
    subscribeRefNames(notified)

    const loading = tableRefBadge(ref({}), 10)
    expect(loading).toEqual({ label: null, invalid: false })
    // loader 经微任务调度，等待其执行
    await vi.waitFor(() => expect(tableGet).toHaveBeenCalledWith(10, 7))

    await vi.waitFor(() => expect(notified).toHaveBeenCalled())
    expect(tableRefBadge(ref({}), 10)).toEqual({ label: '客户表', invalid: false })
  })

  it('组合表名/视图名/每页段：view 与非默认 limit 各占一段', async () => {
    tableGet.mockResolvedValue({ name: '客户表' })
    viewGet.mockResolvedValue({ name: '重点客户' })
    const info = tableRefBadge(ref({ view: 200, limit: 5 }), 10)
    expect(info).toEqual({ label: null, invalid: false })
    await vi.waitFor(() =>
      expect(tableRefBadge(ref({ view: 200, limit: 5 }), 10)).toEqual({
        label: '客户表 · 重点客户 · 每页 5',
        invalid: false,
      }),
    )
    expect(viewGet).toHaveBeenCalledWith(10, 7, 200)
  })

  it('limit 与默认值相同或无 view 时不显示对应段', async () => {
    tableGet.mockResolvedValue({ name: '客户表' })
    viewGet.mockResolvedValue({ name: '重点客户' })
    await vi.waitFor(() =>
      expect(tableRefBadge(ref({ view: 200, limit: 20 }), 10).label).toBe('客户表 · 重点客户'),
    )
  })

  it('表名拉取失败回退 #<ID> 并标记 invalid（视图不再拉取）', async () => {
    tableGet.mockRejectedValue(new Error('404'))
    const notified = vi.fn()
    subscribeRefNames(notified)
    expect(tableRefBadge(ref({ view: 200 }), 10)).toEqual({ label: null, invalid: false })
    await vi.waitFor(() => expect(notified).toHaveBeenCalled())
    expect(tableRefBadge(ref({ view: 200 }), 10)).toEqual({ label: '#7', invalid: true })
    expect(viewGet).not.toHaveBeenCalled()
  })

  it('视图名拉取失败回退 视图 #<ID>，表名正常展示且 invalid', async () => {
    tableGet.mockResolvedValue({ name: '客户表' })
    viewGet.mockRejectedValue(new Error('403'))
    const info = tableRefBadge(ref({ view: 200 }), 10)
    expect(info).toEqual({ label: null, invalid: false })
    await vi.waitFor(() =>
      expect(tableRefBadge(ref({ view: 200 }), 10)).toEqual({
        label: '客户表 · 视图 #200',
        invalid: true,
      }),
    )
  })

  it('workspaceId 缺失返回 label=null 且不发起请求', () => {
    expect(tableRefBadge(ref({}), undefined)).toEqual({ label: null, invalid: false })
    expect(tableGet).not.toHaveBeenCalled()
  })

  it('resetRefNames 清空缓存：重置后同一 ID 重新拉取', async () => {
    tableGet.mockResolvedValue({ name: '客户表' })
    await vi.waitFor(() =>
      expect(tableRefBadge(ref({}), 10).label).toBe('客户表'),
    )
    expect(tableGet).toHaveBeenCalledTimes(1)
    resetRefNames()
    tableRefBadge(ref({}), 10)
    await vi.waitFor(() => expect(tableGet).toHaveBeenCalledTimes(2))
  })
})
