/**
 * StoragePage 空间分配页组件测试.
 *
 * 覆盖：按工作区拥有者分组渲染与组间顺序 / 组头合计 / 行内调整配额提交 PATCH /
 * 数据新鲜度文案 / 未统计占位（不显示 0）/ 立即刷新触发后台统计并回填。
 */

import { describe, expect, it, vi, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import StoragePage, { formatRefreshInterval, formatSnapshotAge } from './StoragePage'
import { renderProviders } from '@/test/render-providers'
import { server, mockUser } from '@/test/msw'

const MB = 1024 * 1024
const STORAGE = '/api/v1/admin/workspaces/storage'

interface ItemOverrides {
  workspace_id: number
  name: string
  owner_username?: string | null
  used_bytes?: number | null
  quota_bytes?: number
  age_seconds?: number | null
}

/** 生成一条列表项（默认「刚统计过、用量已知」） */
function item({
  workspace_id,
  name,
  owner_username = 'alice',
  used_bytes = 10 * MB,
  quota_bytes = 100 * MB,
  age_seconds = 0,
}: ItemOverrides) {
  const known = used_bytes !== null
  return {
    workspace_id,
    name,
    owner_username,
    used_bytes,
    quota_bytes,
    computed_at: known ? '2026-10-24T01:00:00+00:00' : null,
    age_seconds: known ? age_seconds : null,
    is_stale: !known,
    updated_at: null,
  }
}

/** alice 名下 2 个（30MB / 200MB）、bob 1 个（5MB / 50MB）、1 个无拥有者（1MB / 100MB） */
const OVERVIEW = {
  default_quota_bytes: 100 * MB,
  items: [
    item({ workspace_id: 1, name: '销售数据', used_bytes: 10 * MB, quota_bytes: 100 * MB }),
    item({ workspace_id: 2, name: '客户中心', used_bytes: 20 * MB, quota_bytes: 100 * MB }),
    item({ workspace_id: 3, name: '研发库', owner_username: 'bob', used_bytes: 5 * MB, quota_bytes: 50 * MB }),
    item({ workspace_id: 4, name: '遗留库', owner_username: null, used_bytes: 1 * MB }),
  ],
  snapshot_age_seconds: 180,
  refresh_interval_seconds: 300,
  refreshing: false,
  pending_workspace_count: 0,
}

/** 同上，但快照更旧（用于断言刷新后文案变化） */
const OVERVIEW_STALE = { ...OVERVIEW, snapshot_age_seconds: 1800 }

function renderPage() {
  return renderProviders(<StoragePage />, { route: '/admin', initialAuth: { user: mockUser, token: 'fake-token' } })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('StoragePage 空间分配', () => {
  it('按拥有者分组渲染，组头展示拥有者与工作区数', async () => {
    server.use(http.get(STORAGE, () => HttpResponse.json(OVERVIEW)))
    renderPage()

    expect(await screen.findByText('销售数据')).toBeInTheDocument()

    // 组头顺序：按用户名升序，无拥有者置后
    const heads = [...document.querySelectorAll('.cn-owner-group-name')].map((el) => el.textContent)
    expect(heads).toEqual(['alice', 'bob', '未分配拥有者'])

    // 组内归属：工作区只出现在其拥有者分组中
    const groups = [...document.querySelectorAll('.ant-collapse-item')]
    expect(groups).toHaveLength(3)
    expect(groups[0].textContent).toContain('销售数据')
    expect(groups[0].textContent).toContain('客户中心')
    expect(groups[0].textContent).not.toContain('研发库')
    expect(groups[2].textContent).toContain('遗留库')
  })

  it('组头汇总工作区数与合计已用 / 配额', async () => {
    server.use(http.get(STORAGE, () => HttpResponse.json(OVERVIEW)))
    renderPage()

    const aliceHead = (await screen.findByText('alice')).closest('.cn-owner-group-head')
    expect(aliceHead).not.toBeNull()
    expect(aliceHead).toHaveTextContent('2 个工作区')
    expect(aliceHead).toHaveTextContent('30.0 MB / 200.0 MB')

    const bobHead = screen.getByText('bob').closest('.cn-owner-group-head')
    expect(bobHead).toHaveTextContent('1 个工作区')
    expect(bobHead).toHaveTextContent('5.0 MB / 50.0 MB')
  })

  it('行内调整配额后提交 PATCH', async () => {
    let patched: { quota_bytes: number } | null = null
    server.use(
      http.get(STORAGE, () => HttpResponse.json(OVERVIEW)),
      http.patch('/api/v1/admin/workspaces/:id/storage-quota', async ({ request }) => {
        patched = (await request.json()) as { quota_bytes: number }
        return HttpResponse.json({ workspace_id: 1, used_bytes: 10 * MB, quota_bytes: 200 * MB })
      }),
    )
    renderPage()

    fireEvent.click(await screen.findByTestId('quota-edit-1'))
    const input = screen.getByTestId('quota-input-1')
    fireEvent.change(input, { target: { value: '200' } })
    // antd 对两字中文按钮自动插入空格（保 存），按正则匹配
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    await waitFor(() => expect(patched).toEqual({ quota_bytes: 200 * MB }))
  })

  it('顶部展示数据新鲜度与同步周期', async () => {
    server.use(http.get(STORAGE, () => HttpResponse.json(OVERVIEW)))
    renderPage()

    expect(await screen.findByText('3 分钟前')).toBeInTheDocument()
    expect(screen.getByText(/每 5 分钟自动同步/)).toBeInTheDocument()
    expect(screen.queryByText(/个统计中/)).not.toBeInTheDocument()
  })

  it('尚未统计的工作区显示「统计中」而不是 0', async () => {
    const overview = {
      ...OVERVIEW,
      items: [
        item({ workspace_id: 5, name: '新工作区', owner_username: 'carol', used_bytes: null }),
        item({ workspace_id: 6, name: '已统计', owner_username: 'carol', used_bytes: 2 * MB }),
      ],
      snapshot_age_seconds: 0,
      pending_workspace_count: 1,
    }
    server.use(http.get(STORAGE, () => HttpResponse.json(overview)))
    renderPage()

    expect(await screen.findByText('新工作区')).toBeInTheDocument()
    // 已用 / 使用率 / 状态三列都以「统计中」占位
    expect(screen.getAllByText('统计中').length).toBeGreaterThanOrEqual(3)
    // 不把未统计当成 0 展示
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
    expect(screen.queryByText('0 B')).not.toBeInTheDocument()
    // 顶部与组头都提示待统计
    expect(screen.getByText('1 个统计中')).toBeInTheDocument()
    const head = screen.getByText('carol').closest('.cn-owner-group-head')
    expect(head).toHaveTextContent('1 个统计中')
    // 组头合计只汇总已统计的那个
    expect(head).toHaveTextContent('2.0 MB / 200.0 MB')
  })

  it('立即刷新投递后台统计，回填后按钮恢复并更新新鲜度', async () => {
    let accepted = false
    const fresh = { ...OVERVIEW_STALE, snapshot_age_seconds: 0 }
    let listCalls = 0
    server.use(
      http.get(STORAGE, () => {
        listCalls += 1
        return HttpResponse.json(accepted ? fresh : OVERVIEW_STALE)
      }),
      http.post(`${STORAGE}/refresh`, () => {
        accepted = true
        return HttpResponse.json({ status: 'accepted', workspace_ids: [], all: true }, { status: 202 })
      }),
    )
    renderPage()

    expect(await screen.findByText('30 分钟前')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('storage-refresh'))

    expect(await screen.findByText('刚刚')).toBeInTheDocument()
    // 完成后按钮恢复可点（不再显示「统计中…」）
    await waitFor(() => expect(screen.getByTestId('storage-refresh')).toHaveTextContent('立即刷新'))
    expect(listCalls).toBeGreaterThan(1)
  })
})

describe('新鲜度文案', () => {
  it('快照年龄分档', () => {
    expect(formatSnapshotAge(null)).toBe('尚未统计')
    expect(formatSnapshotAge(5)).toBe('刚刚')
    expect(formatSnapshotAge(90)).toBe('1 分钟前')
    expect(formatSnapshotAge(3 * 3600)).toBe('3 小时前')
    expect(formatSnapshotAge(2 * 86400)).toBe('2 天前')
  })

  it('同步周期文案', () => {
    expect(formatRefreshInterval(0)).toContain('仅在手动刷新')
    expect(formatRefreshInterval(30)).toBe('每 30 秒自动同步')
    expect(formatRefreshInterval(300)).toBe('每 5 分钟自动同步')
    expect(formatRefreshInterval(90)).toBe('每 2 分钟自动同步')
  })
})
