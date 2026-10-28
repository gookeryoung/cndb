/**
 * VersionsDrawer 测试 —— 版本时间线渲染 / 差异原地展开（不再切 Tab）/
 * 变更对比挂「产生变更的那一版」行 / 加载与错误态 / 回滚入口 /
 * 折叠提示 / 当前草稿伪条目（需求 0062）。
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
    // 非空提交信息前带「提交修改信息」标签（需求 0063）；空说明只有占位文字
    expect(screen.getAllByText('提交修改信息').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('未填写变更说明')).toBeTruthy()
    expect(screen.getByText('当前')).toBeTruthy()
    // v3 的变更类型徽标与各版本的回滚按钮重名，用 getAllByText
    expect(screen.getAllByText('回滚').length).toBeGreaterThanOrEqual(3)
    expect(screen.getByText('导入')).toBeTruthy()
  })

  it('体积变化与变更入口挂在产生变更的那一版行（最早版没有变更 / 回滚入口）', () => {
    renderDrawer()

    // v4 相对 v3：+40 B；v2 相对 v1：+40 B；v3 与 v2 同体积
    expect(screen.getAllByText('+40 B').length).toBe(2)
    expect(screen.getByText('体积不变')).toBeTruthy()

    expect(screen.queryByTestId('version-diff-toggle-1')).toBeNull()
    // 最早版没有「变更」，但仍可回滚；只有最新版没有回滚入口
    expect(screen.getByTestId('version-rollback-1')).toBeTruthy()
    expect(screen.queryByTestId('version-rollback-4')).toBeNull()
    expect(screen.getByTestId('version-diff-toggle-4')).toBeTruthy()
  })

  it('点「变更」把本版相对上一版的对比对抛给页面（不切换页面）', () => {
    const onToggleDiff = vi.fn()
    renderDrawer({ onToggleDiff })

    fireEvent.click(screen.getByTestId('version-diff-toggle-2'))
    expect(onToggleDiff).toHaveBeenCalledWith({ base: 1, head: 2 })
    // 差异面板只在已展开时出现：本用例未传 diffPair，因此页面上没有 diff
    expect(screen.queryByTestId('version-diff-panel')).toBeNull()
  })

  it('展开态在卡片下方就地渲染差异，按钮变为收起', () => {
    const onToggleDiff = vi.fn()
    renderDrawer({ onToggleDiff, diffPair: { base: 1, head: 2 }, diff: { added: 1, removed: 0, diff: DIFF } })

    const panel = screen.getByTestId('version-diff-panel')
    expect(panel).toBeTruthy()
    expect(screen.getByTestId('document-diff')).toBeTruthy()
    expect(screen.getByText('+1 新增')).toBeTruthy()

    fireEvent.click(screen.getByTestId('version-diff-toggle-2'))
    expect(onToggleDiff).toHaveBeenCalledWith(null)
  })

  it('差异加载中与加载失败各自有独立占位', () => {
    const { unmount } = renderDrawer({ diffPair: { base: 1, head: 2 }, diffLoading: true })
    expect(screen.getByTestId('version-diff-panel')).toBeTruthy()
    expect(screen.queryByTestId('document-diff')).toBeNull()
    unmount()

    renderDrawer({ diffPair: { base: 1, head: 2 }, diffError: true })
    expect(screen.getByText('差异计算失败，请重试')).toBeTruthy()
    expect(screen.queryByTestId('document-diff')).toBeNull()
  })

  it('回滚需要二次确认，确认后回调目标版本号', async () => {
    const onRollback = vi.fn()
    renderDrawer({ onRollback })

    fireEvent.click(screen.getByTestId('version-rollback-2'))
    expect(onRollback).not.toHaveBeenCalled()

    // Popconfirm 走 portal + 异步挂载
    const ok = await screen.findByRole('button', { name: '确认回滚' })
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

  it('有草稿时顶部插入当前草稿条目，原最新版本标记为已发布且无回滚', () => {
    renderDrawer({ draft: { baseVersion: 3 } })

    expect(screen.getByTestId('version-item-draft')).toBeTruthy()
    expect(screen.getByText('草稿')).toBeTruthy()
    expect(screen.getByText('基于 v3 的未提交修改（仅自己可见）')).toBeTruthy()
    expect(screen.getByText('已发布')).toBeTruthy()
    expect(screen.queryByText('当前 v4')).toBeNull()
    // 草稿条目无回滚按钮，但其它版本回滚入口不受影响
    expect(screen.queryByTestId('version-rollback-draft')).toBeNull()
    expect(screen.queryByTestId('version-rollback-4')).toBeTruthy()
  })

  it('点草稿条目的「变更」抛 head=0 哨兵对比对', () => {
    const onToggleDiff = vi.fn()
    renderDrawer({ draft: { baseVersion: 3 }, onToggleDiff })

    fireEvent.click(screen.getByTestId('version-diff-toggle-draft'))
    expect(onToggleDiff).toHaveBeenCalledWith({ base: 3, head: 0 })
  })

  it('展开草稿 diff 时头标签显示「草稿」', () => {
    renderDrawer({ draft: { baseVersion: 3 }, diffPair: { base: 3, head: 0 }, diff: { added: 1, removed: 0, diff: DIFF } })

    expect(screen.getByTestId('version-diff-panel')).toBeTruthy()
    // 「草稿」出现两次：条目名 + diff 头标签
    expect(screen.getAllByText('草稿').length).toBe(2)
  })

  it('无草稿时（draft 为 null）不出现草稿条目，行为不变', () => {
    renderDrawer({ draft: null })
    expect(screen.queryByTestId('version-item-draft')).toBeNull()
    expect(screen.getByText('当前')).toBeTruthy()
    expect(screen.queryByText('已发布')).toBeNull()
  })
})
