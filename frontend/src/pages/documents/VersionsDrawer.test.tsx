/**
 * VersionsDrawer 测试 —— 版本时间线渲染 / 差异原地展开（不再切 Tab）/
 * 加载与错误态 / 回滚入口 / 折叠提示。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import type { VersionItem } from '@/api/documents'
import VersionsDrawer from './VersionsDrawer'

function version(over: Partial<VersionItem> & Pick<VersionItem, 'version_number'>): VersionItem {
  return {
    id: over.version_number,
    document_id: 3,
    content_size: 100,
    content_hash: null,
    change_summary: '',
    change_type: 'manual',
    created_at: '2026-10-18T10:00:00',
    created_by_id: 1,
    ...over,
  }
}

const VERSIONS: VersionItem[] = [
  version({ version_number: 4, content_size: 160, change_summary: '补充交付范围' }),
  version({ version_number: 3, content_size: 120, change_type: 'rollback' }),
  version({ version_number: 2, content_size: 120, change_type: 'auto_import', change_summary: '从 Obsidian 导入' }),
  version({ version_number: 1, content_size: 80, change_summary: '创建文档' }),
]

const DIFF = '--- base\n+++ head\n@@ -1,2 +1,3 @@\n # 标题\n+新增段落\n 正文\n'

type Props = Parameters<typeof VersionsDrawer>[0]

function renderDrawer(over: Partial<Props> = {}) {
  const props: Props = {
    open: true,
    onClose: () => {},
    loading: false,
    versions: VERSIONS,
    total: 4,
    diffPair: null,
    onToggleDiff: () => {},
    diffLoading: false,
    diff: undefined,
    onRollback: () => {},
    ...over,
  }
  const utils = render(<VersionsDrawer {...props} />)
  return { ...utils, props }
}

describe('VersionsDrawer', () => {
  it('渲染时间线与卡片信息，最新版标记为当前', () => {
    renderDrawer()

    expect(screen.getByText('版本历史')).toBeTruthy()
    expect(screen.getByText('共 4 个版本 · 当前 v4')).toBeTruthy()
    for (const n of [1, 2, 3, 4]) {
      expect(screen.getByTestId(`version-item-${n}`)).toBeTruthy()
    }
    expect(screen.getByText('补充交付范围')).toBeTruthy()
    expect(screen.getByText('未填写变更说明')).toBeTruthy()
    expect(screen.getByText('当前')).toBeTruthy()
    expect(screen.getByText('回滚')).toBeTruthy()
    expect(screen.getByText('导入')).toBeTruthy()
  })

  it('体积变化与相对上一版对比（最新版没有对比 / 回滚入口）', () => {
    renderDrawer()

    // v4 相对 v3：+40 B；v2 相对 v1：+40 B；v3 与 v2 同体积
    expect(screen.getAllByText('+40 B').length).toBe(2)
    expect(screen.getByText('体积不变')).toBeTruthy()

    expect(screen.queryByTestId('version-diff-toggle-4')).toBeNull()
    expect(screen.queryByTestId('version-rollback-4')).toBeNull()
    expect(screen.getByTestId('version-diff-toggle-1')).toBeTruthy()
  })

  it('点「与上一版对比」把对比对抛给页面（不切换页面）', () => {
    const onToggleDiff = vi.fn()
    renderDrawer({ onToggleDiff })

    fireEvent.click(screen.getByTestId('version-diff-toggle-2'))
    expect(onToggleDiff).toHaveBeenCalledWith({ base: 2, head: 3 })
    // 差异面板只在已展开时出现：本用例未传 diffPair，因此页面上没有 diff
    expect(screen.queryByTestId('version-diff-panel')).toBeNull()
  })

  it('展开态在卡片下方就地渲染差异，按钮变为收起', () => {
    const onToggleDiff = vi.fn()
    renderDrawer({ onToggleDiff, diffPair: { base: 2, head: 3 }, diff: { added: 1, removed: 0, diff: DIFF } })

    const panel = screen.getByTestId('version-diff-panel')
    expect(panel).toBeTruthy()
    expect(screen.getByTestId('document-diff')).toBeTruthy()
    expect(screen.getByText('+1 新增')).toBeTruthy()

    fireEvent.click(screen.getByTestId('version-diff-toggle-2'))
    expect(onToggleDiff).toHaveBeenCalledWith(null)
  })

  it('差异加载中与加载失败各自有独立占位', () => {
    const { unmount } = renderDrawer({ diffPair: { base: 2, head: 3 }, diffLoading: true })
    expect(screen.getByTestId('version-diff-panel')).toBeTruthy()
    expect(screen.queryByTestId('document-diff')).toBeNull()
    unmount()

    renderDrawer({ diffPair: { base: 2, head: 3 }, diffError: true })
    expect(screen.getByText('差异计算失败，请重试')).toBeTruthy()
    expect(screen.queryByTestId('document-diff')).toBeNull()
  })

  it('回滚需要二次确认，确认后回调目标版本号', async () => {
    const onRollback = vi.fn()
    renderDrawer({ onRollback })

    fireEvent.click(screen.getByTestId('version-rollback-2'))
    expect(onRollback).not.toHaveBeenCalled()

    // Popconfirm 走 portal + 异步挂载
    const ok = await screen.findByRole('button', { name: '回滚' })
    fireEvent.click(ok)
    expect(onRollback).toHaveBeenCalledWith(2)
  })

  it('版本总数大于列表长度时提示只显示最近若干条', () => {
    renderDrawer({ total: 62 })
    expect(screen.getByText(/仅显示最近 4 个版本（共 62 个/)).toBeTruthy()
  })

  it('只有一个版本时给空态，加载中给骨架', () => {
    const { unmount } = renderDrawer({ versions: [VERSIONS[3]], total: 1 })
    expect(screen.getByText('暂无历史版本（首次保存后自动创建）')).toBeTruthy()
    unmount()

    renderDrawer({ loading: true })
    expect(screen.getByTestId('versions-loading')).toBeTruthy()
    expect(screen.queryByText('暂无历史版本（首次保存后自动创建）')).toBeNull()
  })
})
