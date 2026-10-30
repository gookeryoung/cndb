/**
 * MoveTableForm 组件测试 —— 移动表的目标工作区选择.
 *
 * 覆盖：加载态 / 无其他工作区空态 / 正常渲染 Select 选项（排除当前工作区）
 *      / 受控值回显 / 选中目标工作区时回传 onChange.
 */

import { describe, expect, it, vi } from 'vitest'
import { delay, http, HttpResponse } from 'msw'
import { fireEvent, screen } from '@testing-library/react'
import MoveTableForm from './MoveTableForm'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

/** 目标工作区候选：id=10 为当前工作区（应被排除），20/30 可选 */
function mockWorkspaces() {
  server.use(
    http.get('/api/v1/workspaces', () =>
      HttpResponse.json([
        { id: 10, name: '当前工作区' },
        { id: 20, name: '目标工作区A' },
        { id: 30, name: '目标工作区B' },
      ])),
  )
}

describe('MoveTableForm 目标工作区选择', () => {
  it('请求未返回时显示加载中', async () => {
    server.use(
      http.get('/api/v1/workspaces', async () => {
        await delay('infinite')
        return HttpResponse.json([])
      }),
    )
    renderProviders(<MoveTableForm currentWid="10" />)

    expect(await screen.findByText('加载中...')).toBeInTheDocument()
  })

  it('排除当前工作区后无候选时显示空态提示', async () => {
    renderProviders(<MoveTableForm currentWid={10} />)
    // 默认 handler 只有 id=10 的工作区，与 currentWid 相同
    await screen.findByText('没有其他工作区可移动')
  })

  it('有其他工作区时渲染 Select，点击展开后仅列出非当前工作区', async () => {
    mockWorkspaces()
    renderProviders(<MoveTableForm currentWid="10" />)

    // 等待加载完成，Select 出现
    await screen.findByText('选择目标工作区')

    // 展开下拉（antd Select 以 mouseDown 触发）
    fireEvent.mouseDown(screen.getByText('选择目标工作区'))
    expect(await screen.findByText('目标工作区A')).toBeInTheDocument()
    expect(screen.getByText('目标工作区B')).toBeInTheDocument()
    expect(screen.queryByText('当前工作区')).not.toBeInTheDocument()
  })

  it('受控 value 命中的工作区名回显在选择器中', async () => {
    mockWorkspaces()
    renderProviders(<MoveTableForm currentWid="10" value={20} />)

    // 等待加载完成：受控值 20 应回显 label「目标工作区A」
    await screen.findByText('目标工作区A')
    // antd 6：单选选中值直接渲染在 .ant-select-content（无 selection-item 包装）
    expect(document.querySelector('.ant-select-content')?.textContent?.trim()).toBe('目标工作区A')
  })

  it('选中目标工作区时回调 onChange 并回传其 id', async () => {
    mockWorkspaces()
    const onChange = vi.fn()
    renderProviders(<MoveTableForm currentWid="10" onChange={onChange} />)

    await screen.findByText('选择目标工作区')
    fireEvent.mouseDown(screen.getByText('选择目标工作区'))
    fireEvent.click(await screen.findByText('目标工作区B', { selector: '.ant-select-item-option-content' }))

    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith(30, expect.anything())
  })
})
