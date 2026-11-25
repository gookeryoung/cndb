import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, useLocation } from 'react-router-dom'

import ScopeSwitcher from './ScopeSwitcher'
import { renderProviders } from '@/test/render-providers'
import { mockTeam, mockWorkspace } from '@/test/msw'
import type { Team, Workspace } from '@/api'

function LocationProbe() {
  const loc = useLocation()
  return <span data-testid="location">{loc.pathname}{loc.search}</span>
}

function renderSwitcher({
  teams = [mockTeam as unknown as Team],
  workspaces = [mockWorkspace],
  currentWorkspaceId = mockWorkspace.id,
  showLabel = true,
  prefix,
}: {
  teams?: Team[]
  workspaces?: Workspace[]
  currentWorkspaceId?: number | string
  showLabel?: boolean
  prefix?: string
} = {}) {
  return renderProviders(
    <Routes>
      <Route
        path="*"
        element={(
          <>
            <ScopeSwitcher
              teams={teams}
              workspaces={workspaces}
              currentWorkspaceId={currentWorkspaceId}
              showLabel={showLabel}
              prefix={prefix}
            />
            <LocationProbe />
          </>
        )}
      />
    </Routes>,
    { route: '/w' },
  )
}

const teamWs: Workspace = {
  ...mockWorkspace,
  id: 11,
  name: '研发工作区',
  team_id: 500,
  team: { id: 500, name: '研发部', slug: 'rd' },
}

describe('ScopeSwitcher', () => {
  it('触发按钮显示当前工作区，面板按团队分组并高亮当前项', async () => {
    const user = userEvent.setup()
    renderSwitcher({ workspaces: [mockWorkspace, teamWs] })

    expect(screen.getByTestId('ws-switch-btn')).toHaveTextContent('测试工作区')
    await user.click(screen.getByTestId('ws-switch-btn'))

    expect(await screen.findByTestId('scope-switcher-panel')).toBeInTheDocument()
    const teamGroup = screen.getByTestId('scope-group-team-500')
    expect(teamGroup).toHaveTextContent('研发部')
    expect(screen.getByTestId('scope-ws-11')).toBeInTheDocument()
    expect(screen.getByTestId('scope-ws-10')).toHaveAttribute('aria-current', 'true')
  })

  it('点击工作区跳转并关闭面板；团队组「管理」跳团队页', async () => {
    const user = userEvent.setup()
    renderSwitcher({ workspaces: [mockWorkspace, teamWs] })

    await user.click(screen.getByTestId('ws-switch-btn'))
    await user.click(await screen.findByTestId('scope-ws-11'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w/11'))

    await user.click(screen.getByTestId('ws-switch-btn'))
    await user.click(await screen.findByTestId('scope-manage-team-500'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/teams/500'))
  })

  it('底部入口：全部工作区 / 新建工作区 / 团队', async () => {
    const user = userEvent.setup()
    renderSwitcher()

    await user.click(screen.getByTestId('ws-switch-btn'))
    await user.click(await screen.findByTestId('scope-all-workspaces'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w'))

    await user.click(screen.getByTestId('ws-switch-btn'))
    await user.click(await screen.findByTestId('scope-create-workspace'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/w?create=1'))

    await user.click(screen.getByTestId('ws-switch-btn'))
    await user.click(await screen.findByTestId('scope-manage-teams'))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/teams'))
  })

  it('项目多于 8 个时出现搜索框，可按团队名过滤', async () => {
    const many: Workspace[] = Array.from({ length: 9 }, (_, i) => ({
      ...mockWorkspace,
      id: 100 + i,
      name: `工作区${i}`,
      team_id: 500,
      team: { id: 500, name: '研发部', slug: 'rd' },
    }))
    const user = userEvent.setup()
    renderSwitcher({ workspaces: many })

    await user.click(screen.getByTestId('ws-switch-btn'))
    const input = await screen.findByTestId('scope-search-input')
    await user.type(input, '工作区3')
    expect(screen.getByTestId('scope-group-team-500')).toBeInTheDocument()
    expect(screen.getByTestId('scope-ws-103')).toBeInTheDocument()
    expect(screen.queryByTestId('scope-ws-100')).not.toBeInTheDocument()
  })

  it('移动端可隐藏触发按钮文案（仅图标）', () => {
    renderSwitcher({ showLabel: false })
    expect(screen.getByTestId('ws-switch-btn')).not.toHaveTextContent('测试工作区')
  })

  it('无当前工作区（主页 / 团队页）时触发按钮显示「选择工作区」', () => {
    renderProviders(
      <Routes>
        <Route path="*" element={<ScopeSwitcher teams={[]} workspaces={[mockWorkspace]} />} />
      </Routes>,
      { route: '/w' },
    )
    expect(screen.getByTestId('ws-switch-btn')).toHaveTextContent('选择工作区')
  })

  it('完整档只显示工作区名；紧凑档用 prefix 补「团队 / 工作区」', () => {
    const { unmount } = renderSwitcher({
      workspaces: [{ ...mockWorkspace, name: '数据中台' }],
      prefix: '研发部',
    })
    const trigger = screen.getByTestId('ws-switch-btn')
    expect(trigger).toHaveTextContent(/研发部\s*\/\s*数据中台/)
    unmount()

    renderSwitcher({ workspaces: [{ ...mockWorkspace, name: '数据中台' }] })
    const plain = screen.getByTestId('ws-switch-btn')
    expect(plain).toHaveTextContent('数据中台')
    expect(plain).not.toHaveTextContent('研发部')
  })
})
