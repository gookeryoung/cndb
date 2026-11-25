/** 主页导航 rail（需求 0160 C1/C4/C6/C9）.
 *
 * 定位：`/w`、`/teams*` 等**无工作区上下文**的页面左侧导航；进入 `/w/:wid/*` 后
 * 同一位置换回工作区级侧栏（表 / 文档 / 设计 / 设置 / 统计）。同一时刻只有一条侧栏，
 * 不新增第三个导航轴（需求 0157 N1 的修订口径）。
 *
 * 内容口径（与 GitHub 首页「Top repositories + 快捷新建」同一思路）：
 *  - 主操作：新建工作区（`/w?create=1`，与页内按钮同一弹窗）；
 *  - 最近访问：本地记录的 ≤5 个工作区落地路径（`utils/recentWorkspaces`，不落库）；
 *  - 全部工作区 / 团队（含计数）/ 收藏视图（复用 `favorite_views`）；
 *  - 底部：管理团队 / 帮助文档。
 *
 * 实现口径：条目走 antd `Menu`（与工作区设置 / 统计 / 管理台侧栏同款，复用 `.cn-table-nav`
 * 样式与折叠态行为），不自建一套导航样式 —— 少一套 CSS 就少一份与主题漂移的风险。
 * 折叠态（60px）只保留图标入口：新建 / 全部工作区 / 团队 / 更多；最近访问与收藏视图
 * 属于主页内容本身，折叠时不渲染。
 */

import { useMemo } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Button, Menu } from 'antd'
import type { MenuProps } from 'antd'
import {
  ApartmentOutlined, ClockCircleOutlined, FolderOpenOutlined, PlusOutlined,
  QuestionCircleOutlined, SettingOutlined, StarFilled,
} from '@ant-design/icons'
import { teamApi, workspaceApi } from '@/api'
import type { Team, Workspace } from '@/api'
import { useFavoriteViews } from '@/hooks/useFavoriteViews'
import {
  normalizeModules, workspaceLandingSegment, WORKSPACE_MODULE_LABEL,
} from '@/utils/workspaceModules'
import { formatRelativeTime } from '@/utils/datetime'
import { readRecentWorkspaces } from '@/utils/recentWorkspaces'
import type { RecentWorkspaceEntry } from '@/utils/recentWorkspaces'

export interface HomeNavProps {
  /** 桌面端 Sider 折叠态：隐藏文字，只留图标 */
  collapsed?: boolean
  /** 移动端抽屉：不折叠、点击后由调用方收起抽屉 */
  mobile?: boolean
  /** 是否渲染「团队」分区（移动端抽屉由既有团队分组承担时传 false） */
  showTeams?: boolean
  /** 命中任一条目后的回调（移动端用来关闭抽屉） */
  onNavigate?: () => void
}

export default function HomeNav({
  collapsed = false, mobile = false, showTeams = true, onNavigate,
}: HomeNavProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const flat = collapsed && !mobile

  // 与 WorkspaceList / TeamPage 共用同一 queryKey：主页与团队页同时挂载时不会重复请求
  const { data: workspaces = [] } = useQuery<Workspace[]>({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })
  const { data: teams = [] } = useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: () => teamApi.list(),
    retry: false,
  })
  const { data: favoriteViews = [] } = useFavoriteViews()

  const byId = useMemo(() => new Map(workspaces.map(ws => [String(ws.id), ws])), [workspaces])

  /** 最近访问：只展示仍然可读的工作区（退出 / 被移除的条目自动隐去，不发额外请求） */
  const recentItems = useMemo(() => {
    const rows: Array<{ entry: RecentWorkspaceEntry; ws: Workspace }> = []
    for (const entry of readRecentWorkspaces()) {
      const ws = byId.get(entry.wid)
      if (ws) rows.push({ entry, ws })
    }
    return rows.slice(0, 5)
  }, [byId])

  const teamWorkspaceCounts = useMemo(() => new Map(
    teams.map(team => [
      String(team.id),
      workspaces.filter(ws => String(ws.team_id) === String(team.id)).length,
    ]),
  ), [teams, workspaces])

  const countBadge = (count: number) => (
    <span className="cn-ws-group-count" style={{ marginInlineStart: 'var(--cn-space-sm)' }}>{count}</span>
  )

  const items: MenuProps['items'] = []

  if (!flat && recentItems.length > 0) {
    items.push({
      type: 'group',
      label: '最近访问',
      children: recentItems.map(({ entry, ws }) => {
        const modules = normalizeModules(ws.modules)
        const landing = `/w/${ws.id}/${workspaceLandingSegment(modules)}`
        return {
          key: entry.path,
          icon: <ClockCircleOutlined />,
          label: (
            <span data-testid={`home-nav-recent-${ws.id}`}>
              <span className="cn-home-nav-label" title={ws.name}>{ws.name}</span>
              <span className="cn-home-nav-hint">
                {WORKSPACE_MODULE_LABEL[modules[0]] ?? ''} · {formatRelativeTime(new Date(entry.ts).toISOString())}
              </span>
              {/* 记录路径与当前工作区落地段不一致时，点击直接回到上次所在模块 */}
              <span hidden data-testid={`home-nav-recent-landing-${ws.id}`}>{landing}</span>
            </span>
          ),
        }
      }),
    })
  }

  items.push({
    type: 'group',
    label: '工作区',
    children: [{
      key: '/w',
      icon: <FolderOpenOutlined />,
      label: (
        <span data-testid="home-nav-all">
          全部工作区{countBadge(workspaces.length)}
        </span>
      ),
    }],
  })

  if (showTeams && teams.length > 0) {
    items.push({
      type: 'group',
      label: '团队',
      children: teams.map(team => ({
        key: `/teams/${team.id}`,
        icon: <ApartmentOutlined />,
        label: (
          <span data-testid={`home-nav-team-${team.id}`}>
            {team.name}{countBadge(teamWorkspaceCounts.get(String(team.id)) ?? 0)}
          </span>
        ),
      })),
    })
  }

  if (!flat && favoriteViews.length > 0) {
    items.push({
      type: 'group',
      label: '收藏视图',
      children: favoriteViews.slice(0, 5).map(view => ({
        key: `/w/${view.workspace_id}/tables/${view.table_id}?view=${view.view_id}`,
        icon: <StarFilled />,
        label: (
          <span data-testid={`home-nav-view-${view.view_id}`}>
            <span className="cn-home-nav-label" title={view.name}>{view.name}</span>
            <span className="cn-home-nav-hint">{view.workspace_name}</span>
          </span>
        ),
      })),
    })
  }

  items.push(
    {
      key: '/teams',
      icon: <SettingOutlined />,
      label: <span data-testid="home-nav-manage-teams">管理团队</span>,
    },
    {
      key: '/help',
      icon: <QuestionCircleOutlined />,
      label: <span data-testid="home-nav-help">帮助文档</span>,
    },
  )

  // 选中态：主页高亮「全部工作区」，团队页高亮对应团队，/teams 列表页高亮「管理团队」
  const selectedKeys = location.pathname === '/w'
    ? ['/w']
    : location.pathname.startsWith('/teams')
      ? [location.pathname]
      : []

  const go = (path: string) => {
    navigate(path)
    onNavigate?.()
  }

  return (
    <nav
      className={`cn-table-nav cn-home-nav${mobile ? ' cn-home-nav-mobile' : ''}`}
      aria-label="主页导航"
      data-testid="sider-home"
    >
      <div style={{ padding: flat ? 'var(--cn-space-md) var(--cn-space-xs)' : 'var(--cn-space-md) var(--cn-space-lg)' }}>
        <Button
          type="primary"
          block
          icon={<PlusOutlined />}
          aria-label="新建工作区"
          data-testid="home-nav-create"
          onClick={() => go('/w?create=1')}
        >
          {flat ? null : '新建工作区'}
        </Button>
      </div>
      <Menu
        mode="inline"
        selectedKeys={selectedKeys}
        items={items}
        onClick={({ key }) => go(key)}
      />
    </nav>
  )
}
