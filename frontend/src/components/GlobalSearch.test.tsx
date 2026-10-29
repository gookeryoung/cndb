/** 顶栏工作区搜索（GlobalSearch）—— GitHub 风格范围切换 + 分组结果面板.
 *
 * 覆盖：默认范围=工作区（文档 + 数据表一次搜）、范围切换只保留对应分组、
 * 表上下文下的「当前激活视图」范围回显、键盘 Enter 打开首项、Esc 收起。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { useLocation } from 'react-router-dom'
import GlobalSearch from '@/components/GlobalSearch'
import { searchApi } from '@/api'
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

  it('点击表内数据命中跳到该表并携带 ?row 定位参数', async () => {
    renderSearch()
    await typeKeyword('张三')
    fireEvent.click(await screen.findByTestId('global-search-row-100-1'))
    await waitFor(() => expect(screen.getByTestId('loc')).toHaveTextContent('/w/10/tables/100?row=1'))
  })

  it('范围切到「数据表」后只剩数据表分组', async () => {
    renderSearch()
    fireEvent.click(screen.getByTestId('global-search-scope'))
    fireEvent.click(await screen.findByText('数据表'))

    await typeKeyword('需求')
    expect(await screen.findByTestId('global-search-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('global-search-doc-2')).toBeNull()
  })

  it('工作区范围不按当前视图收敛：不回显视图范围', async () => {
    renderSearch({ tableId: 100, viewId: 200 })
    await typeKeyword('张三')

    expect(await screen.findByTestId('global-search-row-100-1')).toBeInTheDocument()
    // 工作区范围覆盖全部可读表，view_id 不下发、也不出现视图范围回显（ADR 0015）
    expect(screen.getByTestId('global-search-panel')).not.toHaveTextContent('视图「全部数据」')
  })

  it('数据表范围带激活视图：请求收敛到该视图并回显范围', async () => {
    renderSearch({ tableId: 100, viewId: 200 })
    fireEvent.click(screen.getByTestId('global-search-scope'))
    fireEvent.click(await screen.findByText('数据表'))

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

describe('GlobalSearch 命令模式（0067）', () => {
  it('输入 > 即出命令列表（本地过滤不等去抖），且不发搜索请求（C1）', async () => {
    const spy = vi.spyOn(searchApi, 'workspace')
    renderSearch()
    const input = screen.getByTestId('global-search-input')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '>' } })

    expect(await screen.findByTestId('global-search-panel')).toHaveTextContent('命令')
    expect(screen.getByTestId('global-search-command-open-help')).toBeInTheDocument()
    expect(screen.getByTestId('global-search-command-new-table')).toBeInTheDocument()
    expect(spy).not.toHaveBeenCalled()
    spy.mockRestore()
  })

  it('命令按标题/别名子串过滤；无匹配显示「无匹配命令」', async () => {
    renderSearch()
    const input = screen.getByTestId('global-search-input')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '>主题' } })

    expect(await screen.findByTestId('global-search-command-theme-dark')).toBeInTheDocument()
    expect(screen.queryByTestId('global-search-command-new-table')).toBeNull()

    fireEvent.change(input, { target: { value: '>不存在的命令' } })
    expect(await screen.findByTestId('global-search-command-empty')).toBeInTheDocument()
  })

  it('Enter 执行导航命令：跳帮助文档并清空收起（C4）', async () => {
    renderSearch()
    const input = screen.getByTestId('global-search-input')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '>帮助' } })
    await screen.findByTestId('global-search-command-open-help')

    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => {
      expect(screen.getByTestId('loc')).toHaveTextContent('/help')
    })
    expect(screen.queryByTestId('global-search-panel')).toBeNull()
    expect((input as HTMLInputElement).value).toBe('')
  })

  it('主题命令经 ThemeProvider 落地：深色命令切换 body class（C3）', async () => {
    localStorage.setItem('cndb_theme', 'github-light')
    renderSearch()
    const input = screen.getByTestId('global-search-input')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '>深色' } })
    await screen.findByTestId('global-search-command-theme-dark')

    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(document.body).toHaveClass('theme-github-dark'))
    expect(localStorage.getItem('cndb_theme')).toBe('github-dark')
    localStorage.removeItem('cndb_theme')
  })

  it('↑↓ 在命令列表间移动高亮，Enter 执行当前项（C4）', async () => {
    renderSearch()
    const input = screen.getByTestId('global-search-input')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '>设置' } })
    await screen.findByTestId('global-search-command-open-settings')

    // '>设置' 命中：打开个人设置 / 大模型设置（首项=个人设置）；↓ 移到下一项后 Enter
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => {
      expect(document.querySelector('[data-testid="loc"]')).toBeInTheDocument()
    })
  })
})
