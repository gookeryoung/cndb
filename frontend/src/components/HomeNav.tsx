/** 主页导航 rail（需求 0160 C1/C4/C9，A′ 口径）.
 *
 * 定位：`/w`、`/teams*` 等**无工作区上下文**的页面左侧导航；进入 `/w/:wid/*` 后
 * 同一位置换回工作区级侧栏（表 / 文档 / 设计 / 设置 / 统计）。同一时刻只有一条侧栏，
 * 不新增第三个导航轴（需求 0157 N1 的修订口径）。
 *
 * **只承载独有信息**，不复述顶栏与右栏已有的入口：
 *  - 最近访问：本地记录的 ≤5 个工作区落地路径（`utils/recentWorkspaces`，不落库）；
 *  - 已收藏：置顶（`pinned`）的工作区 ≤5 个，右侧标注所属团队（收藏是跨团队的扁平列表，
 *    不写团队就分不清归属）；
 *  - 全部工作区：主页锚点，带工作区计数与**待办徽标**（ADR 0160 P2：修改申请 / 问题 / 待审链接
 *    的聚合计数，只读、只有总数，不含 id / 标题；失败静默隐藏徽标，不阻断主页）。
 *  - 我的团队：用户所在团队列表，点击进入 `/teams/:tid`（2026-11-26 用户确认新增侧栏入口；
 *    此前口径是「团队入口只由顶栏 `ScopeSwitcher` 承担」，现修订为顶栏切换器与 rail 并存，
 *    切换器仍提供跨团队分组视图，rail 提供常驻直达入口）。团队接口失败时静默隐藏该分组。
 *  - 我的视图：收藏视图聚合入口（2026-11-26 用户确认新增，修订此前「收藏视图不进 rail」口径），
 *    点击回主页并定位到右栏「我的视图」面板（`/w#my-views`）；无收藏时不渲染，计数与面板共用
 *    `FAVORITE_VIEWS_QUERY_KEY`，同会话不重复请求。
 *
 * 明确**不放**（重复入口）：帮助文档（顶栏常驻图标）、
 * 管理团队（`/teams` 等价于「点第一个团队」，见 `TeamPage.tsx` 的 Navigate）；
 * **新建工作区**也不放（2026-11-27 确认）：页内工具栏与顶栏切换器底部（`ScopeSwitcher`）
 * 已各有一处，rail 只做「去哪」的导航，不做动作入口。
 *
 * 实现口径：条目走 antd `Menu`（与设置 / 统计 / 管理台侧栏同款，复用 `.cn-table-nav`
 * 样式），不自建一套导航样式。主页 rail **不参与折叠**（只有三段，折叠收益为零，
 * 且折叠态 group title 与文字全丢、只剩一排无语义图标）—— 折叠由 `MainLayout` 关闭。
 */

import { useMemo } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Menu } from 'antd'
import type { MenuProps } from 'antd'
import { ClockCircleOutlined, ApartmentOutlined, FolderOpenOutlined, StarFilled, EyeOutlined } from '@ant-design/icons'
import { homeApi, teamApi, workspaceApi } from '@/api'
import { useFavoriteViews } from '@/hooks/useFavoriteViews'
import type { Team, Workspace } from '@/api'
import { normalizeModules, workspaceLandingSegment, WORKSPACE_MODULE_LABEL } from '@/utils/workspaceModules'
import { teamRoleLabel } from '@/utils/roleLabels'
import { formatRelativeTime } from '@/utils/datetime'
import { readRecentWorkspaces } from '@/utils/recentWorkspaces'
import type { RecentWorkspaceEntry } from '@/utils/recentWorkspaces'

export interface HomeNavProps {
  /** 移动端抽屉：额外的上内边距，点击后由调用方收起抽屉 */
  mobile?: boolean
  /** 命中任一条目后的回调（移动端用来关闭抽屉） */
  onNavigate?: () => void
}

/** 当前项：`/w` 高亮全部工作区；`/teams/:tid`（含 `?section=`）高亮对应团队 */
function selectedKey(pathname: string): string[] {
  if (pathname === '/w') return ['/w']
  const m = /^\/teams\/(\d+)/.exec(pathname)
  return m ? [`/teams/${m[1]}`] : []
}

export default function HomeNav({ mobile = false, onNavigate }: HomeNavProps) {
  const navigate = useNavigate()
  const location = useLocation()

  // 与 WorkspaceList 共用同一 queryKey：主页与会话内已加载的列表不会重复请求
  const { data: workspaces = [] } = useQuery<Workspace[]>({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })

  // 待办聚合（ADR 0160）：失败静默（retry:false + 无错误提示），主页其它内容不受影响
  const { data: summary } = useQuery({
    queryKey: ['home-summary'],
    queryFn: homeApi.summary,
    staleTime: 20_000,
    retry: false,
  })
  const pendingTotal = summary?.pending.total ?? 0

  // 我的团队（2026-11-26 新增）：与 TeamPage / ScopeSwitcher 共用 ['teams']，同会话不重复请求；
  // 失败静默隐藏分组，不阻断主页其它导航
  const { data: teams = [] } = useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: () => teamApi.list(),
    retry: false,
  })

  const byId = useMemo(() => new Map(workspaces.map(ws => [String(ws.id), ws])), [workspaces])

  // 我的视图（2026-11-26 新增）：与右栏面板共用同一 queryKey，无收藏时不渲染分组
  const { data: favoriteViews = [] } = useFavoriteViews()

  /** 最近访问：只展示仍然可读的工作区（退出 / 被移除的条目自动隐去，不发额外请求） */
  const recentItems = useMemo(() => {
    const rows: Array<{ entry: RecentWorkspaceEntry; ws: Workspace }> = []
    for (const entry of readRecentWorkspaces()) {
      const ws = byId.get(entry.wid)
      if (ws) rows.push({ entry, ws })
    }
    return rows.slice(0, 5)
  }, [byId])

  const items: MenuProps['items'] = []

  if (recentItems.length > 0) {
    items.push({
      type: 'group',
      label: '最近访问',
      children: recentItems.map(({ entry, ws }) => {
        const modules = normalizeModules(ws.modules)
        const moduleLabel = WORKSPACE_MODULE_LABEL[modules[0]] ?? ''
        const relative = formatRelativeTime(new Date(entry.ts).toISOString())
        return {
          key: entry.path,
          icon: <ClockCircleOutlined />,
          // 单行 label：antd inline Menu 行高固定 40px 且单行 ellipsis，双行会被裁掉
          label: (
            <span
              className="cn-home-nav-row"
              data-testid={`home-nav-recent-${ws.id}`}
              title={`${ws.name}${moduleLabel ? ` · ${moduleLabel}` : ''}${relative ? ` · ${relative}` : ''}`}
            >
              <span className="cn-home-nav-row-name">{ws.name}</span>
              <span className="cn-home-nav-row-hint">{relative}</span>
            </span>
          ),
        }
      }),
    })
  }

  const pinnedItems = workspaces.filter(ws => ws.pinned).slice(0, 5)
  if (pinnedItems.length > 0) {
    items.push({
      type: 'group',
      label: '已收藏',
      children: pinnedItems.map(ws => {
        const modules = normalizeModules(ws.modules)
        const teamName = ws.team?.name ?? '个人'
        return {
          key: `/w/${ws.id}/${workspaceLandingSegment(modules)}`,
          // 与列表行内的收藏星标同色（琥珀）且显式对齐 Menu 图标字号：
          // Filled 星形比同排线性图标视觉偏大，不固定尺寸会与「最近访问 / 全部工作区」不齐（需求 0160 补充）
          icon: <StarFilled className="cn-home-nav-star" style={{ color: '#f59e0b' }} />,
          label: (
            <span
              className="cn-home-nav-row"
              data-testid={`home-nav-pinned-${ws.id}`}
              title={`${ws.name} · ${teamName}`}
            >
              <span className="cn-home-nav-row-name">{ws.name}</span>
              <span className="cn-home-nav-row-hint">{teamName}</span>
            </span>
          ),
        }
      }),
    })
  }

  if (favoriteViews.length > 0) {
    items.push({
      type: 'group',
      label: '我的视图',
      children: [{
        key: '/w#my-views',
        icon: <EyeOutlined />,
        label: (
          <span className="cn-home-nav-row" data-testid="home-nav-views" title="主页右栏收藏的视图">
            <span className="cn-home-nav-row-name">我的视图</span>
            <span className="cn-ws-group-count" style={{ marginInlineStart: 'var(--cn-space-sm)' }}>
              {favoriteViews.length}
            </span>
          </span>
        ),
      }],
    })
  }

  if (teams.length > 0) {
    items.push({
      type: 'group',
      label: '我的团队',
      children: teams.map(team => ({
        key: `/teams/${team.id}`,
        icon: <ApartmentOutlined />,
        label: (
          <span
            className="cn-home-nav-row"
            data-testid={`home-nav-team-${team.id}`}
            title={`${team.name} · ${teamRoleLabel(team.current_user_role)}`}
          >
            <span className="cn-home-nav-row-name">{team.name}</span>
            <span className="cn-home-nav-row-hint">{teamRoleLabel(team.current_user_role)}</span>
          </span>
        ),
      })),
    })
  }

  items.push({
    type: 'group',
    label: '我的工作区',
    children: [{
      key: '/w',
      icon: <FolderOpenOutlined />,
      label: (
        <span data-testid="home-nav-all">
          全部工作区
          {pendingTotal > 0 && (
            <span
              className="cn-home-nav-pending"
              data-testid="home-nav-pending"
              title={`待我处理：修改申请 ${summary?.pending.change_requests ?? 0} · 问题 ${summary?.pending.issues ?? 0} · 待审链接 ${summary?.pending.link_requests ?? 0}`}
            >
              {pendingTotal}
            </span>
          )}
          <span className="cn-ws-group-count" style={{ marginInlineStart: 'var(--cn-space-sm)' }}>
            {workspaces.length}
          </span>
        </span>
      ),
    }],
  })

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
      <Menu
        mode="inline"
        selectedKeys={selectedKey(location.pathname)}
        items={items}
        onClick={({ key }) => go(key)}
      />
    </nav>
  )
}
