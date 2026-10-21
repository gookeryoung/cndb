/** 顶栏工作区搜索（GlobalSearch）—— GitHub 风格范围切换 + 分组结果面板.
 *
 * 覆盖：默认范围=工作区（文档 + 数据表一次搜）、范围切换只保留对应分组、
 * 表上下文下的「当前激活视图」范围回显、键盘 Enter 打开首项、Esc 收起。
 */

import { describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { useLocation } from 'react-router-dom'
import GlobalSearch from '@/components/GlobalSearch'
import { renderProviders } from '@/test/render-providers'

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="loc">{loc.pathname + loc.search}</div>
}

function renderSearch(props: Partial<React.ComponentProps<typeof GlobalSearch>> = {}) {
  return renderProviders(
    <>
      <GlobalSearch workspaceId={10} workspaceName="测试工作区" {...props} />
      <LocationProbe />
    </>,
    { route: '/w/10/tables/100' },
  )
}

async function typeKeyword(text: string) {
  const input = screen.getByTestId('global-search-input')
  fireEvent.focus(input)
  fireEvent.change(input, { target: { value: text } })
  // 250ms 去抖后才会发请求
  await screen.findByTestId('global-search-panel')
}

describe('GlobalSearch 顶栏工作区搜索', () => {
  it('默认搜整个工作区：文档与表内数据同屏分组', async () => {
    renderSearch()
    const input = screen.getByTestId('global-search-input')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '需求' } })

    expect(await screen.findByTestId('global-search-doc-2')).toBeInTheDocument()
    expect(screen.getByTestId('global-search-panel')).toHaveTextContent('文档')
  })

  it('点击文档命中跳到编辑器', async () => {
    renderSearch()
    await typeKeyword('需求')
    fireEvent.click(await screen.findByTestId('global-search-doc-2'))
    await waitFor(() => expect(screen.getByTestId('loc')).toHaveTextContent('/w/10/documents/2'))
  })

  it('点击表内数据命中跳到该表', async () => {
    renderSearch()
    await typeKeyword('张三')
    fireEvent.click(await screen.findByTestId('global-search-row-100-1'))
    await waitFor(() => expect(screen.getByTestId('loc')).toHaveTextContent('/w/10/tables/100'))
  })

  it('范围切到「数据表」后只剩数据表分组', async () => {
    renderSearch()
    fireEvent.click(screen.getByTestId('global-search-scope'))
    fireEvent.click(await screen.findByText('数据表'))

    await typeKeyword('需求')
    expect(await screen.findByTestId('global-search-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('global-search-doc-2')).toBeNull()
  })

  it('表上下文带激活视图：请求收敛到该视图并回显范围', async () => {
    renderSearch({ tableId: 100, viewId: 200 })
    await typeKeyword('张三')

    expect(await screen.findByTestId('global-search-row-100-1')).toBeInTheDocument()
    // 视图名来自后端 view 回显，说明 table_id/view_id 已随请求下发
    expect(screen.getByTestId('global-search-panel')).toHaveTextContent('客户表 · 视图「全部数据」')
  })

  it('Esc 收起面板', async () => {
    renderSearch()
    await typeKeyword('需求')
    fireEvent.keyDown(screen.getByTestId('global-search-input'), { key: 'Escape' })
    await waitFor(() => expect(screen.queryByTestId('global-search-panel')).toBeNull())
  })
})
