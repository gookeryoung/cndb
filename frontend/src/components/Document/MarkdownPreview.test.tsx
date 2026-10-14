/**
 * MarkdownPreview 数据表动态引用测试 — 覆盖：
 * 无工作区上下文按原文渲染 / 合法引用渲染只读表格 / view 引用走视图行端点 /
 * 无效表 ID 显示占位提示 / 标题锚点 id（大纲定位用）。
 */

import { describe, expect, it, beforeEach, vi } from 'vitest'
import { screen, fireEvent } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw'
import { renderProviders } from '@/test/render-providers'
import MarkdownPreview from './MarkdownPreview'

const WID = 10

describe('MarkdownPreview 数据表动态引用', () => {
  beforeEach(() => {
    server.resetHandlers()
  })

  it('无 workspaceId：占位符按原文渲染，不请求数据', () => {
    renderProviders(
      <MarkdownPreview content={'# 标题\n\n{{table:100}}\n\n正文。\n'} />,
    )
    expect(screen.getByRole('heading', { name: '标题' })).toBeInTheDocument()
    // 占位符作为普通文本呈现（react-markdown 输出在段落内）
    expect(screen.getByText(/\{\{table:100\}\}/)).toBeInTheDocument()
  })

  it('合法引用：渲染表名与行数据（records 端点）', async () => {
    renderProviders(
      <MarkdownPreview content={'前文\n\n{{table:100|limit=5}}\n\n后文'} workspaceId={WID} />,
    )
    // 表名 + 行数据出现即视为动态表格渲染成功
    expect(await screen.findByText(/客户表/)).toBeInTheDocument()
    expect(await screen.findByText('张三')).toBeInTheDocument()
    expect(screen.getByText('李四')).toBeInTheDocument()
    // 前后 Markdown 片段保留
    expect(screen.getByText('前文')).toBeInTheDocument()
    expect(screen.getByText('后文')).toBeInTheDocument()
  })

  it('带 view 参数：走视图行端点并渲染', async () => {
    const urls: string[] = []
    server.use(
      http.get('/api/v1/workspaces/:wid/tables/:tid/views/:vid/rows', ({ request }) => {
        urls.push(new URL(request.url).pathname)
        return HttpResponse.json({ rows: [{ id: 1, 姓名: '王五' }], total: 1, view_id: 200 })
      }),
    )
    renderProviders(
      <MarkdownPreview content={'{{table:100|view=200}}'} workspaceId={WID} />,
    )
    expect(await screen.findByText('王五')).toBeInTheDocument()
    expect(urls[0]).toContain('/tables/100/views/200/rows')
  })

  it('无效表 ID：显示占位提示', async () => {
    server.use(
      http.get('/api/v1/workspaces/:wid/tables/:tid', () =>
        new HttpResponse(null, { status: 404 })),
    )
    renderProviders(
      <MarkdownPreview content={'{{table:999}}'} workspaceId={WID} />,
    )
    expect(await screen.findByText('数据表引用无效')).toBeInTheDocument()
    expect(screen.getByText(/表 #999/)).toBeInTheDocument()
  })

  it('标题渲染锚点 id（与大纲解析同算法）', () => {
    renderProviders(
      <MarkdownPreview content={'# 安装指南\n\n## 子节 A\n\n### 深层'} />,
    )
    expect(screen.getByRole('heading', { name: '安装指南' })).toHaveAttribute('id', 'doc-h-安装指南')
    expect(screen.getByRole('heading', { name: '子节 A' })).toHaveAttribute('id', 'doc-h-子节-a')
    expect(screen.getByRole('heading', { name: '深层' })).toHaveAttribute('id', 'doc-h-深层')
  })
})

describe('MarkdownPreview 双向链接', () => {
  beforeEach(() => {
    server.resetHandlers()
  })

  it('[[标题]] 渲染为双链元素，点击触发 onWikilink 回调', () => {
    const onWikilink = vi.fn()
    renderProviders(
      <MarkdownPreview content={'参考 [[会议纪要]] 的结论。'} onWikilink={onWikilink} />,
    )
    const link = screen.getByTestId('doc-wikilink')
    expect(link).toHaveTextContent('会议纪要')
    expect(link).toHaveAttribute('href', `#wikilink:${encodeURIComponent('会议纪要')}`)
    fireEvent.click(link)
    expect(onWikilink).toHaveBeenCalledWith('会议纪要')
  })

  it('代码围栏内的 [[…]] 不转换，普通链接不走双链回调', () => {
    const onWikilink = vi.fn()
    renderProviders(
      <MarkdownPreview
        content={'```md\n[[围栏内]]\n```\n\n[外部链接](https://example.com)'}
        onWikilink={onWikilink}
      />,
    )
    expect(screen.getByText(/\[\[围栏内\]\]/)).toBeInTheDocument()
    expect(screen.queryByTestId('doc-wikilink')).toBeNull()
    const normal = screen.getByRole('link', { name: '外部链接' })
    expect(normal).toHaveAttribute('href', 'https://example.com')
  })
})
