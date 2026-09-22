/**
 * MoveTableForm 组件测试 —— 移动表的目标工作区选择.
 *
 * 覆盖：加载态 / 无其他工作区空态 / 正常渲染 Select 选项（排除当前工作区）。
 */

import { describe, expect, it } from 'vitest'
import { delay, http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import MoveTableForm from './MoveTableForm'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'

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
    await waitFor(() => expect(screen.getByText('没有其他工作区可移动')).toBeInTheDocument())
  })

  it('有其他工作区时渲染 Select，点击展开后仅列出非当前工作区', async () => {
    server.use(
      http.get('/api/v1/workspaces', () =>
        HttpResponse.json([
          { id: 10, name: '当前工作区' },
          { id: 20, name: '目标工作区A' },
          { id: 30, name: '目标工作区B' },
        ])),
    )
    renderProviders(<MoveTableForm currentWid="10" />)

    // 等待加载完成，Select 出现
    await waitFor(() => expect(screen.getByText('选择目标工作区')).toBeInTheDocument())

    // 展开下拉（antd Select 以 mouseDown 触发）
    fireEvent.mouseDown(screen.getByText('选择目标工作区'))
    expect(await screen.findByText('目标工作区A')).toBeInTheDocument()
    expect(screen.getByText('目标工作区B')).toBeInTheDocument()
    expect(screen.queryByText('当前工作区')).not.toBeInTheDocument()
  })
})
