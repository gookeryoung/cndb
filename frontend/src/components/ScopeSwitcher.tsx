/** 团队 / 工作区统一切换器（需求 0157 C1 / C2 / C4）.
 *
 * 顶栏「工作区名 ▾」与移动端导航共用：按团队分组列出工作区（团队单层、组内平铺，无树），
 * 组头提供团队页入口，底部提供「全部工作区 / 新建工作区 / 管理团队」。
 * 只消费 `GET /workspaces` 与 `GET /teams` 的既有载荷，不新增请求（C6）。
 */

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Input, Popover, Tag, Tooltip } from 'antd'
import {
  ApartmentOutlined, FolderOutlined, PlusOutlined, SearchOutlined, SettingOutlined,
  StarFilled,
} from '@ant-design/icons'

import type { Team, Workspace } from '@/api'
import { workspaceRoleLabel } from '@/utils/roleLabels'
import { groupWorkspacesByTeam } from '@/pages/workspace/workspaceGroups'

export interface ScopeSwitcherProps {
  teams: Team[]
  workspaces: Workspace[]
  /** 当前工作区 id（高亮 + 触发按钮文案） */
  currentWorkspaceId?: string | number
  /** 触发按钮是否显示文案（移动端仅图标） */
  showLabel?: boolean
  /** 工作区跳转地址（默认 `/w/<id>`；工作区上下文内传入“同一模块段”地址） */
  workspaceHref?: (workspace: Workspace) => string
  /** 团队页跳转（默认 `/teams/<id>`） */
  teamHref?: (team: { id: number | string; name: string }) => string
}

/** 内部：分组面板（Popover content） */
export function ScopeSwitcherPanel({
  teams, workspaces, currentWorkspaceId, onPickWorkspace, onPickTeam, onAllWorkspaces,
  onCreateWorkspace, onManageTeams, onClose,
}: {
  teams: Team[]
  workspaces: Workspace[]
  currentWorkspaceId?: string | number
  onPickWorkspace: (ws: Workspace) => void
  onPickTeam: (team: { id: number | string; name: string }) => void
  onAllWorkspaces: () => void
  onCreateWorkspace: () => void
  onManageTeams: () => void
  onClose: () => void
}) {
  const [keyword, setKeyword] = useState('')
  const showSearch = teams.length + workspaces.length > 8
  const q = keyword.trim().toLowerCase()

  const filtered = useMemo(() => {
    if (!q) return workspaces
    const teamNameHit = new Set(
      teams.filter(t => t.name.toLowerCase().includes(q)).map(t => String(t.id)),
    )
    return workspaces.filter(ws =>
      (ws.name ?? '').toLowerCase().includes(q)
      || (ws.description ?? '').toLowerCase().includes(q)
      || (ws.team_id != null && teamNameHit.has(String(ws.team_id))),
    )
  }, [workspaces, teams, q])

  const pinned = filtered.filter(ws => ws.pinned)
  const groups = useMemo(
    () => groupWorkspacesByTeam(filtered, teams),
    [filtered, teams],
  )

  const renderRow = (ws: Workspace) => {
    const active = currentWorkspaceId != null && String(ws.id) === String(currentWorkspaceId)
    return (
      <button
        key={ws.id}
        type="button"
        className={active ? 'cn-scope-row cn-scope-row-active' : 'cn-scope-row'}
        data-testid={`scope-ws-${ws.id}`}
        aria-current={active ? 'true' : undefined}
        onClick={() => { onPickWorkspace(ws); onClose() }}
      >
        <FolderOutlined className="cn-scope-row-icon" />
        <span className="cn-scope-row-name">{ws.name}</span>
        {ws.current_user_role && (
          <span className="cn-scope-row-role">{workspaceRoleLabel(ws.current_user_role)}</span>
        )}
      </button>
    )
  }

  return (
    <div
      className="cn-scope-panel"
      data-testid="scope-switcher-panel"
      role="dialog"
      aria-label="切换团队或工作区"
      onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}
    >
      {showSearch && (
        <div className="cn-scope-search">
          <Input
            allowClear
            autoFocus
            size="small"
            prefix={<SearchOutlined />}
            placeholder="搜索团队 / 工作区…"
            aria-label="搜索团队或工作区"
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            data-testid="scope-search-input"
          />
        </div>
      )}

      <div className="cn-scope-body">
        {pinned.length > 0 && (
          <section className="cn-scope-section" data-testid="scope-group-starred">
            <div className="cn-scope-section-head">
              <StarFilled style={{ color: '#f59e0b' }} />
              <span>已收藏</span>
              <span className="cn-scope-count">{pinned.length}</span>
            </div>
            {pinned.map(renderRow)}
          </section>
        )}

        {groups.map(group => {
          const team = group.team
          return (
          <section
            key={group.key}
            className="cn-scope-section"
            data-testid={`scope-group-${group.key}`}
          >
            <div className="cn-scope-section-head">
              <ApartmentOutlined />
              <span className="cn-scope-section-title">{group.title}</span>
              <span className="cn-scope-count">{group.workspaces.length}</span>
              {!group.isPersonal && team && (
                <Tooltip title={`打开「${group.title}」团队页`}>
                  <Button
                    type="text"
                    size="small"
                    className="cn-scope-manage"
                    icon={<SettingOutlined />}
                    aria-label={`管理团队「${group.title}」`}
                    data-testid={`scope-manage-team-${team.id}`}
                    onClick={() => { onPickTeam(team); onClose() }}
                  />
                </Tooltip>
              )}
            </div>
            {group.workspaces.map(renderRow)}
          </section>
          )
        })}

        {filtered.length === 0 && (
          <div className="cn-scope-empty">没有匹配「{keyword.trim()}」的团队或工作区</div>
        )}
      </div>

      <div className="cn-scope-footer">
        <button
          type="button"
          className="cn-scope-footer-btn"
          data-testid="scope-all-workspaces"
          onClick={() => { onAllWorkspaces(); onClose() }}
        >
          全部工作区
        </button>
        <span className="cn-scope-footer-spacer" />
        <Button
          size="small"
          type="text"
          icon={<PlusOutlined />}
          data-testid="scope-create-workspace"
          onClick={() => { onCreateWorkspace(); onClose() }}
        >
          新建
        </Button>
        <Button
          size="small"
          type="text"
          icon={<ApartmentOutlined />}
          data-testid="scope-manage-teams"
          onClick={() => { onManageTeams(); onClose() }}
        >
          团队
        </Button>
      </div>
    </div>
  )
}

/** 顶栏切换器 —— 触发按钮 + 分组面板 */
export default function ScopeSwitcher({
  teams, workspaces, currentWorkspaceId, showLabel = true, workspaceHref, teamHref,
}: ScopeSwitcherProps) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const current = workspaces.find(ws => String(ws.id) === String(currentWorkspaceId))
  const currentTeam = current?.team ?? teams.find(t => String(t.id) === String(current?.team_id))

  // 路由变化（如从面板跳转后返回）关闭面板，避免残留
  useEffect(() => { setOpen(false) }, [currentWorkspaceId])

  const content = (
    <ScopeSwitcherPanel
      teams={teams}
      workspaces={workspaces}
      currentWorkspaceId={currentWorkspaceId}
      onPickWorkspace={ws => navigate(workspaceHref ? workspaceHref(ws) : `/w/${ws.id}`)}
      onPickTeam={team => navigate(teamHref ? teamHref(team) : `/teams/${team.id}`)}
      onAllWorkspaces={() => navigate('/w')}
      onCreateWorkspace={() => navigate('/w?create=1')}
      onManageTeams={() => navigate('/teams')}
      onClose={() => setOpen(false)}
    />
  )

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      placement="bottomLeft"
      arrow={false}
      content={content}
      overlayClassName="cn-scope-popover"
    >
      <Button
        type="text"
        icon={<FolderOutlined />}
        data-testid="ws-switch-btn"
        aria-label={current ? `切换工作区（当前：${current.name}）` : '切换工作区'}
        aria-expanded={open}
      >
        {showLabel && (current
          ? (
            <span className="cn-scope-trigger-label">
              {currentTeam && <Tag className="cn-scope-trigger-team">{currentTeam.name}</Tag>}
              {current.name}
            </span>
          )
          : '工作区')}
      </Button>
    </Popover>
  )
}
